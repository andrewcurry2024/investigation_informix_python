# iostats_v26_mpath.py

## Purpose

iostats_v26.py

### Module notes

iostats_v26.py

Python 2.6 compatible Linux diskstats monitor.

Reads /proc/diskstats directly and calculates iostat-like metrics:

    read_iops
    write_iops
    read_MBps
    write_MBps
    await_ms
    r_await_ms
    w_await_ms
    queue_depth      average queue depth / iostat avgqu-sz/aqu-sz style
    util_pct
    inflight         instantaneous IOs currently in progress

This version also understands Linux multipath:

    * Parses `multipath -ll` using several possible paths:
          multipath
          /sbin/multipath
          /usr/sbin/multipath
    * Maps mpath parent devices, e.g.:
          dm-8 -> mpathd
    * Maps underlying sd path devices, e.g.:
          sdh/sdt/sdaf/sdar -> mpathd
    * Can force mpath parents and/or paths into the capture even when your -p regex
      only matches dm-*.

CSV compatibility:

    The original 14 metric columns are unchanged.
    queue_depth remains column 10.

    Metadata is appended at the end:

      15 device_name
      16 device_type        lvm / mpath / mpath_path / disk
      17 mpath_name
      18 mpath_wwid
      19 mpath_size
      20 mpath_paths
      21 mpath_parent_dm

Examples:

    python iostats_v26.py --list-mpaths

    python iostats_v26.py --list -p '^dm-' --include-mpaths --include-mpath-paths

    python iostats_v26.py -p '^dm-' --include-mpaths --include-mpath-paths -i 2 -o disk_stats.csv

    python iostats_v26.py -p '^(dm-|sd[a-z]+$)' --include-mpaths --include-mpath-paths -i 2 -o disk_stats.csv

    python iostats_v26.py -d dm-8,sdh,sdt,sdaf,sdar -i 1 -o dm8_paths.csv

Notes:

    If you run only:

        -p '^dm-'

    then normal sd path devices will be excluded by the regex. Use:

        --include-mpath-paths

    or a pattern like:

        -p '^(dm-|sd[a-z]+$)'

    to include sdh/sdt/sdaf/sdar rows.

## Location

`io/iostats_v26_mpath.py`

## Usage

```bash
python io/iostats_v26_mpath.py
```

## Command line options

No argparse options detected.

## Detected inputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `path` | open | file/path expression | line 176 |

## Detected outputs

| Path/expression | Method | Type | Code location |
|---|---|---|---|
| `LOG_FILE` | open | file/path expression | line 115 |
| `filename` | open | file/path expression | line 721 |

## Dependencies

- `__future__`
- `optparse`

## Functions

### `now_str()`

No function docstring detected.

### `log_msg(message, also_print=True)`

No function docstring detected.

### `log_info(message)`

No function docstring detected.

### `log_warn(message)`

No function docstring detected.

### `log_error(message)`

No function docstring detected.

### `run_command_candidates(candidates)`

Python 2.6 compatible command runner.

candidates is a list of command lists.
Returns the first non-empty stdout.

### `read_text_file(path)`

No function docstring detected.

### `build_mapper_dm_map()`

Build a map from dm device to /dev/mapper symlink names.

Example:
    /dev/mapper/mpathd -> ../dm-8
    mapper_by_dm["dm-8"] = ["mpathd"]

### `get_multipath_text(multipath_file=None)`

Return multipath -ll text.

multipath is often in /sbin or /usr/sbin and may not be in PATH for non-root.
If --multipath-file is supplied, parse that file instead.

### `parse_multipath_text(text)`

Parse multipath -ll output.

Returns:
  mpath_by_dm["dm-8"] = {
      mpath_name: "mpathd",
      mpath_wwid: "3624...",
      mpath_size: "66T",
      mpath_vendor_model: "PURE,FlashArray",
      mpath_paths: "sdh;sdt;sdaf;sdar"
  }

  path_to_mpath["sdaf"] = same dict plus parent dm info

### `save_current()`

No function docstring detected.

### `parse_multipath_ll(multipath_file=None)`

No function docstring detected.

### `build_device_metadata(multipath_file=None)`

Build metadata for dm parent devices, LVM devices, and sd path devices.

Device types:
    mpath       -> multipath parent, e.g. dm-8/mpathd
    mpath_path  -> underlying sd path, e.g. sdaf under mpathd
    lvm         -> /dev/mapper LVM dm device
    disk        -> other disk-like device

### `get_mpath_dm_devices(metadata)`

No function docstring detected.

### `get_mpath_path_devices(metadata)`

No function docstring detected.

### `is_interesting_device(dev)`

No function docstring detected.

### `compile_pattern(pattern)`

No function docstring detected.

### `device_matches(dev, exact_devices, regex, include_mpaths, include_mpath_paths, mpath_devices, mpath_path_devices)`

Matching rules:

- --include-mpaths forces detected dm multipath parents into collection.
- --include-mpath-paths forces detected sd path devices into collection.
- exact device list matches as given.
- regex matches as given.
- no filter means all interesting devices.

### `parse_exact_devices(device_string)`

No function docstring detected.

### `read_diskstats()`

No function docstring detected.

### `calc_metrics(prev, curr, elapsed)`

No function docstring detected.

### `ensure_csv_header(filename)`

No function docstring detected.

### `metadata_value(metadata, dev, key)`

No function docstring detected.

### `write_csv(filename, timestamp, metrics, metadata)`

No function docstring detected.

### `display_name(metadata, dev)`

No function docstring detected.

### `print_header()`

No function docstring detected.

### `print_metrics(timestamp, metrics, metadata)`

No function docstring detected.

### `list_devices(stats, pattern, exact_devices, show_all, include_mpaths, include_mpath_paths, metadata, mpath_devices, mpath_path_devices)`

No function docstring detected.

### `list_mpaths(metadata)`

No function docstring detected.

### `handle_signal(signum, frame)`

No function docstring detected.

### `parse_options()`

No function docstring detected.

### `main()`

No function docstring detected.

## Notes

- This page was generated by `build_repo_docs.py` using static AST analysis.
- Review examples and detected input/output paths before publishing if the script builds paths dynamically.
