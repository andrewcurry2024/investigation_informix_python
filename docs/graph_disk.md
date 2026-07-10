# graph_disk.py

## Purpose

graph_disk_metric_top10_pdf.py

### Module notes

graph_disk_metric_top10_pdf.py

Graph diskmon.py CSV output and create PNGs + PDF report.

Key behaviour:
  * EACH metric graph selects its own top N devices by that metric.
    Example: await graph = top 10 by await_ms, queue graph = top 10 by queue_depth,
    inflight graph = top 10 by inflight, util graph = top 10 by util_pct, etc.
  * Aggregate graphs always use the COMPLETE filtered set, not top N.
  * PDF report includes intro page, aggregate page, per-metric top-N pages, and optional per-device pages.

Typical:
  python3 graph_disk_metric_top10_pdf.py -i disk_stats.csv -o <SERVER> -p '^dm-' --title "Server dm storage metrics" --warn-await 2 --include-queue

Requires:
  pandas matplotlib

### CLI description

Graph diskmon.py CSV output. Each metric gets its own top-N devices.

## Location

`io/graph_disk.py`

## Usage

```bash
python io/graph_disk.py \
    --input data.csv
```

## Command line options

| Option | Required | Default | Choices | Description |
|---|---:|---|---|---|
| `-i, --input` | Yes | `` | `` | Input CSV from diskmon.py |
| `-o, --output-prefix` | No | `diskmon` | `` | Output filename prefix |
| `-p, --pattern` | No | `None` | `` | Regex device filter, e.g. '^dm-' |
| `-d, --devices` | No | `None` | `` | Comma-separated exact devices, e.g. dm-4,dm-5 |
| `--top-n` | No | `10` | `` | Top N devices per metric. Default: 10. Use 0 for all. (type: `int`) |
| `--top-mode` | No | `p95` | `['max', 'avg', 'p95']` | Ranking mode for each metric. Default: p95 |
| `--all-devices` | No | `` | `` | Plot all filtered devices for every metric, ignoring --top-n (action: `store_true`) |
| `--metric` | No | `None` | `` | Only create one metric graph, e.g. queue_depth |
| `--title` | No | `None` | `` | Optional graph/report title |
| `--warn-await` | No | `2.0` | `` | Await threshold line in ms. Default: 2.0 (type: `float`) |
| `--warn-qdepth` | No | `0.0` | `` | Average queue depth threshold line. Default: off (type: `float`) |
| `--warn-inflight` | No | `0.0` | `` | Inflight/current queue threshold line. Default: off (type: `float`) |
| `--include-queue` | No | `` | `` | Include queue_depth in summary/PDF. Metric-specific queue graph is still created if queue_depth is in CSV. (action: `store_true`) |
| `--legend` | No | `outside` | `['outside', 'best', 'none']` | Legend placement. Default: outside |
| `--list-metrics` | No | `` | `` | List metrics available in the CSV and exit (action: `store_true`) |
| `--no-png` | No | `` | `` | Do not write separate PNG files (action: `store_true`) |
| `--no-pdf` | No | `` | `` | Do not write PDF report (action: `store_true`) |
| `--no-aggregate` | No | `` | `` | Skip aggregate graph. Aggregate normally uses ALL filtered devices. (action: `store_true`) |
| `--no-summary` | No | `` | `` | Skip multi-panel summary. Metric pages are still created. (action: `store_true`) |
| `--per-device-summary` | No | `` | `` | Create per-device summaries for union of top devices across summary metrics (action: `store_true`) |

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `path` | read_csv | CSV file | line 168 |
| `args.input` | read_csv | CSV file | line 530 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `filename` | savefig | image/plot output | line 299 |
| `fig` | savefig | image/plot output | line 301 |
| `pdf_name` | PdfPages | PDF report | line 563 |
| `intro` | savefig | image/plot output | line 565 |

## Dependencies

- `matplotlib`
- `pandas`

## Functions

### `parse_args()`

No function docstring detected.

### `sanitise_filename(value)`

No function docstring detected.

### `parse_device_list(value)`

No function docstring detected.

### `read_csv(path)`

No function docstring detected.

### `apply_filters(df, pattern, devices)`

No function docstring detected.

### `available_metrics(df)`

No function docstring detected.

### `rank_devices_for_metric(df, metric, top_mode)`

No function docstring detected.

### `top_devices_for_metric(df, metric, top_n, top_mode, all_devices)`

No function docstring detected.

### `metric_label(metric)`

No function docstring detected.

### `device_legend(df, dev, metric)`

No function docstring detected.

### `add_thresholds(ax, metric, warn_await, warn_qdepth, warn_inflight)`

No function docstring detected.

### `finish_axis(ax, fig)`

No function docstring detected.

### `place_legend(ax, mode)`

No function docstring detected.

### `save_or_pdf(fig, filename, legend_mode, write_png=True, pdf=None)`

No function docstring detected.

### `build_aggregate(df)`

No function docstring detected.

### `plot_aggregate(df, prefix, title, include_queue, warn_await, warn_qdepth, warn_inflight, write_png=True, pdf=None)`

No function docstring detected.

### `plot_metric_topn(df, metric, prefix, title, top_n, top_mode, all_devices, warn_await, warn_qdepth, warn_inflight, legend_mode, write_png=True, pdf=None)`

No function docstring detected.

### `plot_metric_topn_summary(df, summary_metrics, prefix, title, top_n, top_mode, all_devices, warn_await, warn_qdepth, warn_inflight, legend_mode, write_png=True, pdf=None)`

No function docstring detected.

### `union_top_devices(df, metrics, top_n, top_mode, all_devices)`

No function docstring detected.

### `plot_per_device_summaries(df, devices, prefix, title, include_queue, warn_await, warn_qdepth, warn_inflight, write_png=True, pdf=None)`

No function docstring detected.

### `create_intro_page(title, df, ranked_by_metric, top_n, top_mode, include_queue)`

No function docstring detected.

### `print_report(df, bad_ts, bad_dev, ranked_by_metric, top_n, top_mode, include_queue)`

No function docstring detected.

### `main()`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
