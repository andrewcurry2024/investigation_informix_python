# Investigation Informix Python

Python tooling repository containing standalone investigation and analysis scripts.

The generated documentation below is intended to make each script easier to run, review, and maintain. It is especially useful for operational scripts where the important behaviour is often captured in command line options, inputs, outputs, and generated reports rather than in package-level API docs.

## What is in this repository?

- **Python scripts detected:** 27
- **Per-script documentation:** `docs/`
- **Dependencies file:** `requirements.txt`

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Script index

| Script | Purpose | CLI options | Dependencies | Documentation |
|---|---|---:|---|---|
| `io/comp_iov.py` | Compare diagnostic/input files and report differences. | 0 | stdlib only | [docs](docs/comp_iov.md) |
| `io/graph_disk.py` | graph_disk_metric_top10_pdf.py | 20 | `matplotlib`, `pandas` | [docs](docs/graph_disk.md) |
| `io/iof.py` | Compare Informix onstat -g iof AIO global files between good and bad RSS periods. | 4 | `matplotlib`, `pandas` | [docs](docs/iof.md) |
| `io/ioh.py` | Utility script for ioh. | 0 | `numpy`, `pandas` | [docs](docs/ioh.md) |
| `io/ioh_graph.py` | Utility script for ioh graph. | 0 | `matplotlib`, `pandas` | [docs](docs/ioh_graph.md) |
| `io/iostats.py` | diskmon.py | 12 | stdlib only | [docs](docs/iostats.md) |
| `io/iostats_v26.py` | diskmon.py | 0 | `__future__`, `optparse` | [docs](docs/iostats_v26.md) |
| `io/iostats_v26_mpath.py` | iostats_v26.py | 0 | `__future__`, `optparse` | [docs](docs/iostats_v26_mpath.md) |
| `io/summarise_disk.py` | summarise_diskstats.py | 0 | `__future__`, `optparse` | [docs](docs/summarise_disk.md) |
| `mutex-spi/all_mutex.py` | Utility script for all mutex. | 0 | stdlib only | [docs](docs/all_mutex.md) |
| `mutex-spi/smx_prof.py` | Utility script for smx prof. | 0 | stdlib only | [docs](docs/smx_prof.md) |
| `mutex-spi/spi.py` | Utility script for spi. | 0 | `matplotlib`, `pandas` | [docs](docs/spi.md) |
| `mutex-spi/spi_comp.py` | Compare diagnostic/input files and report differences. | 0 | `matplotlib`, `pandas` | [docs](docs/spi_comp.md) |
| `osmon/osmon_comp.py` | Summarise OSMON/storage performance data. | 0 | `matplotlib`, `pandas` | [docs](docs/osmon_comp.md) |
| `osmon/osmon_comp_evidence.py` | Compare two osmon storage datasets and write a PDF evidence pack. | 10 | `matplotlib`, `numpy`, `pandas` | [docs](docs/osmon_comp_evidence.md) |
| `osmon/osmon_sum.py` | Summarise OSMON/storage performance data. | 0 | `matplotlib`, `pandas` | [docs](docs/osmon_sum.md) |
| `partition-profile/comp_ppf.py` | Compare two Informix partition_profile files. | 16 | `matplotlib`, `pandas` | [docs](docs/comp_ppf.md) |
| `partition-profile/parse_profile.py` | Fast parser for Informix partition profile logs. | 13 | `matplotlib`, `pandas` | [docs](docs/parse_profile.md) |
| `partition-profile/ppf.py` | Compare diagnostic/input files and report differences. | 0 | stdlib only | [docs](docs/ppf.md) |
| `rss/lgr_lpage.py` | Utility script for lgr lpage. | 0 | stdlib only | [docs](docs/lgr_lpage.md) |
| `rss/lograte_enhanced.py` | Utility script for lograte enhanced. | 0 | stdlib only | [docs](docs/lograte_enhanced.md) |
| `rss/plot_all_rss.py` | Plot each RSS server separately as multiplots, with dual axis: | 13 | `matplotlib`, `numpy`, `pandas` | [docs](docs/plot_all_rss.md) |
| `rss/rss_repl_plot_refactored.py` | RSS / OSMon analyser | 6 | `matplotlib`, `numpy`, `pandas` | [docs](docs/rss_repl_plot_refactored.md) |
| `rss/trans_profile.py` | Utility script for trans profile. | 0 | stdlib only | [docs](docs/trans_profile.md) |
| `rss/unified.py` | Utility script for unified. | 0 | stdlib only | [docs](docs/unified.md) |
| `sql-history/parse_his.py` | Utility script for parse his. | 0 | stdlib only | [docs](docs/parse_his.md) |
| `threads/decode_u.py` | Utility script for decode u. | 1 | stdlib only | [docs](docs/decode_u.md) |

## Documentation workflow

Regenerate the README and per-script Markdown files after changing script arguments or behaviour:

```bash
python build_repo_docs.py --repo-root . --docs-dir docs --readme README.md --mkdocs --force
```

If using MkDocs locally:

```bash
pip install mkdocs mkdocs-material
mkdocs serve
```

## Notes

- Documentation is generated using static analysis, so dynamic file paths may need a quick manual check.
- The per-script pages are usually the most useful part of the generated output because they include options, usage, detected inputs, detected outputs, functions, and dependencies.
- Keep meaningful module docstrings and argparse help text in the scripts; that gives the generator better source material.
