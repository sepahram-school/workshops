# Workshop #8 — S3-Compatible Object Storage Benchmark

> **Author:** Mojtaba Banaie · [linkedin.com/in/smbanaie/](https://www.linkedin.com/in/smbanaie/)
> **Date:** June 2026 · [github.com/sepahram-school/workshops](https://github.com/sepahram-school/workshops)

A reproducible, multi-engine benchmark comparing **MinIO**, **RustFS**, and **libreFS** for analytical data workloads. Four progressively realistic engines expose failure modes that simple PUT/GET tests never reveal.

---

## Quick Start

```bash
# 1 — clone & enter
git clone https://github.com/sepahram-school/workshops
cd workshops/8-SeaweedFS-vs-RustFS

# 2 — generate test data (Parquet + binary)
uv run python generate-data.py --size all --files 100
uv run python generate_data_parquet.py --size all --files 100

# 3 — start a target cluster (pick one)
docker compose -f docker/docker-compose-minio.yml   up -d
docker compose -f docker/docker-compose-rustfs.yml  up -d
docker compose -f docker/docker-compose-librefs.yml up -d

# 4 — run the benchmarks
uv run python benchmark_duckdb.py   --target minio --mode mixed  --sizes 1mb,32mb --runs 3
uv run python benchmark_ducklake.py --target minio --mode heavy  --sizes 1mb,32mb --runs 3
uv run python benchmark_iceberg.py  --target minio --mode mixed  --sizes 1mb,32mb --runs 3

# 5 — run all targets at once
uv run python benchmark_duckdb.py --target all --mode mixed --sizes 1mb,32mb --runs 3
```

Results are written to `results_duckdb/`, `results_ducklake/`, `results_iceberg/` — organized as `{mode}/{size}/{target}/run-{N}.json`.

---

## Targets

| System | Endpoint | Credentials | License |
|--------|----------|-------------|---------|
| **MinIO** | `http://localhost:9200` | minioadmin / minioadmin123 | AGPLv3 |
| **RustFS** | `http://127.0.0.1:9000` | rustfsadmin / rustfsadmin | Apache 2.0 |
| **libreFS** | `http://localhost:9100` | admin / password123 | AGPLv3 |

All three clusters run as 3-node Docker containers on `localhost`. MinIO and libreFS use distributed erasure coding; RustFS uses its default cluster configuration.

---

## The Four Benchmark Engines

Each engine adds a layer of realism to expose failure modes invisible to simpler tests.

| Engine | Script | Tests | Metadata | ACID | Analog |
|--------|--------|-------|----------|------|--------|
| **Classic** | `benchmark.py` | Raw S3 PUT/GET bytes | None | No | Backups, blob storage |
| **DuckDB** | `benchmark_duckdb.py` | Columnar Parquet I/O | None | No | Data lake, OLAP |
| **DuckLake** | `benchmark_ducklake.py` | Lakehouse + SQLite metadata | SQLite | Yes | DuckLake, Delta Lake |
| **Iceberg** | `benchmark_iceberg.py` | Iceberg file-based metadata | S3 files | Yes | Apache Iceberg |

### Why not just PUT/GET?

Raw byte benchmarks miss what actually matters in data engineering:

- **Columnar access** — DuckDB reads specific row groups, not whole files
- **Predicate pushdown** — `WHERE` filters skip irrelevant Parquet row groups at the storage layer
- **Metadata overhead** — every Iceberg/DuckLake commit writes manifest files, snapshot pointers, and transaction logs as additional S3 objects
- **Concurrent contention** — Go GC pauses and erasure-coding quorum latency only appear under mixed concurrent load
- **Consistency invariants** — streaming databases (RisingWave Hummock) require strict read-after-write ordering that no throughput metric can measure

---

## Benchmark Modes

### DuckDB (`benchmark_duckdb.py`)

```bash
uv run python benchmark_duckdb.py --target <TARGET> --mode <MODE> --sizes 1mb,32mb --runs 3

# modes: write-only | read-only | mixed | heavy
# thread sweep (1,5,10,20,50):
uv run python benchmark_duckdb.py --target all --thread-sweep --mode mixed --sizes 32mb --runs 3
```

### DuckLake (`benchmark_ducklake.py`)

```bash
uv run python benchmark_ducklake.py --target <TARGET> --mode <MODE> --sizes 1mb,32mb --runs 3

# modes: write-only | read-only | mixed | heavy | transactions | time-travel | snapshots | concurrent
uv run python benchmark_ducklake.py --target minio --mode transactions --runs 3
uv run python benchmark_ducklake.py --target all   --mode time-travel  --runs 1
```

### Iceberg (`benchmark_iceberg.py`)

```bash
uv run python benchmark_iceberg.py --target <TARGET> --mode <MODE> --sizes 1mb,32mb --runs 3

# modes: write-only | read-only | mixed | heavy | time-travel | snapshots | change-detection | update | delete
uv run python benchmark_iceberg.py --target minio --mode change-detection --runs 3
uv run python benchmark_iceberg.py --target all   --mode heavy --heavy-duration 60 --runs 3
```

---

## Key Results (32 MB, n=3)

### DuckDB — Raw Throughput

| Mode | Winner | Result |
|------|--------|--------|
| Write (32 MB) | **libreFS** | 28.8 ± 3.3 MB/s (+42% over MinIO) |
| Write (1 MB) | **RustFS** | 13.2 ± 1.5 MB/s (2x MinIO) |
| Read (32 MB) | **RustFS** | 61.0 ± 7.1 MB/s |
| Heavy (aggregate) | **MinIO** | 29.0 MB/s — highest total throughput |
| Heavy (write P50) | **RustFS** | 0.77s vs MinIO 9.0s |

### DuckLake — Lakehouse

| Mode | Winner | Result |
|------|--------|--------|
| Write (32 MB) | **RustFS** | 19.9 MB/s (tied with MinIO) |
| Transactions (200 ACID) | **RustFS** | 36ms P50, **100% success all targets** |
| Time-travel | **RustFS** | 0.228s P50 |
| Heavy write P50 | **RustFS / libreFS** | ~3.2s vs MinIO 9.1s |

### Iceberg — File-Based Metadata

| Mode | Winner | Result |
|------|--------|--------|
| Write P50 (32 MB) | **RustFS** | 0.059s (2x faster than MinIO 0.121s) |
| Write P50 (1 MB) | **RustFS** | 0.116s (3.5x faster than MinIO 0.412s) |
| Heavy write P50 | **RustFS** | 0.257s vs MinIO 0.819s |
| Change-detection (1 MB) | **RustFS** | 0.060s vs MinIO 0.505s (8x faster) |
| Time-travel | **RustFS** | 0.049s P50 |

### Overall Scorecard

| Target | Wins | Best Domain |
|--------|------|-------------|
| **RustFS** | 7 / 10 | Iceberg, DuckDB reads, DuckLake transactions |
| **libreFS** | 2 / 10 | DuckDB large-file writes, DuckLake reads |
| **MinIO** | 1 / 10 | DuckDB heavy-mode aggregate throughput |

---

## Production Findings

### RustFS — Critical: RisingWave Hummock Failures

RustFS caused **SSTable manifest corruption** in two independent RisingWave deployments, requiring full state recovery with data loss.

**Root cause:** Hummock compaction requires strict read-after-write ordering — each SSTable must be fully durable before its reference appears in the manifest. RustFS does not satisfy this invariant consistently.

**Status:** MinIO and libreFS were both **validated stable** under identical Hummock workloads. The benchmark's heavy mode did not catch this because it does not test multi-object commit ordering — it only measures throughput and latency.

> **Rule:** Do not use RustFS as a backend for RisingWave, Flink state, or Apache Paimon until its consistency guarantees are formally documented and verified.

### MinIO + libreFS — Validated for Streaming

Both systems passed RisingWave Hummock validation. Their shared erasure-coding quorum model (write quorum across 3 nodes before ACK) naturally satisfies the read-after-write ordering Hummock requires.

---

## Recommendations

| Use Case | Recommended | Notes |
|----------|-------------|-------|
| Apache Iceberg data lake | **RustFS** | 2-8x lower latency across all Iceberg modes |
| DuckDB / Trino / Spark OLAP reads | **RustFS** | 61 MB/s, lowest variance |
| Large Parquet batch writes (>32 MB) | **libreFS** | 28.8 MB/s, +42% over MinIO; profile P99 first |
| Streaming ingestion (<5 MB files) | **RustFS** | 2x MinIO throughput on small objects |
| DuckLake ACID lakehouse | **RustFS** | 36ms txn P50, fastest time-travel |
| High-concurrency sustained throughput | **MinIO** | 29 MB/s aggregate heavy-mode |
| RisingWave Hummock backend | **MinIO or libreFS** | Both validated; **not RustFS** |
| ClickHouse Separate Storage from Compute | **MinIO or libreFS** | Strong read-after-write consistency required for MergeTree part merges |
| WebUI + LDAP + AGPLv3 (no AIStor) | **libreFS** | Drop-in MinIO fork with preserved open-source features |
| Apache 2.0 permissive license | **RustFS** | Safe for commercial embedding in analytical pipelines |

### Decision Tree

```
Need RisingWave / ClickHouse S3 / stateful streaming?
  └─ YES → MinIO or libreFS (both validated)
            Do NOT use RustFS

File size < 5 MB? (streaming ingest, Iceberg micro-commits)
  └─ YES → RustFS  (2-3.5x faster writes, 3x faster Iceberg)

File size > 32 MB? (batch Spark, dbt exports, compaction)
  └─ YES → libreFS (28.8 MB/s, +42% over MinIO)
            Profile P99 variance under sustained load first

Need maximum concurrent throughput?
  └─ YES → MinIO  (29 MB/s aggregate heavy-mode; proven quorum)

DuckLake / ACID lakehouse with frequent commits?
  └─ YES → RustFS  (36ms txn P50, fastest time-travel)

Need WebUI + LDAP + AGPLv3 without AIStor?
  └─ YES → libreFS (MinIO fork; production-validated for streaming)
```

---

## Methodology Details

See [`docx-appendix-methodology.md`](docx-appendix-methodology.md) for full methodology including:

- Detailed explanation of all four benchmark designs
- Architecture decisions and rationale
- Result interpretation guide
- Known limitations and fixes applied

### Key Fixes Applied (from peer review)

| # | Fix |
|---|-----|
| 1 | Column-materializing queries instead of `COUNT(*)` — forces full Parquet page reads |
| 3 | `DuckDBAdapter` — extensions loaded once, connection reused per worker thread |
| 4 | Heavy-mode readers re-list S3 keys every 5s to discover fresh writes |
| 5 | `LOAD httpfs` not `INSTALL httpfs` — no network download during benchmark |
| 6 | `SET threads=1` per connection — prevents thread explosion |
| 14 | DuckLake concurrent mode: per-worker SQLite metadata — tests S3, not SQLite WAL |

### Known Limitations

- All tests on Docker loopback (`127.0.0.1`) — no real network latency
- OS page cache warm on reads (Windows; `drop_caches` not available)
- Write throughput includes Parquet CPU encoding overhead
- SeaweedFS excluded this run (Docker Desktop port instability)

---

## Requirements

```
Python  3.13+  via uv
Docker  Desktop (or Docker Engine on Linux)
duckdb          # httpfs + iceberg extensions bundled
boto3           # bucket lifecycle, object size queries
```

```bash
uv sync   # installs all dependencies from pyproject.toml
```

---

*Full benchmark report with expert analysis: [`docx-appendix-methodology.md`](docx-appendix-methodology.md)*
*Workshop series: [github.com/sepahram-school/workshops](https://github.com/sepahram-school/workshops)*
