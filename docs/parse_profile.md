# parse_profile.py

## Purpose

`parse_profile.py` is the main single-file Informix partition profile analysis tool. It parses sampled partition profile logs, joins partnums to object names using a lookup file, buckets activity by time period, calculates rolling averages, and writes CSV/PNG/PDF evidence.

It is designed for hotspot analysis: identifying which tables, indexes, or unknown/temp objects generated the highest reads or buffer reads during an incident window.

## Input

1. Sampled partition profile log
2. Lookup file containing partnum-to-name mappings, usually from `onstat -t` or partition profile lookup output

## Usage

```bash
python3 partition_profile/parse_profile.py     partition_profile_1.log     onstat_t.log     --start 16:00     --end 16:59     --period 1min     --rolling 1     --top 10     --plot-deltas     --no-png
```

## Command-Line Options

| Option | Default | Meaning |
|---|---:|---|
| `profile_file` | required | Sampled partition profile log |
| `lookup_file` | required | Partnum/name mapping file |
| `--start` | `14:00` | Start time, `HH:MM` |
| `--end` | `16:30` | End time, `HH:MM` |
| `--period` | `5min` | Bucket size, e.g. `1min`, `5min`, `15min` |
| `--rolling` | `3` | Rolling average window in periods |
| `--top` | `10` | Top N tables/partitions to graph |
| `--out-prefix` | profile filename stem | Output prefix |
| `--plot-deltas` | off | Use per-sample deltas instead of raw counters |
| `--min-period-total` | `0` | Minimum period total for text notes |
| `--no-png` | off | Skip individual PNG files; still writes PDF |
| `--no-fast-break` | off | Continue reading after end time |
| `--progress-every` | `1000000` | Progress logging interval; `0` disables |

## Important Behaviour

### Time Window Filtering

The script filters rows by `HH:MM`. It supports normal windows such as:

```text
14:00 -> 16:30
```

It also has logic for wrapped windows such as:

```text
23:00 -> 02:00
```

### Delta Mode

With `--plot-deltas`, the script tracks previous counters by partnum and calculates deltas. Negative deltas are clamped to zero, which helps avoid counter wrap poisoning the results.

For workload analysis, delta mode is usually the correct mode.

### Negative Counter Protection

Rows with negative values in key I/O counters are skipped completely and do not update the previous counter state.

Counters checked include:

```text
isrd
iswrt
isrwt
isdel
bfrd
bfwrt
```

## Outputs

The script writes:

- joined filtered CSV
- parsed lookup CSV
- metric period totals CSV
- period ranked CSV
- top-N summary CSV
- top-N period notes TXT
- combined PDF report
- optional PNG charts

Output names include the selected time window, period, rolling window and mode.

## Metrics

In raw mode:

```text
isrd
bfrd
```

In delta mode:

```text
isrd_delta
bfrd_delta
```

## Interpretation

Symptoms to look for:

- one or two objects dominating `isrd_delta`
- high `bfrd_delta` compared with previous known-good samples
- repeated top objects across many buckets
- `UNKNOWN` objects suggesting missing lookup coverage or transient/temp activity

## Related Scripts

Use this with:

```bash
python3 partition_profile/comp_ppf.py bad.log good.log onstat_t.log --plot-deltas
python3 sql/parse_his.py < onstat.g.his.out
python3 io/iof.py bad.iof good.iof
```

## Limitations

- Currently focuses primarily on `isrd` and `bfrd` for single-profile analysis.
- Lookup quality matters. Bad or incomplete lookup files produce more `UNKNOWN` rows.
- Output file volume can be high for large windows and many metrics.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
