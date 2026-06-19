# How to Run the Benchmark

This guide walks you through setting up the environment and running benchmarks step by step.

---

## Prerequisites

- **Docker** and **Docker Compose v2** installed and running
- **Python 3.10+** installed
- **uv** installed (Python package manager)

### Install uv

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Step 1: Set Up the Python Environment

```bash
# Navigate to the workshop directory
cd 8-SeaweedFS-vs-RustFS

# Create a virtual environment
uv venv

# Activate it
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
uv sync
```

---

## Step 2: Generate Test Data

```bash
# Generate all test files (1mb, 16mb, 32mb) — 100 files each
uv run python generate-data.py --size all --files 100

# Or generate specific sizes
uv run python generate-data.py --size 1mb --files 100
uv run python generate-data.py --size 16mb --files 100
uv run python generate-data.py --size 32mb --files 100
```

This creates files in `data/1mb/`, `data/16mb/`, `data/32mb/`.

---

## Step 3: Start a Cluster

Start **one cluster at a time**. Do not run multiple clusters simultaneously.

```bash
# MinIO
docker compose -f docker-compose-minio.yml up -d

# RustFS
docker compose -f docker-compose-rustfs.yml up -d

# libreFS (requires building the image first — see README.md)
docker compose -f docker-compose-librefs.yml up -d

# SeaweedFS
docker compose -f docker-compose-seaweedfs.yml up -d
```

Wait ~15-50 seconds for all containers to be healthy before running benchmarks.

---

## Step 4: Run the Benchmark

### Command Format

```bash
uv run python benchmark.py --target <TARGET> --mode <MODE> --sizes <SIZES> --runs <RUNS> --files <FILES>
```

| Parameter | Options | Default | Description |
|-----------|---------|---------|-------------|
| `--target` | `minio`, `rustfs`, `librefs`, `seaweedfs` | `seaweedfs` | Which system to benchmark |
| `--mode` | `heavy`, `write-only`, `read-only` | `mixed` | Workload type |
| `--sizes` | `1mb`, `16mb`, `32mb` (comma-separated) | `1mb,32mb` | File sizes to test |
| `--runs` | Any integer | `3` | Number of repetitions |
| `--files` | Any integer | `100` | Number of test files per size |

---

## All Benchmark Combinations

Each command follows: **stop → clean → start → wait → benchmark**. Run one command per mode.

### MinIO

```bash
docker compose -f docker-compose-minio.yml down -v 2>&1; rm -rf data-minio; mkdir -p data-minio; docker compose -f docker-compose-minio.yml up -d; Start-Sleep -Seconds 15; uv run python benchmark.py --target minio --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-minio.yml down -v 2>&1; rm -rf data-minio; mkdir -p data-minio; docker compose -f docker-compose-minio.yml up -d; Start-Sleep -Seconds 15; uv run python benchmark.py --target minio --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-minio.yml down -v 2>&1; rm -rf data-minio; mkdir -p data-minio; docker compose -f docker-compose-minio.yml up -d; Start-Sleep -Seconds 15; uv run python benchmark.py --target minio --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### RustFS

```bash
docker compose -f docker-compose-rustfs.yml down -v 2>&1; rm -rf data-rustfs; mkdir -p data-rustfs/node1 data-rustfs/node2 data-rustfs/node3; docker compose -f docker-compose-rustfs.yml up -d; Start-Sleep -Seconds 30; uv run python benchmark.py --target rustfs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-rustfs.yml down -v 2>&1; rm -rf data-rustfs; mkdir -p data-rustfs/node1 data-rustfs/node2 data-rustfs/node3; docker compose -f docker-compose-rustfs.yml up -d; Start-Sleep -Seconds 30; uv run python benchmark.py --target rustfs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-rustfs.yml down -v 2>&1; rm -rf data-rustfs; mkdir -p data-rustfs/node1 data-rustfs/node2 data-rustfs/node3; docker compose -f docker-compose-rustfs.yml up -d; Start-Sleep -Seconds 30; uv run python benchmark.py --target rustfs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### libreFS

```bash
docker compose -f docker-compose-librefs.yml down -v 2>&1; rm -rf data-librefs; mkdir -p data-librefs/node1 data-librefs/node2 data-librefs/node3; docker compose -f docker-compose-librefs.yml up -d; Start-Sleep -Seconds 20; uv run python benchmark.py --target librefs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-librefs.yml down -v 2>&1; rm -rf data-librefs; mkdir -p data-librefs/node1 data-librefs/node2 data-librefs/node3; docker compose -f docker-compose-librefs.yml up -d; Start-Sleep -Seconds 20; uv run python benchmark.py --target librefs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-librefs.yml down -v 2>&1; rm -rf data-librefs; mkdir -p data-librefs/node1 data-librefs/node2 data-librefs/node3; docker compose -f docker-compose-librefs.yml up -d; Start-Sleep -Seconds 20; uv run python benchmark.py --target librefs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### SeaweedFS

```bash
docker compose -f docker-compose-seaweedfs.yml down -v 2>&1; rm -rf data-seaweedfs; mkdir -p data-seaweedfs/volume1 data-seaweedfs/volume2 data-seaweedfs/volume3; docker compose -f docker-compose-seaweedfs.yml up -d; Start-Sleep -Seconds 50; uv run python benchmark.py --target seaweedfs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-seaweedfs.yml down -v 2>&1; rm -rf data-seaweedfs; mkdir -p data-seaweedfs/volume1 data-seaweedfs/volume2 data-seaweedfs/volume3; docker compose -f docker-compose-seaweedfs.yml up -d; Start-Sleep -Seconds 50; uv run python benchmark.py --target seaweedfs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1

docker compose -f docker-compose-seaweedfs.yml down -v 2>&1; rm -rf data-seaweedfs; mkdir -p data-seaweedfs/volume1 data-seaweedfs/volume2 data-seaweedfs/volume3; docker compose -f docker-compose-seaweedfs.yml up -d; Start-Sleep -Seconds 50; uv run python benchmark.py --target seaweedfs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

---

## Quick Benchmark (Single Run)

For a fast test with 1 run instead of 3:

```bash
uv run python benchmark.py --target minio --mode heavy --sizes 1mb,16mb,32mb --runs 1 --files 20 2>&1
```

---

## Step 5: Stop the Cluster

```bash
# Stop and remove containers + volumes
docker compose -f docker-compose-minio.yml down -v

# Clean data directories
rm -rf data-minio
```

---

## Full Benchmark (All Systems)

To run the entire benchmark suite automatically:

```bash
.\run-benchmark.ps1
```

This starts each cluster sequentially, runs all modes and sizes, and cleans up between systems.

---

## Troubleshooting

### SeaweedFS times out or hangs

SeaweedFS requires a cluster restart between benchmark modes due to gRPC connection pool degradation:

```bash
docker compose -f docker-compose-seaweedfs.yml down -v
rm -rf data-seaweedfs
docker compose -f docker-compose-seaweedfs.yml up -d
# Wait 50 seconds, then run the next benchmark
```

### RustFS not responding on localhost

Use `127.0.0.1` instead of `localhost` — Windows Docker Desktop has IPv6 issues with some containers.

### Disk space errors

128mb benchmarks generate ~1.3 GB per run. Clean data between sizes:

```bash
docker compose -f docker-compose-<system>.yml down -v
rm -rf data-<system>
```
