# iof.py

Compare onstat -g iof outputs from bad vs good periods.

Usage:
```bash
python3 iof.py bad.iof good.iof --mode last --prefix rss
```
Creates CSVs and PNG graphs showing KAIO latency, IO rates and tempdb activity.