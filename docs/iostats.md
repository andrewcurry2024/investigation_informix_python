# iostats.py

## Purpose

diskmon.py

### Module notes

diskmon.py

Linux disk latency / queue depth collector using /proc/diskstats.

Designed for older Linux hosts and Python 3.6.

Captures per-device:

    read_iops
    write_iops
    read_MBps
    write_MBps
    await_ms
    r_await_ms
    w_await_ms
    queue_depth
    util_pct
    inflight

Useful for Informix / RSS investigations where storage latency and queue
depth need to be correlated with replication lag.

Examples:

    ./diskmon.py --list

    ./diskmon.py -p '^dm-' -i 1 -o ld6_diskstats.csv

    ./diskmon.py -d dm-4,dm-5 -i 1 -o dm_only.csv

    ./diskmon.py -p '^dm-' -i 5 -o disk.csv --log-file diskmon.log

### CLI description

Monitor Linux disk await, queue depth, util and IOPS via /proc/diskstats

## Location

`io/iostats.py`

## Usage

```bash
python io/iostats.py \
    --output data.csv \
    --log-file VALUE
```

## Command line options

| Option | Required | Default | Choices | Description |
|---|---:|---|---|---|
| `-i, --interval` | No | `1.0` | `` | Sample interval in seconds. Default: 1 (type: `float`) |
| `-o, --output` | No | `diskstats.csv` | `` | CSV output file. Default: diskstats.csv |
| `-d, --device` | No | `` | `` | Comma-separated exact device names, e.g. dm-4,dm-5,sda |
| `-p, --pattern` | No | `` | `` | Regex device filter, e.g. '^dm-' or '^dm-(4\|5\|6)$' |
| `--list` | No | `` | `` | List matching devices and exit (action: `store_true`) |
| `--all` | No | `` | `` | With --list, show all devices including partitions/loop/ram (action: `store_true`) |
| `--log-file` | No | `` | `` | Optional runtime log file |
| `--quiet` | No | `` | `` | Do not print live metrics to screen; still writes CSV (action: `store_true`) |
| `--no-csv` | No | `` | `` | Do not write CSV, print only (action: `store_true`) |
| `--max-samples` | No | `0` | `` | Stop after N samples. Default 0 means run until Ctrl+C (type: `int`) |
| `--warn-await` | No | `0.0` | `` | Optional warning threshold for await_ms, e.g. 2.0 (type: `float`) |
| `--warn-qdepth` | No | `0.0` | `` | Optional warning threshold for queue depth, e.g. 1.0 (type: `float`) |

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `path` | open | file/path expression | line 195 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `LOG_FILE` | open | file/path expression | line 74 |
| `filename` | open | file/path expression | line 404 |

## Dependencies

No third-party imports detected. The script appears to use the Python standard library only.

## Functions

### `now_str()`

No function docstring detected.

### `log_msg(message, also_print=True)`

Write message to optional log file and optionally stdout.

### `log_error(message)`

No function docstring detected.

### `log_warn(message)`

No function docstring detected.

### `log_info(message)`

No function docstring detected.

### `is_interesting_device(dev)`

Basic default filter for real-ish block devices.

We still collect everything internally, but this helps --list output
and default display from becoming too noisy.

Common devices:
  sdX       SCSI/SAN paths
  dm-X      device mapper / multipath / LVM
  nvmeXnY   NVMe
  vdX       virtio
  xvdX      Xen
  hdX       old IDE

### `compile_pattern(pattern)`

No function docstring detected.

### `device_matches(dev, exact_devices=None, regex=None)`

Device filter rules.

If no filters supplied, allow all interesting devices.
If exact device list supplied, match those.
If regex supplied, match regex.
If both supplied, device may match either.

### `read_diskstats()`

Read /proc/diskstats.

Kernel diskstats fields, simplified:

  0 major
  1 minor
  2 device
  3 reads completed
  4 reads merged
  5 sectors read
  6 ms reading
  7 writes completed
  8 writes merged
  9 sectors written
  10 ms writing
  11 ios in progress
  12 ms doing io
  13 weighted ms doing io

Some newer kernels expose more fields after these; we ignore them.

### `safe_delta(curr, prev)`

No function docstring detected.

### `calc_metrics(prev, curr, elapsed)`

Calculate iostat-like metrics from two samples.

await_ms:
    (delta read_ms + delta write_ms) / total IOs

r_await_ms:
    delta read_ms / read IOs

w_await_ms:
    delta write_ms / write IOs

queue_depth:
    delta weighted_io_ms / elapsed_ms

util_pct:
    delta io_ms / elapsed_ms * 100

Notes:
  - util_pct can exceed 100 on some stacked/virtual devices.
  - dm-* is usually the most useful layer for multipath/LVM views.

### `ensure_csv_header(filename)`

Write CSV header if file does not exist or is empty.

### `write_csv(filename, timestamp, metrics)`

No function docstring detected.

### `print_header()`

No function docstring detected.

### `print_metrics(timestamp, metrics)`

No function docstring detected.

### `list_devices(stats, pattern=None, exact_devices=None, show_all=False)`

No function docstring detected.

### `handle_signal(signum, frame)`

No function docstring detected.

### `parse_args()`

No function docstring detected.

### `main()`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
