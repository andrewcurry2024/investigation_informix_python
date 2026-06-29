# spi_comp.py

## Purpose

`spi_comp.py` compares two `onstat -g spi` captures and enriches spin lock entries with object names where a partnum can be mapped via an `onstat -t` style lookup file.

It is intended for before/after or old/new SPI comparison.

## Input

Three files:

1. Old/before SPI capture
2. New/after SPI capture
3. `onstat -t` mapping file

## Usage

```bash
python3 spinlocks/spi_comp.py spi_old.out spi_new.out onstat_t.log
```

The script usage string currently says:

```text
Usage: python3 spi.py <spi_old> <spi_new> <onstat_t_file>
```

If you keep the filename as `spi_comp.py`, update that message later for clarity.

## What It Does

- Parses the `Spin locks with waits` section.
- Classifies entries using similar logic to `spi.py`.
- Extracts partnums where present in spin lock names.
- Maps partnums to object names using the lookup file.
- Calculates pain score.
- Diffs old vs new frames.
- Creates top delta/pain charts.

## Pain Score

```text
pain = num_loops * avg_loop_wait
```

The comparison focuses on changes in this derived ranking value.

## Output

Expected output includes:

- differential SPI rows
- object-enriched rows where partnum mapping succeeds
- top changed spinlocks
- grouped object-level pain changes
- plots for top deltas and object groups

## When To Use

Use when you have SPI captures from two points in time and want to show whether contention increased, decreased, or moved to a different object/category.

## Limitations

- Relies on partnum patterns being present in SPI names.
- Object mapping depends on lookup file quality.
- Classification is string-based.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
