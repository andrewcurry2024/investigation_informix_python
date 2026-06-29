# comp_ppf.py

## Purpose

`comp_ppf.py` compares two sampled Informix partition profile logs: one bad/problem period and one good/clean period. It is built for evidence generation and is more advanced than `ppf.py` because it supports time windows, period bucketing, rolling averages, multiple metrics, CSV outputs, PNG charts and a combined PDF report.

A key feature is that `UNKNOWN` partitions are aggregated into a single synthetic object called `TEMPTABLESUSED`. This avoids false comparisons between transient temp partnums that may not exist in both files.

## Input

1. Bad/problem partition profile file
2. Good/clean partition profile file
3. Lookup file containing partnum/name mapping

## Usage

```bash
python3 partition_profile/comp_ppf.py     bad_partition_profile.log     good_partition_profile.log     onstat_t.log     --label-a "Bad RSS"     --label-b "Good RSS"     --start 15:30     --end 18:30     --period 5min     --rolling 3     --top 20     --plot-deltas
```

## Command-Line Options

| Option | Default | Meaning |
|---|---:|---|
| `profile_file_a` | required | Bad/problem partition profile file |
| `profile_file_b` | required | Good/clean partition profile file |
| `lookup_file` | required | Partnum lookup file |
| `--label-a` | `Bad weekend` | Label for file A |
| `--label-b` | `Good weekend` | Label for file B |
| `--start` | `15:00` | Start time `HH:MM` |
| `--end` | `18:00` | End time `HH:MM` |
| `--period` | `5min` | Bucket size |
| `--rolling` | `3` | Rolling average periods |
| `--top` | `20` | Top N objects to report/plot |
| `--plot-deltas` | off | Use counter deltas; strongly recommended |
| `--metrics` | default delta list | Comma-separated metrics |
| `--out-prefix` | generated | Output prefix |
| `--no-png` | off | Skip PNGs, still write CSV/PDF |
| `--no-fast-break` | off | Continue reading after end time |
| `--progress-every` | `1000000` | Progress print frequency |

## Default Metrics

```text
isrd_delta
bfrd_delta
iswrt_delta
bfwrt_delta
seqsc_delta
```

Other valid metric families include:

```text
seqsc
lkrqs
lkwts
touts
isrd
iswrt
isrwt
isdel
dlks
bfrd
bfwrt
```

and their `_delta` forms.

## UNKNOWN / TEMP Handling

Known objects are compared by object/partnum.

Unknown objects are rolled up into:

```text
TEMPTABLESUSED
```

This is important during Informix troubleshooting because temp partnums can be transient. Comparing unknown temp partnums one by one can produce misleading results.

## Outputs

The script creates:

- joined raw CSV
- comparable CSV
- parsed lookup CSV
- per-metric period totals CSV
- per-metric source summary CSV
- per-metric object comparison CSV
- per-metric period comparison CSV
- per-metric group summary CSV
- per-metric group period comparison CSV
- combined PDF report
- optional PNG charts

## Example Evidence Questions

This script helps answer:

- Was total read activity higher in the bad period?
- Which named objects were higher in the bad period?
- Was temp-table activity a major contributor?
- Did the workload differ across the whole window or only in bursts?
- Were sequential scans materially different?
- Were writes/buffer writes enough to matter?

## For RSS Lag Investigations

A typical workflow:

```bash
python3 partition_profile/comp_ppf.py     new_data/ld620/partition_profile_1.log     new_data/sat27/partition_profile_1.log     new_data/onstat_t.log     --label-a "LD6 problem period"     --label-b "SAT27 comparison"     --start 15:30     --end 18:30     --period 5min     --rolling 3     --top 20     --plot-deltas
```

Then cross-check the top objects against:

```bash
python3 sql/parse_his.py < onstat.g.his.out
python3 io/iof.py bad.iof good.iof
python3 osmon/osmon_comp_evidence.py bad_osmon.log good_osmon.log
```

## Limitations

- Lookup quality directly affects named object reporting.
- Large input files can generate many outputs.
- Delta metrics are usually preferable; raw counters can mislead if used casually.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
