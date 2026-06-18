# S3 Without MinIO: A Benchmark of SeaweedFS vs RustFS vs libreFS

**When MinIO changed its license, data engineering teams needed alternatives.** This workshop provides a hands-on benchmark comparing four S3-compatible storage systems: **SeaweedFS** (Apache 2.0), **RustFS** (AGPLv3), **libreFS** (AGPLv3), and **MinIO** (AGPLv3 baseline). We deploy each as a Docker cluster, benchmark concurrent writes, and stress-test with a **heavy mixed workload** — concurrent reads and writes simultaneously.

All benchmarks were run in isolation — one cluster active at a time, with full cleanup between runs — to eliminate resource contention.

---

## Important Limitations

**This benchmark was run on a single machine with Docker.** The results are directional, not absolute. Here's what we can and cannot claim:

| Factor | What We Tested | What Production Looks Like |
|--------|---------------|---------------------------|
| Network | Loopback (zero latency) | Real NICs, switches, possible cross-rack |
| Disk | Shared Docker volumes | Dedicated disks per node |
| Failure injection | Docker stop | Real node crashes, disk failures |
| Scale | 3 "nodes" on 1 host | Dozens of nodes across racks |
| Data size | ~17-544 MB per run | TBs to PBs |

**Do not treat these numbers as production performance guarantees.** Use them to narrow your candidate list, then test on your actual hardware.

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

---

## Prerequisites

- **Docker** and **Docker Compose v2** installed
- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) (or pip)
- **16 GB RAM** minimum (32 GB recommended)
- **50 GB free disk space**
- **Linux, macOS, or Windows (PowerShell/WSL2)**

---

## Quick Start

### 1. Install Dependencies

```bash
uv sync
# or: pip install boto3
```

### 2. Generate Test Data

```bash
uv run python generate-data.py --size all --files 100
```

This creates files in `data/1mb/`, `data/16mb/`, `data/32mb/` (100 files each, random bytes).

### 3. Run the Full Benchmark

```bash
.\run-benchmark.ps1
```

This orchestrates the entire benchmark: starts each cluster, runs all modes, cleans up between systems.

### 4. Or Run Individual Benchmarks

```bash
# Start a cluster first (e.g., MinIO)
docker compose -f docker-compose-minio.yml up -d

# Run benchmark
uv run python benchmark.py --target minio --mode heavy --sizes 1mb,16mb,32mb --runs 3 --files 20

# Stop cluster
docker compose -f docker-compose-minio.yml down -v
```

### Benchmark Options

```bash
uv run python benchmark.py --help

# Target: minio, rustfs, librefs, seaweedfs, all
# Mode: heavy, write-only, read-only
# Sizes: 1mb, 16mb, 32mb (comma-separated)
# Runs: number of repetitions (default: 3)
# Files: number of test files (default: 100)
```

---

## Cluster Configurations

### MinIO (1 container)

| Container | Image | Role |
|-----------|-------|------|
| **minio** | `minio/minio:latest` | Single-node S3 server with erasure coding |

The simplest deployment — one process handles everything.

### SeaweedFS (9 containers)

| Container | Image | Role |
|-----------|-------|------|
| **master1/2/3** | `chrislusf/seaweedfs:latest` | Raft cluster for volume allocation |
| **volume1/2/3** | `chrislusf/seaweedfs:latest` | Data storage nodes |
| **filer** | `chrislusf/seaweedfs:latest` | POSIX filesystem namespace |
| **s3** | `chrislusf/seaweedfs:latest` | S3-compatible API gateway |

Every write flows through **4 hops**: `S3 gateway → filer → master → volume node`.

### RustFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **rustfs-1/2/3** | `rustfs/rustfs:latest` | Full S3 server + storage node (erasure coded) |

Each node runs a complete server — no coordination step needed.

### libreFS (3 containers)

| Container | Image | Role |
|-----------|-------|------|
| **librefs-1/2/3** | `librefs:local` | Full MinIO-compatible server + storage |

Same architecture as MinIO distributed mode. Build the image first:

```bash
curl -L -o librefs https://github.com/libreFS/libreFS/releases/download/RELEASE.2026-05-04T00-42-47Z/librefs-linux-amd64
chmod +x librefs
docker build -f Dockerfile.librefs -t librefs:local .
```

---

## Endpoints

| System | S3 API | Credentials | Web UI |
|--------|--------|-------------|--------|
| MinIO | `http://localhost:9200` | `minioadmin` / `minioadmin123` | `http://localhost:9201` |
| RustFS | `http://127.0.0.1:9000` | `rustfsadmin` / `rustfsadmin` | `http://localhost:9011` |
| libreFS | `http://localhost:9100` | `admin` / `password123` | `http://localhost:9101` |
| SeaweedFS | `http://127.0.0.1:8533` | `admin` / `admin` | `http://localhost:8888/filer/` |

> **Note:** RustFS and SeaweedFS require `127.0.0.1` instead of `localhost` due to IPv6 handling on Windows Docker Desktop.

---

## The 5-Thread Limit: Why SeaweedFS Can't Handle 20 Threads

Every write in SeaweedFS requires a round-trip to the master to "assign a volume" before data can be stored:

```
Client → S3 Gateway → Filer → Master (assign volume) → Volume Node
```

With 20 concurrent threads, the master serializes all assignments. The connections pile up, hit the deadline timeout, and fail. At 5 threads, the master can assign volumes fast enough that connections return before the deadline.

Reads bypass the master entirely (volume location is already known), so heavy mode works well at 5 threads because it's 90%+ reads.

---

## Benchmark Results

The full benchmark results, analysis, and recommendations are documented in [`report_lastrun.md`](report_lastrun.md).

### Key Results: Heavy Mixed Workload (concurrent reads + writes, 30s)

| File Size | MinIO | RustFS | libreFS | SeaweedFS |
|-----------|-------|--------|---------|-----------|
| **1 MB** | **81.1 MB/s** | 25.0 MB/s | 27.0 MB/s | 27.8 MB/s |
| **16 MB** | **117.3 MB/s** | 44.3 MB/s | 51.1 MB/s | 27.0 MB/s |
| **32 MB** | **102.5 MB/s** | 42.9 MB/s | 58.8 MB/s | 32.7 MB/s |

### Key Findings

1. **MinIO dominates heavy throughput** — 117.3 MB/s (16mb), 102.5 MB/s (32mb)
2. **SeaweedFS excels at read latency** — P50: 0.133s (1mb), lowest across all sizes
3. **MinIO best at read-only** — 141.6 MB/s (32mb)
4. **libreFS competitive** — 73.3 MB/s (32mb) read-only, 58.8 MB/s (32mb) heavy
5. **All systems 100% success** across all tested sizes (1mb, 16mb, 32mb)

### Recommendation Matrix

| Use Case | Recommended | Why |
|----------|-------------|-----|
| Data lake / analytics | **MinIO** | Highest throughput, proven at scale |
| S3 drop-in replacement | **libreFS** | Full MinIO-compatible API, WebUI/LDAP |
| Low-latency reads | **SeaweedFS** | Lowest read P50 across all sizes |
| POSIX filesystem needed | **SeaweedFS** | Apache 2.0, POSIX support via Filer |
| Commercial SaaS | **MinIO or RustFS** | Stability + performance + license |

---

## Cleanup

```bash
# Stop all clusters
docker compose -f docker-compose-minio.yml down -v
docker compose -f docker-compose-rustfs.yml down -v
docker compose -f docker-compose-librefs.yml down -v
docker compose -f docker-compose-seaweedfs.yml down -v

# Remove data directories
rm -rf data-minio data-rustfs data-librefs data-seaweedfs
```

---

## Files

| File | Description |
|------|-------------|
| `benchmark.py` | Main benchmark script |
| `generate-data.py` | Test data generator |
| `run-benchmark.ps1` | Full benchmark orchestrator |
| `docker-compose-*.yml` | Cluster configurations |
| `Dockerfile.librefs` | libreFS image build |
| `report_lastrun.md` | Full benchmark results and analysis |

---

*All benchmarks in this article are reproducible. Clone the workshop, run the commands, and verify the results yourself. The code is designed for transparency — no hidden optimizations, no cherry-picked numbers.*
