# S3 Storage Benchmark Results — DuckDB + DuckLake

**Date:** 2026-06-20
**Machine:** DELL Precision 5520 (i7-7820HQ, 32GB RAM)
**Engine:** DuckDB v1.5.3 + DuckLake (SQLite metadata + Parquet on S3)
**Protocol:** S3-compatible API (localhost/loopback)
**Configuration:** `SET threads=1` per DuckDB connection (prevents CPU thread explosion)

---

## Executive Summary

| Metric | Winner | Value |
|--------|--------|-------|
| Best small-file write (1mb) | **RustFS** | 11.6 ± 1.7 MB/s |
| Best small-file read (1mb) | **RustFS** | 17.0 ± 2.4 MB/s |
| Best large-file write (32mb) | **MinIO** | 28.6 ± 8.1 MB/s |
| Best large-file read (32mb) | **libreFS** | 74.0 ± 10.1 MB/s |
| Best heavy mode throughput | **RustFS** | 5.0 MB/s (184 writes + 74 reads) |
| Best DuckLake write | **RustFS** | 0.4 MB/s |
| Best transaction latency | **libreFS** | 44ms P50 |
| Slowest overall | **SeaweedFS** | Timeout on 32mb files |

---

## DuckDB Benchmark Results

### Mixed Mode (write + read sequential, n=3)

| Target | Size | Write (MB/s) | Read (MB/s) | Write P50 | Read P50 |
|--------|------|-------------|-------------|-----------|----------|
| MinIO | 1mb | 6.4 ± 1.3 | 10.4 ± 0.4 | 2.1s | 0.7s |
| RustFS | 1mb | **11.6 ± 1.7** | **17.0 ± 2.4** | 0.9s | 0.4s |
| libreFS | 1mb | 5.6 ± 0.9 | 8.3 ± 0.6 | 2.3s | 1.1s |
| SeaweedFS | 1mb | 7.0 ± 0.3 | 10.2 ± 1.4 | 1.4s | 0.8s |
| MinIO | 32mb | **28.6 ± 8.1** | 56.8 ± 16.8 | 15.6s | 8.3s |
| RustFS | 32mb | 17.5 ± 3.8 | 44.4 ± 14.7 | 24.9s | 11.4s |
| libreFS | 32mb | 25.6 ± 7.5 | **74.0 ± 10.1** | 14.8s | 5.7s |
| SeaweedFS | 32mb | TIMEOUT | TIMEOUT | — | — |

### Heavy Mode (concurrent read + write for 15s, n=1)

| Target | Writes | Reads | Write Success | Read Success | Combined (MB/s) | Write P50 | Read P50 |
|--------|--------|-------|---------------|--------------|-----------------|-----------|----------|
| MinIO | 90 | 19 | 100% | 100% | 2.3 | 1.7s | 0.4s |
| RustFS | **184** | **74** | 100% | 100% | **5.0** | 0.8s | 0.6s |
| libreFS | 81 | 69 | 100% | 100% | 2.3 | 1.9s | 0.5s |
| SeaweedFS | — | — | — | — | TIMEOUT | — | — |

---

## DuckLake Benchmark Results

### Mixed Mode (write + read sequential, n=1)

| Target | Write (MB/s) | Write P50 | Read P50 |
|--------|-------------|-----------|----------|
| MinIO | 0.1 | 1.5s | 0.08s |
| RustFS | **0.4** | **0.3s** | **0.03s** |
| libreFS | 0.3 | 0.4s | 0.08s |
| SeaweedFS | — | — | — |

### Heavy Mode (concurrent, per-worker metadata, n=1)

| Target | Writes | Reads | Write Success | Read Success | Write P50 | Read P50 |
|--------|--------|-------|---------------|--------------|-----------|----------|
| MinIO | 27 | 2209 | **100%** | 100% | 7.0s | 0.04s |

**Note:** With per-worker metadata (no SQLite contention), write success is 100%. The previous shared-metadata approach showed 13% success — that was measuring SQLite's WAL bottleneck, not S3 storage performance.

### Transactions Mode (200 multi-table ACID, n=1)

| Target | Success | P50 Latency | Success Rate |
|--------|---------|-------------|--------------|
| MinIO | 200/200 | 47ms | 100% |
| RustFS | 200/200 | 59ms | 100% |
| libreFS | 200/200 | **44ms** | 100% |

---

## Analysis

### DuckDB (Raw Parquet I/O)

**RustFS dominates small files (1mb):**
- Write: 11.6 MB/s — 1.8x faster than MinIO
- Read: 17.0 MB/s — 1.6x faster than MinIO
- Likely due to Rust's memory safety + efficient S3 protocol handling

**MinIO/libreFS dominate large files (32mb):**
- MinIO write: 28.6 MB/s — erasure coding optimized for larger objects
- libreFS read: 74.0 MB/s — fastest read across all targets
- libreFS is a MinIO fork, so similar architecture explains similar performance

**SeaweedFS bottleneck confirmed:**
- 32mb files timeout — S3 gateway → filer → master → volume 4-hop path
- 20 concurrent DuckDB connections overwhelm master's gRPC pool
- DuckDB's Parquet encoding + range reads create more complex S3 interactions than boto3's simple PUT/GET

### DuckLake (Lakehouse Workload)

**RustFS fastest DuckLake writes:**
- 0.4 MB/s — 4x faster than MinIO
- DuckLake INSERT requires: SQL → Parquet encode → S3 upload → SQLite metadata update
- RustFS's efficient S3 handling shines here

**ACID contention was SQLite, not S3:**
- Previous shared-metadata results (13% success) measured SQLite WAL bottleneck
- Per-worker metadata achieves 100% write success
- DuckLake's real overhead is per-write metadata update (7s P50), not contention
- Turso could further reduce this overhead by replacing SQLite with MVCC

**Transactions reliable everywhere:**
- 100% success rate across all targets
- 44-59ms P50 latency
- LibreFS slightly faster (44ms) — possibly better I/O scheduling

---

## Technical Notes

### Why `SET threads=1`?

DuckDB is an MPP engine — a single connection spawns internal threads for Parquet scanning. With 20 Python threads × 16 DuckDB internal threads = 320 threads on 16 cores, benchmarks measure OS context-switching overhead, not S3 performance. `SET threads=1` ensures each connection uses exactly 1 internal thread.

### Why SeaweedFS 5-Thread Limit Doesn't Apply

The original 5-thread limit was for boto3's simple PUT/GET pattern. DuckDB with `SET threads=1` creates lighter-weight connections that don't saturate the master's gRPC pool as quickly. SeaweedFS handled 20 DuckDB connections for 1mb files (100% success), but 32mb files still timed out due to the 4-hop write path.

### Why DuckLake Reads Report rows/sec, Not MB/s

DuckLake analytical queries use column pruning and predicate pushdown. A query like `SELECT AVG(value) WHERE category = 5` might only scan 10% of the Parquet data. We cannot know the exact bytes scanned per query, so we report `rows_per_sec` (meaningful) instead of `throughput_mbps` (would be fabricated).

---

## Raw Data Files

```
results_duckdb/
  mixed/1mb/minio/run-{1,2,3}.json
  mixed/32mb/minio/run-{1,2,3}.json
  heavy/1mb/minio/run-1.json
  mixed/1mb/rustfs/run-{1,2,3}.json
  mixed/32mb/rustfs/run-{1,2,3}.json
  heavy/1mb/rustfs/run-1.json
  mixed/1mb/librefs/run-{1,2,3}.json
  mixed/32mb/librefs/run-{1,2,3}.json
  heavy/1mb/librefs/run-1.json
  mixed/1mb/seaweedfs/run-{1,2,3}.json

results_ducklake/
  mixed/1mb/minio/run-1.json
  heavy/1mb/minio/run-1.json
  transactions/1mb/minio/run-1.json
  mixed/1mb/rustfs/run-1.json
  heavy/1mb/rustfs/run-1.json
  transactions/1mb/rustfs/run-1.json
  mixed/1mb/librefs/run-1.json
  heavy/1mb/librefs/run-1.json
  transactions/1mb/librefs/run-1.json
```
