# UBOS GDP Explorer — The Whole Project, Explained

A plain-language account of what was built, how, why each tool was chosen, and what
a project like this is actually good for.

Written for someone who is technical enough to read a command but who wants the
*reasoning* rather than the jargon.

---

## Part 1 — What this project is, in one paragraph

The Uganda Bureau of Statistics (UBOS) publishes the country's GDP figures as
Excel spreadsheets. Those spreadsheets are built for humans to read, not for
computers to process: titles floating above tables, merged header cells, hidden
worksheets, footnotes, and broken formulas left behind by earlier edits. This
project takes five of those workbooks and turns them into a clean, checked
database, then puts a small web dashboard on top so you can look at Uganda's GDP
by year, by quarter, and by economic activity — and click through to see exactly
which cell in which spreadsheet each number came from.

**By the numbers:** 5 source workbooks → 21,690 individual observations → 30
economic activities → 49 time periods → one queryable database (~11 MB) → a
5-page dashboard. Around 2,900 lines of Python and 670 lines of configuration
and SQL.

---

## Part 2 — Why this is harder than it sounds

If spreadsheets were tidy, this project would be one line of code:
`pandas.read_excel("gdp.xlsx")`. They are not. Here is what was actually in the
files, all of it verified by reading the raw bytes rather than assumed:

| The problem | Why it breaks naive code |
|---|---|
| The number you want starts on **row 5**, not row 1 | Rows 1–4 hold a title, a blank, a year header and a quarter header |
| Fiscal years are **merged across four columns** | Only the first of four columns holds the text "2016/17"; the other three are empty |
| One workbook **repeats** the year instead of merging it | So code that only handles merging breaks on that file, and vice versa |
| One workbook has **annual totals hidden inside a quarterly sheet**, in columns B–F | Reading "all the numbers in this row" silently mixes yearly and quarterly figures into one series |
| Sheets contain **cached errors** like `#REF!` and `#DIV/0!` | These arrive as text, so a "total" column becomes unusable |
| The annual workbook's **only two visible sheets are entirely broken** (`#REF!` everywhere); all the real data is in *hidden* sheets | A sensible-sounding rule — "read the visible sheets" — returns nothing but garbage |
| Excel reports a table as **256 columns × 166 rows** when the real table is 40 × 25 | Trusting the reported size gives you thousands of empty cells |
| The same activity is called `AGRICULTURE,FORESTRY&FISHING` in one file and `Agriculture, forestry and fishing` in another | Joining the two datasets on name fails |
| Two releases (March and June) **overlap by 38 quarters** | Load both naively and every figure appears twice |
| The old annual file is **`.xls`**, not `.xlsx` | Modern Python libraries cannot read it at all |

There was also a trap that no amount of care in code would catch: three sheets
label a row `Construction SA` and `Construction Trend` instead of `Construction`.
More on how that was caught in Part 4.

---

## Part 3 — The six phases, and why they happened in that order

### Phase 1 — Look before touching (inspection)

**What:** Before writing any pipeline, every workbook was opened and examined:
sheet names, real dimensions, first 20 rows, where headers sit, where footnotes
sit, which cells are merged, which sheets are hidden, which contain real numbers.
The findings went into `reports/inspection_report.md`, with every statement
marked **[F]** for *fact observed in the file* or **[A]** for *assumption*.

**Why this first:** Almost every failed data project fails here. Someone assumes
the shape of the data, writes 500 lines against that assumption, and then spends
days patching symptoms. Two hours of looking prevented a day of guessing. The
fact/assumption labelling matters too — later, when something looked wrong, it was
possible to go back and ask "was that a thing I *saw*, or a thing I *assumed*?"

**What it changed:** The inspection is why the final pipeline needs only *two*
table readers instead of a general-purpose "figure out any spreadsheet" engine.
Once you can see that nine sheets share one identical layout and three share
another, the problem shrinks dramatically.

### Phase 2 — Decide the shape of the answer (architecture)

**What:** A written design, agreed before coding: what a single row of clean data
looks like, how annual and quarterly data live side by side, how two releases of
the same numbers are handled, how a number stays traceable to its source cell.

**Why:** Writing it down surfaced disagreements cheaply. Two of the reviewer's
decisions changed the code before it existed:

1. **Don't guess the growth basis.** The spreadsheets say only "PERCENTAGE
   CHANGE". They never say whether that means "compared to the same quarter last
   year" or "compared to last quarter". The design originally planned to infer it
   from the size of the numbers. That was overruled — and rightly. The field is
   recorded as *unknown* and the dashboard says so. A plausible guess, presented
   as fact, is worse than an honest gap.
2. **Keep all three quarterly variants** (original, seasonally adjusted,
   trend-cycle) rather than just the raw one.

Writing the design also caught two of my own arithmetic mistakes: I described "12
source blocks" when the scope table listed 21, and a "31-row" activity list that
is actually 30 rows. Cheap to fix on paper; annoying to fix in code.

### Phase 3 — Extract and validate (the pipeline)

**What:** Python reads the 21 chosen table blocks out of the 5 workbooks and
writes three files:

- `gdp_observations.parquet` — 21,690 rows, one per number
- `source_blocks.parquet` — where each block came from, including a fingerprint of the file
- `rejects.parquet` — 5,940 cells that were *refused*, each with a reason

**Why a "rejects" file:** This is the single most useful design decision in the
project. Every cell that does not become a number is written down with the reason
it was rejected. Nothing disappears quietly. If a figure is missing from the
dashboard, you can find out why in one query instead of re-reading spreadsheets.

**Why configuration instead of cleverness:** The location of every table —
which sheet, which rows, which header row — lives in a text file
(`config/sources.yml`), not scattered through the code. There are only 5
workbooks. Listing exactly where the data is, is more honest and far more
reliable than writing code that tries to *guess* where data is. When UBOS
publishes the next quarter, the change is a few lines of configuration, not new
code.

### Phase 4 — Make it queryable (DuckDB)

**What:** The Parquet files are loaded into a small analytical database with six
data tables and eight ready-made views. The Parquet files remain the source of
truth; the database is a *derived* thing that can be deleted and rebuilt in about
a second.

**Why bother, when the Parquet files already exist?** Two reasons. First, the
database enforces the rules — it physically cannot hold a duplicate observation,
or a number pointing at an activity that does not exist. Second, the dashboard
asks many small questions per click, and answering them in SQL over a real table
is simpler and faster than re-reading files each time.

### Phase 5 — Make it visible (Streamlit dashboard)

**What:** A five-page web app: an overview with headline figures, a
by-activity page, a growth page, a quarterly/seasonal page, and a data-and-lineage
page where you can filter every observation, export it, and trace any single
figure back to `Original_VA!CC15` in a named workbook.

**Why the dashboard shows warnings:** The awkward truths from the data are
carried into the interface rather than hidden. When you view growth, it tells you
UBOS does not state the basis. When you view the current fiscal year, it warns
that only three quarters exist so the four cannot be summed. The dropdown menus
are built from what actually exists in the data, so you *cannot* select
"current-price growth" — because UBOS never published it.

### Phase 6 — Publish it (Git and GitHub)

**What:** The project was put into version control and pushed to GitHub — code,
configuration, documentation and the original source spreadsheets, but *not* the
generated data files or the Python environment.

**Why exclude the generated files:** They can be rebuilt from the raw
spreadsheets in seconds, byte-for-byte identically (this was tested: two rebuilds
produce the same content fingerprint). Committing them would mean a repository
that grows every time anyone runs anything. The Python environment folder alone
is 592 MB, versus 2.3 MB for everything worth keeping.

---

## Part 4 — The tools: what, why, and what was rejected

### Python

**Why:** It has the best-supported libraries for both ends of this problem —
reading damaged Excel files *and* serving a web page — so the entire project uses
one language. No glue code between a "data language" and a "web language".

**What was rejected:** R is excellent at statistics but weaker for the messy
file-wrangling and web-serving parts. JavaScript reads spreadsheets adequately
but has a thinner toolkit for tabular analysis. Neither would have been *wrong*;
Python simply required the fewest moving parts.

### openpyxl and xlrd — two Excel readers, not one

**Why two:** Four of the workbooks are modern `.xlsx` files, which `openpyxl`
reads. The annual workbook is a `.xls` file in the 1990s-era BIFF8 format, which
`openpyxl` and pandas **cannot read at all**. Only `xlrd` (pinned to version
2.0.1) handles it.

**How the mess was contained:** Both readers hide behind one small module
(`io_excel.py`) that presents every cell as one of four things: empty, a number,
text, or an Excel error. The table-reading code never learns which library is
underneath. This is why adding a third format later would touch one file.

**A detail that mattered:** the two libraries report errors differently.
`openpyxl` hands back the text `"#DIV/0!"`; `xlrd` returns an error *code*. Early
on, a sheet appeared to be full of the number 23 — which was actually error code
23, meaning `#REF!`. Catching that is the difference between "this sheet has
data" and "this sheet is broken".

### pandas + Parquet (via pyarrow)

**Why Parquet rather than CSV:** CSV forgets things. It has no idea that a column
is a number, a date, or text, so every program that reads it re-guesses — and
sometimes guesses differently. Parquet stores the type *with* the data, compresses
well (655 KB for 21,690 fully-described rows), and is read natively by almost
every modern data tool. Anyone with Python, R, or DuckDB can open these files in
one line, years from now, with no special software.

**Why not go straight from Excel to the database:** Because then the database
becomes the only copy, and rebuilding means re-parsing spreadsheets. The Parquet
layer is a clean, checked, permanent checkpoint that everything downstream is
built from.

### YAML for configuration

**Why:** The list of "which table lives where" needs to be edited by a human,
including by a human who does not write Python. YAML is readable, supports
comments (so each odd case is explained next to the setting), and separating
*what to extract* from *how to extract it* is what makes the next release a
config change instead of a code change.

### DuckDB

**Why:** DuckDB is a database that runs *inside* the application — a single file
on disk, no server to install, start, secure, or pay for. It is built for
analytical questions ("sum this by that, across all years") rather than
transactional ones, and it reads Parquet directly. For a dataset this size it
answers every dashboard question instantly.

**What was rejected and why:**

- **PostgreSQL / MySQL** — real servers, needing installation, credentials,
  backups and a running process. All that overhead buys features this project does
  not use: many simultaneous writers, permissions, network access. Wrong tool.
- **SQLite** — also file-based and excellent, but organised row-by-row, which
  suits "fetch this one record" more than "average this column across 20,000
  rows". It also cannot read Parquet natively.
- **A cloud warehouse (BigQuery, Snowflake)** — sensible at a thousand times this
  size. Here it would add cost, latency, an internet dependency and an account,
  to query 11 MB.
- **Nothing at all, just pandas** — tempting, and it would work. The database was
  chosen for the *guarantees*: the schema refuses duplicates and orphan
  references, which turns "we checked it once" into "it cannot be otherwise".

### Streamlit

**Why:** It turns a Python script into a web page with no HTML, CSS or JavaScript.
A filter is one line: `st.radio("Price basis", ...)`. For a data tool whose
purpose is to show numbers and let someone slice them, this is the shortest
honest path from data to something usable.

**What was rejected:** React with a separate API would give total control over
appearance, at the cost of building and maintaining two applications instead of
one — and the design brief was explicitly a small, quick tool. Jupyter notebooks
are great for exploring but poor for handing to someone else. Excel dashboards
would have re-created the exact problem this project exists to solve.

### Altair for charts

**Why:** You describe what you want ("fiscal year on the x-axis, value on the
y-axis, colour by price basis") and it handles the drawing. It is Streamlit's
native charting partner, so tooltips and interactivity come free — which is how
each chart tooltip can show the source worksheet and cell alongside the number.

### Git and GitHub

**Why:** Version control answers "what changed, when, and why" — indispensable
once a project has more than one file. GitHub adds an off-machine backup and a
way to hand the work to someone else. A `.gitignore` file lists what must never
be committed: the 592 MB environment, the rebuildable data, and credentials.

**That last one earned its place immediately.** A mistyped `ssh-keygen` command
left an SSH *private key* sitting in the project folder. It was caught before any
commit, and the ignore rules were widened so that class of file can never be
committed. That is a genuinely common way people leak credentials on GitHub.

---

## Part 5 — How the data is organised (in plain terms)

Imagine one enormous, very boring table. Each row is **one number** from one
spreadsheet cell, and the columns around it explain what that number *means*:

- **When** — fiscal year `2024/25`, or the quarter `2024/25Q3`
- **What** — the economic activity, e.g. *Manufacturing*
- **Which kind of number** — a value in billions of shillings, or a percentage change
- **Measured how** — at today's prices ("current") or inflation-adjusted ("constant 2016/17")
- **Smoothed how** — raw, seasonally adjusted, or trend
- **From which release** — March 2026 or June 2026, and whether this is the newest
- **From exactly where** — workbook, worksheet, published table name, and cell reference

Around that central table sit four small reference tables: the list of activities
(and which sector each belongs to), the list of time periods, the list of source
workbooks, and the list of releases. This is a standard arrangement called a
**star schema** — one table of facts in the middle, reference tables around it.
It is popular because it is easy to reason about and easy to query.

### The one trap worth understanding

The data contains both **totals and their parts**. "Industry" is a row. So are
"Manufacturing", "Mining", "Electricity", "Water" and "Construction" — which add
up to Industry. If you sum the whole column you get roughly double the real GDP.

This is handled by labelling every activity with its level (`total`, `sector`,
`activity`, `adjustment`) and never showing two levels mixed together in the same
chart. The dashboard makes you pick a level, and says why.

---

## Part 6 — How we know it is actually right

This is the part most data projects skip. Claiming the numbers are correct is
easy; demonstrating it is the work.

**During extraction (12 checks):** the natural key is unique; every activity label
matched the crosswalk; every period is well-formed; totals reconcile to their
parts within 0.5%; every source block produced the expected number of rows.

**In the database (12 more checks):** row counts match the Parquet files exactly;
no observation points at a non-existent activity or period; each series has
exactly one "current" row; the growth basis is still unknown (a check that a
future careless edit cannot silently fill it in).

**Three results worth highlighting:**

1. **The four quarters sum exactly to the published annual figure** for all nine
   complete fiscal years. That is powerful, because the quarterly and annual
   figures come from *different workbooks*, in *different file formats*, read by
   *different libraries*, via *different code paths*. They agreeing to
   floating-point precision means the whole chain is behaving.

2. **The unadjusted constant-price series are identical across the two releases** —
   all 2,280 overlapping values. The spreadsheet's own footnote claims there were
   no revisions; the data confirms it. Meanwhile the seasonally adjusted series
   *were* revised on about 1,100 values each, exactly as another footnote warns.

3. **`Construction SA` was caught by a deliberate hard failure.** The pipeline
   treats an unrecognised row label as an *error* that stops everything, rather
   than skipping the row. On the first run it stopped, complaining about
   `Construction SA` and `Construction Trend`. Those were verified to genuinely be
   the Construction row (its neighbours still summed correctly to the Industry
   total) and added as known aliases. Had unknown labels been skipped quietly,
   Construction would simply have been *missing* from six series, and nobody would
   have noticed.

**What is still assumed, and labelled as such:** that Uganda's fiscal year runs
July–June (used to turn `2016/17Q1` into real dates), and that the numbers UBOS
publishes are correct. And the growth basis remains unknown by choice.

---

## Part 7 — What this could be used for

### Who would use it, and for what

**A journalist on deadline.** *Scenario:* the Finance Ministry claims the economy
grew 6.4% and manufacturing is booming. The reporter has 40 minutes. Today that
means downloading a spreadsheet, hunting for the right hidden sheet, and squinting
at merged cells. With this tool: open the growth page, select Manufacturing,
compare it against the sector average, and screenshot the chart. Crucially, the
tooltip names the exact workbook and cell — so the claim in the article can be
sourced precisely, and an editor can verify it.

**A researcher or graduate student.** *Scenario:* a thesis on whether Uganda's
services sector is pulling away from agriculture needs 39 quarters of consistent
data. Normally that is two weeks of copy-paste, with transcription errors baked
in. Here it is one CSV export, already reconciled, with lineage attached so the
supervisor can check any figure.

**A bank or investment analyst.** *Scenario:* a lender is deciding exposure limits
for construction. They need the sector's quarterly trajectory, seasonally
adjusted, in real terms — and they need to know how much previous estimates were
revised, because a number that moves 500 billion shillings between releases
should not be trusted to three decimal places. The revision data is retained
precisely for this.

**A government analyst or donor agency.** *Scenario:* preparing a briefing on
agriculture's contribution over a decade. They need consistent definitions across
years, and an audit trail, because the briefing will be challenged.

**A civic-tech or transparency organisation.** *Scenario:* they want to publish
"Uganda's economy in charts" for the public. They need a maintained, checkable
pipeline rather than hand-made graphics that rot after one release.

### How they would use it

Three levels, depending on skill:

1. **Click.** Use the dashboard, read charts, export a CSV.
2. **Query.** Point any SQL tool at `data/ubos.duckdb` and ask direct questions.
3. **Build on it.** Import the Parquet files into R, Python or a BI tool as a
   trusted starting point.

### Variations of the same idea

The valuable part of this project is not GDP — it is the *pattern*: messy official
spreadsheets → checked dataset → queryable database → dashboard, with lineage
throughout. Swap the source and everything else survives:

- **Other UBOS releases** — inflation (CPI), trade, population, labour force.
  Same shape, same problems, mostly config changes.
- **Government budget and spending data** — allocated versus actually spent, by
  ministry and district. Politically valuable and consistently badly formatted.
- **Health or education statistics** — clinic stock-outs, exam results, staffing by
  district.
- **Other countries' statistics offices** — the "Excel built for humans" problem is
  universal. The same architecture applies to Kenya, Tanzania, Rwanda, Ghana.
- **Regional comparison** — combine several countries' GDP into one comparable
  series. Harder, because definitions differ, but the lineage design is exactly
  what makes such reconciliation defensible.
- **Internal corporate reporting** — plenty of companies run on monthly Excel
  workbooks with the same structural chaos.

---

## Part 8 — Could this be a business? Is it an MVP?

Honest answer first: **as it stands, this is a working MVP of a tool, not yet a
business.** It proves the hard part is solvable. What it lacks is any way to get
new data automatically, and any reason for someone to pay.

*The illustrative figures below are for reasoning about shape and viability, not
researched market prices.*

### What makes it a genuine MVP

It does one complete job end to end: raw spreadsheets in, verified answers out,
with proof. It is small enough to change cheaply and structured enough not to
collapse when the next release arrives. Most importantly, it de-risks the
expensive unknown — nobody now has to wonder *whether* those spreadsheets can be
parsed reliably.

### What is deliberately missing

1. **Automatic collection.** Someone must download the workbooks by hand. This is
   the biggest gap, and the obvious next build.
2. **Alerting.** No "notify me when new GDP figures are published".
3. **Breadth.** Only GDP by activity. Not expenditure, trade, inflation or
   employment.
4. **Multi-user hosting.** It runs on one machine with no accounts or permissions.
5. **History across many releases.** The revision analysis works, but with only
   two vintages.

### Routes to being economically viable

**Route 1 — Data subscription (most plausible).** Banks, consultancies, research
firms and donor programmes each pay a modest monthly fee for a maintained,
verified statistical feed with an API. *Scenario:* fifteen organisations paying a
mid-range monthly subscription would comfortably fund one part-time maintainer.
The product is not the charts — it is **saved analyst hours plus a defensible
audit trail**. An analyst who spends two days per quarter wrangling spreadsheets
costs far more than the subscription.

**Route 2 — Consulting pull-through.** Publish the dashboard free as credible
proof of competence; sell the same pipeline as a service to organisations
drowning in their own spreadsheets. *Scenario:* a ministry or NGO paying for a
bespoke "our messy reports → clean dashboard" build, where the pipeline
architecture is reused and only the extraction config and crosswalk change. The
public tool becomes the portfolio.

**Route 3 — Grant or institutional funding.** Open-data and transparency funders
support exactly this kind of public-good infrastructure. Not a business, but a
real way to keep it maintained, and appropriate given the data is public.

**Route 4 — Embedded in journalism or education.** A newsroom or university pays
for maintenance because their staff use it weekly. Small revenue, high
credibility.

**Route 5 — Wider platform.** Expand to many datasets and countries and it becomes
"the reliable source for East African official statistics". Larger prize, needs
real investment, and the competitive moat is unglamorous: **coverage and
trustworthiness**, not features.

### Why the cost side is favourable

Running costs are near zero, by design. There is no database server. The data is
megabytes. A small virtual machine can host the dashboard for the price of a few
coffees a month. There are no licence fees — every tool used is free and
open-source. The real cost is human: someone watching for new releases and
handling layout changes when UBOS reformats a sheet.

### The honest risks

- **UBOS could change their spreadsheet layouts**, breaking extraction. The
  config-driven design keeps the fix small, and the QA checks mean breakage is
  *loud* rather than silent — which is the important property.
- **UBOS could publish a proper API**, making the extraction work redundant.
  That would be good for Uganda and bad for this specific value proposition.
- **Willingness to pay for public data is often low**, precisely because it is
  free. The sellable thing is *reliability and time saved*, which requires a track
  record.
- **One-person maintenance** is a real risk; documentation like this file exists
  partly to reduce it.

### Where I would go next

1. **Automatic collection** — watch the UBOS site, fetch new workbooks, run the
   pipeline, flag anything that changed shape. Turns a static snapshot into a
   living dataset, and is the difference between a demo and a product.
2. **Add one more dataset** — inflation, most likely. Proves the architecture
   generalises rather than fitting GDP by luck.
3. **Deploy it publicly** so people can use it without installing anything.
4. **A weekly or monthly digest email** — the cheapest possible test of whether
   anyone actually cares.

---

## Part 9 — Running it yourself

```bash
# One-time setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Build the data from the original spreadsheets
PYTHONPATH=src .venv/bin/python -m ubos_explorer.pipeline
PYTHONPATH=src .venv/bin/python -m ubos_explorer.warehouse

# Run the dashboard
PYTHONPATH=src .venv/bin/streamlit run app/Home.py
```

Then open <http://localhost:8501>.

Steps two and three print their own validation results. If they pass, the data is
sound; if not, they say precisely what failed.

---

## Part 10 — Small glossary

| Term | Meaning |
|---|---|
| **GDP** | The total value of everything a country produces in a period |
| **Current prices** | Value in the money of the day, including inflation |
| **Constant prices** | Value with inflation removed, so real growth is visible |
| **Fiscal year** | Uganda's budget year, July to June, written `2024/25` |
| **Seasonally adjusted** | Predictable yearly patterns (harvests, holidays) removed |
| **Trend-cycle** | A smoothed line showing underlying direction |
| **Parquet** | A compact file format that stores data types along with the data |
| **DuckDB** | A database that lives in a single file, with no server to run |
| **Star schema** | One central table of facts, surrounded by small reference tables |
| **Lineage** | The record of exactly where a number came from |
| **ISIC** | An international code system for classifying economic activities |
| **MVP** | Minimum Viable Product — the smallest version that does a real job |
| **Vintage / release** | A particular published edition of the statistics |

---

## Closing note

The single idea worth taking from this project is that **the checks are the
product**. Anyone can pull numbers out of a spreadsheet. What makes a dataset
usable by someone who is accountable for their conclusions is being able to answer
three questions: *Where exactly did this number come from? What was thrown away
and why? How do you know it is right?*

That is why there is a rejects file, a lineage column on every row, twenty-four
automated checks, and a growth field that stubbornly says "unknown" rather than
offering a confident guess.
