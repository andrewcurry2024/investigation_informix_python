# comp_iov.py

## Purpose

`comp_iov.py` compares two Informix `onstat -g iov` captures. It is aimed at bad-vs-good I/O VP comparison, for example comparing a lagging RSS server against a cleaner baseline RSS server.

The script parses `class/vp/id` rows and compares I/O activity across matching VP rows. It gives both high-level totals and detailed per-VP differences.

## Typical Use Case

Use this when you want to answer questions like:

- Is the bad host doing more total I/O than the good host?
- Is KAIO/AIO activity materially different?
- Are specific VP rows responsible for the difference?
- Are there new or missing VP rows between captures?
- Are there obvious I/O red flags such as errors or high `io/wup`?

## Input

Two text files containing `onstat -g iov` output.

Expected row shape:

```text
class/vp/id s io/s totalops dskread dskwrite dskcopy wakeups io/wup errors tempops
kio -1 0 i 1883.0 ...
```

Rows are keyed by:

```text
class/vp/id
```

For example:

```text
kio/-1/0
```

## Usage

```bash
python3 io/comp_iov.py bad_iov.out good_iov.out
```

Example from an RSS investigation:

```bash
python3 io/comp_iov.py     new_weekend/bad_rss_log_ld6ux351/iov.out     new_weekend/good_rss_log_gibux354/iov.out
```

## Output

The script prints several sections:

1. **Overall totals**  
   Totals for `io_s`, `totalops`, `dskread`, `dskwrite`, `dskcopy`, `wakeups`, `errors` and `tempops`.

2. **Summary totals by class**  
   Aggregates by VP class such as `kio`, `aio`, etc.

3. **Top io/s changes**  
   Ranks the biggest absolute differences in `io_s`.

4. **New / missing VPs**  
   Highlights VP rows present only in one file.

5. **Quick red flags**  
   Flags errors and high `io/wup` values.

6. **VP comparison**  
   Detailed per-row comparison sorted by largest change.

## Metrics Compared

| Metric | Meaning |
|---|---|
| `io_s` | I/O per second |
| `totalops` | Total operations |
| `dskread` | Disk reads |
| `dskwrite` | Disk writes |
| `dskcopy` | Disk copy operations |
| `wakeups` | Wakeups |
| `io_wup` | I/O per wakeup |
| `errors` | I/O errors |
| `tempops` | Temp operations |

## Interpretation

A positive difference means the good file is higher than the bad file in the current script calculation. If you are using the first file as the bad/problem file and the second as the good/baseline file, read the column labels carefully rather than assuming the sign always means bad-minus-good.

For evidence work, the most useful sections are usually:

- overall totals
- summary by class
- top io/s changes
- red flags

## Limitations

- Only rows with exactly the expected column count are parsed.
- It is a point-in-time/snapshot-style comparison unless the input files themselves contain equivalent captured intervals.
- It does not calculate elapsed-time-normalised deltas from multiple snapshots.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
