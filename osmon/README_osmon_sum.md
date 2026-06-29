# osmon_sum.py

## Purpose

`osmon_sum.py` plots a quick three-panel summary of a single OSMON storage dataset. It is useful for a first look at storage throughput, latency and utilisation in a fixed time window.

## Input

One OSMON summary file with columns similar to:

```text
date time rmbs_tot wmbs_tot await_avg pctutil_avg await_hotcnt await_hotavg svctm_hotcnt svctm_hotavg pctutil_hotcnt pctutil_hotavg ...
```

The script requires at least 16 fields per row and skips repeated header rows.

## Usage

```bash
python3 osmon/osmon_sum.py osmon_sum_1.log
```

## Time Window

The current script filters to:

```text
15:00 to 18:00
```

If you regularly analyse different windows, convert these hard-coded values to command-line options or use `osmon_comp_evidence.py`, which already supports `--start` and `--end`.

## Output

The script opens a matplotlib figure with three stacked charts:

1. Disk throughput
   - Read MB/s
   - Write MB/s

2. Disk latency
   - `await_avg`
   - `await_hotavg`

3. Disk utilisation
   - `%util_avg`
   - `%util_hotavg`

## When To Use

Use it for quick visual review of one host/period before doing a formal bad-vs-good comparison.

## Limitations

- No CSV output.
- Uses `plt.show()`, so it expects a graphical session.
- Fixed time window.
- For evidence packs, use `osmon_comp_evidence.py` instead.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
