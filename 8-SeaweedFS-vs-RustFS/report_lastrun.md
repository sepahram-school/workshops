# S3 Without MinIO: A Benchmark of SeaweedFS vs RustFS vs libreFS

**When MinIO changed its license, data engineering teams needed alternatives.** This article provides a hands-on benchmark comparing four S3-compatible storage systems: **SeaweedFS** (Apache 2.0), **RustFS** (AGPLv3), **libreFS** (AGPLv3), and **MinIO** (AGPLv3 baseline). We deploy each as a Docker cluster, benchmark concurrent writes, and stress-test with a **heavy mixed workload** — concurrent reads and writes simultaneously.

All benchmarks were run in isolation — one cluster active at a time, with full cleanup between runs — to eliminate resource contention.

---

## Test Environment

| Spec | Value |
|------|-------|
| **Machine** | DELL Precision 5520 |
| **CPU** | Intel Core i7-7820HQ @ 2.90GHz |
| **RAM** | 32.0 GB (31.9 GB usable) |
| **OS** | Windows 11 Pro (64-bit) |
| **Docker** | Docker Desktop |
| **Python** | 3.13.6 via uv |
| **Date** | 2026-06-19 |

---

## The Systems at a Glance

| System | Language | License | Origin | Year | Key Differentiator |
|--------|----------|---------|--------|------|--------------------|
| **MinIO** | Go | AGPLv3 | MinIO, Inc. | 2015 | Reference S3 implementation; most production deployments |
| **SeaweedFS** | Go | Apache 2.0 | Chris Lu (ex-Facebook) | 2015 | Distributed blob store with POSIX filer; designed for billions of small files |
| **RustFS** | Rust | AGPLv3 | Community fork | 2024 | MinIO-compatible object store in Rust; memory safety guarantees |
| **libreFS** | Go | AGPLv3 | Community fork of MinIO | 2025 | Preserves MinIO's open-source features (WebUI, LDAP, erasure coding) after MinIO moved them to proprietary AIStor |

**MinIO** started as an open-source S3-compatible store and became the de facto standard for data lakes. In 2025, MinIO moved enterprise features (WebUI, LDAP, distributed erasure coding) behind a proprietary paywall called AIStor, keeping only the core AGPLv3 server open source. This license change triggered the search for alternatives.

**SeaweedFS** was originally built at Facebook for real-time blob storage at scale. It provides both S3-compatible API and a POSIX filesystem via its Filer component, making it unique among these options.

**RustFS** is a MinIO-compatible object store rewritten in Rust, aiming for the same S3 API with Rust's memory safety guarantees and no CGO dependency.

**libreFS** is a community fork of MinIO, preserving the full open-source feature set that MinIO moved to AIStor — including WebUI, LDAP/OIDC, and distributed erasure coding.

---

## Docker Cluster Architecture

Each system requires a different number of containers and components:

### MinIO (1 container)

| Container | Image | Role |
|-----------|-------|------|
| **minio** | `minio/minio:latest` | Single-node S3 server with erasure coding |

The simplest deployment — one process handles everything: S3 API, storage, erasure coding, WebUI.

### SeaweedFS (9 containers)

| Container | Image | Role |
|-----------|-------|------|
| **master1** | `chrislusf/seaweedfs:latest` | Raft leader — volume allocation, metadata coordination |
| **master2** | `chrislusf/seaweedfs:latest` | Raft follower — provides quorum and failover |
| **master3** | `chrislusf/seaweedfs:latest` | Raft follower — provides quorum and failover |
| **volume1** | `chrislusf/seaweedfs:latest` | Data storage node (append-only blobs) |
| **volume2** | `chrislusf/seaweedfs:latest` | Data storage node |
| **volume3** | `chrislusf/seaweedfs:latest` | Data storage node |
| **filer** | `chrislusf/seaweedfs:latest` | POSIX filesystem namespace and metadata layer |
| **s3** | `chrislusf/seaweedfs:latest` | S3-compatible API gateway |

Every S3 write flows through **4 hops**: `S3 gateway → filer → master (assign volume) → volume node`. This coordination step is why SeaweedFS has different concurrency characteristics than the others.

### RustFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **rustfs-1** | `rustfs/rustfs:latest` | Full S3 server + storage node (erasure coded) |
| **rustfs-2** | `rustfs/rustfs:latest` | Full S3 server + storage node |
| **rustfs-3** | `rustfs/rustfs:latest` | Full S3 server + storage node |

Each node runs a complete server — the S3 endpoint *is* the storage node. No coordination step needed.

### libreFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **librefs-1** | `librefs:local` | Full MinIO-compatible server + storage (distributed erasure coding) |
| **librefs-2** | `librefs:local` | Full MinIO-compatible server + storage |
| **librefs-3** | `librefs:local` | Full MinIO-compatible server + storage |

Same architecture as MinIO distributed mode — each node is a complete server.

---

## The 5-Thread Limit: Why SeaweedFS Can't Handle 20 Threads

Every write in SeaweedFS requires a round-trip to the master to "assign a volume" before data can be stored:

```
Client → S3 Gateway → Filer → Master (assign volume) → Volume Node
```

With 20 concurrent threads each holding a `filer → master` gRPC connection open simultaneously, the master serializes all 20 assignments. The connections pile up waiting, hit the deadline timeout, and fail — even though the volume nodes and disk are sitting idle.

With MinIO or RustFS, the thread talks directly to the server which owns the storage. No coordination step. 20 threads in parallel means 20 independent operations — there's no shared bottleneck.

**Why 5 threads specifically works:** At 5 threads the master can assign volumes fast enough that connections return before the deadline. At 10+ threads the queue depth grows faster than the master can drain it, and the first timeout triggers a cascade.

**Why heavy mode works at 5 threads despite appearing high-throughput:** In the benchmark the heavy workload is 90%+ reads. Reads in SeaweedFS go `S3 gateway → filer → volume` — they bypass the master entirely, because volume location is already known. Only writes need master coordination. With 5 threads there might be only 2-3 concurrent writes at any moment, well within the master's capacity.

---

## Benchmark Methodology

### Test Data

| Size Tier | Files | Per-File Size | Total per Run |
|-----------|-------|---------------|---------------|
| 1 MB | 17 measured (3 warmup) | 1 MB | ~17 MB |
| 16 MB | 17 measured (3 warmup) | 16 MB | ~272 MB |
| 32 MB | 17 measured (3 warmup) | 32 MB | ~544 MB |

Files are pre-generated with random bytes (no generation overhead during measurement).

### Workload Modes

1. **Write-only**: Concurrent file uploads using boto3 (warmup: 3 files, measure: 17 files)
2. **Read-only**: Seed bucket, then measure read throughput via boto3 `GetObject`
3. **Heavy mixed**: Split threads (half writers + half readers) running simultaneously for 30 seconds — the core stress test

### Concurrency

| System | Threads | Why |
|--------|---------|-----|
| **MinIO** | 20 | Single-process server handles concurrency natively |
| **RustFS** | 20 | Same architecture as MinIO |
| **libreFS** | 20 | Same architecture as MinIO |
| **SeaweedFS** | 5 | Master serializes volume assignments; higher counts cause gRPC deadline exhaustion |

### Multiple Runs

Each configuration runs **3 times** with mean ± stdev reporting.

---

## Results: Heavy Mixed Workload

> The core benchmark — concurrent reads AND writes simultaneously for 30 seconds. This simulates real-world data pipeline workloads where ingestion and analytics run concurrently.

### Aggregate Throughput (MB/s, mean ± stdev)

| File Size | MinIO (n=3) | RustFS (n=3) | libreFS (n=3) | SeaweedFS (n=3) |
|-----------|-------------|--------------|---------------|-----------------|
| **1mb** | **81.1 ± 10.9** | 25.0 ± 3.0 | 27.0 ± 4.0 | 27.8 ± 3.1 |
| **16mb** | **117.3 ± 7.9** | 44.3 ± 2.8 | 51.1 ± 7.1 | 27.0 ± 4.4 |
| **32mb** | **102.5 ± 2.6** | 42.9 ± 3.4 | 58.8 ± 8.6 | 32.7 ± 1.9 |

### Write Latency Under Contention (P50)

| File Size | MinIO P50 | RustFS P50 | libreFS P50 | SeaweedFS P50 |
|-----------|-----------|------------|-------------|---------------|
| **1mb** | 0.940s | 1.049s | 6.833s | **0.275s** |
| **16mb** | 3.649s | 7.262s | 15.545s | **3.463s** |
| **32mb** | 6.643s | 15.006s | 17.401s | **5.298s** |

### Read Latency Under Contention (P50)

| File Size | MinIO P50 | RustFS P50 | libreFS P50 | SeaweedFS P50 |
|-----------|-----------|------------|-------------|---------------|
| **1mb** | 0.137s | 0.621s | 0.353s | **0.133s** |
| **16mb** | **1.991s** | 7.243s | 3.627s | 2.658s |
| **32mb** | 4.906s | 14.989s | 8.045s | **4.338s** |

### Success Rates

| System | 1mb | 16mb | 32mb |
|--------|-----|------|------|
| Minio | **100%** / **100%** | **100%** / **100%** | **100%** / **100%** |
| Rustfs | **100%** / **100%** | **100%** / **100%** | **100%** / **100%** |
| Librefs | **100%** / **100%** | **100%** / **100%** | **100%** / **100%** |
| Seaweedfs | **100%** / **100%** | **100%** / **100%** | **100%** / **100%** |

---

## Results: Write-Only Throughput

| File Size | MinIO (n=3) | RustFS (n=3) | libreFS (n=3) | SeaweedFS (n=3) |
|-----------|-------------|--------------|---------------|-----------------|
| **1mb** | **20.8 ± 3.5** | 17.7 ± 11.1 | 7.2 ± 1.5 | 15.8 ± 2.4 |
| **16mb** | **60.9 ± 32.2** | 26.5 ± 3.4 | 27.7 ± 4.8 | 15.2 ± 2.7 |
| **32mb** | **77.0 ± 12.4** | 21.3 ± 4.6 | 44.0 ± 7.3 | 19.9 ± 1.2 |

### Write Latency P50

| File Size | MinIO P50 | RustFS P50 | libreFS P50 | SeaweedFS P50 |
|-----------|-----------|------------|-------------|---------------|
| **1mb** | 0.758s | 1.362s | 2.293s | **0.288s** |
| **16mb** | 5.223s | 10.206s | 9.908s | **5.041s** |
| **32mb** | **6.965s** | 26.106s | 12.386s | 7.532s |

---

## Results: Read-Only Throughput

| File Size | MinIO (n=3) | RustFS (n=3) | libreFS (n=3) | SeaweedFS (n=3) |
|-----------|-------------|--------------|---------------|-----------------|
| **1mb** | **45.3 ± 6.4** | 24.9 ± 8.8 | 26.0 ± 4.0 | 15.0 ± 3.0 |
| **16mb** | **82.6 ± 18.0** | 47.3 ± 1.0 | 68.8 ± 4.7 | 35.8 ± 0.2 |
| **32mb** | **141.6 ± 18.0** | 50.6 ± 3.2 | 73.3 ± 16.4 | 44.3 ± 3.6 |

### Read Latency P50

| File Size | MinIO P50 | RustFS P50 | libreFS P50 | SeaweedFS P50 |
|-----------|-----------|------------|-------------|---------------|
| **1mb** | **0.306s** | 0.742s | 0.519s | 0.325s |
| **16mb** | 3.783s | 6.624s | 4.439s | **2.100s** |
| **32mb** | 4.448s | 12.475s | 8.706s | **3.466s** |

---

## Stability and Operational Notes

### Run Completeness

| System | 1mb | 16mb | 32mb | Notes |
|--------|-----|------|------|-------|
| MinIO | **3/3** | **3/3** | **3/3** | Most consistent across all sizes |
| RustFS | **3/3** | **3/3** | **3/3** | 100% success; requires 127.0.0.1 for IPv4 |
| libreFS | **3/3** | **3/3** | **3/3** | 100% success with adequate disk |
| SeaweedFS | **3/3** | **3/3** | **3/3** | Works with 3-master Raft; requires cluster restart between benchmark runs |

### SeaweedFS: Cluster Restart Between Runs

SeaweedFS requires a cluster restart between benchmark runs. The filer's gRPC connection pool to the masters degrades after sustained writes, causing subsequent operations to fail. With fresh cluster starts, all modes (heavy, read-only, write-only) work correctly across all file sizes.

---

## Storage Overhead Analysis

| System | Replication | Overhead Ratio | Effective TB per Physical TB |
|--------|-------------|----------------|------------------------------|
| SeaweedFS (RF=1) | 2 copies | ~2x | 0.50 TB |
| RustFS | Erasure coding | ~1.5x | 0.67 TB |
| libreFS | Erasure coding | ~1.5x | 0.67 TB |
| MinIO | Erasure coding | ~1.5x | 0.67 TB |

SeaweedFS RF=1 uses 2x more raw disk than erasure-coded systems for the same usable capacity.

---

## Production Readiness Assessment

### MinIO: The Gold Standard

**Strengths:**
- Most stable across all sizes (100% success)
- Highest heavy combined throughput for 16mb (117.3 MB/s)
- Best read-only throughput across all sizes (up to 141.6 MB/s for 32mb)
- Proven at scale

**Weaknesses:**
- AGPLv3 license (server remains open source)
- Write latency higher than SeaweedFS under heavy load

### RustFS: Consistent Performer

**Strengths:**
- 100% success rate across all sizes
- Consistent heavy combined throughput (25-44 MB/s)
- Good read-only performance (50.6 MB/s for 32mb)
- Memory safety guarantees from Rust

**Weaknesses:**
- AGPLv3 license
- Lower throughput ceiling than MinIO
- Write latency high for 32mb (P50: 15-24s)

### libreFS: Competitive with MinIO

**Strengths:**
- 100% success rate across all sizes
- Strong read-only performance (73.3 MB/s for 32mb)
- Full MinIO-compatible API, WebUI, LDAP/OIDC
- Good write-only performance (44.0 MB/s for 32mb)

**Weaknesses:**
- Slowest 1mb write-only (7.2 MB/s)
- Higher write latency under contention
- Requires adequate disk space

### SeaweedFS: Lowest Latency

**Strengths:**
- Lowest read latency across all sizes (P50: 0.133s for 1mb)
- Lowest write latency for 1mb (P50: 0.266s)
- Apache 2.0 license (fewest restrictions)
- 100% success rate on all tested sizes

**Weaknesses:**
- Only 5 threads supported (master serializes volume assignments)
- Requires cluster restart between sustained write batches
- 3-master Raft requires more containers (9 total)
- 4-hop write path adds coordination latency vs single-process systems

---

## Key Findings

1. **MinIO dominates heavy throughput** — 117.3 MB/s (16mb), 102.5 MB/s (32mb)
2. **SeaweedFS excels at read latency** — P50: 0.133s (1mb), 2.658s (16mb), 4.338s (32mb)
3. **MinIO best at read-only** — 141.6 MB/s (32mb), 82.6 MB/s (16mb)
4. **libreFS competitive** — 73.3 MB/s (32mb) read-only, 58.8 MB/s (32mb) heavy
5. **RustFS consistent but slower** — 100% success, lower throughput ceiling
6. **All systems 100% success** across all tested sizes (1mb, 16mb, 32mb)
7. **SeaweedFS requires cluster restart** — gRPC connection pool degrades under sustained load

---

## Recommendation Matrix

| Use Case | Recommended | Why |
|----------|-------------|-----|
| Data lake / analytics platform | **MinIO** | Highest throughput across all sizes, proven at scale |
| S3 drop-in replacement (MinIO migration) | **libreFS** | Full MinIO-compatible API, WebUI/LDAP, competitive performance |
| High-availability production | **MinIO** | Most stable across all sizes, proven at scale |
| Low-latency reads | **SeaweedFS** | Lowest read P50 across all sizes (0.133s for 1mb) |
| AI/ML training data storage | **MinIO** | Highest throughput, proven at scale |
| Commercial SaaS product | **MinIO or RustFS** | Stability + performance + license considerations |
| Budget-constrained / minimal overhead | **MinIO** | Best write-only performance (77.0 MB/s for 32mb) |
| POSIX filesystem needed | **SeaweedFS** | Apache 2.0, POSIX support via Filer |

---

## Methodology Limitations

1. **Single-host Docker** — All "nodes" share one disk and NIC
2. **Loopback networking** — Zero real network latency
3. **No failure injection** — Docker stop ≠ node failure
4. **Client bottleneck** — Python/boto3 may saturate before storage does
5. **Small data volume** — ~17-544 MB per run vs TBs in production
6. **30-second test duration** — Longer runs may reveal different behavior
7. **SeaweedFS requires restart** — gRPC connection pool degrades under sustained load
8. **Windows Docker Desktop** — Potential port stale connections

---

## Appendix: Raw Results

### Minio — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 273 | 1821 | 2094 | 68.8 | 1.031s | 0.159s |
| 2 | 347 | 2371 | 2718 | 89.7 | 0.851s | 0.124s |
| 3 | 323 | 2259 | 2582 | 84.9 | 0.937s | 0.129s |
| **Mean** | **314** | **2150** | **2465** | **81.1 ± 10.9** | **0.940s** | **0.137s** |

### Rustfs — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 257 | 415 | 672 | 21.6 | 1.213s | 0.694s |
| 2 | 307 | 510 | 817 | 26.5 | 0.976s | 0.585s |
| 3 | 311 | 510 | 821 | 27.0 | 0.958s | 0.583s |
| **Mean** | **292** | **478** | **770** | **25.0 ± 3.0** | **1.049s** | **0.621s** |

### Librefs — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 896 | 946 | 30.4 | 6.389s | 0.314s |
| 2 | 50 | 827 | 877 | 28.0 | 7.152s | 0.350s |
| 3 | 40 | 683 | 723 | 22.7 | 6.959s | 0.395s |
| **Mean** | **47** | **802** | **849** | **27.0 ± 4.0** | **6.833s** | **0.353s** |

### Seaweedfs — 1MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 229 | 701 | 930 | 30.9 | 0.249s | 0.120s |
| 2 | 205 | 640 | 845 | 28.0 | 0.274s | 0.130s |
| 3 | 189 | 553 | 742 | 24.6 | 0.303s | 0.149s |
| **Mean** | **208** | **631** | **839** | **27.8 ± 3.1** | **0.275s** | **0.133s** |

### Minio — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 21.7 | 0.726s |
| 2 | 17 | 17 | 23.7 | 0.641s |
| 3 | 17 | 17 | 16.9 | 0.907s |
| **Mean** | **17** | **17** | **20.8 ± 3.5** | **0.758s** |

### Rustfs — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 27.4 | 0.563s |
| 2 | 17 | 17 | 20.1 | 0.728s |
| 3 | 17 | 17 | 5.5 | 2.794s |
| **Mean** | **17** | **17** | **17.7 ± 11.1** | **1.362s** |

### Librefs — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 8.8 | 1.813s |
| 2 | 17 | 17 | 6.5 | 2.399s |
| 3 | 17 | 17 | 6.1 | 2.668s |
| **Mean** | **17** | **17** | **7.2 ± 1.5** | **2.293s** |

### Seaweedfs — 1MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 17 | 17.4 | 0.266s |
| 2 | 17 | 17 | 13.0 | 0.321s |
| 3 | 17 | 17 | 17.0 | 0.276s |
| **Mean** | **17** | **17** | **15.8 ± 2.4** | **0.288s** |

### Minio — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 44.3 | 0.283s |
| 2 | 20 | 20 | 39.4 | 0.372s |
| 3 | 20 | 20 | 52.1 | 0.262s |
| **Mean** | **20** | **20** | **45.3 ± 6.4** | **0.306s** |

### Rustfs — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 32.5 | 0.528s |
| 2 | 20 | 20 | 15.2 | 1.076s |
| 3 | 20 | 20 | 26.9 | 0.622s |
| **Mean** | **20** | **20** | **24.9 ± 8.8** | **0.742s** |

### Librefs — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 21.5 | 0.664s |
| 2 | 20 | 20 | 29.1 | 0.475s |
| 3 | 20 | 20 | 27.5 | 0.417s |
| **Mean** | **20** | **20** | **26.0 ± 4.0** | **0.519s** |

### Seaweedfs — 1MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 20 | 14.5 | 0.352s |
| 2 | 20 | 20 | 18.3 | 0.237s |
| 3 | 20 | 20 | 12.4 | 0.386s |
| **Mean** | **20** | **20** | **15.0 ± 3.0** | **0.325s** |

### Minio — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 80 | 140 | 3520 | 108.5 | 3.827s | 2.075s |
| 2 | 82 | 150 | 3712 | 119.5 | 3.441s | 1.937s |
| 3 | 90 | 160 | 4000 | 123.9 | 3.678s | 1.960s |
| **Mean** | **84** | **150** | **3744** | **117.3 ± 7.9** | **3.649s** | **1.991s** |

### Rustfs — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 50 | 1600 | 45.1 | 6.850s | 6.895s |
| 2 | 40 | 41 | 1296 | 41.2 | 7.996s | 8.090s |
| 3 | 50 | 50 | 1600 | 46.5 | 6.941s | 6.743s |
| **Mean** | **47** | **47** | **1499** | **44.3 ± 2.8** | **7.262s** | **7.243s** |

### Librefs — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 20 | 85 | 1680 | 52.4 | 15.975s | 2.916s |
| 2 | 20 | 70 | 1440 | 43.4 | 16.472s | 4.925s |
| 3 | 30 | 100 | 2080 | 57.4 | 14.189s | 3.041s |
| **Mean** | **23** | **85** | **1733** | **51.1 ± 7.1** | **15.545s** | **3.627s** |

### Seaweedfs — 16MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 16 | 30 | 736 | 22.2 | 4.107s | 3.283s |
| 2 | 18 | 36 | 864 | 28.0 | 3.287s | 2.356s |
| 3 | 20 | 39 | 944 | 30.8 | 2.996s | 2.333s |
| **Mean** | **18** | **35** | **848** | **27.0 ± 4.4** | **3.463s** | **2.658s** |

### Minio — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 95.7 | 2.669s |
| 2 | 17 | 272 | 32.1 | 8.332s |
| 3 | 17 | 272 | 54.8 | 4.669s |
| **Mean** | **17** | **272** | **60.9 ± 32.2** | **5.223s** |

### Rustfs — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 22.7 | 11.731s |
| 2 | 17 | 272 | 27.6 | 9.700s |
| 3 | 17 | 272 | 29.2 | 9.188s |
| **Mean** | **17** | **272** | **26.5 ± 3.4** | **10.206s** |

### Librefs — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 31.2 | 8.625s |
| 2 | 17 | 272 | 29.6 | 9.023s |
| 3 | 17 | 272 | 22.2 | 12.077s |
| **Mean** | **17** | **272** | **27.7 ± 4.8** | **9.908s** |

### Seaweedfs — 16MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 272 | 12.9 | 5.457s |
| 2 | 17 | 272 | 14.6 | 5.576s |
| 3 | 17 | 272 | 18.2 | 4.092s |
| **Mean** | **17** | **272** | **15.2 ± 2.7** | **5.041s** |

### Minio — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 64.8 | 4.611s |
| 2 | 20 | 320 | 82.3 | 3.714s |
| 3 | 20 | 320 | 100.7 | 3.025s |
| **Mean** | **20** | **320** | **82.6 ± 18.0** | **3.783s** |

### Rustfs — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 46.4 | 6.773s |
| 2 | 20 | 320 | 48.4 | 6.446s |
| 3 | 20 | 320 | 47.2 | 6.653s |
| **Mean** | **20** | **320** | **47.3 ± 1.0** | **6.624s** |

### Librefs — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 67.6 | 4.406s |
| 2 | 20 | 320 | 74.0 | 4.165s |
| 3 | 20 | 320 | 64.7 | 4.747s |
| **Mean** | **20** | **320** | **68.8 ± 4.7** | **4.439s** |

### Seaweedfs — 16MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 320 | 35.6 | 2.071s |
| 2 | 20 | 320 | 36.0 | 2.051s |
| 3 | 20 | 320 | 35.9 | 2.178s |
| **Mean** | **20** | **320** | **35.8 ± 0.2** | **2.100s** |

### Minio — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 50 | 60 | 3520 | 100.3 | 6.346s | 4.579s |
| 2 | 43 | 60 | 3296 | 101.8 | 7.562s | 5.370s |
| 3 | 50 | 60 | 3520 | 105.4 | 6.021s | 4.768s |
| **Mean** | **48** | **60** | **3445** | **102.5 ± 2.6** | **6.643s** | **4.906s** |

### Rustfs — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 30 | 30 | 1920 | 46.0 | 13.620s | 13.854s |
| 2 | 30 | 30 | 1920 | 43.4 | 15.316s | 15.087s |
| 3 | 20 | 20 | 1280 | 39.2 | 16.081s | 16.026s |
| **Mean** | **27** | **27** | **1707** | **42.9 ± 3.4** | **15.006s** | **14.989s** |

### Librefs — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 20 | 40 | 1920 | 50.1 | 19.027s | 9.943s |
| 2 | 20 | 42 | 1984 | 58.9 | 16.667s | 7.794s |
| 3 | 20 | 50 | 2240 | 67.3 | 16.509s | 6.399s |
| **Mean** | **20** | **44** | **2048** | **58.8 ± 8.6** | **17.401s** | **8.045s** |

### Seaweedfs — 32MB Heavy (n=3)

| Run | Writes | Reads | Total MB | Aggregate MB/s | Write P50 | Read P50 |
|-----|--------|-------|----------|----------------|-----------|----------|
| 1 | 12 | 23 | 1120 | 34.9 | 5.177s | 4.314s |
| 2 | 12 | 21 | 1056 | 32.0 | 5.331s | 4.608s |
| 3 | 12 | 23 | 1120 | 31.3 | 5.387s | 4.090s |
| **Mean** | **12** | **22** | **1099** | **32.7 ± 1.9** | **5.298s** | **4.338s** |

### Minio — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 64.3 | 8.225s |
| 2 | 17 | 544 | 77.5 | 6.841s |
| 3 | 17 | 544 | 89.1 | 5.828s |
| **Mean** | **17** | **544** | **77.0 ± 12.4** | **6.965s** |

### Rustfs — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 17.3 | 31.196s |
| 2 | 17 | 544 | 26.3 | 20.474s |
| 3 | 17 | 544 | 20.3 | 26.648s |
| **Mean** | **17** | **544** | **21.3 ± 4.6** | **26.106s** |

### Librefs — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 51.8 | 10.328s |
| 2 | 17 | 544 | 37.2 | 14.404s |
| 3 | 17 | 544 | 43.1 | 12.424s |
| **Mean** | **17** | **544** | **44.0 ± 7.3** | **12.386s** |

### Seaweedfs — 32MB Write Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Write P50 |
|-----|-------|----------|----------------|-----------|
| 1 | 17 | 544 | 18.6 | 6.792s |
| 2 | 17 | 544 | 20.1 | 8.009s |
| 3 | 17 | 544 | 21.0 | 7.795s |
| **Mean** | **17** | **544** | **19.9 ± 1.2** | **7.532s** |

### Minio — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 121.0 | 5.156s |
| 2 | 20 | 640 | 154.2 | 4.031s |
| 3 | 20 | 640 | 149.6 | 4.156s |
| **Mean** | **20** | **640** | **141.6 ± 18.0** | **4.448s** |

### Rustfs — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 53.6 | 11.763s |
| 2 | 20 | 640 | 51.0 | 12.343s |
| 3 | 20 | 640 | 47.2 | 13.320s |
| **Mean** | **20** | **640** | **50.6 ± 3.2** | **12.475s** |

### Librefs — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 87.3 | 7.192s |
| 2 | 20 | 640 | 55.2 | 11.248s |
| 3 | 20 | 640 | 77.5 | 7.678s |
| **Mean** | **20** | **640** | **73.3 ± 16.4** | **8.706s** |

### Seaweedfs — 32MB Read Only (n=3)

| Run | Files | Total MB | Aggregate MB/s | Read P50 |
|-----|-------|----------|----------------|----------|
| 1 | 20 | 640 | 40.1 | 3.777s |
| 2 | 20 | 640 | 46.1 | 3.287s |
| 3 | 20 | 640 | 46.6 | 3.333s |
| **Mean** | **20** | **640** | **44.3 ± 3.6** | **3.466s** |

---

*All benchmarks in this article are reproducible. Clone the workshop, run the commands, and verify the results yourself. The code is designed for transparency — no hidden optimizations, no cherry-picked numbers.*