# osmon_comp.py

## Purpose

`osmon_comp.py` compares two OSMON storage datasets, labelled in the code as previous/current weekend. It aligns data by time-of-day, resamples it, calculates summary deltas, writes CSV outputs and creates comparison charts.

It is useful when you want to compare broad storage behaviour across two similar periods.

## Input

Two OSMON files:

```text
previous_weekend_file
current_weekend_file
```

## Usage

```bash
python3 osmon/osmon_comp.py previous_osmon.log current_osmon.log
```

Example:

```bash
python3 osmon/osmon_comp.py     new_data/ld620/osmon_sum_1.log     new_data/sat27/osmon_sum_1.log
```

## Fixed Settings In Script

```python
START_TIME = time(15, 0, 0)
END_TIME   = time(18, 0, 0)
RESAMPLE_RULE = "1min"
```

## Compared Metrics

```text
rmbs_tot
wmbs_tot
await_avg
await_hotavg
svctm_hotavg
pctutil_avg
pctutil_hotavg
```

## Outputs

CSV files:

```text
osmon_compare_summary.csv
osmon_compare_timeseries_delta.csv
osmon_compare_latency_by_read_bucket.csv
```

Charts shown interactively:

- previous vs current throughput
- throughput delta
- previous vs current latency
- latency delta
- previous vs current utilisation
- utilisation delta
- mean percentage change
- P95 percentage change

## Bucket Analysis

The script includes a latency-by-read-throughput bucket analysis. This is useful because it checks whether latency differences remain visible at broadly comparable read throughput levels.

## Interpretation

Look for:

- higher await/service time in the bad/current period
- lower completed read throughput despite worse service time
- higher p95 latency rather than only higher mean latency
- similar utilisation but worse service time, which can suggest not simple aggregate saturation

## Limitations

- Labels are previous/current rather than bad/good.
- Time window is hard-coded.
- Uses `plt.show()` rather than saving all graphs.
- For shareable evidence, prefer `osmon_comp_evidence.py`.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
