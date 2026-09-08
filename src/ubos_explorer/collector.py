"""Collector: find and fetch UBOS statistical workbooks, safely.

What this does
--------------
1. Discovers workbook links on configured UBOS pages, plus re-checks the files we
   already ingested.
2. Classifies every candidate as NEW, UNCHANGED, CHANGED or MISSING by comparing
   the published bytes against what we already hold.
3. Downloads only what is new or changed, into ``data/incoming/``.
4. Probes each downloaded workbook against the layout that ``sources.yml``
   expects, and reports any mismatch loudly.

What this deliberately does NOT do
----------------------------------
* It never writes to ``data/raw/``. Promoting a workbook is a human decision, so
  the hash-pinned provenance of already-ingested files cannot be disturbed.
* It never disables TLS verification. www.ubos.org omits its intermediate
  certificate, so we supply the missing public intermediate instead.
* It does not run the ingestion pipeline. A newly published workbook is not
  assumed to be parseable: across the only two releases we have, the layout
  changed both times.

Usage::

    python -m ubos_explorer.collector            # check only, no downloads
    python -m ubos_explorer.collector --fetch    # download new/changed files
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi
import requests
import yaml
from bs4 import BeautifulSoup

from .io_excel import file_sha256, open_workbook

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_CONFIG = PACKAGE_DIR / "config" / "collector.yml"

WORKBOOK_SUFFIXES = (".xlsx", ".xls")

NEW = "NEW"
CHANGED = "CHANGED"
UNCHANGED = "UNCHANGED"
MISSING = "MISSING"
ERROR = "ERROR"


@dataclass
class Candidate:
    filename: str
    url: str
    status: str = ""
    remote_size: int | None = None
    remote_sha256: str | None = None
    local_sha256: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    note: str = ""
    downloaded_to: str | None = None
    layout: str = ""


@dataclass
class Config:
    raw: dict
    path: Path

    @property
    def http(self) -> dict:
        return self.raw["http"]

    @property
    def upload_prefix(self) -> str:
        return self.raw["site"]["upload_path"].rstrip("/")

    def url_for(self, filename: str) -> str:
        return f"{self.raw['site']['base_url'].rstrip('/')}{self.upload_prefix}/{filename}"

    def dir(self, key: str) -> Path:
        return PROJECT_ROOT / self.raw["paths"][key]

    @property
    def ca_bundle(self) -> str | bool:
        """Path to a trust store that can verify www.ubos.org.

        Note: requests/OpenSSL *replace* the default trust store with whatever
        file is given, they do not add to it. Supplying only the missing
        intermediate therefore fails, because its issuing root is no longer
        trusted. The two must be concatenated: intermediate + normal roots.
        """
        if not self.http.get("verify_tls", True):
            # Guard rail: refusing to honour verify_tls=false is intentional.
            raise SystemExit(
                "collector.yml sets verify_tls: false. Refusing to run: that would "
                "let anyone between you and UBOS substitute the statistics. Supply "
                "the missing intermediate certificate instead."
            )
        bundle = self.http.get("ca_bundle")
        if not bundle:
            return True
        path = PACKAGE_DIR / bundle
        if not path.exists():
            raise SystemExit(f"ca_bundle not found: {path}")
        return _combined_trust_store(path)


def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    return Config(yaml.safe_load(path.read_text(encoding="utf-8")), path)


_TRUST_STORE_CACHE: dict[Path, str] = {}


def _combined_trust_store(extra_cert: Path) -> str:
    """Write `extra_cert` + the normal CA roots to a temp file, return its path.

    Cached per process. Kept outside the repository so a generated file is never
    mistaken for a checked-in certificate.
    """
    if extra_cert in _TRUST_STORE_CACHE:
        return _TRUST_STORE_CACHE[extra_cert]
    roots = Path(certifi.where()).read_text(encoding="utf-8")
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix="-ubos-trust.pem", delete=False, encoding="utf-8"
    )
    with handle:
        handle.write(extra_cert.read_text(encoding="utf-8"))
        handle.write("\n")
        handle.write(roots)
    _TRUST_STORE_CACHE[extra_cert] = handle.name
    return handle.name


class Client:
    """Polite HTTP client: one connection, fixed delay, honest user agent."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.delay = float(cfg.http.get("delay_seconds", 2.0))
        self.timeout = int(cfg.http.get("timeout_seconds", 60))
        self.retries = int(cfg.http.get("max_retries", 2))
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg.http["user_agent"]
        # requests needs the full chain; www.ubos.org sends only its leaf cert.
        self._verify = cfg.ca_bundle

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _request(self, method: str, url: str, **kwargs):
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                return self.session.request(
                    method, url, timeout=self.timeout, verify=self._verify,
                    allow_redirects=True, **kwargs
                )
            except requests.RequestException as exc:  # network/TLS failure
                last_error = exc
                time.sleep(self.delay * (attempt + 1))
        raise last_error  # type: ignore[misc]

    def head(self, url: str):
        return self._request("HEAD", url)

    def get_text(self, url: str) -> str:
        response = self._request("GET", url)
        response.raise_for_status()
        return response.text

    def download(self, url: str, dest: Path) -> tuple[int, str]:
        """Stream to disk, returning (bytes, sha256)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        response = self._request("GET", url, stream=True)
        response.raise_for_status()
        with open(tmp, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        tmp.replace(dest)
        return size, digest.hexdigest()


# ------------------------------------------------------------------ discovery --

def discover(client: Client, cfg: Config) -> dict[str, str]:
    """Return {filename: url} for workbook links found on the listing pages."""
    found: dict[str, str] = {}
    patterns = [p.upper() for p in cfg.raw.get("interesting_patterns", [])]
    for page in cfg.raw.get("discovery_pages", []):
        try:
            html = client.get_text(page)
        except Exception as exc:
            print(f"  ! could not read {page}: {type(exc).__name__}", file=sys.stderr)
            continue
        soup = BeautifulSoup(html, "html.parser")
        hits = 0
        for anchor in soup.find_all("a", href=True):
            url = urljoin(page, anchor["href"])
            path = urlparse(url).path
            if not path.lower().endswith(WORKBOOK_SUFFIXES):
                continue
            filename = Path(path).name
            if patterns and not any(p in filename.upper() for p in patterns):
                continue
            found.setdefault(filename, url)
            hits += 1
        print(f"  {page} -> {hits} workbook link(s)")
    return found


def local_hashes(cfg: Config) -> dict[str, str]:
    """sha256 of everything already in data/raw/ and data/incoming/."""
    hashes: dict[str, str] = {}
    for key in ("raw", "incoming"):
        directory = cfg.dir(key)
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in WORKBOOK_SUFFIXES:
                hashes.setdefault(path.name, file_sha256(path))
    return hashes


def classify(client: Client, cfg: Config, candidates: dict[str, str],
             known: dict[str, str]) -> list[Candidate]:
    """Decide NEW / CHANGED / UNCHANGED / MISSING for each candidate.

    A HEAD request gives size, ETag and Last-Modified cheaply. Size alone cannot
    prove equality, so a file we already hold is treated as UNCHANGED only when
    the size matches; anything else is reported for a byte-level check.
    """
    results: list[Candidate] = []
    for filename, url in sorted(candidates.items()):
        item = Candidate(filename=filename, url=url, local_sha256=known.get(filename))
        try:
            response = client.head(url)
        except Exception as exc:
            item.status, item.note = ERROR, f"{type(exc).__name__}: {exc}"[:120]
            results.append(item)
            continue
        if response.status_code == 404:
            item.status, item.note = MISSING, "no longer published at this URL"
            results.append(item)
            continue
        if not response.ok:
            item.status, item.note = ERROR, f"HTTP {response.status_code}"
            results.append(item)
            continue
        item.etag = response.headers.get("ETag")
        item.last_modified = response.headers.get("Last-Modified")
        length = response.headers.get("Content-Length")
        item.remote_size = int(length) if length and length.isdigit() else None

        if item.local_sha256 is None:
            item.status = NEW
        elif item.remote_size is None:
            item.status, item.note = CHANGED, "no Content-Length; verify by download"
        else:
            local_path = _find_local(cfg, filename)
            if local_path and local_path.stat().st_size == item.remote_size:
                item.status = UNCHANGED
            else:
                item.status, item.note = CHANGED, "size differs from our copy"
        results.append(item)
    return results


def _find_local(cfg: Config, filename: str) -> Path | None:
    for key in ("raw", "incoming"):
        path = cfg.dir(key) / filename
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------- layout probe --

def probe_layout(path: Path, sources_cfg: dict) -> str:
    """Check a downloaded workbook against what sources.yml expects.

    Returns a human-readable verdict. This is the guard against silently
    ingesting a workbook whose shape has changed: across the two releases we
    have, the layout changed both times.
    """
    blocks = [b for b in sources_cfg["blocks"] if b["file"] == path.name]
    if not blocks:
        return "no sources.yml entry yet - needs a config block before ingestion"
    engine = blocks[0]["engine"]
    try:
        workbook = open_workbook(path, engine)
    except Exception as exc:
        return f"UNREADABLE: {type(exc).__name__}: {exc}"[:140]
    problems: list[str] = []
    try:
        for block in blocks:
            sheet_name = block["sheet"]
            if sheet_name not in workbook.sheet_names:
                problems.append(f"sheet {sheet_name!r} missing")
                continue
            sheet = workbook.sheet(sheet_name)
            layout = sources_cfg["layouts"][block["layout"]]
            if block["layout"] == "quarterly_va":
                quarter_row = layout["quarter_row"]
                quarters = sum(
                    1 for c in range(1, sheet.n_cols + 1)
                    if sheet.text(quarter_row, c) in ("Q1", "Q2", "Q3", "Q4")
                )
                if quarters == 0:
                    problems.append(f"{sheet_name}: no quarter labels on row {quarter_row}")
            else:
                year_row = block["year_row"]
                years = sum(
                    1 for c in range(1, sheet.n_cols + 1)
                    if re.match(r"^\d{4}/\d{2}$", sheet.text(year_row, c))
                )
                if years == 0:
                    problems.append(f"{sheet_name}: no fiscal years on row {year_row}")
    finally:
        workbook.close()
    if problems:
        return "LAYOUT CHANGED: " + "; ".join(problems[:4])
    return f"layout matches expectations ({len(blocks)} block(s))"


# --------------------------------------------------------------------- runner --

def run(fetch: bool, cfg: Config) -> tuple[list[Candidate], dict]:
    client = Client(cfg)
    print("discovery:")
    discovered = discover(client, cfg)
    watched = {name: cfg.url_for(name) for name in cfg.raw.get("watch_files", [])}
    candidates = {**watched, **discovered}
    print(f"  {len(discovered)} discovered + {len(watched)} watched "
          f"= {len(candidates)} unique candidate(s)\n")

    known = local_hashes(cfg)
    results = classify(client, cfg, candidates, known)

    if fetch:
        sources_cfg = yaml.safe_load(
            (PACKAGE_DIR / "config" / "sources.yml").read_text(encoding="utf-8")
        )
        incoming = cfg.dir("incoming")
        for item in results:
            if item.status not in (NEW, CHANGED):
                continue
            dest = incoming / item.filename
            try:
                size, digest = client.download(item.url, dest)
            except Exception as exc:
                item.status, item.note = ERROR, f"download failed: {type(exc).__name__}"
                continue
            item.remote_size, item.remote_sha256 = size, digest
            item.downloaded_to = str(dest.relative_to(PROJECT_ROOT))
            if item.local_sha256 == digest:
                # Size differed but bytes match, or our copy was already current.
                item.status, item.note = UNCHANGED, "bytes identical to our copy"
                dest.unlink(missing_ok=True)
                item.downloaded_to = None
                continue
            item.layout = probe_layout(dest, sources_cfg)

    summary = {
        "checked_at": dt.datetime.now().isoformat(timespec="seconds"),
        "candidates": len(results),
        "counts": {
            status: sum(1 for r in results if r.status == status)
            for status in (NEW, CHANGED, UNCHANGED, MISSING, ERROR)
        },
        "fetched": bool(fetch),
    }
    return results, summary


def write_manifest(cfg: Config, results: list[Candidate], summary: dict) -> Path:
    incoming = cfg.dir("incoming")
    incoming.mkdir(parents=True, exist_ok=True)
    path = incoming / "collection_manifest.json"
    payload = {
        "summary": summary,
        "items": [
            {
                "filename": r.filename,
                "url": r.url,
                "status": r.status,
                "remote_size": r.remote_size,
                "remote_sha256": r.remote_sha256,
                "local_sha256": r.local_sha256,
                "etag": r.etag,
                "last_modified": r.last_modified,
                "downloaded_to": r.downloaded_to,
                "layout": r.layout,
                "note": r.note,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check for and fetch new UBOS statistical workbooks."
    )
    parser.add_argument("--fetch", action="store_true",
                        help="download NEW/CHANGED files into data/incoming/ "
                             "(default is check only)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    print(f"config : {args.config.name}")
    print(f"mode   : {'FETCH' if args.fetch else 'CHECK ONLY (no downloads)'}")
    print(f"tls    : verification ON, chain from {cfg.http['ca_bundle']}")
    print(f"polite : {cfg.http['delay_seconds']}s between requests\n")

    results, summary = run(args.fetch, cfg)

    width = max((len(r.filename) for r in results), default=10)
    print(f"{'status':<10} {'file':<{width}} {'size':>10}  note")
    print("-" * (26 + width))
    for item in sorted(results, key=lambda r: (r.status, r.filename)):
        size = f"{item.remote_size:,}" if item.remote_size else "-"
        detail = item.layout or item.note
        print(f"{item.status:<10} {item.filename:<{width}} {size:>10}  {detail}")

    counts = summary["counts"]
    print(f"\n{counts[NEW]} new, {counts[CHANGED]} changed, {counts[UNCHANGED]} unchanged, "
          f"{counts[MISSING]} missing, {counts[ERROR]} error")

    manifest = write_manifest(cfg, results, summary)
    print(f"manifest: {manifest.relative_to(PROJECT_ROOT)}")

    if counts[NEW] or counts[CHANGED]:
        print(
            "\nNext steps for anything downloaded to data/incoming/:\n"
            "  1. Read the layout verdict above. A changed layout needs a human.\n"
            "  2. Move the file into data/raw/ (never overwrite an existing file).\n"
            "  3. Add or update its blocks in config/sources.yml.\n"
            "  4. Re-run: python -m ubos_explorer.pipeline && "
            "python -m ubos_explorer.warehouse"
        )
    if counts[ERROR]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
