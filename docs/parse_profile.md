# parse_profile.py

## Purpose

Fast parser for Informix partition profile logs.

### CLI description

Fast parser for Informix partition profile logs. Joins partnum to table name lookup, buckets by period, calculates rolling averages, and outputs CSV/PNG/PDF.

## Location

`partition-profile/parse_profile.py`

## Usage

```bash
python partition-profile/parse_profile.py \
    VALUE \
    VALUE
```

## Command line options

| Option | Required | Default | Choices | Description |
|---|---:|---|---|---|
| `profile_file` | Yes | `` | `` | Sampled partition_profile log file |
| `lookup_file` | Yes | `` | `` | Partition profiles lookup file containing partnum/name mapping |
| `--start` | No | `14:00` | `` | Start time HH:MM. Default: 14:00 |
| `--end` | No | `16:30` | `` | End time HH:MM. Default: 16:30 |
| `--period` | No | `5min` | `` | Bucket size, e.g. 1min, 5min, 15min, 30min, 1h. Default: 5min |
| `--rolling` | No | `3` | `` | Rolling average window in number of periods. Default: 3 (type: `int`) |
| `--top` | No | `10` | `` | Top N tables/partitions to graph. Default: 10 (type: `int`) |
| `--out-prefix` | No | `None` | `` | Output prefix. Default uses profile filename stem |
| `--plot-deltas` | No | `` | `` | Use per-sample deltas instead of raw counter values (action: `store_true`) |
| `--min-period-total` | No | `0` | `` | Minimum period total to include in text notes. Default: 0 (type: `int`) |
| `--no-png` | No | `` | `` | Do not write individual PNGs, only write the combined PDF (action: `store_true`) |
| `--no-fast-break` | No | `` | `` | Do not stop reading after the end time is passed. Use this if the file contains multiple days and you want all matching time windows. (action: `store_true`) |
| `--progress-every` | No | `1000000` | `` | Print progress every N lines. Default: 1000000. Set 0 to disable. (type: `int`) |

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `filename` | open | file/path expression | line 357 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `fig` | savefig | image/plot output | line 688 |
| `output_file` | savefig | image/plot output | line 752 |
| `output_file` | open | file/path expression | line 807 |
| `period_csv` | to_csv | CSV file | line 885 |
| `period_ranked_csv` | to_csv | CSV file | line 886 |
| `top_csv` | to_csv | CSV file | line 887 |
| `joined_csv` | to_csv | CSV file | line 1061 |
| `lookup_csv` | to_csv | CSV file | line 1062 |
| `all_charts_pdf` | PdfPages | PDF report | line 1070 |

## Dependencies

- `matplotlib`
- `pandas`

## Functions

### `parse_args()`

No function docstring detected.

### `normalise_partnum(value)`

Normalise Informix partnum values so these match:

  0x1000fa
  1000fa
  001000fa

all become:

  1000fa

### `validate_hhmm(value, arg_name)`

No function docstring detected.

### `is_timestamp_line(line)`

Cheap timestamp check before split().

Expected:

  2026-06-13 00:01:30 ...

### `hhmm_in_window(hhmm, start_hhmm, end_hhmm)`

Time-only window test.

Handles:

  14:00 -> 16:30

and wrapped windows:

  23:00 -> 02:00

### `should_fast_break(hhmm, start_hhmm, end_hhmm, seen_window)`

Safe only for normal same-day/sequential windows.

If file is single-day and ordered, this avoids reading the rest of the file.

### `parse_int_fast(value)`

No function docstring detected.

### `full_number_formatter(x, pos)`

Matplotlib axis formatter.

Forces 1000000 to render as:

  1,000,000

rather than:

  1e6

### `apply_full_number_axis(ax)`

Disable scientific notation and use full comma-separated numbers.

### `apply_time_axis(ax)`

Format datetime X-axis as HH:MM.

### `has_negative_io_counter(parts)`

Return True if any IO counter is negative.

This catches rows like:

  bfrd=-4219904008

These are skipped completely and do not update delta state.

### `parse_partition_profile_fast(filename, start_hhmm, end_hhmm, want_deltas=False, fast_break=True, progress_every=1000000)`

Fast sequential parser.

It avoids:
  - building rows outside the requested window
  - parsing all columns
  - pd.to_datetime() per line
  - split() for obvious out-of-window rows unless needed for delta warm-up

Keeps only:
  datetime
  partnum
  isrd
  bfrd
  isrd_delta
  bfrd_delta

If want_deltas=True, it tracks previous counters for each partnum even before
the window starts, so the first in-window sample can get a real delta.

Rows containing negative IO counters are skipped completely and do not update
prev_by_partnum. This avoids poisoning delta calculations after a wrapped value.

### `parse_partition_lookup(filename)`

Parse lookup file in this format:

  Partition profiles
  partnum    lkrqs lkwts dlks touts isrd iswrt isrwt isdel bfrd bfwrt seqsc rhitratio name
  0x6        0     0     0    0     0    0     0     0     0    0     0     0         sysmaster:informix.syscfgtab
  0xa        0     0     0    0     0    0     0     0     0    0     0     0         sysmaster:informix.sysptnhdr

Main mapping:

  partnum -> name

### `join_lookup(profile_df, lookup_df)`

No function docstring detected.

### `build_period_totals(df, metric, period)`

Create one row per period/table with the total metric for that period.

### `add_rolling_average(period_df, rolling_window)`

Add rolling average by partnum/table across period totals.

### `get_top_tables(period_df, top_n)`

Rank tables by total over the selected time window.

### `mark_top_per_period(period_df)`

Rank each table within each period by period_total.

### `truncate_label(label, max_len=85)`

No function docstring detected.

### `add_summary_page_to_pdf(pdf, title, lines)`

Add a simple text summary page to the combined PDF.

### `plot_top_over_time(period_df, top_df, value_col, title, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_top_bar(top_df, title, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `write_period_notes(period_ranked_df, top_n, min_period_total, output_file)`

Write readable text notes showing top N per period.

### `format_top_summary_lines(top_df, metric, top_n)`

No function docstring detected.

### `process_metric(filtered_df, metric, args, out_prefix, safe_start, safe_end, mode, pdf=None)`

No function docstring detected.

### `main()`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
