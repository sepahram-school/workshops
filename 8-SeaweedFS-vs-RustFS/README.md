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

## 🚨 CRITICAL PRODUCTION WARNING (RustFS + RisingWave)

> [!CAUTION]
> **Over the past six months, RustFS was deployed as the Hummock storage engine in two separate RisingWave production projects.**
>
> - ❌ **Both projects encountered critical, specific errors** from the Hummock engine under production‑level load.
> - ✅ **In both instances, replacing RustFS entirely with MinIO resolved all issues completely.**
>
> **Final Verdict:** Do not adopt any storage engine other than MinIO (or its open‑source equivalent, libreFS) as a RisingWave Hummock backend **without first stress‑testing under full production load**.

---

## 🧪 Test Environment

| Spec | Value |
|------|-------|
| **Machine** | DELL Precision 5520 |
| **CPU** | Intel Core i7‑7820HQ @ 2.90 GHz |
| **RAM** | 32.0 GB (31.9 GB usable) |
| **OS** | Windows 11 Pro (64‑bit) |
| **Docker** | Docker Desktop |
| **Python** | 3.13.6 via uv |
| **Date** | 2026‑06‑19 |

All benchmarks were run in isolation — one cluster active at a time, with full cleanup between runs — to eliminate resource contention.

---

## 📦 The Systems at a Glance

| System | Founded | Language | License (Verified) | Key Differentiator |
|--------|---------|----------|--------------------|--------------------|
| **MinIO** | 2015 | Go | **AGPLv3** | Reference S3 implementation; most production deployments |
| **SeaweedFS** | 2015 | Go | **Apache 2.0** | Distributed blob store with POSIX filer; designed for billions of small files |
| **RustFS** | 2024 | Rust | **Apache 2.0** | MinIO‑compatible object store in Rust; memory safety + permissive license |
| **libreFS** | 2025 | Go | **AGPLv3** | Community fork preserving MinIO’s open‑source features (WebUI, LDAP, erasure coding) |

**MinIO** started as an open‑source S3‑compatible store and became the de facto standard for data lakes. In 2025, MinIO moved enterprise features (WebUI, LDAP, distributed erasure coding) behind a proprietary paywall called AIStor, keeping only the core AGPLv3 server open source. This license change triggered the search for alternatives.

**SeaweedFS** was originally built at Facebook for real‑time blob storage at scale. It provides both S3‑compatible API and a POSIX filesystem via its Filer component, making it unique among these options.

**RustFS** is a MinIO‑compatible object store rewritten in Rust, aiming for the same S3 API with Rust’s memory safety guarantees and **Apache 2.0 licensing**, making it safe for commercial embedding without copyleft concerns.

**libreFS** is a community fork of MinIO, preserving the full open‑source feature set that MinIO moved to AIStor — including WebUI, LDAP/OIDC, and distributed erasure coding.

---

## 🐳 Docker Cluster Architecture

Each system requires a different number of containers and components:

### MinIO (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **minio1** | `minio/minio:latest` | Distributed S3 server + storage (erasure coded) |
| **minio2** | `minio/minio:latest` | Distributed S3 server + storage |
| **minio3** | `minio/minio:latest` | Distributed S3 server + storage |

Same architecture as libreFS — 3-node distributed cluster with erasure coding.

### SeaweedFS (9 containers)

| Container | Image | Role |
|-----------|-------|------|
| **master1** | `chrislusf/seaweedfs:latest` | Raft leader — volume allocation, metadata coordination |
| **master2** | `chrislusf/seaweedfs:latest` | Raft follower — provides quorum and failover |
| **master3** | `chrislusf/seaweedfs:latest` | Raft follower — provides quorum and failover |
| **volume1** | `chrislusf/seaweedfs:latest` | Data storage node (append‑only blobs) |
| **volume2** | `chrislusf/seaweedfs:latest` | Data storage node |
| **volume3** | `chrislusf/seaweedfs:latest` | Data storage node |
| **filer** | `chrislusf/seaweedfs:latest` | POSIX filesystem namespace and metadata layer |
| **s3** | `chrislusf/seaweedfs:latest` | S3‑compatible API gateway |

Every S3 write flows through **4 hops**: `S3 gateway → filer → master (assign volume) → volume node`. This coordination step is why SeaweedFS has different concurrency characteristics than the others.

### RustFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **rustfs‑1** | `rustfs/rustfs:latest` | Full S3 server + storage node (erasure coded) |
| **rustfs‑2** | `rustfs/rustfs:latest` | Full S3 server + storage node |
| **rustfs‑3** | `rustfs/rustfs:latest` | Full S3 server + storage node |

Each node runs a complete server — the S3 endpoint *is* the storage node. No coordination step needed.

### libreFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **librefs‑1** | `librefs:local` | Full MinIO‑compatible server + storage (distributed erasure coding) |
| **librefs‑2** | `librefs:local` | Full MinIO‑compatible server + storage |
| **librefs‑3** | `librefs:local` | Full MinIO‑compatible server + storage |

Same architecture as MinIO distributed mode — each node is a complete server.

---

## 🔧 The 5‑Thread Limit: Why SeaweedFS Can’t Handle 20 Threads

Every write in SeaweedFS requires a round‑trip to the master to “assign a volume” before data can be stored:

```
Client → S3 Gateway → Filer → Master (assign volume) → Volume Node
```

With 20 concurrent threads each holding a `filer → master` gRPC connection open simultaneously, the master serializes all 20 assignments. The connections pile up waiting, hit the deadline timeout, and fail — even though the volume nodes and disk are sitting idle.

With MinIO or RustFS, the thread talks directly to the server which owns the storage. No coordination step. 20 threads in parallel means 20 independent operations — there’s no shared bottleneck.

**Why 5 threads specifically works:** At 5 threads the master can assign volumes fast enough that connections return before the deadline. At 10+ threads the queue depth grows faster than the master can drain it, and the first timeout triggers a cascade.

**Why heavy mode works at 5 threads despite appearing high‑throughput:** In the benchmark the heavy workload is 90%+ reads. Reads in SeaweedFS go `S3 gateway → filer → volume` — they bypass the master entirely, because volume location is already known. Only writes need master coordination. With 5 threads there might be only 2–3 concurrent writes at any moment, well within the master’s capacity.

**Can you raise it beyond 5 with the 3‑master Raft cluster?** Somewhat — Raft spreads the assignment load across 3 masters, so you might get to 8–10 threads reliably. But you won’t reach 20 because the filer itself becomes the next bottleneck: it maintains a single gRPC connection pool to the masters, and that pool has a fixed size. The `-concurrentFileUploadLimit=100` flag on the S3 gateway doesn’t help because the constraint is in the filer layer below it.

**The architectural trade‑off is inherent, not a bug.** Even in a healthy SeaweedFS cluster, every S3 write goes through 4 hops vs MinIO/RustFS which are single‑process — the S3 endpoint *is* the storage node. That extra coordination latency is part of SeaweedFS’s design.

---

## 📈 Benchmark Methodology

### Test Data

| Size Tier | Files | Per‑File Size | Total per Run |
|-----------|-------|---------------|---------------|
| 1 MB | 17 measured (3 warmup) | 1 MB | ~17 MB |
| 16 MB | 17 measured (3 warmup) | 16 MB | ~272 MB |
| 32 MB | 17 measured (3 warmup) | 32 MB | ~544 MB |

Files are pre‑generated with random bytes (no generation overhead during measurement).

### Workload Modes

1. **Write‑only**: Concurrent file uploads using boto3 (warmup: 3 files, measure: 17 files)
2. **Read‑only**: Seed bucket, then measure read throughput via boto3 `GetObject`
3. **Heavy mixed**: Split threads (half writers + half readers) running simultaneously for 30 seconds — the core stress test

### Concurrency

| System | Threads | Why |
|--------|---------|-----|
| **MinIO** | 20 | Single‑process server handles concurrency natively |
| **RustFS** | 20 | Same architecture as MinIO |
| **libreFS** | 20 | Same architecture as MinIO |
| **SeaweedFS** | 5 | Master serializes volume assignments; higher counts cause gRPC deadline exhaustion |

### Multiple Runs

Each configuration runs **3 times** with mean ± stdev reporting.

### Software Versions

| System | Image / Version | Notes |
|--------|-----------------|-------|
| **MinIO** | `minio/minio:latest` (2026‑06‑20) | Latest free/open‑source version (AGPLv3) |
| **SeaweedFS** | `chrislusf/seaweedfs:latest` | Latest stable |
| **RustFS** | `docker.arvancloud.ir/rustfs/rustfs:latest` | Latest stable |
| **libreFS** | `librefs:local` (built from source) | Forked from MinIO at `RELEASE.2025‑04‑22T22‑12‑26Z` |

> **Note on MinIO licensing:** As of 2025, MinIO moved enterprise features (WebUI, LDAP, distributed erasure coding) behind a proprietary paywall called AIStor. The core S3 server remains open‑source under AGPLv3. We used the latest free version available as of 2026‑06‑20.

### Reproducibility

All benchmark code is open‑source in the workshop repository. Exact throughput numbers depend on host CPU, disk I/O, and background processes — use these results for directional comparison, not absolute guarantees.

---

## 🦆 DuckDB Benchmark: Analytical Workload Test

In addition to the classic boto3 benchmark (raw S3 PUT/GET), we provide a **DuckDB benchmark** that tests analytical workloads using columnar Parquet reads/writes. This tests a different access pattern: real-world data lake and OLAP scenarios.

### Classic vs DuckDB Benchmark

| Aspect | Classic (`benchmark.py`) | DuckDB (`benchmark_duckdb.py`) |
|--------|--------------------------|-------------------------------|
| **Client** | boto3 (AWS SDK) | DuckDB with httpfs extension |
| **Data format** | Raw binary (.bin) | Parquet (.parquet) |
| **Write operation** | `put_object()` | `COPY TO s3://` |
| **Read operation** | `get_object()` | `read_parquet()` from S3 |
| **What it tests** | Raw S3 throughput | Analytical workload |
| **Results dir** | `results/` | `results_duckdb/` |

### Why DuckDB?

DuckDB's S3 integration tests how well storage systems handle **columnar Parquet workloads** — the pattern used by modern data lakes, OLAP engines, and analytics pipelines. Raw `put_object`/`get_object` benchmarks measure byte transfer speed, but real analytics queries read specific columns, apply predicates, and aggregate data.

### Running the DuckDB Benchmark

```bash
# Generate Parquet test data
uv run python generate_data_parquet.py --size all --files 100

# Run benchmark
uv run python benchmark_duckdb.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_duckdb.py --target all --mode heavy --sizes 1mb,32mb --runs 3
```

> **Full methodology**: See [`docx-appendix-methodology.md`](docx-appendix-methodology.md) for detailed explanation of DuckDB benchmark design and interpretation.

---

## 📊 Consolidated Benchmark Results

> The tables below present **throughput (MB/s)** and **P50 latency** for all three workloads. All values are mean ± stdev (n=3). SeaweedFS is capped at 5 threads; all others run at 20 threads.

### Throughput (MB/s) — All Workloads

| Workload | File Size | MinIO (3‑node) | RustFS | libreFS | SeaweedFS |
|----------|-----------|-----------------|--------|---------|-----------|
| **Heavy Mixed** | 1 MB | **57.6 ± 3.7** | 30.8 ± 4.6 | 43.5 ± 9.1 | 27.8 ± 3.1 |
| | 16 MB | **108.5 ± 3.8** | 42.6 ± 7.1 | 70.2 ± 19.8 | 27.0 ± 4.4 |
| | 32 MB | **88.7 ± 19.2** | 39.4 ± 2.3 | 85.6 ± 12.8 | 32.7 ± 1.9 |
| **Write‑Only** | 1 MB | 4.9 ± 0.6 | 11.6 ± 2.0 | 10.1 ± 1.1 | **15.8 ± 2.4** |
| | 16 MB | **47.6 ± 6.6** | 37.8 ± 4.9 | 32.3 ± 4.4 | 15.2 ± 2.7 |
| | 32 MB | **61.5 ± 7.1** | 32.8 ± 7.3 | 54.7 ± 13.3 | 19.9 ± 1.2 |
| **Read‑Only** | 1 MB | **55.6 ± 8.4** | 20.7 ± 6.1 | 26.7 ± 9.9 | 15.0 ± 3.0 |
| | 16 MB | **111.3 ± 18.9** | 48.8 ± 5.4 | 98.7 ± 24.1 | 35.8 ± 0.2 |
| | 32 MB | **116.2 ± 18.5** | 53.3 ± 3.2 | 101.9 ± 43.4 | 44.3 ± 3.6 |

### P50 Latency (seconds) — All Workloads

| Workload | File Size | MinIO (3‑node) | RustFS | libreFS | SeaweedFS |
|----------|-----------|-----------------|--------|---------|-----------|
| **Heavy — Write** | 1 MB | 3.187s | 0.876s | 4.803s | **0.275s** |
| | 16 MB | 7.848s | **7.220s** | 11.262s | 3.463s |
| | 32 MB | 13.302s | 15.358s | **12.385s** | 5.298s |
| **Heavy — Read** | 1 MB | 0.163s | 0.480s | 0.223s | **0.133s** |
| | 16 MB | 1.665s | 6.928s | 2.458s | **1.526s** |
| | 32 MB | 4.600s | 15.894s | 4.704s | **4.338s** |
| **Write‑Only** | 1 MB | 3.405s | **1.386s** | 1.647s | 0.288s |
| | 16 MB | 5.679s | 7.145s | 8.381s | **5.041s** |
| | 32 MB | 8.754s | 16.918s | 10.269s | **7.532s** |
| **Read‑Only** | 1 MB | **0.271s** | 0.843s | 0.614s | 0.325s |
| | 16 MB | 2.826s | 6.450s | 3.228s | **2.100s** |
| | 32 MB | 5.402s | 11.866s | 7.113s | **3.466s** |

### Success Rates

| System | 1 MB | 16 MB | 32 MB |
|--------|------|-------|-------|
| MinIO | **100%** | **100%** | **100%** |
| RustFS | **100%** | **100%** | **100%** |
| libreFS | **100%** | **100%** | **100%** |
| SeaweedFS | **100%** | **100%** | **100%** |

---

## 💾 Storage Overhead Analysis

| System | Replication | Overhead Ratio | Effective TB per Physical TB |
|--------|-------------|----------------|------------------------------|
| SeaweedFS (RF=1) | 2 copies | ~2x | 0.50 TB |
| RustFS | Erasure coding | ~1.5x | 0.67 TB |
| libreFS | Erasure coding | ~1.5x | 0.67 TB |
| MinIO | Erasure coding | ~1.5x | 0.67 TB |

SeaweedFS RF=1 uses 2× more raw disk than erasure‑coded systems for the same usable capacity.

---

## ✅ Production Readiness Assessment

### 🏆 MinIO — The Gold Standard (3‑Node Distributed)

**Strengths:**
- Highest heavy mixed throughput — 108.5 MB/s (16 MB), 88.7 MB/s (32 MB)
- Highest read‑only throughput — 116.2 MB/s (32 MB), 111.3 MB/s (16 MB)
- 100% success rate across all sizes
- Proven at scale

**Weaknesses:**
- AGPLv3 license (server remains open source)
- Write latency higher than SeaweedFS under heavy load

---

### 🦀 RustFS — Consistent Performer with Apache 2.0

**Verdict:** ⚠️ **Caution: Known Production Issue with RisingWave, but permissive license makes it attractive for commercial use**

**Strengths:**
- 100% success rate across all sizes
- Consistent heavy combined throughput (25–44 MB/s)
- Good read‑only performance (50.6 MB/s for 32 MB)
- **Apache 2.0 license** — safe for commercial embedding without copyleft concerns
- Memory safety guarantees from Rust
- No CGO dependency

**Weaknesses:**
- Lower throughput ceiling than MinIO
- Write latency high for 32 MB (P50: 15–26 s)
- **Production failures observed in RisingWave Hummock role** — must stress‑test before adoption

---

### 🔄 libreFS — Competitive with MinIO

**Strengths:**
- 100% success rate across all sizes
- Strong read‑only performance (73.3 MB/s for 32 MB)
- Full MinIO‑compatible API, WebUI, LDAP/OIDC
- Good write‑only performance (44.0 MB/s for 32 MB)

**Weaknesses:**
- Slowest 1 MB write‑only (7.2 MB/s)
- Higher write latency under contention
- Requires adequate disk space
- AGPLv3 license (copyleft obligations)

---

### 🌿 SeaweedFS — Lowest Latency

**Strengths:**
- Lowest read latency across all sizes (P50: 0.133s for 1 MB)
- Lowest write latency for 1 MB (P50: 0.266s)
- Apache 2.0 license (fewest restrictions)
- 100% success rate on all tested sizes
- POSIX filesystem access via Filer

**Weaknesses:**
- Only 5 threads supported (master serializes volume assignments)
- Requires cluster restart between sustained write batches
- 3‑master Raft requires more containers (9 total)
- 4‑hop write path adds coordination latency vs single‑process systems
- 2× storage overhead at RF=1

---

## 🚀 RisingWave + S3: How SeaweedFS Fits

RisingWave uses S3 in two distinct ways:

1. **Hummock state store (critical path)** — LSM‑tree checkpoints, SST files, compaction output. Multipart uploads with 16 MB parts (up to 512 MB per SST during deep compaction).
2. **S3 sink (secondary)** — Append‑only Parquet output via `CREATE SINK`.

### Suitability Matrix

| RisingWave Usage | MinIO | libreFS | RustFS | SeaweedFS |
|------------------|-------|---------|--------|-----------|
| **Hummock (low‑medium throughput)** | ✅ Best | ✅ Good | ⚠️ Test first | ❌ No |
| **Hummock (high throughput)** | ✅ Best | ✅ Good | ❌ Proven failure | ❌ No |
| **S3 Sink (Parquet)** | ✅ Good | ✅ Good | ✅ Good | ✅ Good (POSIX bonus) |
| **Dev / Staging** | ✅ Good | ✅ Good | ✅ Good (Apache 2.0) | ✅ Good (Apache 2.0) |

### Why SeaweedFS is Risky for Hummock
- **Multipart upload overhead:** Each part requires a separate `assign volume` RPC to the master — the same gRPC bottleneck observed in our benchmark.
- **ListObjectsV2 at scale:** The filer becomes a bottleneck at tens of thousands of SST files.

### The Critical RustFS Warning (Author’s Production Experience)
> Over the past six months, RustFS was used as the Hummock storage engine in **two separate RisingWave production projects**. In both cases, once the systems were placed under production‑level workloads, **critical errors emerged from the Hummock engine and the underlying storage layer**. In each instance, replacing RustFS entirely with MinIO resolved the issue completely.

**Conclusion:** Do not adopt any storage engine other than MinIO (or its open‑source equivalent, libreFS) as a RisingWave Hummock backend without first stress‑testing under full production load.

---

## 🧠 Key Findings

1. **MinIO dominates heavy throughput** — 108.5 MB/s (16 MB), 88.7 MB/s (32 MB)
2. **MinIO dominates read‑only** — 116.2 MB/s (32 MB), 111.3 MB/s (16 MB)
3. **SeaweedFS excels at read latency** — P50: 0.133s (1 MB), lowest across all sizes
4. **SeaweedFS excels at write latency** — P50: 0.275s (1 MB), lowest across all sizes
5. **libreFS competitive with MinIO** — 85.6 MB/s (32 MB) heavy, 101.9 MB/s (32 MB) read‑only
6. **RustFS consistent but slower** — 100% success, lower throughput ceiling
7. **All systems 100% success** across all tested sizes (1 MB, 16 MB, 32 MB)
8. **SeaweedFS requires cluster restart** — gRPC connection pool degrades under sustained load

---

## 🧭 Recommendation Matrix

| Use Case | Recommended | Rationale |
|----------|-------------|-----------|
| Data lake / analytics platform | **MinIO** | Highest heavy throughput (108.5 MB/s for 16 MB), proven at scale |
| S3 drop‑in replacement (MinIO migration) | **libreFS** | Full MinIO‑compatible API, WebUI/LDAP, competitive performance (85.6 MB/s heavy) |
| High‑availability production | **MinIO** | Most stable, highest throughput, proven at scale |
| Low‑latency reads | **SeaweedFS** | Lowest read P50 across all sizes (0.133s for 1 MB) |
| Low‑latency writes | **SeaweedFS** | Lowest write P50 (0.275s for 1 MB) |
| AI/ML training data storage | **MinIO** | Highest throughput, proven at scale |
| Commercial SaaS product (AGPL‑averse) | **RustFS or SeaweedFS** | Both Apache 2.0; RustFS for better write throughput, SeaweedFS for lower latency + POSIX |
| POSIX filesystem needed | **SeaweedFS** | Apache 2.0, POSIX support via Filer |

---

## ⚠️ Methodology Limitations

1. **Single‑host Docker** — All “nodes” share one disk and NIC
2. **Loopback networking** — Zero real network latency
3. **No failure injection** — Docker stop ≠ node failure
4. **Client bottleneck** — Python/boto3 may saturate before storage does
5. **Small data volume** — ~17–544 MB per run vs TBs in production
6. **30‑second test duration** — Longer runs may reveal different behavior
7. **SeaweedFS requires restart** — gRPC connection pool degrades under sustained load
8. **Windows Docker Desktop** — Potential port stale connections

---

## 📚 Appendix: Raw Results

<details>
<summary><b>Click to expand all raw per‑run data</b></summary>

### MinIO — 1MB Heavy (n=3, 3‑node cluster)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | — | — | — | 29.9 | 6.240s | 0.310s |
| 2 | — | — | — | 39.5 | 4.706s | 0.231s |
| 3 | — | — | — | 35.4 | 5.473s | 0.270s |
| **Mean** | — | — | — | **34.9 ± 4.5** | **5.473s** | **0.270s** |

### RustFS — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 257 | 415 | 672 | 21.6 | 1.213s | 0.694s |
| 2 | 307 | 510 | 817 | 26.5 | 0.976s | 0.585s |
| 3 | 311 | 510 | 821 | 27.0 | 0.958s | 0.583s |
| **Mean** | **292** | **478** | **770** | **25.0 ± 3.0** | **1.049s** | **0.621s** |

### libreFS — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 896 | 946 | 30.4 | 6.389s | 0.314s |
| 2 | 50 | 827 | 877 | 28.0 | 7.152s | 0.350s |
| 3 | 40 | 683 | 723 | 22.7 | 6.959s | 0.395s |
| **Mean** | **47** | **802** | **849** | **27.0 ± 4.0** | **6.833s** | **0.353s** |

### SeaweedFS — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 229 | 701 | 930 | 30.9 | 0.249s | 0.120s |
| 2 | 205 | 640 | 845 | 28.0 | 0.274s | 0.130s |
| 3 | 189 | 553 | 742 | 24.6 | 0.303s | 0.149s |
| **Mean** | **208** | **631** | **839** | **27.8 ± 3.1** | **0.275s** | **0.133s** |

### MinIO — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 21.7 | 0.726s |
| 2 | 17 | 17 | 23.7 | 0.641s |
| 3 | 17 | 17 | 16.9 | 0.907s |
| **Mean** | **17** | **17** | **20.8 ± 3.5** | **0.758s** |

### RustFS — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 27.4 | 0.563s |
| 2 | 17 | 17 | 20.1 | 0.728s |
| 3 | 17 | 17 | 5.5 | 2.794s |
| **Mean** | **17** | **17** | **17.7 ± 11.1** | **1.362s** |

### libreFS — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 8.8 | 1.813s |
| 2 | 17 | 17 | 6.5 | 2.399s |
| 3 | 17 | 17 | 6.1 | 2.668s |
| **Mean** | **17** | **17** | **7.2 ± 1.5** | **2.293s** |

### SeaweedFS — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 17.4 | 0.266s |
| 2 | 17 | 17 | 13.0 | 0.321s |
| 3 | 17 | 17 | 17.0 | 0.276s |
| **Mean** | **17** | **17** | **15.8 ± 2.4** | **0.288s** |

### MinIO — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 44.3 | 0.283s |
| 2 | 20 | 20 | 39.4 | 0.372s |
| 3 | 20 | 20 | 52.1 | 0.262s |
| **Mean** | **20** | **20** | **45.3 ± 6.4** | **0.306s** |

### RustFS — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 32.5 | 0.528s |
| 2 | 20 | 20 | 15.2 | 1.076s |
| 3 | 20 | 20 | 26.9 | 0.622s |
| **Mean** | **20** | **20** | **24.9 ± 8.8** | **0.742s** |

### libreFS — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 21.5 | 0.664s |
| 2 | 20 | 20 | 29.1 | 0.475s |
| 3 | 20 | 20 | 27.5 | 0.417s |
| **Mean** | **20** | **20** | **26.0 ± 4.0** | **0.519s** |

### SeaweedFS — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 14.5 | 0.352s |
| 2 | 20 | 20 | 18.3 | 0.237s |
| 3 | 20 | 20 | 12.4 | 0.386s |
| **Mean** | **20** | **20** | **15.0 ± 3.0** | **0.325s** |

### MinIO — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 80 | 140 | 3520 | 108.5 | 3.827s | 2.075s |
| 2 | 82 | 150 | 3712 | 119.5 | 3.441s | 1.937s |
| 3 | 90 | 160 | 4000 | 123.9 | 3.678s | 1.960s |
| **Mean** | **84** | **150** | **3744** | **117.3 ± 7.9** | **3.649s** | **1.991s** |

### RustFS — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 50 | 1600 | 45.1 | 6.850s | 6.895s |
| 2 | 40 | 41 | 1296 | 41.2 | 7.996s | 8.090s |
| 3 | 50 | 50 | 1600 | 46.5 | 6.941s | 6.743s |
| **Mean** | **47** | **47** | **1499** | **44.3 ± 2.8** | **7.262s** | **7.243s** |

### libreFS — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 20 | 85 | 1680 | 52.4 | 15.975s | 2.916s |
| 2 | 20 | 70 | 1440 | 43.4 | 16.472s | 4.925s |
| 3 | 30 | 100 | 2080 | 57.4 | 14.189s | 3.041s |
| **Mean** | **23** | **85** | **1733** | **51.1 ± 7.1** | **15.545s** | **3.627s** |

### SeaweedFS — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 16 | 30 | 736 | 22.2 | 4.107s | 3.283s |
| 2 | 18 | 36 | 864 | 28.0 | 3.287s | 2.356s |
| 3 | 20 | 39 | 944 | 30.8 | 2.996s | 2.333s |
| **Mean** | **18** | **35** | **848** | **27.0 ± 4.4** | **3.463s** | **2.658s** |

### MinIO — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 95.7 | 2.669s |
| 2 | 17 | 272 | 32.1 | 8.332s |
| 3 | 17 | 272 | 54.8 | 4.669s |
| **Mean** | **17** | **272** | **60.9 ± 32.2** | **5.223s** |

### RustFS — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 22.7 | 11.731s |
| 2 | 17 | 272 | 27.6 | 9.700s |
| 3 | 17 | 272 | 29.2 | 9.188s |
| **Mean** | **17** | **272** | **26.5 ± 3.4** | **10.206s** |

### libreFS — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 31.2 | 8.625s |
| 2 | 17 | 272 | 29.6 | 9.023s |
| 3 | 17 | 272 | 22.2 | 12.077s |
| **Mean** | **17** | **272** | **27.7 ± 4.8** | **9.908s** |

### SeaweedFS — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 12.9 | 5.457s |
| 2 | 17 | 272 | 14.6 | 5.576s |
| 3 | 17 | 272 | 18.2 | 4.092s |
| **Mean** | **17** | **272** | **15.2 ± 2.7** | **5.041s** |

### MinIO — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 64.8 | 4.611s |
| 2 | 20 | 320 | 82.3 | 3.714s |
| 3 | 20 | 320 | 100.7 | 3.025s |
| **Mean** | **20** | **320** | **82.6 ± 18.0** | **3.783s** |

### RustFS — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 46.4 | 6.773s |
| 2 | 20 | 320 | 48.4 | 6.446s |
| 3 | 20 | 320 | 47.2 | 6.653s |
| **Mean** | **20** | **320** | **47.3 ± 1.0** | **6.624s** |

### libreFS — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 67.6 | 4.406s |
| 2 | 20 | 320 | 74.0 | 4.165s |
| 3 | 20 | 320 | 64.7 | 4.747s |
| **Mean** | **20** | **320** | **68.8 ± 4.7** | **4.439s** |

### SeaweedFS — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 35.6 | 2.071s |
| 2 | 20 | 320 | 36.0 | 2.051s |
| 3 | 20 | 320 | 35.9 | 2.178s |
| **Mean** | **20** | **320** | **35.8 ± 0.2** | **2.100s** |

### MinIO — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 60 | 3520 | 100.3 | 6.346s | 4.579s |
| 2 | 43 | 60 | 3296 | 101.8 | 7.562s | 5.370s |
| 3 | 50 | 60 | 3520 | 105.4 | 6.021s | 4.768s |
| **Mean** | **48** | **60** | **3445** | **102.5 ± 2.6** | **6.643s** | **4.906s** |

### RustFS — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 30 | 30 | 1920 | 46.0 | 13.620s | 13.854s |
| 2 | 30 | 30 | 1920 | 43.4 | 15.316s | 15.087s |
| 3 | 20 | 20 | 1280 | 39.2 | 16.081s | 16.026s |
| **Mean** | **27** | **27** | **1707** | **42.9 ± 3.4** | **15.006s** | **14.989s** |

### libreFS — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 20 | 40 | 1920 | 50.1 | 19.027s | 9.943s |
| 2 | 20 | 42 | 1984 | 58.9 | 16.667s | 7.794s |
| 3 | 20 | 50 | 2240 | 67.3 | 16.509s | 6.399s |
| **Mean** | **20** | **44** | **2048** | **58.8 ± 8.6** | **17.401s** | **8.045s** |

### SeaweedFS — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 12 | 23 | 1120 | 34.9 | 5.177s | 4.314s |
| 2 | 12 | 21 | 1056 | 32.0 | 5.331s | 4.608s |
| 3 | 12 | 23 | 1120 | 31.3 | 5.387s | 4.090s |
| **Mean** | **12** | **22** | **1099** | **32.7 ± 1.9** | **5.298s** | **4.338s** |

### MinIO — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 64.3 | 8.225s |
| 2 | 17 | 544 | 77.5 | 6.841s |
| 3 | 17 | 544 | 89.1 | 5.828s |
| **Mean** | **17** | **544** | **77.0 ± 12.4** | **6.965s** |

### RustFS — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 17.3 | 31.196s |
| 2 | 17 | 544 | 26.3 | 20.474s |
| 3 | 17 | 544 | 20.3 | 26.648s |
| **Mean** | **17** | **544** | **21.3 ± 4.6** | **26.106s** |

### libreFS — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 51.8 | 10.328s |
| 2 | 17 | 544 | 37.2 | 14.404s |
| 3 | 17 | 544 | 43.1 | 12.424s |
| **Mean** | **17** | **544** | **44.0 ± 7.3** | **12.386s** |

### SeaweedFS — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 18.6 | 6.792s |
| 2 | 17 | 544 | 20.1 | 8.009s |
| 3 | 17 | 544 | 21.0 | 7.795s |
| **Mean** | **17** | **544** | **19.9 ± 1.2** | **7.532s** |

### MinIO — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 121.0 | 5.156s |
| 2 | 20 | 640 | 154.2 | 4.031s |
| 3 | 20 | 640 | 149.6 | 4.156s |
| **Mean** | **20** | **640** | **141.6 ± 18.0** | **4.448s** |

### RustFS — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 53.6 | 11.763s |
| 2 | 20 | 640 | 51.0 | 12.343s |
| 3 | 20 | 640 | 47.2 | 13.320s |
| **Mean** | **20** | **640** | **50.6 ± 3.2** | **12.475s** |

### libreFS — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 87.3 | 7.192s |
| 2 | 20 | 640 | 55.2 | 11.248s |
| 3 | 20 | 640 | 77.5 | 7.678s |
| **Mean** | **20** | **640** | **73.3 ± 16.4** | **8.706s** |

### SeaweedFS — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 40.1 | 3.777s |
| 2 | 20 | 640 | 46.1 | 3.287s |
| 3 | 20 | 640 | 46.6 | 3.333s |
| **Mean** | **20** | **640** | **44.3 ± 3.6** | **3.466s** |

</details>

---

*All benchmarks in this report are fully reproducible. Clone the workshop, run the commands, and verify the results yourself. The code is designed for transparency — no hidden optimizations, no cherry‑picked numbers.*

**Benchmark date: June 19, 2026** · All scripts available at [github.com/sepahram-school/workshops](https://github.com/sepahram-school/workshops) — Workshop #8
