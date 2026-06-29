# parse_his.py

## Purpose

`parse_his.py` parses Informix SQL history output from `onstat -g his`. It extracts statement blocks, normalises SQL text, extracts runtime, extracts estimated cost, and groups similar statements.

It is useful for workload analysis during a performance incident.

## Input

Text from `onstat -g his`, normally via stdin:

```bash
cat onstat.g.his.out | python3 sql/parse_his.py
```

## Usage

```bash
cat run.053026165429/onstat.g.his.053026165429 | python3 sql/parse_his.py
```

## What It Does

### Statement splitting

Splits the stream using markers like:

```text
Statement #123:
```

### SQL extraction

Extracts content after:

```text
Statement text:
```

Stops extraction before sections such as:

```text
SELECT using table
Iterator/Explain
Statement information:
```

### Normalisation

The script normalises SQL by:

- lowercasing
- replacing quoted strings with `?`
- replacing whole numbers with `?`
- collapsing whitespace

Example conceptually:

```sql
SELECT * FROM customer WHERE id = 123 AND name = 'ANDREW'
```

becomes:

```sql
select * from customer where id = ? and name = ?
```

### Cost extraction

Looks for the estimated section and takes the last numeric-heavy line as the cost candidate.

### Runtime extraction

Extracts:

```text
Run Time <number>
```

### Session extraction

Extracts:

```text
Sess_id <number>
```

falling back to `unknown`.

## Output

The exact printed summary depends on the complete script body, but the parser is designed to produce grouped SQL evidence by normalised statement, runtime and estimated cost.

## Investigation Use

Use it after partition profile analysis to answer:

- Which SQL shapes were active during the incident?
- Do expensive SQL patterns touch the hot objects?
- Are repeated statements driving table/index activity?
- Does the workload explain sequential scan or read deltas?

## Limitations

- SQL extraction depends on the `onstat -g his` formatting.
- Estimated cost parsing is heuristic.
- Runtime is only available if present in the captured text.

---

## General Notes

These scripts are investigation utilities. They assume the input files follow the Informix output formats they were written against. If a file parses to zero rows, first check that the source command output really contains the expected section headers and columns.

Where possible, compare equivalent time windows and treat counter deltas as more meaningful than raw cumulative counters.

## Suggested Git Practice

Commit the script, this README, and a tiny anonymised example input/output pair together. That makes the tool easier to understand later without needing access to the original customer evidence.
