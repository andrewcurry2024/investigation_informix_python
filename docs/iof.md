# iof.py

## Purpose

`iof.py` compares Informix `onstat -g iof` / AIO global file output between a bad RSS period and a good RSS period. It is built for storage evidence: identifying which chunks/dbspaces had higher I/O rates, higher KAIO operation counts, higher estimated KAIO time, or worse read/write service times.

This is one of the stronger evidence scripts because it turns chunk-level I/O differences into CSV outputs and PNG charts.

## Typical Use Case

Use it when investigating:

- RSS lag that may be storage-related
- temp dbspace activity explosions
- logical log / physical log I/O differences
- chunks with worse KAIO read or write average time
- whether the bad server had more operations, slower operations, or both

## Input

Two `iof.out` files:

1. Bad/problem file
2. Good/baseline file

Expected section:

```text
AIO global files:
gfd pathname bytes read page reads bytes write page writes io/s
```

Followed by operation detail rows such as:

```text
kaio_reads  47320  0.0014
kaio_writes 246025 0.0013
```

## Usage

```bash
python3 io/iof.py bad.iof good.iof
```

With explicit duplicate handling and prefix:

```bash
python3 io/iof.py     new_weekend/bad_rss_log_ld6ux351/iof.out     new_weekend/good_rss_log_gibux354/iof.out     --mode last     --prefix rss_ld6_vs_good
```

## Command-Line Options

| Option | Values | Default | Meaning |
|---|---|---:|---|
| `--mode` | `last`, `sum` | `last` | How to handle duplicate pathnames |
| `--prefix` | text | `iof` | Prefix used for generated CSV and PNG files |

## Duplicate Handling

### `--mode last`

Uses the last occurrence for each pathname. Best when the file contains repeated snapshots and you want the final state.

### `--mode sum`

Sums counters/volumes and recalculates weighted averages. Useful if duplicate rows represent separate rows that need combining.

## Output Files

Generated CSVs:

```text
<prefix>_parsed_raw.csv
<prefix>_parsed_reduced.csv
<prefix>_good_vs_bad_comparison.csv
```

Generated PNGs include delta and narrative graphs, such as:

```text
<prefix>_07_delta_io_s.png
<prefix>_08_delta_kaio_read_ms.png
<prefix>_09_delta_kaio_write_ms.png
<prefix>_10_delta_kaio_total_s.png
<prefix>_11_delta_total_kaio_ops.png
<prefix>_12_tempdbs_kaio_total_good_vs_bad.png
<prefix>_13_tempdbs_kaio_total_pct_increase.png
<prefix>_14_top20_read_service_time_good_vs_bad.png
<prefix>_15_top20_write_service_time_good_vs_bad.png
<prefix>_16_log_phys_kaio_total_good_vs_bad.png
<prefix>_17_top20_delta_kaio_total_s.png
<prefix>_18_top20_delta_io_s.png
<prefix>_19_top20_delta_read_service_time.png
```

## Derived Metrics

| Metric | Meaning |
|---|---|
| `mb_read` | Bytes read converted to MiB |
| `mb_write` | Bytes written converted to MiB |
| `total_mb` | Read + write MiB |
| `total_pages` | Read + write pages |
| `kaio_read_ms` | KAIO read average time in ms |
| `kaio_write_ms` | KAIO write average time in ms |
| `total_kaio_ops` | KAIO reads + writes |
| `kaio_total_s` | operation count × average time, as a relative weight |

## Interpretation

The script itself prints a useful interpretation hint:

- Higher bad KAIO ms supports slower I/O completion.
- Higher bad KAIO ops with similar ms supports increased I/O volume/pressure.
- Higher bad ops and higher ms is the strongest storage-pressure signal.

## Practical Investigation Pattern

Run this alongside:

```bash
python3 io/comp_iov.py bad/iov.out good/iov.out
python3 osmon/osmon_comp_evidence.py bad/osmon.log good/osmon.log
python3 partition_profile/comp_ppf.py bad_profile.log good_profile.log onstat_t.log --plot-deltas
```

## Limitations

- Requires `AIO global files` section to be present.
- The `kaio_total_s` metric is a relative evidence metric, not elapsed wall-clock time.
- Pattern-specific charts assume naming conventions such as `tmpdbs`, `llogdbs`, and `physdbs`.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
