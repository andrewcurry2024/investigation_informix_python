# spi.py

## Purpose

`spi.py` analyses Informix `onstat -g spi` spin lock wait output. It classifies spin lock entries, removes known low-value noise, calculates a simple `pain_score`, and shows the top entries by loops, average loop wait and pain score.

## Input

A single `onstat -g spi` output file containing the section:

```text
Spin locks with waits
```

Rows are expected to match:

```text
Num Waits   Num Loops   Avg Loop/Wait   Name
```

## Usage

```bash
python3 spinlocks/spi.py onstat.g.spi.out
```

## Classification

The script classifies entries into:

| Category | Match Logic |
|---|---|
| `noise` | Fast mutex buffer/bhash/lru style entries |
| `io` | Names containing `aio` or `gfile` |
| `logging` | Names containing `logrecover` or `log` |
| `transaction` | Names containing `tx` or `transaction` |
| `cpu` | Names containing `vp_lock`, `vproc`, `mtcb`, `cl_lock` |
| `other` | Anything else retained for visibility |

Known noise is dropped. Other entries are kept.

## Pain Score

```text
pain_score = num_loops * avg_loop_wait
```

This is not an Informix native metric. It is a practical ranking signal to help identify entries that have both volume and wait cost.

## Output

The script prints:

- parsed row count
- category breakdown
- top 20 by `num_loops`
- top 20 by `avg_loop_wait`
- top 20 by `pain_score`

It also displays charts:

- top spinlocks by num loops
- top spinlocks by average loop/wait
- top spinlocks by pain score
- pain score by category

## When To Use

Use this when investigating:

- CPU contention
- mutex/spin behaviour
- possible logging or transaction contention
- whether a suspected bottleneck has SPI support

## Limitations

- Classification is string-based and deliberately simple.
- `pain_score` is a ranking aid, not a formal engine metric.
- Uses `plt.show()`, so headless environments may need `savefig` changes.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
