# Benchmark Report — All Targets

**Date:** 2026-06-20
**Machine:** DELL Precision 5520 (i7-7820HQ, 32GB RAM)
**Engine:** DuckDB v1.5.3 + DuckLake (SQLite metadata + Parquet on S3)

---

## DuckDB Benchmark Results

### Mixed Mode (write + read sequential, 3 runs)

| Target | Size | Write (MB/s) | Read (MB/s) | Write P50 | Read P50 |
|--------|------|-------------|-------------|-----------|----------|
| **MinIO** | 1mb | 6.4 ± 1.3 | 10.4 ± 0.4 | 2.1s | 0.7s |
| **RustFS** | 1mb | 11.6 ± 1.7 | 17.0 ± 2.4 | 0.9s | 0.4s |
| **libreFS** | 1mb | 5.6 ± 0.9 | 8.3 ± 0.6 | 2.3s | 1.1s |
| **SeaweedFS** | 1mb | 7.0 ± 0.3 | 10.2 ± 1.4 | 1.4s | 0.8s |
| **MinIO** | 32mb | 28.6 ± 8.1 | 56.8 ± 16.8 | 15.6s | 8.3s |
| **RustFS** | 32mb | 17.5 ± 3.8 | 44.4 ± 14.7 | 24.9s | 11.4s |
| **libreFS** | 32mb | 25.6 ± 7.5 | 74.0 ± 10.1 | 14.8s | 5.7s |
| **SeaweedFS** | 32mb | TIMEOUT | TIMEOUT | — | — |

### Heavy Mode (concurrent read + write for 15s)

| Target | Writes | Reads | Success | Combined |
|--------|--------|-------|---------|----------|
| **MinIO** | 90 | 19 | 100% | 2.3 MB/s |
| **RustFS** | 184 | 74 | 100% | 5.0 MB/s |
| **libreFS** | 81 | 69 | 100% | 2.3 MB/s |
| **SeaweedFS** | TIMEOUT | — | — | — |

---

## DuckLake Benchmark Results

### Mixed Mode (write + read sequential)

| Target | Size | Write (MB/s) | Write P50 | Read P50 |
|--------|------|-------------|-----------|----------|
| **MinIO** | 1mb | 0.1 | 1.5s | 0.08s |
| **RustFS** | 1mb | 0.4 | 0.3s | 0.03s |
| **libreFS** | 1mb | 0.3 | 0.4s | 0.08s |
| **SeaweedFS** | — | SKIPPED | — | — |

### Heavy Mode (concurrent, shared SQLite metadata)

| Target | Writes | Reads | Write Success | Read Success | Combined |
|--------|--------|-------|---------------|--------------|----------|
| **MinIO** | 31 | 2995 | 12.9% | 100% | 1.4 MB/s |
| **RustFS** | 41 | 2026 | 14.6% | 100% | 0.9 MB/s |
| **libreFS** | 46 | 810 | 13.0% | 100% | 0.3 MB/s |

### Transactions Mode (200 multi-table ACID)

| Target | Success | P50 Latency |
|--------|---------|-------------|
| **MinIO** | 100% | 47ms |
| **RustFS** | 100% | 59ms |
| **libreFS** | 100% | 44ms |

---

## Key Findings

### DuckDB (Raw Parquet I/O)

1. **libreFS wins on large file reads**: 74.0 MB/s (32mb) — fastest of all targets
2. **RustFS wins on small file writes**: 11.6 MB/s (1mb) — 1.8x faster than MinIO
3. **MinIO wins on large file writes**: 28.6 MB/s (32mb) — erasure coding optimized for larger objects
4. **SeaweedFS too slow for DuckDB**: 32mb files timeout — S3 gateway → filer → master → volume 4-hop bottleneck
5. **Heavy mode**: RustFS handles most concurrent operations (184 writes + 74 reads)

### DuckLake (Lakehouse Workload)

1. **RustFS fastest DuckLake writes**: 0.4 MB/s — 4x faster than MinIO
2. **ACID contention similar across all targets**: ~13% write success under concurrent load (SQLite WAL is the bottleneck, not S3)
3. **Transactions reliable everywhere**: 100% success, 44-59ms P50
4. **Read latency consistent**: 0.03-0.08s P50 across all targets
5. **libreFS slowest DuckLake**: 0.3 MB/s writes, fewest concurrent reads (810)

### Why SeaweedFS Failed DuckDB Benchmarks

SeaweedFS's S3 gateway routes every operation through 4 hops:
```
S3 gateway → filer → master (assign volume) → volume node
```

With DuckDB using `SET threads=1` per connection but 20 concurrent connections, the master's gRPC connection pool becomes saturated. The original 5-thread limit was designed for boto3's simpler request pattern. DuckDB's Parquet encoding + range reads create more complex S3 interactions that overwhelm SeaweedFS's coordination layer.

---

## Files Generated

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
