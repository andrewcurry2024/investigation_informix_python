# comp_ppf.py

## Purpose

Compare two Informix partition_profile files.

### CLI description

Compare two Informix partition_profile files. File A is treated as the bad/problem period. File B is treated as the good/clean period. UNKNOWN partitions are aggregated as TEMPTABLESUSED.

## Location

`partition-profile/comp_ppf.py`

## Usage

```bash
python partition-profile/comp_ppf.py \
    VALUE \
    VALUE \
    VALUE
```

## Command line options

| Option | Required | Default | Choices | Description |
|---|---:|---|---|---|
| `profile_file_a` | Yes | `` | `` | Bad/problem partition_profile file |
| `profile_file_b` | Yes | `` | `` | Good/clean partition_profile file |
| `lookup_file` | Yes | `` | `` | Partition profile lookup file containing partnum/name mapping |
| `--label-a` | No | `Bad weekend` | `` | Label for profile file A |
| `--label-b` | No | `Good weekend` | `` | Label for profile file B |
| `--start` | No | `15:00` | `` | Start time HH:MM. Default: 15:00 |
| `--end` | No | `18:00` | `` | End time HH:MM. Default: 18:00 |
| `--period` | No | `5min` | `` | Bucket size, e.g. 1min, 5min, 15min. Default: 5min |
| `--rolling` | No | `3` | `` | Rolling average window in periods. Default: 3 (type: `int`) |
| `--top` | No | `20` | `` | Top N objects to report/plot. Default: 20 (type: `int`) |
| `--plot-deltas` | No | `` | `` | Use counter deltas instead of raw cumulative values. Strongly recommended. (action: `store_true`) |
| `--metrics` | No | `,.join(...)` | `` | Comma-separated metrics to process. Default: isrd_delta,bfrd_delta,iswrt_delta,bfwrt_delta,seqsc_delta |
| `--out-prefix` | No | `None` | `` | Output prefix |
| `--no-png` | No | `` | `` | Do not write PNGs, only PDF/CSV (action: `store_true`) |
| `--no-fast-break` | No | `` | `` | Do not stop reading after end time (action: `store_true`) |
| `--progress-every` | No | `1000000` | `` | Progress print frequency. 0 disables. (type: `int`) |

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `filename` | open | file/path expression | line 254 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `fig` | savefig | image/plot output | line 780 |
| `output_file` | savefig | image/plot output | line 888 |
| `period_csv` | to_csv | CSV file | line 1113 |
| `source_summary_csv` | to_csv | CSV file | line 1114 |
| `object_compare_csv` | to_csv | CSV file | line 1115 |
| `period_compare_csv` | to_csv | CSV file | line 1116 |
| `group_summary_csv` | to_csv | CSV file | line 1117 |
| `group_period_compare_csv` | to_csv | CSV file | line 1118 |
| `combined_csv` | to_csv | CSV file | line 1373 |
| `comparable_csv` | to_csv | CSV file | line 1374 |
| `lookup_csv` | to_csv | CSV file | line 1393 |
| `all_charts_pdf` | PdfPages | PDF report | line 1402 |

## Dependencies

- `matplotlib`
- `pandas`

## Functions

### `parse_args()`

No function docstring detected.

### `validate_hhmm(value, arg_name)`

No function docstring detected.

### `hhmm_to_minutes(hhmm)`

No function docstring detected.

### `minutes_to_hhmm(minutes)`

No function docstring detected.

### `hhmm_in_window(hhmm, start_hhmm, end_hhmm)`

No function docstring detected.

### `should_fast_break(hhmm, start_hhmm, end_hhmm, seen_window)`

No function docstring detected.

### `is_timestamp_line(line)`

No function docstring detected.

### `parse_int_fast(value)`

No function docstring detected.

### `normalise_partnum(value)`

No function docstring detected.

### `elapsed_minutes_from_timestamp(time_s, start_hhmm)`

No function docstring detected.

### `full_number_formatter(x, pos)`

No function docstring detected.

### `elapsed_minutes_formatter_factory(start_hhmm)`

No function docstring detected.

### `apply_full_number_y_axis(ax)`

No function docstring detected.

### `apply_full_number_x_axis(ax)`

No function docstring detected.

### `apply_elapsed_time_axis(ax, start_hhmm)`

No function docstring detected.

### `truncate_label(label, max_len=95)`

No function docstring detected.

### `safe_filename_part(value)`

No function docstring detected.

### `has_negative_counter(parts)`

No function docstring detected.

### `parse_partition_profile_fast(filename, source_label, start_hhmm, end_hhmm, want_deltas=True, fast_break=True, progress_every=1000000)`

No function docstring detected.

### `parse_partition_lookup(filename)`

No function docstring detected.

### `join_lookup(profile_df, lookup_df)`

No function docstring detected.

### `add_comparison_object_columns(df)`

Important bit:

Known objects are compared individually by partnum/table.

UNKNOWN objects are not compared individually because their partnums are
transient and may not exist in both samples. Instead, all UNKNOWN activity
is aggregated into one synthetic object called TEMPTABLESUSED.

### `build_period_totals(df, metric, period)`

No function docstring detected.

### `add_rolling_average(period_df, rolling_window)`

No function docstring detected.

### `build_object_summary(period_df, label_a, label_b)`

No function docstring detected.

### `build_period_overall(period_df, label_a, label_b)`

No function docstring detected.

### `build_group_summary(object_compare)`

Slightly different to the object summary.

This returns just:
  - KNOWN_OBJECT
  - TEMPTABLESUSED

but the primary comparison is object_summary, where TEMPTABLESUSED is already
one synthetic comparable row.

### `build_group_period_compare(period_df, label_a, label_b)`

No function docstring detected.

### `print_metric_verdict(metric, object_compare, group_summary, label_a, label_b)`

No function docstring detected.

### `add_summary_page_to_pdf(pdf, title, lines)`

No function docstring detected.

### `format_stats_lines(stats)`

No function docstring detected.

### `format_object_lines(title, df, sort_col, limit)`

No function docstring detected.

### `format_group_lines(metric, group_summary)`

No function docstring detected.

### `plot_period_overall(period_compare, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_group_bar(group_summary, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_group_periods(group_period_compare, compare_group, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_top_bad_good_bar(object_compare, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_bad_minus_good_bar(object_compare, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `plot_individual_comparison(period_df, object_row, metric, args, output_file, pdf=None, write_png=True)`

No function docstring detected.

### `process_metric(df, metric, args, out_prefix, safe_start, safe_end, pdf)`

No function docstring detected.

### `main()`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
