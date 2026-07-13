# parse_partition_sum.py

## Purpose

parse_partition_sum.py

### Module notes

parse_partition_sum.py

Parse Informix partition_summary TOP blocks, join partnums to onstat -T
Tblspaces output, plot metrics over time, and optionally bundle all plots
into a single PDF.

Input partition_summary example:

  2026-07-11 00:01:48 TOP partions for npages
  2026-07-11 00:01:48 800061     1         31616
  2026-07-11 00:01:48 9000a4     2         31616

Lookup onstat -T example:

  Tblspaces
      n address          flgs      ucnt tblnum   physaddr         npages ...
      1 69c0f548         8         0    6        0:0              0      ... sysmaster:informix.syscfgtab
     26 58d473d0         0         1    100001   1:14             8800   ... rootdbs:informix.TBLSpace

Outputs:

  output-dir/partition_summary_joined.csv
  output-dir/unmapped_partnums.csv
  output-dir/metric_<metric>.png
  output-dir/<pdf name>

Example:

  python3 parse_partition_sum.py     --summary 0711/partition_summary_1.log     --lookup onstat_T     --output-dir partition_out     --pdf partition_summary_report.pdf     --start "2026-07-11 00:00:00"     --end "2026-07-11 06:00:00"     --top-n 10     --smooth-ewm-span 5

### CLI description

Parse Informix partition summary TOP blocks, join to onstat -T Tblspaces lookup, plot metrics and create a PDF.

## Location

`partition-profile/parse_partition_sum.py`

## Usage

```bash
python partition-profile/parse_partition_sum.py \
    --lookup VALUE
```

## Command line options

| Option | Required | Default | Choices | Description |
|---|---:|---|---|---|
| `--summary` | No | `partition_summary` | `` | Path to partition_summary file. Default: partition_summary |
| `--lookup` | Yes | `` | `` | Path to onstat -T Tblspaces lookup file. |
| `--output-dir` | No | `partition_summary_out` | `` | Output directory. Default: partition_summary_out |
| `--pdf` | No | `partition_summary_report.pdf` | `` | PDF report file name. If relative, written inside output-dir. Use --no-pdf to skip. Default: partition_summary_report.pdf |
| `--no-pdf` | No | `` | `` | Do not create combined PDF report. (action: `store_true`) |
| `--no-png` | No | `` | `` | Do not save individual PNG files. (action: `store_true`) |
| `--start` | No | `None` | `` | Inclusive start datetime. Example: '2026-07-11 00:00:00' |
| `--end` | No | `None` | `` | Inclusive end datetime. Example: '2026-07-11 06:00:00' |
| `--metrics` | No | `,.join(...)` | `` | Comma-separated metrics to parse/plot. |
| `--top-n` | No | `15` | `` | Number of partitions/tables to plot per metric. Use 0 for all. Default: 15 (type: `int`) |
| `--top-by` | No | `max` | `['max', 'mean', 'last', 'total']` | How to choose top partitions/tables. Default: max |
| `--smooth-window` | No | `0` | `` | Rolling smoothing window. Example: 3, 5, 10. Default: 0 disabled. (type: `int`) |
| `--smooth-ewm-span` | No | `0` | `` | Exponential smoothing span. Example: 5, 10, 20. Default: 0 disabled. (type: `int`) |
| `--fill-missing-zero` | No | `` | `` | Treat missing TOP entries as zero. Default leaves them as NaN because missing from TOP-N does not necessarily mean zero. (action: `store_true`) |
| `--no-raw-underlay` | No | `` | `` | When smoothing, do not plot faint raw data underneath. (action: `store_true`) |
| `--exclude-sysmaster` | No | `` | `` | Exclude sysmaster:* objects. (action: `store_true`) |
| `--exclude-sysadmin` | No | `` | `` | Exclude sysadmin:* objects. (action: `store_true`) |
| `--exclude-sysutils` | No | `` | `` | Exclude sysutils:* objects. (action: `store_true`) |
| `--fig-width` | No | `24.0` | `` | Figure width for PNG/PDF chart pages. Default: 16 (type: `float`) |
| `--fig-height` | No | `10.0` | `` | Figure height for PNG/PDF chart pages. Default: 9 (type: `float`) |

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `filename` | open | file/path expression | line 214 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `fig` | savefig | image/plot output | line 766 |
| `all_csv` | to_csv | CSV file | line 772 |
| `metric_file` | to_csv | CSV file | line 779 |
| `output_file` | to_csv | CSV file | line 803 |
| `pdf_path` | PdfPages | PDF report | line 1112 |
| `png_file` | savefig | image/plot output | line 1147 |

## Dependencies

- `matplotlib`
- `pandas`

## Functions

### `object_type(name)`

Classify object type from tblname.

### `normalise_partnum(value)`

Normalise Informix partnum values so these match:

  0x1000fa
  1000fa
  001000fa

all become:

  1000fa

### `to_number_or_none(value)`

Convert integer-ish text to int, otherwise return None.

### `parse_datetime_arg(value, arg_name)`

Parse datetime argument supplied as:

  YYYY-MM-DD HH:MM:SS
  YYYY-MM-DDTHH:MM:SS
  YYYY-MM-DD HH:MM
  YYYY-MM-DD

Returns pandas Timestamp or None.

### `parse_partition_lookup(filename)`

Parse Informix onstat -T Tblspaces lookup.

Expected format:

  Tblspaces
      n address          flgs      ucnt tblnum   physaddr         npages     nused      npdata     nrows      nextns name
      1 69c0f548         8         0    6        0:0              0          0          0          0          0      sysmaster:informix.syscfgtab
     26 58d473d0         0         1    100001   1:14             8800       8254       0          742        24     rootdbs:informix.TBLSpace

Main mapping:

  tblnum -> name

Returns dataframe with:

  lookup_partnum
  partnum_key
  tblname
  lookup_physaddr
  lookup_npages
  lookup_nused
  lookup_npdata
  lookup_nrows

### `parse_partition_summary(filename, allowed_metrics=None)`

Parse repeated timestamp TOP blocks from partition_summary.

Produces:

  timestamp
  metric
  partnum
  partnum_key
  rank
  value
  source_lineno

Handles typo:

  TOP partions for npages

and normal spelling:

  TOP partitions for npages

### `apply_time_filter(df, start_ts=None, end_ts=None)`

Filter dataframe by timestamp.

Start is inclusive.
End is inclusive.

### `make_display_name(row, max_len=110)`

Prefer table name when known, otherwise use partnum.

Examples:

  stores:informix.orders [800061]
  UNKNOWN [800061]

### `choose_top_entities(metric_df, top_n, top_by)`

Choose which partitions/tables to plot for one metric.

top_by:

  max    - highest observed value during the period
  mean   - highest mean value during the period
  last   - highest value at the latest timestamp
  total  - highest total/sum across the period

### `apply_smoothing(pivot, smooth_window=0, smooth_ewm_span=0)`

Apply optional smoothing.

Rolling:

  --smooth-window 3
  --smooth-window 5

EWM:

  --smooth-ewm-span 5
  --smooth-ewm-span 10

If both are supplied, rolling is applied first, then EWM.

### `nice_metric_title(metric)`

No function docstring detected.

### `create_metric_figure(df, metric, top_n=15, top_by=max, smooth_window=0, smooth_ewm_span=0, fill_missing_zero=False, plot_raw=True, figsize=(16, 9))`

Create matplotlib figure for one metric.

Missing TOP entries are left as NaN by default because absence from
a TOP-N block does not necessarily mean the value was zero.

### `add_pdf_cover_page(pdf, df, args, generated_metrics, start_ts=None, end_ts=None)`

Add a simple cover/summary page to the PDF.

### `write_metric_csvs(df, output_dir)`

No function docstring detected.

### `write_unmapped_report(df, output_dir)`

No function docstring detected.

### `print_summary(df, before_filter_rows=None)`

No function docstring detected.

### `parse_args(argv)`

No function docstring detected.

### `main(argv=None)`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
