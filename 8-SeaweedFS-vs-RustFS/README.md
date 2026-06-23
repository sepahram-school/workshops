# S3 Without MinIO: A Benchmark of SeaweedFS vs RustFS vs libreFS

[![Benchmark Date](https://img.shields.io/badge/Benchmark%20Date-June%202026-blue)](https://shields.io/)
[![License](https://img.shields.io/badge/License-Mixed%20(AGPL%2FApache)-lightgrey)](https://shields.io/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready%20%28MinIO%29-green)](https://shields.io/)
[![Test Environment](https://img.shields.io/badge/Env-Docker%20%2B%20Windows%2011-orange)](https://shields.io/)

**When MinIO changed its license, data engineering teams needed alternatives.** This report provides a hands‑on, reproducible benchmark comparing four S3‑compatible storage systems: **SeaweedFS** (Apache 2.0), **RustFS** (Apache 2.0), **libreFS** (AGPLv3), and **MinIO** (AGPLv3 baseline). We deploy each as a Docker cluster, benchmark concurrent writes, and stress‑test with a **heavy mixed workload** — concurrent reads and writes simultaneously.

> **Author:** Mojtaba Banaie — [LinkedIn](https://www.linkedin.com/in/smbanaie/)  
> **Machine:** DELL Precision 5520 (i7‑7820HQ, 32GB RAM)  
> **Workloads:** Write‑Only · Read‑Only · Heavy Mixed (30s concurrent)  
> **File Sizes:** 1 MB · 16 MB · 32 MB  
> **Code & Reproducibility:** [github.com/sepahram-school/workshops](https://github.com/sepahram-school/workshops) — Workshop #8

---

## CRITICAL PRODUCTION WARNING (RustFS + RisingWave)

> [!CAUTION]
> **Over the past six months, RustFS was deployed as the Hummock storage engine in two separate RisingWave production projects.**
>
> - Both projects encountered critical, specific errors from the Hummock engine under production‑level load.
> - In both instances, replacing RustFS entirely with MinIO resolved all issues completely.
>
> **Final Verdict:** Do not adopt any storage engine other than MinIO (or its open‑source equivalent, libreFS) as a RisingWave Hummock backend **without first stress‑testing under full production load**.

---

## Table of Contents

1. [Test Environment](#test-environment)
2. [The Systems at a Glance](#the-systems-at-a-glance)
3. [How to Run](#how-to-run)
4. [Benchmark Overview](#benchmark-overview)
5. [Results](#results)
6. [Production Readiness](#production-readiness)
7. [Recommendation Matrix](#recommendation-matrix)
8. [Methodology Limitations](#methodology-limitations)

---

## Test Environment

| Spec | Value |
|------|-------|
| **Machine** | DELL Precision 5520 |
| **CPU** | Intel Core i7‑7820HQ @ 2.90 GHz |
| **RAM** | 32.0 GB (31.9 GB usable) |
| **OS** | Windows 11 Pro (64‑bit) |
| **Docker** | Docker Desktop |
| **Python** | 3.13.6 via uv |
| **Date** | 2026‑06‑22 |

All benchmarks were run in isolation — one cluster active at a time, with full cleanup between runs — to eliminate resource contention.

---

## The Systems at a Glance

| System | Founded | Language | License (Verified) | Key Differentiator |
|--------|---------|----------|--------------------|--------------------|
| **MinIO** | 2015 | Go | **AGPLv3** | Reference S3 implementation; most production deployments |
| **SeaweedFS** | 2015 | Go | **Apache 2.0** | Distributed blob store with POSIX filer; designed for billions of small files |
| **RustFS** | 2024 | Rust | **Apache 2.0** | MinIO‑compatible object store in Rust; memory safety + permissive license |
| **libreFS** | 2025 | Go | **AGPLv3** | Community fork preserving MinIO's open‑source features (WebUI, LDAP, erasure coding) |

---

## How to Run

### Prerequisites

- **Docker** and **Docker Compose v2** installed and running
- **Python 3.10+** installed
- **uv** installed (Python package manager)

```bash
# Install uv
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 1: Set Up Environment

```bash
cd 8-SeaweedFS-vs-RustFS
uv venv
uv sync
```

### Step 2: Generate Test Data

```bash
uv run python generate-data.py --size all --files 100
uv run python generate_data_parquet.py --size all --files 100
```

### Step 3: Start a Target Cluster

```bash
# MinIO (3-node distributed)
docker compose -f docker-compose-minio.yml up -d

# RustFS (3-node)
docker compose -f docker-compose-rustfs.yml up -d

# libreFS (3-node)
docker compose -f docker-compose-librefs.yml up -d

# SeaweedFS (9 containers)
docker compose -f docker-compose-seaweedfs.yml up -d
```

### Step 4: Run Benchmarks

#### Benchmark 1: Classic (boto3 — Raw S3 PUT/GET)

```bash
uv run python benchmark.py --target minio --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20
uv run python benchmark.py --target minio --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20
uv run python benchmark.py --target minio --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20
```

#### Benchmark 2: DuckDB (Analytical Parquet I/O)

```bash
uv run python benchmark_duckdb.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_duckdb.py --target minio --mode read-only --sizes 1mb --runs 3
uv run python benchmark_duckdb.py --target minio --mode heavy --sizes 1mb,32mb --runs 3
```

#### Benchmark 3: DuckLake (Lakehouse — SQLite Metadata)

```bash
uv run python benchmark_ducklake.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_ducklake.py --target minio --mode read-only --sizes 1mb --runs 3
uv run python benchmark_ducklake.py --target minio --mode heavy --sizes 1mb,32mb --runs 3
uv run python benchmark_ducklake.py --target minio --mode transactions
uv run python benchmark_ducklake.py --target minio --mode time-travel
uv run python benchmark_ducklake.py --target minio --mode snapshots
```

#### Benchmark 4: Iceberg (Lakehouse — File-Based Metadata)

```bash
uv run python benchmark_iceberg.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode read-only --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode heavy --sizes 1mb,32mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode time-travel --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode snapshots --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode change-detection --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target minio --mode update --sizes 1mb --runs 1
uv run python benchmark_iceberg.py --target minio --mode delete --sizes 1mb --runs 1
```

> **SeaweedFS:** Run preprocessing before each mode due to gRPC connection pool degradation.

### Step 5: Stop and Clean

```bash
# Stop all clusters
docker compose -f docker-compose-minio.yml down -v
docker compose -f docker-compose-rustfs.yml down -v
docker compose -f docker-compose-librefs.yml down -v
docker compose -f docker-compose-seaweedfs.yml down -v

# Remove data directories
rm -rf data-minio data-rustfs data-librefs data-seaweedfs data data_parquet
```

### Results Directory

```
results/              ← Classic (boto3)
results_duckdb/       ← DuckDB (Parquet I/O)
results_ducklake/     ← DuckLake (SQLite metadata)
results_iceberg/      ← Iceberg (file-based metadata)
```

Each directory follows: `{mode}/{size}/{target}/run-{N}.json`

### Troubleshooting

| Problem | Solution |
|---------|----------|
| SeaweedFS times out | Run preprocessing before each mode |
| RustFS not responding | Use `127.0.0.1` instead of `localhost` (IPv6 issue) |
| Disk space errors | Clean data between runs (Step 5) |
| Docker port conflict | `docker compose down -v` then `docker system prune` |

---

## Benchmark Overview

Four benchmarks test progressively more realistic workloads:

| Benchmark | Script | What It Tests | Results Dir |
|-----------|--------|--------------|-------------|
| **Classic** | `benchmark.py` | Raw S3 throughput (PUT/GET) | `results/` |
| **DuckDB** | `benchmark_duckdb.py` | Analytical Parquet I/O | `results_duckdb/` |
| **DuckLake** | `benchmark_ducklake.py` | Lakehouse (SQLite metadata) | `results_ducklake/` |
| **Iceberg** | `benchmark_iceberg.py` | Iceberg-style (file-based metadata) | `results_iceberg/` |

### DuckDB Benchmark Modes
`write-only` · `read-only` · `heavy`

### DuckLake Benchmark Modes
`write-only` · `read-only` · `heavy` · `transactions` · `time-travel` · `snapshots`

### Iceberg Benchmark Modes
`write-only` · `read-only` · `mixed` · `heavy` · `time-travel` · `snapshots` · `change-detection` · `update` · `delete`

---

## Results

### DuckDB: Parquet I/O Throughput (MB/s, 32mb)

| Target | Write-Only | Read-Only | Heavy |
|--------|-----------|-----------|-------|
| **MinIO** | 20.2 ± 1.6 | 50.7 ± 4.4 | 29.0 (W) |
| **RustFS** | 21.8 ± 1.0 | **61.0 ± 7.1** | 8.3 (W) |
| **libreFS** | **28.8 ± 3.3** | 54.5 ± 10.8 | 4.3 (W) |

**libreFS** leads large-file writes. **RustFS** leads reads.

### DuckLake: Lakehouse (P50 Latency, 32mb)

| Target | Write-Only | Read-Only | Heavy (W/R) |
|--------|-----------|-----------|-------------|
| **MinIO** | 19.7 MB/s | 0.055s | 9.075s / - |
| **RustFS** | 19.9 MB/s | 0.059s | 3.215s / 0.029s |
| **libreFS** | 11.3 MB/s | 0.090s | 3.239s / 0.062s |

**RustFS** and **libreFS** handle concurrent DuckLake loads 3x better than MinIO.

### Iceberg: File-Based Metadata (P50 Latency, 32mb)

| Target | Write-Only | Read-Only | Mixed (W/R) | Heavy (W/R) |
|--------|-----------|-----------|-------------|-------------|
| **MinIO** | 0.121s | 0.023s | 0.129s / 0.039s | 0.819s / 0.112s |
| **RustFS** | **0.059s** | **0.014s** | **0.056s / 0.015s** | **0.257s / 0.082s** |
| **libreFS** | 0.172s | 0.034s | 0.172s / 0.069s | 1.098s / 0.072s |

**RustFS dominates Iceberg workloads** — 2x faster writes, 1.6x faster reads than MinIO.

### Iceberg-Specific Modes (P50 Latency, 32mb)

| Target | Time-Travel | Snapshots | Change-Detection | Update | Delete |
|--------|-------------|-----------|------------------|--------|--------|
| **MinIO** | 0.128s | 0.168s | 0.100s | 0.130s | 0.463s |
| **RustFS** | **0.049s** | **0.049s** | **0.053s** | 0.144s | **0.081s** |
| **libreFS** | 0.142s | 0.116s | 0.202s | 0.299s | 0.186s |

### Cross-Engine Comparison (1mb, P50 Latency)

| Target | Engine | Write-Only | Read-Only | Heavy |
|--------|--------|-----------|-----------|-------|
| **MinIO** | DuckDB | 2.335s | 0.786s | 2.475s |
| | DuckLake | 0.248s | 0.050s | 9.075s |
| | Iceberg | 0.412s | 0.024s | 0.819s |
| **RustFS** | DuckDB | 1.127s | 0.556s | 1.495s |
| | DuckLake | 0.425s | 0.040s | 3.215s |
| | Iceberg | **0.116s** | 0.029s | **0.257s** |
| **libreFS** | DuckDB | 2.306s | 0.864s | 3.052s |
| | DuckLake | 0.475s | **0.030s** | 3.239s |
| | Iceberg | 0.228s | 0.066s | 1.098s |

---

## Production Readiness

### MinIO — The Gold Standard

**Strengths:** Highest heavy throughput (108.5 MB/s for 16mb), proven at scale, 100% success.
**Weaknesses:** AGPLv3 license, slower writes under Iceberg workloads.

### RustFS — Apache 2.0 Performer

**Strengths:** Fastest Iceberg writes (0.059s P50), Apache 2.0 license, memory safety.
**Weaknesses:** Production failures observed with RisingWave Hummock.

### libreFS — MinIO-Compatible Alternative

**Strengths:** Highest DuckDB large-file writes (28.8 MB/s), full MinIO API compatibility.
**Weaknesses:** AGPLv3 license, slower under concurrent Iceberg loads.

### SeaweedFS — Lowest Latency

**Strengths:** Lowest read/write latency for small files, Apache 2.0, POSIX support.
**Weaknesses:** 5-thread limit, 9 containers required, 2x storage overhead.

---

## Recommendation Matrix

| Use Case | Recommended | Rationale |
|----------|-------------|-----------|
| Iceberg data lake | **RustFS** | 2-8x faster across all Iceberg modes |
| DuckDB analytical queries | **RustFS** | Highest read throughput (61 MB/s) |
| Large Parquet file writes | **libreFS** | 28.8 MB/s, 42% faster than MinIO |
| Concurrent mixed workloads | **RustFS** | Lowest P50 under contention |
| DuckLake lakehouse | **RustFS** | Fastest transactions (36ms) and time-travel |
| Proven production stability | **MinIO** | Highest heavy-mode throughput |
| S3 drop-in replacement | **libreFS** | Full MinIO-compatible API |
| Low-latency small files | **SeaweedFS** | Lowest P50 across all sizes |
| Commercial (AGPL-averse) | **RustFS or SeaweedFS** | Both Apache 2.0 |

---

## Methodology Limitations

1. **Single-host Docker** — All "nodes" share one disk and NIC
2. **Loopback networking** — Zero real network latency
3. **No failure injection** — Docker stop != node failure
4. **Client bottleneck** — Python/boto3 may saturate before storage does
5. **Small data volume** — ~17-544 MB per run vs TBs in production
6. **Windows Docker Desktop** — Potential port stale connections

---

## Methodology Details

See [`docx-appendix-methodology.md`](docx-appendix-methodology.md) for detailed explanation of all four benchmark designs, architecture decisions, and result interpretation.

---

*All benchmarks fully reproducible. Clone the workshop, run the commands, verify results.*

**Benchmark date: June 22, 2026** · [github.com/sepahram-school/workshops](https://github.com/sepahram-school/workshops) — Workshop #8
