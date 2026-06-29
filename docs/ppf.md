# ppf.py

## Purpose

`ppf.py` is a quick before/after comparator for `onstat -g ppf` snapshots. It is intentionally simple: load two files, join by partnum, calculate deltas, and print top objects by key counters.

## Input

Two partition profile snapshots:

```text
before.ppf
after.ppf
```

Rows must start with a hex partnum such as:

```text
0x1000fa ... table_name
```

## Usage

```bash
python3 partition_profile/ppf.py before.ppf after.ppf
```

Example:

```bash
python3 partition_profile/ppf.py     run.053026165323/onstat.g.ppf.053026165323     run.053026165429/onstat.g.ppf.053026165429
```

## Output

Five ranked sections:

```text
TOP ISRD DELTA
TOP BUFFER READ DELTA
TOP SEQ SCAN DELTA
TOP ISWRT DELTA
TOP BUFFER WRITE DELTA
```

Each row includes:

```text
<delta> <partnum> <object name>
```

## Counters

| Counter | Meaning |
|---|---|
| `isrd` | Index/dbspace reads depending on Informix counter context |
| `iswrt` | Writes |
| `bfrd` | Buffer reads |
| `bfwrt` | Buffer writes |
| `seqsc` | Sequential scans |

## When To Use

Use this for quick checks where you have two snapshots close together and just want to know what moved.

For sampled time-window analysis, use `parse_profile.py` or `comp_ppf.py` instead.

## Limitations

- Only compares partnums present in both files.
- No CSV or graph output.
- Does not resolve transient unknown/temp partnums specially.
- Does not bucket by time.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
