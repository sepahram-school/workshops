# ADBC vs psycopg3 — Benchmarking Workshop

Compare **ADBC (Arrow Database Connectivity)** against **psycopg3** under 20 concurrent threads on PostgreSQL 18. Full analysis and results are available on [Medium]() — link to be added.

## Prerequisites

- Docker Engine + Docker Compose (v2+), Python 3.9–3.12, [uv](https://docs.astral.sh/uv/)

## Quick Start

```bash
# 1. Start PostgreSQL
docker compose up -d

# 2. Init Python env
uv init --bare && uv venv
# source .venv/bin/activate  (Linux/macOS)
# .venv\Scripts\activate     (Windows)

# 3. Install deps
uv add -r requirements.txt

# 4. Generate 1M records
python src/generate_data.py --records 1000000

# 5. Run benchmark
python src/benchmark.py --driver both --mode all --threads 20 --queries 5 --runs 2
```

## Modes

| Flag | Description |
|------|-------------|
| `--mode mixed` | Small-to-medium analytical queries (GROUP BY, filtered scans) |
| `--mode large` | Large-result queries (window functions, self-joins) |
| `--mode fetch` | Pure fetch-speed benchmark (10k–500k rows) |
| `--mode all` | All three modes |
| `--analyze` | Run EXPLAIN analysis and exit |
| `--log-file PATH` | Custom log path |

> ⚠️ **Critical:** Always use `fetch_arrow_table()` for ADBC, not `fetchall()`. The benchmark handles this automatically via `consume_result()`.

## Structure

```
6-ADBC-Performance-Comparison/
├── docker-compose.yml       # PostgreSQL 18 (port 5454)
├── requirements.txt
├── pyproject.toml
├── uv.lock
├── src/
│   ├── generate_data.py     # Resumable data generator
│   └── benchmark.py         # Benchmark with warm‑up & percentiles
└── primary_data/            # PG data volume (gitignored)
```
