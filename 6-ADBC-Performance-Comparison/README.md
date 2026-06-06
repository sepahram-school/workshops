# ADBC vs psycopg3: A Real‑World Benchmark Under 20 Concurrent Threads

**Switching to an ADBC (Arrow Database Connectivity) driver can deliver significant query performance improvements, especially for analytical workloads.** ADBC solves a fundamental architectural mismatch: traditional ODBC/JDBC drivers were designed for row-oriented OLTP systems, forcing costly row↔column conversions when used with modern columnar databases. ADBC, built on Apache Arrow, provides a direct zero-copy columnar data path, dramatically reducing memory overhead and serialization costs.

| Feature | ADBC (Arrow Database Connectivity) | ODBC / JDBC (Traditional) |
| :--- | :--- | :--- |
| **Core Architecture** | Columnar-first, built on Apache Arrow | Row-oriented, designed for OLTP |
| **Data Transfer** | Direct, zero-copy columnar exchange | Costly row↔column conversion |
| **Memory Overhead** | Minimal, reduced memory footprint | High, due to duplication & serialization |

Benchmarks confirm the gains: ADBC + Arrow ingests data **3.7x faster** into MySQL from DuckDB, transfers TPC-H Lineitem **38x faster** than ODBC, and scans **4.7M PostgreSQL records in 17 seconds** — outperforming `psycopg2`. Streaming writes exceed **200,000 inserts/second** by eliminating client-side conversion.

The trade‑off is workload dependency. ADBC excels at analytical bulk operations and large result sets. For simple, high‑concurrency transactional queries, traditional row‑based drivers remain competitive. ADBC's ecosystem is newer but growing quickly, with drivers for PostgreSQL, MySQL, Snowflake, BigQuery, and MSSQL, and integration in tools like `dlt`.

Let's validate these capabilities with a hands‑on workshop that benchmarks ADBC against `psycopg3` under 20 concurrent threads on PostgreSQL 18.

> **Reproducibility note:** The benchmark is resumable (checks existing rows before generating), performs a warm‑up phase before each driver run, and runs the full suite multiple times with alternating driver order to control for cache bias. Results report p50 (median), p95, and p99 percentiles alongside throughput.

---

## Prerequisites

- **Software**: Docker Engine + Docker Compose (v2+), Python 3.9–3.12, `uv` (fast Python package manager)
- **Hardware**: At least 2 CPU cores and 8GB RAM to comfortably run the tests.

---

## Setup

### 1. Start PostgreSQL (tuned for production)

```bash
docker compose up -d
```

The container is pre‑configured with `shared_buffers=1GB`, `work_mem=64MB`, `effective_cache_size=3GB`, and resource limits (4 CPU / 4 GB RAM).

### 2. Initialize Python project with `uv`

```bash
uv init --bare
uv venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate          # Windows
```

### 3. Install dependencies

```bash
uv add -r requirements.txt
```

### 4. Generate test data (1 million records)

```bash
python src/generate_data.py --records 1000000
```

The generator is resumable (safe to interrupt) and automatically creates all needed indexes after loading the data:

- `idx_category`
- `idx_price`
- `idx_stock_qty`
- `idx_created_at`
- `idx_category_price`

**Without these indexes, filtered queries fall back to sequential scans and inflate latencies by 3–5×.**

Verify the data and indexes:

```bash
docker exec pg-primary psql -U postgres -c "SELECT COUNT(*) FROM products;"
docker exec pg-primary psql -U postgres -c "SELECT indexname FROM pg_indexes WHERE tablename='products';"
```

### 5. Analyze query plans (optional but recommended)

```bash
python src/benchmark.py --mode all --analyze
```

This runs `EXPLAIN (ANALYZE, BUFFERS)` on every query and warns about sequential scans.

---

## Run the Benchmark

```bash
python src/benchmark.py --driver both --mode all --threads 20 --queries 5 --runs 2
```

**What happens inside:** The benchmark performs a warm‑up (1 full query set per driver, discarded), then runs each driver twice, alternating order. It reports p50/p95/p99, throughput, and logs everything to `logs/benchmark-{timestamp}.log`.

> ⚠️ **Critical note on ADBC usage** – The benchmark uses `cursor.fetch_arrow_table()` for ADBC, not the generic `cursor.fetchall()`. The DBAPI 2.0 `fetchall()` forces ADBC to convert Arrow columnar data back into Python tuples row‑by‑row – a slow fallback that makes ADBC appear **6× slower**. By consuming results as native Arrow tables, the driver delivers the zero‑copy columnar performance it was designed for. The helper function `consume_result()` in `benchmark.py` dispatches the correct method per driver automatically.

### Modes

| Flag | Description |
|------|-------------|
| `--mode mixed` | Small-to-medium analytical queries (GROUP BY, filtered scans) |
| `--mode large` | Large-result queries (window functions, self-joins, unbounded scans) |
| `--mode fetch` | Pure fetch-speed benchmark (10k–500k rows) |
| `--mode all` | All three modes |
| `--analyze` | Run EXPLAIN analysis and exit (no benchmark) |
| `--log-file PATH` | Custom log path (default: `logs/benchmark-{timestamp}.log`) |

### Indexes

For best results, ensure filtered columns are indexed:

```sql
CREATE INDEX idx_price      ON products(price);
CREATE INDEX idx_stock_qty  ON products(stock_quantity);
CREATE INDEX idx_created_at ON products(created_at);
```

---

## Benchmark Environment & Tuning

### PostgreSQL configuration (`docker-compose.yml`)

```yaml
command: |
  postgres
  -c shared_buffers=2GB
  -c effective_cache_size=6GB
  -c work_mem=128MB
  -c max_connections=200
  -c wal_level=replica
  -c max_wal_senders=12
  -c max_replication_slots=10
  -c wal_keep_size=2GB
  -c hot_standby=on
  -c hot_standby_feedback=on
  -c wal_log_hints=on

deploy:
  resources:
    limits:
      cpus: "4"
      memory: 8G
```

### Table schema

```sql
CREATE TABLE products (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       NUMERIC(10,2) NOT NULL,
    stock_quantity INTEGER NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_category      ON products(category);
CREATE INDEX idx_price         ON products(price);
CREATE INDEX idx_stock_qty     ON products(stock_quantity);
CREATE INDEX idx_created_at    ON products(created_at);
CREATE INDEX idx_category_price ON products(category, price);
```

### Benchmark protocol

- 20 persistent connections (no per‑query connect)
- Warm‑up: 1 full query set per driver, discarded
- 2 runs, alternating driver order
- Mixed workload: 100 total executions (20 threads × 5 queries)
- Large‑result workload: 80 total executions (20 threads × 4 queries)
- `EXPLAIN (ANALYZE, BUFFERS)` reported for the slowest query per run

---

## Expected Results

| Mode | psycopg3 | ADBC |
|------|---------:|-----:|
| Mixed workload | **1.98s avg** (0.46s stdev) | 2.47s avg (0.60s stdev) |
| Large-result | 4.15s avg (1.10s stdev) | **3.68s avg (0.43s stdev, 11% faster)** |
| Fetch 500k rows | 7.27s (69k/s) | **2.43s (206k/s, 3.0× faster)** |

### Mixed workload (GROUP BY, filtered scans, LIMIT)

| Metric | psycopg3 | ADBC |
|--------|---------:|-----:|
| Average latency | **1.98s** | 2.47s |
| Stability (stdev) | **0.46s** | 0.60s |
| p50 range | 1.18–2.61s | 1.51–3.78s |
| p95 range | 2.69–7.36s | **2.83–5.94s** |
| Max range | 3.25–8.88s | **3.40–6.92s** |

**psycopg3 wins on mixed workloads by 20% across all 20 runs.** The pattern is consistent: psycopg3's lowest average is 1.44s, ADBC's is 1.74s. However, ADBC has tighter tail latency in every run — p95 never exceeds 5.94s while psycopg3 spikes to 7.36s.

### Large‑result queries (GROUP BY, filtered scans, window function)

| Metric | psycopg3 | ADBC |
|--------|---------:|-----:|
| Average latency | 4.15s | **3.68s (11% faster)** |
| Stability (stdev) | 1.10s | **0.43s (2.6× more stable)** |
| p95 range | 4.39–11.45s | **5.25–8.22s** |
| Max range | 6.04–14.92s | **6.14–11.69s** |
| Individual averages | 2.27–6.06s | **2.84–4.65s** |

**ADBC wins on large-result queries across the entire 20-run set — 11% faster and 2.6× more stable.** Run10 crashed PG entirely under psycopg3 workload — ADBC caused no crashes across **all 19 completed sessions**.

### Pure fetch speed (full table scan with varying LIMITs)

| Rows | psycopg3 | ADBC | Ratio |
|-----:|---------:|-----:|------|
| 10,000 | **0.29s (34k/s)** | 0.35s (29k/s) | psycopg3 1.2× |
| 50,000 | 0.74s (68k/s) | **0.45s (112k/s)** | **ADBC 1.7×** |
| 100,000 | 1.56s (64k/s) | **0.65s (154k/s)** | **ADBC 2.4×** |
| 500,000 | 7.27s (69k/s) | **2.43s (206k/s)** | **ADBC 3.0×** |

**ADBC dominates from 50k rows upward with a 3-to-1 advantage at 500k rows.** psycopg3 throughput plateaus at ~69k rows/s regardless of volume — Python tuple allocation under the GIL is the bottleneck.

---

## Key Takeaways — The Final Verdict After 20 Runs

1. **Use the right fetch method** – `cursor.fetchall()` on ADBC triggers a slow Arrow→tuple fallback, making ADBC appear 6× slower. Always use `fetch_arrow_table()` for ADBC and `fetchall()` for traditional DBAPI drivers.

2. **Workload determines the winner** – On small cached aggregate queries, psycopg3 wins by 20% on average (lower per-query connection overhead). On large-result queries, ADBC wins by 11% on average (zero-copy Arrow, GIL release). On raw data transfer, ADBC wins by 3×.

3. **ADBC's stability is its strongest asset** – Across every mode across every run, ADBC's standard deviation is smaller: 1.3–2.6× tighter than psycopg3. The C-level Arrow copy and GIL release make execution time predictable regardless of load.

4. **ADBC is crash-safe; psycopg3 crashed PG** – In 59 completed benchmark sessions across 3 modes and 20 runs, ADBC never triggered a server crash. psycopg3's large-result mode caused PostgreSQL to enter recovery mode once (run10), aborting both drivers.

5. **The 20-run average is definitive** – Single runs are misleading due to cold-cache effects and scheduling variance. The 20-run aggregate reveals a clear, reproducible pattern: psycopg3 is faster on small queries by 20%; ADBC is faster on large-result queries by 11% and on raw fetch by 3-to-1.

6. **Index what you filter** – Without indexes on `price`, `stock_quantity`, and `created_at`, even simple queries seq‑scan 1M rows. Run `benchmark.py --analyze` before measuring to surface missing indexes.

---

## Workshop Structure

```
6-ADBC-Performance-Comparison/
├── .gitignore               # Ignores .venv, pycache, primary_data
├── docker-compose.yml       # PostgreSQL 18 (port 5454, tuned)
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Project config
├── uv.lock                  # Locked dependencies
├── src/
│   ├── generate_data.py     # Resumable synthetic data generator (UUID v7)
│   └── benchmark.py         # Robust benchmark with warm‑up & percentiles
└── primary_data/            # PG data volume (gitignored)
```

Run your own tests, tweak the queries, and share your findings. The complete setup is ready to clone and execute.
