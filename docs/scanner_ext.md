# scanner_ext.py

## Purpose

`scanner_ext.py` is the fuller passive OSINT-style Informix prospect scanner. It reads companies from CSV or Excel, searches public Bing results for Informix / OneDB / legacy technology signals, scores the evidence, caches results, and writes an Excel workbook with summary and evidence tabs.

## Scope

The script explicitly does **not**:

- scan private systems
- probe ports
- exploit anything
- prove current production usage

It only identifies public evidence or leads for manual review.

## Input

Default input:

```text
companies.xlsx
```

Expected columns:

```text
Account Name
Website URL
```

The script attempts to cope with slight column name differences.

## Usage

```bash
python3 prospecting/scanner_ext.py     --input companies.xlsx     --output informix_prospects.xlsx
```

## Installation

```bash
pip install pandas requests beautifulsoup4 openpyxl
```

## Features

- CSV and Excel input support
- public Bing result page searches
- caching under `.informix_scan_cache`
- randomised user agents
- polite delays
- keyword scoring
- source scoring
- source categories such as jobs, vendor, document, procurement
- summary and evidence output tabs

## Evidence Categories

Strong direct signals include:

- IBM Informix
- Informix DBA
- Informix Database Administrator
- HCL Informix
- Informix

Source signals include:

- LinkedIn indexed results
- Indeed results
- Glassdoor results
- UK job boards
- Stack Exchange results
- GitHub/GitLab results
- IBM/vendor results
- PDF/document results
- tender/procurement/RFP wording

## Output

Default output:

```text
informix_prospects.xlsx
```

The output includes summary information, evidence, queries and configuration/limitations.

## Interpretation

Use the workbook to prioritise manual review. A high score means stronger public evidence, not confirmed production usage.

## Limitations

- Search engine HTML can change.
- Public evidence can be stale.
- Job adverts may indicate historical or third-party usage.
- Vendor/procurement references need manual validation.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
