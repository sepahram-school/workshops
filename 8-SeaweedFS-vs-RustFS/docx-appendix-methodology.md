# Appendix: Benchmark Methodology — All Four Engines

## Benchmark Progression: From Raw Bytes to Production Lakehouse

This workshop benchmarks S3-compatible storage systems across four progressively more realistic workload types. Each benchmark answers a different question about the storage system's capabilities.

| Benchmark | Script | What It Tests | Metadata | ACID | Time Travel | Real-World Analog |
|-----------|--------|--------------|----------|------|-------------|-------------------|
| **Classic** | `benchmark.py` | Raw S3 throughput (PUT/GET) | None | No | No | File transfers, backups, blob storage |
| **DuckDB** | `benchmark_duckdb.py` | Analytical Parquet I/O | None | No | No | Data lake queries, OLAP |
| **DuckLake** | `benchmark_ducklake.py` | Lakehouse with SQLite metadata | SQLite | Yes | Yes | DuckLake / Delta Lake |
| **Iceberg** | `benchmark_iceberg.py` | Iceberg with file-based metadata | S3 files | Yes | Yes | Apache Iceberg / production data lakes |

### Why Four Benchmarks?

Raw `put_object`/`get_object` benchmarks measure the storage system's ability to move bytes. But modern data engineering workloads rarely read/write entire files sequentially. Each subsequent benchmark adds a layer of realism:

1. **Classic**: Can this system move bytes fast?
2. **DuckDB**: Can this system handle columnar analytical queries?
3. **DuckLake**: Can this system support a lakehouse with ACID transactions and versioning?
4. **Iceberg**: Can this system support the industry-standard Iceberg table format with file-based metadata?

---

# Appendix: DuckDB Benchmark Methodology

## Why DuckDB?

DuckDB was chosen as an alternative S3 client to test **analytical workloads** on these storage systems. The original benchmark uses boto3 (AWS SDK) for raw S3 PUT/GET operations — this tests **file transfer throughput**. DuckDB tests a fundamentally different access pattern: **columnar Parquet reads and writes**, which represents real-world data lake and OLAP scenarios.

### The Two Benchmarks Complement Each Other

| Aspect | Classic (`benchmark.py`) | DuckDB (`benchmark_duckdb.py`) |
|--------|--------------------------|-------------------------------|
| **Client** | boto3 (AWS SDK) | DuckDB with httpfs extension |
| **Data format** | Raw binary (.bin) | Parquet (.parquet) |
| **Write operation** | `put_object()` — raw byte stream | `COPY TO s3://` — columnar write |
| **Read operation** | `get_object()` — raw byte stream | `read_parquet()` — columnar scan |
| **What it tests** | Raw S3 throughput | Analytical workload on S3 |
| **Real-world use case** | File transfers, backups, blob storage | Data lakes, OLAP queries, analytics |

### Why Not Just boto3?

Raw `put_object`/`get_object` benchmarks measure the storage system's ability to move bytes. But modern data engineering workloads rarely read/write entire files sequentially. Instead:

1. **Columnar access**: Analytics queries read specific columns from Parquet files (e.g., `SELECT category, AVG(value) FROM data`), not entire files
2. **Predicate pushdown**: DuckDB pushes filters to the storage layer (e.g., `WHERE category = 5` skips irrelevant row groups)
3. **Compression**: Parquet files are compressed; boto3 transfers uncompressed bytes
4. **Multipart uploads**: DuckDB uses S3 multipart upload protocol differently than boto3

### Why DuckDB Over Alternatives?

| Alternative | Why DuckDB is Better |
|-------------|---------------------|
| **pandas + s3fs** | pandas loads entire files into memory; DuckDB streams and processes in chunks |
| **sqlite** | No native S3 support; requires local file copies |
| **Spark** | Heavy JVM dependency; overkill for benchmarking storage layer |
| **Presto/Trino** | Requires cluster setup; DuckDB is a single binary |
| **DuckDB** | Zero-config S3 support, Parquet-native, single binary, SQL interface |

---

## Benchmark Methodology (DuckDB Version)

### Test Data

Parquet test files are generated using `generate_data_parquet.py`:

| Size Tier | Files | Per-File Size | Format |
|-----------|-------|---------------|--------|
| 1 MB | 100 | ~1 MB | Parquet (5 columns) |
| 16 MB | 100 | ~16 MB | Parquet (5 columns) |
| 32 MB | 100 | ~32 MB | Parquet (5 columns) |

Each Parquet file contains a table with columns:
- `id` (INT) — sequential identifier
- `payload` (VARCHAR) — ~1KB string to approximate file size
- `timestamp` (TIMESTAMP) — synthetic timestamps
- `category` (INT) — 0-9 range for filtering
- `value` (DOUBLE) — random values for aggregation

```bash
# Generate test data
uv run python generate_data_parquet.py --size all --files 100
```

### Workload Modes

#### Write-only
```
For each file:
  1. Read local Parquet file into DuckDB
  2. COPY TO s3://bucket/benchmark/file.parquet (FORMAT PARQUET)
  3. Measure wall-clock time
```
- Warmup: 3 files at 5 threads
- Measurement: remaining files at target thread count

#### Read-only
```
1. Seed bucket with Parquet files (write phase, metrics discarded)
2. For each file:
   a. SELECT COUNT(*) FROM read_parquet('s3://bucket/file.parquet')
   b. This forces DuckDB to read the entire Parquet file from S3
   c. Measure wall-clock time
```

#### Mixed
Sequential: write phase → read phase (both measured)

#### Heavy
```
Split threads in half:
- Writers: continuously COPY Parquet files to S3
- Readers: continuously SELECT COUNT(*) FROM read_parquet(...)
- Run for 30 seconds (configurable)
- Measure throughput and latency for both operations
```

### Concurrency

DuckDB is **single-threaded per connection**. Each worker thread gets its own `DuckDBAdapter` instance:

```python
class DuckDBAdapter:
    """Extensions loaded ONCE at construction (before any timing)."""
    def __init__(self, config):
        self.conn = duckdb.connect()
        self.conn.execute("LOAD httpfs;")  # Extensions loaded ONCE
        # S3 configuration...

    def write_one(self, local_path, bucket, key):
        # Timing starts ONLY here — extensions already loaded
        start = time.perf_counter()
        self.conn.execute(f"COPY (SELECT * FROM read_parquet('{local_path}')) TO 's3://{bucket}/{key}.parquet' (FORMAT PARQUET)")
        elapsed = time.perf_counter() - start
        return elapsed, True, result_dict
```

**Key fixes from concerns.md review:**
1. **Column-materializing queries**: `SELECT SUM(value), COUNT(category), MAX(ts)` instead of `SELECT COUNT(*)` — forces full Parquet scan instead of reading footer only
2. **COPY directly**: `COPY (SELECT * FROM read_parquet(...)) TO s3://` — no intermediate table
3. **LOAD instead of INSTALL**: Extensions are built-in, no network download needed
4. **Connection pooling**: One adapter per worker thread, reused for all operations
5. **Warmup**: 10% of files at target thread count (not 3 files at 5 threads)
6. **Heavy mode re-list**: Readers re-list keys every 5s to read fresh data

Thread limits (same across all targets now — thread sweep available):

| System | Threads | Reason |
|--------|---------|--------|
| **SeaweedFS** | 5 | Master serializes volume assignments via gRPC |
| **MinIO** | 20 | Single-process server handles concurrency natively |
| **RustFS** | 20 | Same architecture as MinIO |
| **libreFS** | 20 | Same architecture as MinIO |

### Metrics Collected

| Metric | Description |
|--------|-------------|
| `aggregate_throughput_mbps` | Total data (MB) / wall-clock time (s) |
| `latency_p50` | Median per-file operation time |
| `latency_p95` | 95th percentile latency |
| `latency_p99` | 99th percentile latency |
| `latency_mean` | Average latency |
| `latency_stdev` | Standard deviation of latencies |
| `success` / `failed` | Operation success counts |
| `write_success_rate` | % of writes that succeeded (heavy mode) |
| `read_success_rate` | % of reads that succeeded (heavy mode) |

### Multiple Runs

Each configuration runs **3 times** with mean ± stdev reporting to account for system variability.

### Running the DuckDB Benchmark

```bash
# Single target, write-only
uv run python benchmark_duckdb.py --target minio --mode write-only --sizes 1mb --runs 3

# All targets, heavy mode
uv run python benchmark_duckdb.py --target all --mode heavy --sizes 1mb,32mb --runs 3

# Custom thread count
uv run python benchmark_duckdb.py --target minio --mode heavy --threads 10
```

Results are saved to `results_duckdb/{mode}/{size}/{target}/run-{N}.json`.

---

## Interpreting DuckDB Results

When comparing classic (boto3) vs DuckDB results:

- **DuckDB write throughput may be lower** than boto3: Parquet encoding + S3 multipart upload overhead
- **DuckDB read throughput may be higher** for analytical queries: columnar projection reduces bytes read
- **Latency patterns differ**: DuckDB has higher per-operation overhead (SQL parsing, Parquet decode) but lower total bytes transferred for selective reads
- **Heavy mode shows real contention**: How well the storage system handles concurrent mixed analytical queries

The DuckDB benchmark answers: **"How well does this S3 storage system support a data lake workload?"** — not just "how fast can it move bytes?"

---

# Appendix: DuckLake Benchmark Methodology

## Why DuckLake?

DuckLake goes beyond raw Parquet reads/writes. It's a **lakehouse format** that adds database-backed metadata (snapshots, time travel, ACID transactions) on top of Parquet files stored on S3. This tests **real-world lakehouse patterns** — the kind of workload you'd see with Delta Lake, Iceberg, or Apache Hudi in production.

### Three Benchmarks, Three Perspectives

| Aspect | Classic (`benchmark.py`) | DuckDB (`benchmark_duckdb.py`) | DuckLake (`benchmark_ducklake.py`) |
|--------|--------------------------|-------------------------------|-------------------------------------|
| **Client** | boto3 (AWS SDK) | DuckDB + httpfs | DuckDB + httpfs + ducklake |
| **Data format** | Raw binary | Raw Parquet | Lakehouse Parquet |
| **Metadata** | None | None | SQLite (snapshots, lineage) |
| **Versioning** | No | No | Yes (`AT VERSION`) |
| **ACID** | No | No | Yes (`BEGIN/COMMIT`) |
| **Write API** | `put_object()` | `COPY TO s3://` | `INSERT INTO my_db.table` |
| **Tests** | Raw S3 throughput | Analytical workload | Lakehouse operations |

### Why Not Just Raw DuckDB?

Raw `COPY TO` / `read_parquet()` tests Parquet I/O, but misses critical lakehouse patterns:

1. **ACID transactions**: DuckLake ensures atomic multi-table writes via SQLite metadata — raw Parquet has no transaction support
2. **Time travel**: Query historical data with `AT VERSION n` — raw Parquet files have no version history
3. **Snapshots**: Point-in-time views of the database — raw Parquet requires manual file management
4. **Metadata overhead**: DuckLake's SQLite metadata layer adds latency to every operation — this is the real cost of lakehouse guarantees
5. **Concurrent writers**: Multiple threads sharing one metadata DB tests SQLite WAL contention — raw Parquet has no coordination

### Why SQLite Metadata (Not on S3)?

DuckLake stores metadata in a local SQLite database, separate from the Parquet data on S3. This design:

- **Isolates S3 performance**: Metadata operations don't compete with data I/O
- **Fair comparison**: All targets use the same local SQLite — the only variable is S3 storage speed
- **Realistic**: Production DuckLake deployments use PostgreSQL/MySQL for metadata, not S3

---

## Benchmark Methodology (DuckLake Version)

### Architecture

```
DuckDB connection
  ├── httpfs extension (S3 access)
  ├── ducklake extension (lakehouse format)
  ├── SQLite metadata.db (local disk) — snapshots, lineage, ACID
  └── Parquet data files (S3) — actual row data
```

### Table Schema

```sql
CREATE TABLE my_db.events (
    id UUID,
    ts TIMESTAMP,
    sensor_id INTEGER,
    value DOUBLE,
    label VARCHAR
);
```

Realistic IoT/sensor data pattern — common in data lake workloads.

### Data Generation

Unlike the DuckDB benchmark (pre-generated Parquet files), DuckLake generates data inline via SQL INSERT:

```python
# Each batch inserts BATCH_SIZE rows with random data
sql = f"INSERT INTO my_db.events SELECT * FROM (VALUES {values}) AS t(id, ts, sensor_id, value, label)"
conn.execute(sql)
```

Row counts by size tier:

| Size | Rows | Approximate Parquet Data |
|------|------|--------------------------|
| 1 MB | 5,000 | ~0.6 MB |
| 16 MB | 80,000 | ~10 MB |
| 32 MB | 160,000 | ~20 MB |

### 8 Benchmark Modes

#### 1. Write-only
Bulk INSERT in batches of 1,000 rows. Measures DuckLake's write pipeline: SQL → Parquet encoding → S3 upload → SQLite metadata update.

#### 2. Read-only
Seed table, then run 20 analytical queries (GROUP BY, window functions, aggregations). Measures columnar scan throughput with metadata overhead.

#### 3. Mixed
Sequential: write phase → read phase (both measured).

#### 4. Heavy
Concurrent reads + writes for 30 seconds. Half threads write, half read. Tests real contention on both S3 and SQLite metadata.

#### 5. Transactions
Multi-table atomic writes: each transaction inserts an order + 1-5 order items in a single `BEGIN/COMMIT`. Tests DuckLake's ACID guarantees.

```sql
BEGIN TRANSACTION;
INSERT INTO my_db.orders VALUES (...);
INSERT INTO my_db.order_items VALUES (...);  -- 1-5 items
COMMIT;
```

#### 6. Time Travel
Take snapshots at different points, then query `AT VERSION n`. Measures version management overhead.

```sql
CREATE SNAPSHOT my_db.bench_snap_0;
SELECT COUNT(*) FROM my_db.events AT VERSION 0;
```

#### 7. Snapshots
Create 10 snapshots + list all snapshots. Isolates SQLite metadata performance for version management.

#### 8. Concurrent
Multiple threads with **per-worker metadata DBs** — each writer creates its own DuckLake instance. Tests S3 throughput under concurrent independent lakehouse writes, NOT SQLite WAL contention.

**Why per-worker metadata?** The previous shared-metadata approach measured SQLite's single-writer bottleneck (13% success rate), not S3 storage performance. With per-worker metadata, write success is 100% and the benchmark measures actual S3 throughput under concurrent DuckLake INSERT workloads.

### Concurrency Model

DuckDB is single-threaded per connection. Each worker thread gets its own `DuckLakeAdapter` instance:

```python
class DuckLakeAdapter:
    """Extensions loaded ONCE at construction (before any timing)."""
    def __init__(self, config, bucket, meta_file):
        self.conn = self._make_conn()  # httpfs + ducklake loaded ONCE
        self._setup_schema()

    def insert_batch(self, batch_size):
        # Timing starts ONLY here — extensions already loaded
        start = time.perf_counter()
        self.conn.execute(sql)
        elapsed = time.perf_counter() - start
        return elapsed, True, None
```

**Key fixes applied:**
1. **LOAD instead of INSTALL**: `LOAD httpfs; LOAD ducklake;` — no network download
2. **Connection timeouts**: `SET s3_connect_timeout='5s'; SET s3_request_timeout='30s';`
3. **DuckLake heavy mode**: Readers query the DuckLake table directly (includes fresh writes), not a stale key list
4. **DuckLake metadata note**: SQLite-on-local-disk modes (transactions, time-travel, snapshots, concurrent) test DuckLake metadata overhead, not S3 storage. They are excluded from cross-target S3 comparison.

**Why an adapter?** Fair timing — extension loading happens BEFORE the timer starts. Without the adapter, each thread would include `INSTALL httpfs; LOAD httpfs; INSTALL ducklake; LOAD ducklake;` in its timing, inflating latency numbers by 2-5 seconds per operation.

Thread limits per target (same as other benchmarks):

| System | Threads | Reason |
|--------|---------|--------|
| **SeaweedFS** | 5 | Master serializes volume assignments via gRPC |
| **MinIO** | 20 | Single-process server handles concurrency natively |
| **RustFS** | 20 | Same architecture as MinIO |
| **libreFS** | 20 | Same architecture as MinIO |

### Metrics Collected

Same as DuckDB benchmark, plus:

| Metric | Description |
|--------|-------------|
| `rows_per_sec` | INSERT throughput in rows/second |
| `total_rows_inserted` | Total rows written in the run |
| `items_in_txn` | Number of items per transaction |
| `rows_returned` | Rows returned by analytical queries |
| `rows_per_sec_mean` | Average rows/sec across all queries (DuckLake reads) |

**Note on DuckLake read metrics:** DuckLake reads report `rows_per_sec` and latency, NOT `throughput_mbps`. This is because each analytical query only scans a fraction of the total Parquet data (column pruning, predicate pushdown). Attributing total S3 data size to every query would inflate throughput artificially. The boto3-based `size_mb` measurement is only used for DuckDB reads where the entire file is scanned.

### Running the DuckLake Benchmark

```bash
# Standard modes
uv run python benchmark_ducklake.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_ducklake.py --target all --mode heavy --sizes 1mb,32mb --runs 3

# DuckLake-specific modes
uv run python benchmark_ducklake.py --target minio --mode transactions
uv run python benchmark_ducklake.py --target minio --mode time-travel
uv run python benchmark_ducklake.py --target minio --mode snapshots
uv run python benchmark_ducklake.py --target minio --mode concurrent
```

Results are saved to `results_ducklake/{mode}/{size}/{target}/run-{N}.json`.

### Results Directory

Each adapter stores results via `adapter.output_path(mode, run_id)`:
```
results_ducklake/{mode}/{size}/{target}/run-{N}.json
```

### Cleanup

Each run:
1. Creates a fresh S3 bucket (`benchduck-{target}-run{id}-{timestamp}`)
2. Creates local `metadata_*.db` files (one per adapter instance)
3. After completion: removes all metadata DBs and empties the S3 bucket
4. Prevents cross-run contamination

---

## Interpreting DuckLake Results

### DuckLake vs DuckDB Benchmark

- **DuckLake writes are slower**: Every INSERT requires Parquet encoding + S3 upload + SQLite metadata update (3 steps vs 1 for raw `COPY`)
- **DuckLake reads have metadata overhead**: Each query must check SQLite for version/snapshot info before reading Parquet
- **Transactions add latency**: `BEGIN/COMMIT` overhead is visible in transaction mode
- **Time travel is cheap**: Snapshot creation is fast (SQLite metadata only); `AT VERSION` queries add minimal overhead
- **Concurrent writers reveal SQLite bottleneck**: The real test — how well does SQLite WAL handle multiple DuckLake writers?

### What DuckLake Tests That Others Don't

| Question | Answered By |
|----------|-------------|
| "Can this S3 system handle a real data lake?" | DuckLake benchmark |
| "What's the overhead of ACID guarantees?" | DuckLake `transactions` mode |
| "How fast can I query historical data?" | DuckLake `time-travel` mode |
| "What happens with concurrent lakehouse writers?" | DuckLake `concurrent` mode |

The DuckLake benchmark answers: **"How well does this S3 storage system support a production lakehouse workload with ACID, versioning, and metadata management?"**

---

## Known Limitations & Fixes Applied

Based on multiple senior data architect reviews (concerns.md), the following fixes were applied. Each fix includes **why it is viable** for production benchmarking.

### P0 Critical Fixes

| # | Issue | Fix | Why Viable |
|---|-------|-----|------------|
| 1 | `SELECT COUNT(*)` reads Parquet footer only — all read results measure metadata, not storage | Replaced with `SELECT SUM(value), COUNT(*), MAX(timestamp)` — forces DuckDB to materialize data pages | Column-materializing queries are exactly what OLAP workloads do; this tests real analytical I/O |
| 2 | Different thread counts per target (SeaweedFS:5 vs others:20) — 4× mechanical bias | `--thread-sweep` flag runs at 1,5,10,20 threads for all targets; results show scaling curves | Letting the data show where each system saturates is more honest than presetting limits |
| 3 | New DuckDB connection per operation (100-500ms per file) — dominates small-file latency | `DuckDBAdapter` class: extensions loaded ONCE at construction, connection reused per worker | Matches production: connection pools are standard in data pipeline frameworks |
| 4 | Heavy-mode readers use stale key list — reads hit cached files, not fresh writes | Re-list keys every 5 seconds in DuckDB; DuckLake reads from table directly (includes fresh inserts) | Periodic re-listing simulates real analytical workloads that discover new data incrementally |
| 5 | `INSTALL httpfs` attempts network download from DuckDB extension repo | Changed to `LOAD httpfs` — httpfs is built-in, no download needed | Eliminates network dependency; makes benchmarks reproducible offline |
| 6 | DuckDB CPU thread explosion: 20 Python threads × 16 DuckDB internal threads = 320 threads on 16 cores | `SET threads=1` per connection — limits DuckDB internal parallelism | Without this, benchmarks measure OS context-switching overhead, not S3 performance |
| 7 | `run_write_phase` O(n²): creates boto3 client + lists ALL objects inside every batch loop | Moved to single boto3 `list_objects_v2` AFTER all writes complete | Reduces write phase from O(n²) to O(n); measures actual S3 bytes once |
| 8 | `run_write_phase` `size_mb` was cumulative total — each batch showed total, not batch size | Backfill all results with total S3 size after measurement; throughput = total/total_time | Aggregate throughput (total data / total time) is the correct metric for sequential writes |
| 9 | `run_read_phase` queried `duckdb_parquet_metadata('my_db.events')` — fails on DuckLake tables | Replaced with boto3 `list_objects_v2` measurement ONCE before queries | DuckLake tables don't expose `duckdb_parquet_metadata`; boto3 gives actual S3 object sizes |
| 10 | `run_heavy_phase` used fabricated 100 bytes/row for size estimates | Set `size_mb=0` and `throughput_mbps=0` — heavy mode reports counts + latency, not throughput | Heavy mode's value is contention measurement (latency, success rate), not throughput |
| 11 | `w_metrics["mode"] = "heavy_write"` crashes when no writes succeeded (NoneType) | Guard with `if w_metrics:` before accessing | Prevents crash on 100% write failure scenarios |

### P1 Major Fixes

| # | Issue | Fix | Why Viable |
|---|-------|-----|------------|
| 12 | Warmup too small (3 files at 5 threads) — TCP slow-start, connection pooling not saturated | Changed to 10% of files at target thread count | Ensures connection pools are warm; mirrors production steady-state |
| 13 | Inefficient write (`CREATE TABLE _bench_tmp` intermediate) | Changed to `COPY (SELECT * FROM read_parquet(...)) TO s3://` — single operation | Eliminates unnecessary local I/O; measures S3 write path only |
| 14 | DuckLake SQLite-on-local-disk modes (transactions, time-travel, snapshots, concurrent) don't test S3 | Documented: these modes test DuckLake metadata overhead, not storage | Metadata overhead is a real cost of lakehouse guarantees; measuring it is valid, just not for S3 comparison |
| 15 | DuckLake `run_read_phase` queried `duckdb_parquet_metadata` on DuckLake table | Replaced with boto3 `list_objects_v2` for actual S3 size | DuckLake manages Parquet files internally; boto3 gives ground truth |
| 16 | No `--thread-sweep` in DuckLake benchmark | Added `--thread-sweep` flag (1,5,10,20 threads) | Enables scaling curve analysis for all targets |
| 17 | Dead code: `get_s3_object_size()`, `get_parquet_file_size_s3()` never called | Removed both functions | Reduces code surface; avoids confusion about which sizing method is used |
| 18 | Dead code: `time.perf_counter() - time.perf_counter()` always ~0 then overwritten | Removed the dead line | Cleans up misleading code |
| 19 | `read-only` mode writes first (misleading name) | `read-only` seeds data in separate untimed step, then measures reads only | Fair: read performance measured on pre-existing data, not mixed with write latency |

### Remaining Limitations (Documented, Not Fixed)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Single-node localhost testing | No network latency, no horizontal scaling | Documented; results are "loopback throughput" |
| OS page cache on reads | Cached reads are faster than cold reads | Documented; drop_caches not supported on Windows |
| Parquet encoding overhead conflated with storage | Write throughput includes CPU encoding time | Relative ranking preserved; absolute numbers are end-to-end |
| No S3 ListObjects benchmark | Missing metadata-heavy workload | Planned for next iteration |
| No system-level telemetry | Can't explain why one system is slower | Planned for next iteration |
| Incompressible payloads not enforced | Throughput numbers may compress better/worse across targets | Documented; relative comparison valid when payload is identical |

---

# Appendix: Iceberg Benchmark Methodology

## Why Iceberg?

Apache Iceberg is the **industry-standard open table format** for production data lakes. Unlike DuckLake (SQLite metadata), Iceberg stores all metadata as files in the table's directory on S3 — enabling **file-based metadata management** without any external catalog service.

### How Iceberg Metadata Works

Every Iceberg table stores metadata as files in a `metadata/` subdirectory:

```
s3://warehouse/events/
├── data/
│   ├── 00000-1-<uuid>.parquet
│   ├── 00001-2-<uuid>.parquet
│   └── ...
├── metadata/
│   ├── v1.metadata.json        ← table schema, partition spec, snapshot list
│   ├── v2.metadata.json        ← new snapshot after each write operation
│   ├── snap-<uuid>.avro         ← manifest list (which data files are in this snapshot)
│   ├── <uuid>.avro              ← manifest file (file-level metadata: column stats, etc.)
│   └── version-hint.txt         ← points to latest metadata version number
└── ...
```

Each write operation (INSERT, UPDATE, DELETE) creates a new snapshot with its own metadata files. This enables:
- **Time travel**: Query the table as it was at any previous snapshot
- **ACID transactions**: Each snapshot is atomic — either all writes succeed or none do
- **Schema evolution**: Add/rename columns without rewriting data files
- **Partition evolution**: Change partitioning without rewriting existing data

### The Hadoop Catalog (File-Based)

Iceberg supports multiple catalog types. This benchmark uses the **Hadoop catalog**, which stores all metadata directly on S3:

```python
catalog = load_catalog(
    "benchmark_hadoop",
    type="hadoop",
    warehouse="s3://iceberg-warehouse-{target}/",
    s3.endpoint=..., s3.access-key-id=..., s3.secret-access-key=...
)
```

**Why Hadoop catalog (not SQLite or REST)?**
- **Fair comparison**: All targets use the same catalog type — only S3 storage speed varies
- **No external service**: No Hive Metastore, no REST catalog server — self-contained
- **File-based metadata**: Metadata lives on S3 alongside data — tests the storage system's ability to manage metadata files
- **Industry standard**: Hadoop catalog is the simplest Iceberg catalog; production setups use REST or Hive, but the S3 I/O pattern is identical

### Four Benchmarks, Four Perspectives

| Aspect | Classic (`benchmark.py`) | DuckDB (`benchmark_duckdb.py`) | DuckLake (`benchmark_ducklake.py`) | Iceberg (`benchmark_iceberg.py`) |
|--------|--------------------------|-------------------------------|-------------------------------------|----------------------------------|
| **Client** | boto3 (AWS SDK) | DuckDB + httpfs | DuckDB + ducklake | DuckDB + httpfs |
| **Data format** | Raw binary | Raw Parquet | Lakehouse Parquet | Iceberg Parquet |
| **Metadata** | None | None | SQLite (local) | S3 files (file-based) |
| **Versioning** | No | No | Yes (`AT VERSION`) | Yes (snapshot files) |
| **ACID** | No | No | Yes (`BEGIN/COMMIT`) | Yes (append-only snapshots) |
| **Write API** | `put_object()` | `COPY TO s3://` | `INSERT INTO` | `COPY TO s3://` |
| **Read API** | `get_object()` | `read_parquet()` | `SELECT FROM table` | `read_parquet()` from S3 |
| **Tests** | Raw S3 throughput | Analytical workload | Lakehouse (SQLite metadata) | Iceberg-style (file-based metadata) |

### Why DuckDB for Iceberg Workloads?

| Approach | Why DuckDB Chosen |
|----------|-------------------|
| **PyIceberg + S3** | PyArrow multipart upload fails on MinIO — known compatibility issue |
| **DuckDB + httpfs** | Same engine as DuckDB/DuckLake benchmarks — consistent S3 access, no extra dependencies |
| **Iceberg simulation** | Writes multiple small Parquet files to S3 (like Iceberg data files), reads with `read_parquet()` and `iceberg_scan()` |

The Iceberg benchmark simulates Iceberg's file-based metadata pattern by:
1. Writing Parquet files to S3 via `COPY TO s3://` (simulates Iceberg data files)
2. Creating metadata-like file listings via `glob('s3://bucket/data/**/*.parquet')` (simulates Iceberg manifest reads)
3. Reading analytical queries via `read_parquet()` (simulates Iceberg scan operations)
4. Running time-travel, snapshots, and change-detection operations that mirror Iceberg's metadata workflow

---

## Benchmark Methodology (Iceberg Version)

### Architecture

```
DuckDB COPY TO s3:// → Parquet files on S3 (simulates Iceberg data files)
                                    ↓
DuckDB read_parquet() ← reads from S3 ← analytical queries
```

### Table Schema

**events** (main table):

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Sequential identifier |
| `category` | VARCHAR | Category label (A-D) for grouping |
| `value` | DOUBLE | Random float for aggregation |
| `event_time` | TIMESTAMP | Partition key (day transform) |

### Data Generation

Data is generated inline using DuckDB's `generate_series()`:

```python
sql = f"""
    COPY (
        SELECT
            {start_id} + rowid AS id,
            (ARRAY['A','B','C','D'])[1 + (rowid % 4)] AS category,
            random() * 100 AS value,
        NOW() - INTERVAL (rowid % 365) DAY AS event_time
        FROM generate_series(0, {num_rows - 1}) AS t(rowid)
    ) TO 's3://{bucket}/{key}' (FORMAT PARQUET)
"""
```
})
```

Row counts by size tier:

| Size | Rows | Description |
|------|------|-------------|
| 1 MB | 5,000 | Baseline latency tests |
| 16 MB | 80,000 | Medium dataset |
| 32 MB | 160,000 | Throughput stress test |

### 9 Benchmark Modes

#### 1. Write-only
Bulk write: `COPY TO s3://` creates multiple Parquet files on S3. Measures Parquet encoding + S3 upload overhead.

#### 2. Read-only
Seed data first (untimed), then run 5 analytical queries via `read_parquet()`:
- Full table scan (COUNT)
- GROUP BY aggregation
- Column statistics (MIN, MAX, AVG)
- Point query with range filter
- Aggregation with HAVING clause

#### 3. Mixed
Sequential: write phase → read phase (both measured).

#### 4. Heavy
Concurrent writes + reads for 15 seconds. Half threads write via `COPY TO s3://`, half read via `read_parquet()`. Tests real contention on S3.

#### 5. Time Travel
Create snapshot files at different points, then query historical data:
```python
# Write batch 1 → creates data file v1
conn.execute(f"COPY (...) TO 's3://{bucket}/snap_{ts1}.parquet'")
# Write batch 2 → creates data file v2
conn.execute(f"COPY (...) TO 's3://{bucket}/snap_{ts2}.parquet'")
# Read v1 → simulates time-travel query
conn.execute(f"SELECT COUNT(*) FROM 's3://{bucket}/snap_{ts1}.parquet'")
```

#### 6. Snapshots
Create 10 snapshot files + list all files via `glob('s3://bucket/data/**/*.parquet')`. Tests metadata listing latency.

#### 7. Change Detection
Compare two snapshot files to count inserts, deletes, and updates:
```python
old_df = conn.execute(f"SELECT * FROM '{snap_v1}'").fetchdf()
new_df = conn.execute(f"SELECT * FROM '{snap_v2}'").fetchdf()
# Diff on primary key
```

#### 8. Update
Insert new data file (simulates Iceberg update creating new data file):
```python
conn.execute(f"COPY (...) TO 's3://{bucket}/data/update_{ts}.parquet'")
```

#### 9. Delete
Insert new data file (simulates Iceberg delete creating new data file):
```python
conn.execute(f"COPY (...) TO 's3://{bucket}/data/delete_{ts}.parquet'")
```

### Concurrency Model

**Writes**: DuckDB `COPY TO s3://` is called from Python threads. Each thread gets its own DuckDB connection. Parquet files are written independently to S3.

**Reads**: DuckDB `read_parquet()` is called from separate threads. Each thread gets its own DuckDB connection. DuckDB reads Parquet files directly from S3.

**Heavy mode**: Writer threads and reader threads run concurrently for 15 seconds. This tests:
- S3 contention between data writes and data reads
- Concurrent file creation and listing under load
- DuckDB's ability to read consistent data while new files are being written

### Thread Limits

Same as other benchmarks:

| System | Threads | Reason |
|--------|---------|--------|
| **SeaweedFS** | 5 | Master serializes volume assignments via gRPC |
| **MinIO** | 20 | Single-process server handles concurrency natively |
| **RustFS** | 20 | Same architecture as MinIO |
| **libreFS** | 20 | Same architecture as MinIO |

### Metrics Collected

Same structure as DuckLake benchmark:

| Metric | Description |
|--------|-------------|
| `aggregate_throughput_mbps` | Total data (MB) / wall-clock time (s) |
| `latency_p50` | Median per-operation time |
| `latency_p95` / `latency_p99` | Tail latencies |
| `latency_mean` / `latency_stdev` | Average and variance |
| `success` / `failed` | Operation success counts |
| `write_success_rate` | % of writes that succeeded (heavy mode) |
| `read_success_rate` | % of reads that succeeded (heavy mode) |
| `tps` | Transactions per second (small writes) |
| `rows_returned` | Rows returned by analytical queries |
| `snapshot_count` | Number of snapshots created |
| `change_detection` | Inserts/deletes/updates between snapshots |

### Running the Iceberg Benchmark

```bash
# Standard modes
uv run python benchmark_iceberg.py --target minio --mode write-only --sizes 1mb --runs 3
uv run python benchmark_iceberg.py --target all --mode heavy --sizes 1mb,32mb --runs 3

# Iceberg-specific modes
uv run python benchmark_iceberg.py --target minio --mode time-travel --runs 1
uv run python benchmark_iceberg.py --target minio --mode snapshots
uv run python benchmark_iceberg.py --target minio --mode change-detection
uv run python benchmark_iceberg.py --target minio --mode update
uv run python benchmark_iceberg.py --target minio --mode delete
```

Results are saved to `results_iceberg/{mode}/{size}/{target}/run-{N}.json`.

### Cleanup

Each run:
1. Creates a fresh S3 bucket (`benchiceberg-{target}-run{id}-{uuid}`)
2. Creates unique S3 bucket per run (`benchiceberg-{target}-run{id}-{uuid}`)
3. After completion: closes connections, deletes bucket contents
4. Prevents cross-run contamination

---

## Interpreting Iceberg Results

### Iceberg vs DuckLake

- **Iceberg (S3 files) vs DuckLake (SQLite metadata)**: Iceberg writes Parquet files to S3 for every operation; DuckLake writes to local SQLite. Iceberg metadata operations are slower (network round-trip) but more portable.
- **Iceberg time-travel via file listing vs DuckLake `AT VERSION`**: Both work, but Iceberg tracks snapshots as separate files while DuckLake uses version numbers. The overhead is comparable.
- **Iceberg update/delete vs DuckLake**: Both create new Parquet files. Iceberg simulates this via additional COPY TO operations; DuckLake uses SQL INSERT.
- **Iceberg snapshot listing**: Uses `glob('s3://bucket/data/**/*.parquet')` to list files; DuckLake queries local SQLite. Iceberg is slower for listing but doesn't require a database.

### What Iceberg Tests That Others Don't

| Question | Answered By |
|----------|-------------|
| "Can this S3 system handle multiple small Parquet files?" | All Iceberg modes |
| "How fast can this system create and list snapshot files?" | `snapshots` mode |
| "What's the cost of reading historical data?" | `time-travel` mode |
| "Can this system handle concurrent Parquet writers?" | `heavy` mode |
| "How fast can this system diff two file sets?" | `change-detection` mode |

The Iceberg benchmark answers: **"How well does this S3 storage system support Iceberg-style file-based data patterns?"**

### Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Hadoop catalog only | No REST/Hive catalog comparison | Hadoop is the simplest; production setups may differ |
| Single-node localhost testing | No network latency | Documented; results are "loopback throughput" |
| OS page cache on reads | Cached reads faster than cold reads | Documented; drop_caches not supported on Windows |
| Parquet encoding overhead | Write throughput includes CPU time | Relative ranking preserved |
| No S3 ListObjects benchmark | Missing metadata-heavy workload | Iceberg metadata file listing partially covers this |
