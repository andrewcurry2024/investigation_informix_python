# ioh.py

## Purpose

`ioh.py` parses Informix I/O history style output and summarises each dbspace/chunk by total I/O, peak I/O and trend slope.

It is useful as a quick-ranking tool when you want to see which dbspaces were busiest and which were trending upwards during the capture.

## Input

A single `ioh.out` text file.

The parser expects a dbspace/path header row followed by time-series rows.

Header-like row:

```text
3 rootdbs_01 81920 40 1232896 602 494.8
```

Time-series row:

```text
16:53:46 5 0.1 0.00054 25 0.4 0.00112
```

## Usage

```bash
python3 io/ioh.py ioh.out
```

## Output

The script prints:

- number of parsed rows
- first few parsed rows
- busiest dbspaces by total I/O
- worst/degrading dbspaces by trend slope

It also writes:

```text
ioh_summary.csv
```

## Metrics

| Metric | Meaning |
|---|---|
| `read_ops` | Read operations |
| `read_ios` | Read I/O rate/value from source row |
| `read_op_time` | Read operation time |
| `write_ops` | Write operations |
| `write_ios` | Write I/O rate/value from source row |
| `write_op_time` | Write operation time |
| `total_io` | `read_ios + write_ios` |
| `peak_io` | Highest `total_io` seen for that path |
| `trend_slope` | Simple linear slope over sample order |

## Interpretation

A positive trend slope means the dbspace load increased during the sample. This does not by itself prove a fault, but it is a useful pointer when correlated with RSS lag, KAIO timings, osmon latency, or partition profile deltas.

## Limitations

- It uses simple string sorting of `HH:MM:SS`, so the file should represent a sensible time window.
- Trend slope is a quick indicator, not a statistical model.
- It does not create graphs; use `ioh_graph.py` for visual output.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
