# ioh_graph.py

## Purpose

`ioh_graph.py` graphs read and write operation time from an Informix IOH-style capture. It focuses on the top 10 dbspaces by summed read operation time and the top 10 by summed write operation time.

## Input

One IOH-style text file.

## Usage

```bash
python3 io/ioh_graph.py ioh.out
```

## Output

The script prints the parsed row count and opens two matplotlib charts:

1. `IOH Trend — READ Op Time (Top 10 Dbspaces)`
2. `IOH Trend — WRITE Op Time (Top 10 Dbspaces)`

## When To Use

Use this when you want a quick visual check of whether a small number of dbspaces dominate read/write operation time.

## Notes For Headless Servers

The script currently uses:

```python
plt.show()
```

If running on a server without a graphical display, change this to `plt.savefig(...)` or run with a non-interactive matplotlib backend.

Suggested quick edit:

```python
plt.savefig("ioh_read_top10.png", dpi=150)
```

and repeat for the write chart.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
