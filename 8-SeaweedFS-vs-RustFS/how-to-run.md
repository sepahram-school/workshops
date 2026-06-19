# How to Run the Benchmark

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
cd 8-SeaweedFS-vs-RustFS
uv venv
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

```bash
uv sync
```

---

## Step 2: Generate Test Data

```bash
uv run python generate-data.py --size all --files 100
```

---

## Step 3: Preprocessing

Run the preprocessing block for the system you want to benchmark. Repeat for each system.

### PowerShell (Windows) — Example for MinIO

```powershell
docker compose -f docker-compose-minio.yml down -v 2>&1
Remove-Item -Recurse -Force "data-minio" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "data-minio\node1", "data-minio\node2", "data-minio\node3" | Out-Null
docker compose -f docker-compose-minio.yml up -d
Start-Sleep -Seconds 15
```

> Repeat with `docker-compose-rustfs.yml` / `data-rustfs\node1,2,3` (sleep 30), `docker-compose-librefs.yml` / `data-librefs\node1,2,3` (sleep 20), or `docker-compose-seaweedfs.yml` / `data-seaweedfs\volume1,2,3` (sleep 50).

### Bash / macOS / Linux — Example for MinIO

```bash
docker compose -f docker-compose-minio.yml down -v 2>&1
rm -rf data-minio
mkdir -p data-minio/node1 data-minio/node2 data-minio/node3
docker compose -f docker-compose-minio.yml up -d
sleep 15
```

> Repeat with `docker-compose-rustfs.yml` / `data-rustfs/node1,2,3` (sleep 30), `docker-compose-librefs.yml` / `data-librefs/node1,2,3` (sleep 20), or `docker-compose-seaweedfs.yml` / `data-seaweedfs/volume1,2,3` (sleep 50).

---

## Step 4: Run Benchmark

Run one command per mode. Each command runs all sizes (1mb, 16mb, 32mb) in sequence.

### MinIO

```bash
uv run python benchmark.py --target minio --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target minio --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target minio --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### RustFS

```bash
uv run python benchmark.py --target rustfs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target rustfs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target rustfs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### libreFS

```bash
uv run python benchmark.py --target librefs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target librefs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target librefs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

### SeaweedFS

```bash
uv run python benchmark.py --target seaweedfs --mode write-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target seaweedfs --mode read-only --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
uv run python benchmark.py --target seaweedfs --mode heavy --sizes "1mb,16mb,32mb" --runs 3 --files 20 2>&1
```

> **SeaweedFS:** Run preprocessing (Step 3) before each mode due to gRPC connection pool degradation.

---

## Step 5: Stop and Clean

```powershell
# PowerShell
docker compose -f docker-compose-minio.yml down -v
docker compose -f docker-compose-rustfs.yml down -v
docker compose -f docker-compose-librefs.yml down -v
docker compose -f docker-compose-seaweedfs.yml down -v
Remove-Item -Recurse -Force "data-minio","data-rustfs","data-librefs","data-seaweedfs" -ErrorAction SilentlyContinue
```

```bash
# Bash / macOS / Linux
docker compose -f docker-compose-minio.yml down -v
docker compose -f docker-compose-rustfs.yml down -v
docker compose -f docker-compose-librefs.yml down -v
docker compose -f docker-compose-seaweedfs.yml down -v
rm -rf data-minio data-rustfs data-librefs data-seaweedfs
```

---

## Full Benchmark (All Systems)

To run the entire benchmark suite automatically:

```powershell
.\run-benchmark.ps1
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| SeaweedFS times out | Run preprocessing before each mode |
| RustFS not responding on localhost | Use `127.0.0.1` instead (IPv6 issue) |
| Disk space errors | Clean data between runs (Step 5) |
