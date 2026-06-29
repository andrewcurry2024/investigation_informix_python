# osmon_comp_evidence.py

## Purpose

`osmon_comp_evidence.py` compares bad vs good OSMON storage datasets and writes a PDF evidence pack. It is the most useful OSMON script when you need something shareable for an incident review, RCA note, or customer-facing technical explanation.

The report focuses on whether the bad period was busier, slower, or both.

## Input

Two OSMON files:

1. Bad/problem file
2. Good/clean file

## Usage

```bash
python3 osmon/osmon_comp_evidence.py     bad_osmon.log     good_osmon.log     --label-a "Bad period"     --label-b "Good period"     --start 15:30     --end 18:30     --period 1min     --out-prefix osmon_ld6_evidence
```

## Command-Line Options

| Option | Default | Meaning |
|---|---:|---|
| `bad_file` | required | Bad/problem OSMON file |
| `good_file` | required | Good/clean OSMON file |
| `--label-a` | `Bad period` | Label for bad file |
| `--label-b` | `Good period` | Label for good file |
| `--start` | `15:30` | Start time `HH:MM` |
| `--end` | `18:30` | End time `HH:MM` |
| `--period` | `1min` | Resample period |
| `--bucket-size` | `100` | Read MB/s bucket size |
| `--min-bucket-samples` | `10` | Minimum samples per bucket |
| `--out-prefix` | `osmon_evidence` | Output file prefix |

## Outputs

CSV files:

```text
<out-prefix>_headline_summary.csv
<out-prefix>_aligned_timeseries.csv
<out-prefix>_latency_service_by_read_bucket.csv
<out-prefix>_correlations.csv
<out-prefix>_service_time_thresholds.csv
<out-prefix>_service_time_efficiency_summary.csv
<out-prefix>_service_time_efficiency_timeseries.csv
```

PDF:

```text
<out-prefix>_osmon_evidence_report.pdf
```

PNG files:

```text
<out-prefix>_evidence_graphs_with_service_time.png
<out-prefix>_bucket_deltas_with_service_time.png
```

## Report Sections

The PDF includes:

- input and purpose page
- evidence verdict
- headline summary
- comparable read-throughput bucket analysis
- wait and service-time threshold counts
- service-time efficiency summary
- correlation analysis
- evidence graphs
- bucket delta graphs

## Key Metrics

| Metric | Meaning |
|---|---|
| `rmbs_tot` | Completed read MB/s |
| `wmbs_tot` | Completed write MB/s |
| `await_avg` | Average wait time |
| `await_hotavg` | Hot-device wait time |
| `svctm_hotavg` | Hot-device service time |
| `pctutil_avg` | Average utilisation |
| `pctutil_hotavg` | Hot-device utilisation |
| `cpu_avg_busy` | Average CPU busy from OSMON row |

## Evidence Logic

The script explicitly tries to separate:

- **more work**: higher completed throughput / more MB/s
- **slower service**: higher `await_hotavg` or `svctm_hotavg`
- **efficiency loss**: less read MB/s per service-time ms
- **threshold behaviour**: more samples above wait/service thresholds

## Suggested Interpretation Pattern

Strong storage-pressure evidence is usually:

- bad period has worse hot service time
- bad period completes less or similar throughput
- comparable read-throughput buckets still show worse service/wait time
- service-time threshold counts are higher in the bad period

## Limitation / Caveat

The script does **not** prove root cause on its own. It provides host-level storage evidence that should be correlated with Informix metrics such as `iof`, `iov`, `partition_profile`, RSS backlog and SQL history.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
