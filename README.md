# Vireo Support-Ticket Analysis

Root-cause analysis pipeline and operational dashboard investigating Vireo's customer satisfaction (CSAT) decline.

## Environment & Requirements

- **Python Version**: Built and tested on `Python 3.14.0` (compatible with `Python >= 3.10`).
- **Data Privacy Notice**: The client's raw CSV exports are proprietary customer data and are **not included** in this public repository.

### Data Setup
To run the pipeline, place the client's 5 raw CSV data files in the `data/` directory:
- `data/tickets.csv` (Raw customer support ticket logs)
- `data/orders.csv` (Order master with SKUs, dates, and manufacturing lot codes)
- `data/customers.csv` (Customer master profiles)
- `data/products.csv` (Product catalog with retail prices and wholesale unit costs)
- `data/agents.csv` (Agent roster with site, shift, and team assignments)

*(Note: `data/number_summary.json` is included as it contains only high-level financial aggregations without customer or agent identifiers).*

---

## Installation & Execution Instructions

Run all commands from the repository root:

### 1. Create and Activate Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
```

**On macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

Install pinned requirements using `pip`:
```bash
pip install -r requirements.txt
```

---

## Pipeline Execution Order

Execute the pipeline scripts in the following exact sequence:

### Step 1: Clean and Prepare Support Data
Performs timestamp correction (+5h30m UTC to IST for legacy Freshdesk tickets), attaches product lot codes via direct order matching and chronological fallback, runs duplicate and unit verification checks, and computes operational metrics (handle time, first response time, SLA breaches, junk IVR flags, and double compensations).
```bash
python src/clean.py
```
- **Output File**: `data/clean.csv` (11,750 rows with rectified timestamps, lot codes, and operational flags).

### Step 2: Root-Cause Finding Analysis
Analyzes `data/clean.csv` to isolate the driver of the CSAT drop across product groups and lot codes, and prints monthly comparisons (Sep 2025 – Jun 2026) with sample sizes.
```bash
python src/finding.py
```
- **Output**: Terminal summary table and monthly CSAT comparison printed to stdout.

### Step 3: Business & Financial Impact Analysis
Computes excess replacements across sensitivity baselines, evaluates financial impact (policy cost vs. Finance standard), assesses extra contacts and SLA breach credits, measures CSAT drop attribution, and simulates early lot-level alerts.
```bash
python src/number.py
```
- **Output File**: `data/number_summary.json`.

### Step 4: Per-Agent Performance & Case-Mix Evaluation
Evaluates agents against peer group benchmarks (Standard Frontline, Hardware Triage Rota, and Tier 2 Escalations & Warranty) using 95% bootstrap confidence intervals, computes mix-adjusted CSAT via regression, and breaks down SLA breach rates by shift and site.
```bash
python src/agents.py
```
- **Output File**: `data/agent_table.csv`.

### Step 5: Rule-Based Text Extraction & Symptom Timeline
Extracts actions from agent notes (`replacement_of_faulty_unit`, `reshipment_lost_parcel`, `refund`, `none`), compares text actions to structured fields, evaluates replacement rate and headline sensitivity ranges, runs weekly symptom alert simulations across products, and exports an unlabelled evaluation sample. If `data/label_sample.csv` already exists, it skips the export to prevent overwriting manual annotations.
```bash
python src/textread.py
```
- **Output Files**: `data/label_sample.csv` (exploratory evaluation sample), SHA-256 hash validation for `src/patterns.py`.

### Step 6: Hand-Label Ground Truth Sample
Open `data/label_sample.csv` and annotate the ground truth for each ticket in the two dedicated columns:
- `my_symptom`: The verified customer symptom (e.g. `battery_charging`, `bluetooth_connectivity`, `audio_sound_quality`, `missing_item`, etc.)
- `my_action`: The verified support resolution action (`replacement_of_faulty_unit`, `reshipment_lost_parcel`, `refund`, `none`)

### Step 7: Evaluate Classification Rules Against Ground Truth
Evaluates the frozen regex rules in `src/patterns.py` against the labelled test set in `data/label_sample.csv`.
The script verifies the SHA-256 checksum of `src/patterns.py`, calculates per-stratum (`pulse2`, `other`) accuracy for actions and symptoms alongside Wilson 95% confidence intervals, prints confusion matrices, computes precision and recall for critical actions (`replacement_of_faulty_unit` and `refund`), lists discrepancy ticket IDs without leaking message text, and exports `data/my_labels.csv` and `output/eval_results.json`.
*(Note: `output/eval_results.json` is absent until labels exist. If `my_symptom` or `my_action` are blank, the script exits cleanly with an informative message).*
```bash
python src/evaluate.py
```
- **Output Files**: `data/my_labels.csv` (minimal ground-truth table: ticket_id, stratum, my_symptom, my_action), `output/eval_results.json`.

### Step 8: Generate Self-Contained HTML Dashboard
Reads `data/clean.csv`, `data/agent_table.csv`, `data/number_summary.json`, and optionally `output/eval_results.json` to generate a self-contained, standalone operations dashboard with inline SVG charts and embedded CSS (no JavaScript libraries, no external CDN dependencies).
*(Note: `output/eval_results.json` is absent until labels exist; the dashboard displays a clear "PENDING" badge for the text-reader evaluation section until evaluation is performed).*
```bash
python src/dashboard.py
```
- **Output File**: `output/dashboard.html`.

---

## Directory Structure

```text
├── .gitignore                # Excludes raw data CSVs, virtual environments, and caches
├── AGENTS.md                 # Project rules, constraints, and operational guidelines
├── NOTES.md                  # Honesty log (decisions, empirical checks, evidence, discarded approaches)
├── README.md                 # Setup, environment, and execution instructions
├── requirements.txt          # Pinned Python package dependencies
├── data/
│   ├── tickets.csv           # Raw support tickets (not included; place client export here)
│   ├── orders.csv            # Raw orders data (not included; place client export here)
│   ├── customers.csv         # Raw customer profiles (not included; place client export here)
│   ├── products.csv          # Raw product master (not included; place client export here)
│   ├── agents.csv            # Raw agent profiles (not included; place client export here)
│   ├── clean.csv             # Generated by src/clean.py (gitignored)
│   ├── number_summary.json   # Financial impact summary generated by src/number.py (included)
│   ├── agent_table.csv       # Agent performance table generated by src/agents.py (gitignored)
│   ├── label_sample.csv      # Unlabelled evaluation sample generated by src/textread.py (gitignored)
│   └── my_labels.csv         # Verified ground-truth labels exported by src/evaluate.py (tracked)
├── output/
│   ├── dashboard.html        # Generated standalone HTML dashboard
│   └── eval_results.json     # Text evaluation metrics generated by src/evaluate.py (absent until labelled)
└── src/
    ├── clean.py              # Pipeline data cleaning and validation script
    ├── finding.py            # Root-cause analysis script
    ├── number.py             # Business number and financial valuation script
    ├── agents.py             # Agent evaluation and case-mix adjustment script
    ├── patterns.py           # Compiled regex rules for text actions and symptoms (frozen v1)
    ├── textread.py           # Rule-based text extraction and audit script
    ├── evaluate.py           # Evaluates patterns.py against human labels with Wilson CIs
    └── dashboard.py          # Self-contained dashboard generator
```
