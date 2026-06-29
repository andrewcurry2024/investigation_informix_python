# decode_u.py

## Purpose

`decode_u.py` decodes Informix `onstat -u` userthread flag strings into readable labels. The original file was named `deconde_u.py`; it is worth renaming it to `decode_u.py` in Git.

## Input

Text from `onstat -u`, normally piped via stdin.

## Usage

```bash
cat onstat.u.out | python3 threads/decode_u.py
```

or directly:

```bash
onstat -u | python3 threads/decode_u.py
```

## Options

| Option | Default | Meaning |
|---|---:|---|
| `-k` | `2` | Present in parser; current logic still reads flags from column 2 |

## Decoded Flag Positions

The decoder maps selected flag positions to labels.

### Wait / State Position

| Flag | Label |
|---|---|
| `B` | `BUFFER_WAIT` |
| `C` | `CHECKPOINT_WAIT` |
| `G` | `LOG_BUFFER_WRITE` |
| `L` | `LOCK_WAIT` |
| `S` | `MUTEX_WAIT` |
| `T` | `TRANSACTION_WAIT` |
| `Y` | `CONDITION_WAIT` |
| `X` | `ROLLBACK_CLEANUP` |
| `D` | `DEFUNCT` |

### Other Positions

| Condition | Label |
|---|---|
| second char `*` | `IO_FAILURE` |
| third char `A` | `BACKUP_THREAD` |
| fourth char `P` | `PRIMARY_THREAD` |
| fifth char `R` | `READING` |
| fifth char `X` | `CRITICAL_SECTION` |
| sixth char `R` | `RECOVERY_THREAD` |
| seventh char `B` | `BTREE_CLEANER` |
| seventh char `C` | `THREAD_CLEANUP` |
| seventh char `D` | `DAEMON` |
| seventh char `F` | `PAGE_CLEANER` |

## Output

The script prints the original line and appends decoded labels separated by tabs.

Header lines are passed through unchanged.

## When To Use

Use during incident review when `onstat -u` contains compact flags and you want to quickly see whether sessions are in lock waits, mutex waits, log buffer writes, condition waits, etc.

## Suggested Rename

```bash
git mv deconde_u.py threads/decode_u.py
```

Then update usage docs and scripts accordingly.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
