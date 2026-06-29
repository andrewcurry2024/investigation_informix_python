# Informix RSS Investigation Toolkit

## Overview

This repository contains a set of Python utilities developed during the investigation of a recurring Informix RSS replication lag issue affecting a single RSS server.

The investigation focused on identifying why a single RSS instance was unable to keep up with log apply processing while:

- The primary server remained healthy.
- Other RSS servers remained in sync.
- Replication lag appeared during a predictable weekly window.
- Significant I/O degradation and KIO VP growth were observed.

The tools in this repository automate extraction and comparison of Informix diagnostic outputs collected through:

- ifxcollect
- onstat
- osmon
- dbmonitor
- RSS diagnostics

The aim was to move beyond individual snapshots and provide evidence-based comparisons between:

- Good vs Bad periods
- Primary vs RSS
- Healthy RSS vs Lagging RSS

---

# Investigation Workflow

The investigation followed four broad areas.

## 1. Storage and I/O Analysis

Purpose:

Determine whether I/O response times and storage behaviour changed during RSS lag events.

Tools:

```text
io/
├── comp_iov.py
├── iof.py
├── ioh.py
├── ioh_graph.py
```

Analysis performed:

- Chunk-level read/write latency comparison.
- Good vs bad read service time analysis.
- KAIO activity analysis.
- Read and write service-time visualisation.
- Identification of slow chunks.
- Correlation between lag events and storage latency.

Outputs:

- Top read service time increases.
- Top write service time increases.
- KAIO utilisation analysis.
- Disk response time charts.

Key observations:

- Multiple chunks showed materially higher service times during lag events.
- KIO VP counts increased substantially during degraded periods.
- I/O queues became visible during lag windows.

---

## 2. Partition and Buffer Pool Analysis

Purpose:

Determine whether specific tables or indexes were responsible for excessive read activity.

Tools:

```text
partition-profile/
├── ppf.py
├── comp_ppf.py
├── parse_profile.py
```

Analysis performed:

- Parsing `onstat -g ppf` output.
- Delta calculations between snapshots.
- Identification of top physical reads.
- Identification of top buffer reads.
- Partition-level activity ranking.

Key metrics examined:

```text
ISRD  - Disk reads
ISWRT - Disk writes
BFRD  - Buffer reads
BFWRT - Buffer writes
SEQSC - Sequential scans
```

Example findings:

```text
openbet.tcnjcustomer_aud
```

was responsible for the largest read activity observed during one sample period.

This raised the possibility of:

- Large object scans.
- Buffer pool churn.
- Table growth causing workload amplification.
- Query plan changes.

---

## 3. Thread and Wait Analysis

Purpose:

Understand how Informix threads behaved during the problem period.

Tools:

```text
threads/
├── decode_u.py
```

Analysis performed:

- Decoding thread states.
- Analysing waiting threads.
- Identifying resource waits.
- Tracking thread behaviour across snapshots.

Outputs:

- Thread state breakdown.
- Long-running sessions.
- Wait state tracking.

---

## 4. Mutex Contention Analysis

Purpose:

Determine whether engine-level contention was contributing to lag.

Tools:

```text
mutex-spi/
├── spi.py
├── spi_comp.py
```

Analysis performed:

- Mutex activity comparison.
- Spin wait analysis.
- Engine contention comparison.
- Good vs bad mutex behaviour.

Outputs:

- Highest contention mutexes.
- Delta comparison reports.
- Wait hotspot identification.

---

## 5. Operating System Correlation

Purpose:

Correlate Informix behaviour with operating system activity.

Tools:

```text
osmon/
├── osmon_sum.py
├── osmon_comp.py
├── osmon_comp_evidence.py
```

Analysis performed:

- CPU comparison.
- Memory comparison.
- I/O comparison.
- Process behaviour review.
- Evidence extraction from osmon collections.

Outputs:

- Good vs bad comparisons.
- System resource summaries.
- Potential bottleneck identification.

---

## 6. SQL Activity Analysis

Purpose:

Review SQL workload executed during lag events.

Tools:

```text
sql-history/
├── parse_his.py
```

Analysis performed:

- SQL extraction.
- Statement ranking.
- Long-running query identification.
- Query correlation with partition activity.

Outputs:

- Top statements by activity.
- Candidate problem queries.
- SQL workload summaries.

---

# Typical Investigation Process

The investigation generally followed the sequence below:

```text
Replication Lag Observed
           │
           ▼
Compare RSS vs Healthy RSS
           │
           ▼
Analyse Storage Behaviour
           │
           ▼
Analyse KIO Activity
           │
           ▼
Identify High Activity Tables
           │
           ▼
Analyse SQL Workload
           │
           ▼
Review Buffer Pool Impact
           │
           ▼
Review Thread Waits
           │
           ▼
Build Evidence-Based Hypothesis
```

---

# Example Investigation Questions

The toolkit was used to answer questions such as:

### Storage

- Did read service times increase?
- Did write service times increase?
- Which chunks became slower?

### Engine

- Did KIO VPs increase?
- Were KIO queues present?
- Were threads waiting on resources?

### Workload

- Which tables generated most reads?
- Which indexes generated most reads?
- Did large scans coincide with lag?

### SQL

- Which statements were active?
- Were query plans potentially changing?
- Were audit tables generating excessive activity?

### Replication

- Was the RSS receiving work?
- Was the RSS unable to apply work?
- Was lag associated with local resource pressure?

---

# Repository Structure

```text
.
├── examples
├── io
├── mutex-spi
├── osmon
├── partition-profile
├── sql-history
├── threads
├── README.md
└── requirements.txt
```

Each module contains:

```text
.py  -> analysis tool
.md  -> methodology / usage notes
```

---

# Investigation Outcome

The tools were developed to support root cause analysis rather than prove a predetermined theory.

The collection and comparison process enabled:

- Repeatable analysis.
- Snapshot comparison.
- Evidence generation from Informix diagnostics.
- Identification of workload, buffer pool and storage related patterns.

The repository provides a reusable framework for analysing:

- RSS lag.
- Storage bottlenecks.
- Buffer pool pressure.
- Query workload issues.
- Informix engine contention.
- General performance investigations.
