# scanner.py

## Purpose

`scanner.py` is a simple passive public-search tool for finding organisations with possible public Informix evidence. It reads a company list, searches public Bing results for Informix-related terms, scores keyword hits, and writes an Excel workbook.

## Important Safety / Scope Note

This is passive public web research. It does not scan private systems, probe ports, exploit anything, or prove current production usage. Treat the output as leads for manual review only.

## Input

Default input file:

```text
companies.csv
```

The script looks for a column containing `account` in its name and treats that as the company name column.

## Usage

```bash
python3 prospecting/scanner.py
```

## Output

Default output file:

```text
informix_prospects.xlsx
```

The workbook contains companies sorted by score.

## Search Templates

The script searches combinations such as:

```text
"{company}" Informix
"{company}" "IBM Informix"
"{company}" "Informix DBA"
"{company}" Genero
"{company}" 4GL
"{company}" "Enterprise Replication"
"{company}" OneDB
site:linkedin.com/jobs "{company}" Informix
site:indeed.com "{company}" Informix
site:glassdoor.com "{company}" Informix
```

## Keyword Scores

Strong terms include:

```text
informix
ibm informix
informix dba
informix administrator
informix developer
informix migration
informix upgrade
informix hdr
informix rss
enterprise replication
onedb
genero
4gl
ifxjdbc
informix jdbc
```

## Confidence Bands

The script maps total scores to:

| Score | Confidence |
|---:|---|
| `>= 300` | Very High |
| `>= 150` | High |
| `>= 50` | Medium |
| otherwise | Low |

## Limitations

- Scraping search results can be brittle.
- Public search results are not proof of live system usage.
- The script has fixed input/output filenames.
- The extended version, `scanner_ext.py`, is better for repeatable work.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
