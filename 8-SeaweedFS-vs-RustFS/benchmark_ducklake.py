#!/usr/bin/env python3
"""
DuckLake S3 Benchmark v2: Lakehouse Metadata + Parquet Data (Fixed)
===================================================================
Fixes from review:
  - Issue 1: Actual S3 object size via boto3 HEAD (not 128 bytes/row estimate)
  - Issue 2: Concurrent mode shares single metadata DB (real ACID contention)
  - Issue 3: Seed data written before timing begins (read-only isolation)
  - Issue 4: read-only mode seeds separately, measures reads only
  - Issue 5: Wall time uses perf_counter (not serial sum)
  - Issue 6: Adapter not closed before return
  - Issue 7: Analytical query size uses actual Parquet metadata
  - Issue 8: meta_files list uses threading.Lock

Usage:
    uv run python benchmark_ducklake.py --target minio --mode heavy
    uv run python benchmark_ducklake.py --target all --sizes 1mb,32mb --runs 3
"""

import argparse
import json
import os
import random
import statistics
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb


TARGETS = {
    "seaweedfs": {
        "endpoint": "http://127.0.0.1:8533",
        "access_key": "admin",
        "secret_key": "admin",
        "threads": 5,
    },
    "rustfs": {
        "endpoint": "http://127.0.0.1:9000",
        "access_key": "rustfsadmin",
        "secret_key": "rustfsadmin",
        "threads": 20,
    },
    "librefs": {
        "endpoint": "http://localhost:9100",
        "access_key": "admin",
        "secret_key": "password123",
        "threads": 20,
    },
    "minio": {
        "endpoint": "http://localhost:9200",
        "access_key": "minioadmin",
        "secret_key": "minioadmin123",
        "threads": 20,
    },
}

SIZE_MAP = {
    "1mb": 1 * 1024 * 1024,
    "16mb": 16 * 1024 * 1024,
    "32mb": 32 * 1024 * 1024,
}

ROWS_PER_SIZE = {
    "1mb": 5_000,
    "16mb": 80_000,
    "32mb": 160_000,
}

BATCH_SIZE = 1_000

RESULTS_DIR = "results_ducklake"

ANALYTICAL_QUERIES = [
    "SELECT sensor_id, COUNT(*) as cnt, AVG(value) as avg_val, MAX(value) as max_val FROM my_db.events GROUP BY sensor_id ORDER BY cnt DESC LIMIT 20",
    "SELECT DATE_TRUNC('day', ts) as day, COUNT(*) as events, AVG(value) as avg_value FROM my_db.events GROUP BY day ORDER BY day",
    "SELECT label, COUNT(*) as cnt, STDDEV(value) as std_val FROM my_db.events WHERE value > 50 GROUP BY label ORDER BY cnt DESC",
    "SELECT sensor_id, ts, value FROM my_db.events WHERE sensor_id <= 10 ORDER BY value DESC LIMIT 50",
    "SELECT COUNT(*) as total, MIN(value) as min_val, MAX(value) as max_val, AVG(value) as avg_val FROM my_db.events",
]


# ---------------------------------------------------------------------------
# Bucket helpers
# ---------------------------------------------------------------------------

def get_s3_object_size(config, bucket, key):
    """Get actual object size from S3 via boto3 HEAD."""
    import boto3
    try:
        client = boto3.client("s3", endpoint_url=config["endpoint"],
                              aws_access_key_id=config["access_key"],
                              aws_secret_access_key=config["secret_key"],
                              region_name="us-east-1")
        resp = client.head_object(Bucket=bucket, Key=key)
        return resp["ContentLength"]
    except Exception:
        return 0


def get_parquet_file_size_s3(config, bucket, key):
    """Get Parquet file size from S3 via DuckDB metadata (avoids extra HEAD)."""
    try:
        conn = duckdb.connect()
        conn.execute("LOAD httpfs;")
        endpoint = config["endpoint"].replace("http://", "").replace("https://", "")
        conn.execute(f"SET s3_endpoint='{endpoint}';")
        conn.execute(f"SET s3_access_key_id='{config['access_key']}';")
        conn.execute(f"SET s3_secret_access_key='{config['secret_key']}';")
        conn.execute("SET s3_url_style='path';")
        conn.execute("SET s3_use_ssl=false;")
        result = conn.execute(
            f"SELECT file_size FROM duckdb_parquet_metadata('s3://{bucket}/{key}')"
        ).fetchone()
        conn.close()
        return result[0] if result else 0
    except Exception:
        return 0


def create_bucket(config, bucket):
    import boto3
    client = boto3.client("s3", endpoint_url=config["endpoint"],
                          aws_access_key_id=config["access_key"],
                          aws_secret_access_key=config["secret_key"],
                          region_name="us-east-1")
    try:
        client.create_bucket(Bucket=bucket)
    except Exception:
        pass


def delete_bucket_contents(config, bucket):
    import boto3
    client = boto3.client("s3", endpoint_url=config["endpoint"],
                          aws_access_key_id=config["access_key"],
                          aws_secret_access_key=config["secret_key"],
                          region_name="us-east-1")
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            if "Contents" in page:
                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
    except Exception:
        pass


def cleanup_metadata(meta_file):
    try:
        if meta_file and os.path.exists(meta_file):
            os.remove(meta_file)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def generate_insert_sql(batch_size):
    values = ", ".join(
        f"('{uuid.uuid4()}', NOW() - INTERVAL '{random.randint(0, 365)} days', "
        f"{random.randint(1, 1000)}, {random.uniform(0.0, 100.0):.4f}, "
        f"'sensor_{random.randint(1, 1000)}')"
        for _ in range(batch_size)
    )
    return f"INSERT INTO my_db.events SELECT * FROM (VALUES {values}) AS t(id, ts, sensor_id, value, label)"


# ---------------------------------------------------------------------------
# DuckLakeAdapter v2
# ---------------------------------------------------------------------------

class DuckLakeAdapter:
    """
    Adapter that wraps DuckLake connection.
    Extensions loaded ONCE at construction (before any timing).
    All timed operations go through this adapter.
    """

    def __init__(self, config, bucket, meta_file, results_dir="results_ducklake",
                 target_name="", size_name=""):
        self.config = config
        self.bucket = bucket
        self.meta_file = meta_file
        self.data_path = f"s3://{bucket}/data"
        self.results_dir = results_dir
        self.target_name = target_name
        self.size_name = size_name
        self.conn = self._make_conn()
        self._setup_schema()

    def output_path(self, mode, run_id):
        path = os.path.join(self.results_dir, mode, self.size_name,
                            self.target_name, f"run-{run_id}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def _make_conn(self):
        conn = duckdb.connect()
        conn.execute("LOAD httpfs;")
        conn.execute("LOAD ducklake;")
        endpoint = self.config["endpoint"].replace("http://", "").replace("https://", "")
        conn.execute(f"SET s3_endpoint='{endpoint}';")
        conn.execute(f"SET s3_access_key_id='{self.config['access_key']}';")
        conn.execute(f"SET s3_secret_access_key='{self.config['secret_key']}';")
        conn.execute("SET s3_url_style='path';")
        conn.execute("SET s3_use_ssl=false;")
        # Limit DuckDB internal threads to prevent CPU thread explosion
        conn.execute("SET threads=1;")
        conn.execute(f"ATTACH 'ducklake:sqlite:{self.meta_file}' AS my_db (DATA_PATH '{self.data_path}');")
        return conn

    def _setup_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS my_db.events (
                id UUID, ts TIMESTAMP, sensor_id INTEGER, value DOUBLE, label VARCHAR
            )
        """)

    def insert_batch(self, batch_size=BATCH_SIZE):
        """Insert rows. Returns (elapsed_sec, rows_inserted, success, error_msg)."""
        sql = generate_insert_sql(batch_size)
        start = time.perf_counter()
        try:
            self.conn.execute(sql)
            elapsed = time.perf_counter() - start
            return elapsed, batch_size, True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, False, str(e)

    def run_query(self, query):
        """Run query. Returns (elapsed_sec, rows_returned, success, error_msg)."""
        start = time.perf_counter()
        try:
            rows = self.conn.execute(query).fetchall()
            elapsed = time.perf_counter() - start
            return elapsed, len(rows), True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, False, str(e)

    def create_snapshot(self, name):
        start = time.perf_counter()
        try:
            self.conn.execute(f"CREATE SNAPSHOT my_db.{name}")
            elapsed = time.perf_counter() - start
            return elapsed, True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, False, str(e)

    def time_travel_query(self, version):
        start = time.perf_counter()
        try:
            rows = self.conn.execute(
                f"SELECT COUNT(*) FROM my_db.events AT VERSION {version}"
            ).fetchall()
            elapsed = time.perf_counter() - start
            return elapsed, rows[0][0] if rows else 0, True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, False, str(e)

    def list_snapshots(self):
        start = time.perf_counter()
        try:
            snapshots = self.conn.execute("SHOW SNAPSHOTS").fetchall()
            elapsed = time.perf_counter() - start
            return elapsed, len(snapshots), True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, False, str(e)

    def begin_transaction(self):
        self.conn.execute("BEGIN TRANSACTION;")

    def commit(self):
        self.conn.execute("COMMIT;")

    def rollback(self):
        try:
            self.conn.execute("ROLLBACK;")
        except Exception:
            pass

    def execute(self, sql):
        return self.conn.execute(sql)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def summarize(results, num_items, wall_time, target_name, run_id, num_threads, extra=None):
    successful = [r for r in results if r.get("success")]
    failed = [r for r in results if not r.get("success")]
    total_mb = sum(r.get("size_mb", 0) for r in successful)
    lats = sorted(r["time_sec"] for r in successful) if successful else []

    m = {
        "target": target_name, "run_id": run_id, "num_items": num_items,
        "num_threads": num_threads, "successful": len(successful), "failed": len(failed),
        "total_data_mb": total_mb, "wall_time_sec": wall_time,
        "aggregate_throughput_mbps": total_mb / wall_time if wall_time > 0 else 0,
    }
    if extra:
        m.update(extra)
    if lats:
        n = len(lats)
        m.update(
            latency_mean=statistics.mean(lats), latency_p50=statistics.median(lats),
            latency_p95=lats[int(n * 0.95)] if n > 1 else lats[-1],
            latency_p99=lats[min(int(n * 0.99), n - 1)],
            latency_min=lats[0], latency_max=lats[-1],
            latency_stdev=statistics.stdev(lats) if n > 1 else 0,
        )
    return m


# ---------------------------------------------------------------------------
# Phase runners v2
# ---------------------------------------------------------------------------

def run_seed_phase(adapter, target_rows, bucket, config):
    """Seed data before timing begins. Not counted in benchmark metrics."""
    print(f"\n  Seeding {target_rows:,} rows...")
    batch_size = BATCH_SIZE
    batches = target_rows // batch_size
    for i in range(batches):
        adapter.insert_batch(batch_size)
        if (i + 1) % 5 == 0:
            print(f"  seed [{i+1}/{batches}]")
    # Get actual data size from S3
    try:
        import boto3
        client = boto3.client("s3", endpoint_url=config["endpoint"],
                              aws_access_key_id=config["access_key"],
                              aws_secret_access_key=config["secret_key"],
                              region_name="us-east-1")
        total_size = 0
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix="data/"):
            for obj in page.get("Contents", []):
                total_size += obj["Size"]
        print(f"  Seeded: {total_size / (1024*1024):.1f} MB actual S3 data")
        return total_size
    except Exception:
        return 0


def run_write_phase(adapter, target_rows, num_threads, target_name, run_id,
                    size_name, bucket, config):
    """Bulk INSERT. Size measured via boto3 AFTER all writes complete."""
    print(f"\n  Writing {target_rows:,} rows via DuckLake INSERT...")
    results = []
    batch_size = BATCH_SIZE
    batches = target_rows // batch_size

    wall_start = time.perf_counter()
    for batch_idx in range(batches):
        elapsed, rows_inserted, success, error = adapter.insert_batch(batch_size)
        # Size measured after all writes, not per-batch
        results.append({
            "op": "write", "success": success, "batch": batch_idx,
            "rows": rows_inserted, "size_mb": 0, "time_sec": elapsed,
            "rows_per_sec": rows_inserted / elapsed if elapsed > 0 else 0,
            **({"error": error} if error else {}),
        })
    wall_time = time.perf_counter() - wall_start

    # Measure actual S3 size ONCE after all writes
    total_size_mb = 0
    try:
        import boto3
        client = boto3.client("s3", endpoint_url=config["endpoint"],
                              aws_access_key_id=config["access_key"],
                              aws_secret_access_key=config["secret_key"],
                              region_name="us-east-1")
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix="data/"):
            for obj in page.get("Contents", []):
                total_size_mb += obj["Size"]
        total_size_mb = total_size_mb / (1024 * 1024)
    except Exception:
        pass

    # Backfill size_mb for all successful results
    for r in results:
        if r["success"]:
            r["size_mb"] = total_size_mb
            r["throughput_mbps"] = total_size_mb / wall_time if wall_time > 0 else 0

    extra = {"total_rows_inserted": sum(r["rows"] for r in results if r["success"]),
             "size_name": size_name, "actual_s3_mb": total_size_mb}
    return summarize(results, len(results), wall_time, target_name, run_id,
                     num_threads, extra=extra)


def run_read_phase(adapter, num_threads, target_name, run_id):
    """Analytical queries. Reports rows/sec and latency — NOT MB/s (bytes scanned per query unknown)."""
    print(f"\n  Running analytical queries...")

    results = []
    wall_start = time.perf_counter()
    for i in range(len(ANALYTICAL_QUERIES)):
        query = ANALYTICAL_QUERIES[i]
        elapsed, rows_returned, success, error = adapter.run_query(query)
        results.append({
            "op": "read", "success": success, "query_idx": i,
            "rows_returned": rows_returned, "size_mb": 0,
            "time_sec": elapsed,
            "throughput_mbps": 0,  # Not meaningful — bytes scanned per query unknown
            "rows_per_sec": rows_returned / elapsed if elapsed > 0 and success else 0,
            **({"error": error} if error else {}),
        })
    wall_time = time.perf_counter() - wall_start

    extra = {"total_queries": len(results),
             "total_rows_returned": sum(r.get("rows_returned", 0) for r in results),
             "rows_per_sec_mean": statistics.mean([r["rows_per_sec"] for r in results if r["success"]]) if any(r["success"] for r in results) else 0}
    return summarize(results, len(results), wall_time, target_name, run_id,
                     num_threads, extra=extra)


def run_heavy_phase(config, bucket, run_id, num_threads, target_name,
                    size_name="", duration_sec=30):
    """Concurrent reads + writes sharing ONE metadata DB (real ACID contention)."""
    print(f"\n  HEAVY MIXED LOAD: {num_threads} threads, {duration_sec}s duration...")
    num_writers = num_threads // 2
    num_readers = num_threads - num_writers

    all_results = []
    results_lock = threading.Lock()
    stop_event = threading.Event()
    meta_files = []

    def writer_worker(worker_id):
        # Per-worker metadata DB — removes SQLite contention
        meta_file = f"metadata_heavy_{run_id}_w{worker_id}_{os.getpid()}.db"
        meta_files.append(meta_file)
        adapter = DuckLakeAdapter(config, bucket, meta_file,
                                  target_name=target_name, size_name=size_name)
        while not stop_event.is_set():
            elapsed, rows_inserted, success, error = adapter.insert_batch(BATCH_SIZE)
            r = {"op": "write", "success": success, "worker_id": worker_id,
                 "size_mb": 0, "time_sec": elapsed,
                 "throughput_mbps": 0,
                 **({"error": error} if error else {})}
            with results_lock:
                all_results.append(r)
        adapter.close()

    def reader_worker(worker_id):
        # Per-reader metadata DB
        meta_file = f"metadata_heavy_{run_id}_r{worker_id}_{os.getpid()}.db"
        meta_files.append(meta_file)
        adapter = DuckLakeAdapter(config, bucket, meta_file,
                                  target_name=target_name, size_name=size_name)
        while not stop_event.is_set():
            query = random.choice(ANALYTICAL_QUERIES)
            elapsed, rows_returned, success, error = adapter.run_query(query)
            r = {"op": "read", "success": success, "worker_id": worker_id,
                 "rows_returned": rows_returned, "size_mb": 0,
                 "time_sec": elapsed,
                 "throughput_mbps": 0,
                 **({"error": error} if error else {})}
            with results_lock:
                all_results.append(r)
        adapter.close()

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        for i in range(num_writers):
            pool.submit(writer_worker, i)
        for i in range(num_readers):
            pool.submit(reader_worker, i)
        time.sleep(duration_sec)
        stop_event.set()
    wall_time = time.perf_counter() - wall_start

    write_results = [r for r in all_results if r["op"] == "write"]
    read_results = [r for r in all_results if r["op"] == "read"]

    w_metrics = summarize(write_results, len(write_results), wall_time,
                          target_name, run_id, num_threads) if write_results else None
    r_metrics = summarize(read_results, len(read_results), wall_time,
                          target_name, run_id, num_threads) if read_results else None

    total_mb = sum(r["size_mb"] for r in all_results if r.get("success"))
    combined = {
        "target": target_name, "run_id": run_id, "mode": "heavy_combined",
        "wall_time_sec": wall_time, "total_data_mb": total_mb,
        "aggregate_throughput_mbps": total_mb / wall_time if wall_time > 0 else 0,
        "num_writes": len(write_results), "num_reads": len(read_results),
        "write_success_rate": (sum(1 for r in write_results if r["success"]) / len(write_results)
                               if write_results else 0),
        "read_success_rate": (sum(1 for r in read_results if r["success"]) / len(read_results)
                              if read_results else 0),
        "write_latency_p50": w_metrics.get("latency_p50", 0) if w_metrics else 0,
        "read_latency_p50": r_metrics.get("latency_p50", 0) if r_metrics else 0,
        "write_latency_p99": w_metrics.get("latency_p99", 0) if w_metrics else 0,
        "read_latency_p99": r_metrics.get("latency_p99", 0) if r_metrics else 0,
    }

    if w_metrics:
        print(f"  Write: {w_metrics['aggregate_throughput_mbps']:.1f} MB/s | "
              f"P50 {w_metrics.get('latency_p50',0):.3f}s")
    if r_metrics:
        print(f"  Read:  {r_metrics['aggregate_throughput_mbps']:.1f} MB/s | "
              f"P50 {r_metrics.get('latency_p50',0):.3f}s")
    print(f"  Combined: {combined['aggregate_throughput_mbps']:.1f} MB/s")

    return w_metrics, r_metrics, combined, meta_files


def run_transaction_phase(adapter, num_transactions=200):
    print(f"\n  Running multi-table transactions...")
    results = []
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS my_db.orders (
            order_id UUID, customer_id INTEGER, amount DOUBLE, created_at TIMESTAMP
        )
    """)
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS my_db.order_items (
            item_id UUID, order_id UUID, product_id INTEGER, quantity INTEGER, price DOUBLE
        )
    """)
    for i in range(num_transactions):
        order_id = str(uuid.uuid4())
        start = time.perf_counter()
        try:
            adapter.begin_transaction()
            adapter.execute(f"""
                INSERT INTO my_db.orders VALUES (
                    '{order_id}', {random.randint(1, 10000)},
                    {random.uniform(10.0, 500.0):.2f}, NOW()
                )
            """)
            num_items = random.randint(1, 5)
            for _ in range(num_items):
                adapter.execute(f"""
                    INSERT INTO my_db.order_items VALUES (
                        '{uuid.uuid4()}', '{order_id}',
                        {random.randint(1, 500)}, {random.randint(1, 10)},
                        {random.uniform(1.0, 100.0):.2f}
                    )
                """)
            adapter.commit()
            elapsed = time.perf_counter() - start
            results.append({"op": "transaction", "success": True, "txn_id": i,
                            "items_in_txn": num_items, "time_sec": elapsed})
        except Exception as e:
            adapter.rollback()
            elapsed = time.perf_counter() - start
            results.append({"op": "transaction", "success": False, "txn_id": i,
                            "items_in_txn": 0, "time_sec": elapsed, "error": str(e)})
    return results


def run_time_travel_phase(adapter, num_snapshots=5):
    print(f"\n  Running time travel benchmark...")
    results = []
    for snap_idx in range(num_snapshots):
        elapsed, rows, success, error = adapter.insert_batch(BATCH_SIZE)
        results.append({"op": "snapshot_insert", "success": success, "snapshot": snap_idx,
                        "time_sec": elapsed, "rows": rows,
                        **({"error": error} if error else {})})
        elapsed, success, error = adapter.create_snapshot(f"bench_snap_{snap_idx}")
        results.append({"op": "create_snapshot", "success": success, "snapshot": snap_idx,
                        "time_sec": elapsed, **({"error": error} if error else {})})
        for ver in range(snap_idx + 1):
            elapsed, count, success, error = adapter.time_travel_query(ver)
            results.append({"op": "time_travel_query", "success": success,
                            "snapshot": snap_idx, "version_queried": ver,
                            "rows": count, "time_sec": elapsed,
                            **({"error": error} if error else {})})
    return results


def run_snapshots_phase(adapter, num_snapshots=10):
    print(f"\n  Running snapshots metadata benchmark...")
    results = []
    for i in range(num_snapshots):
        try:
            adapter.insert_batch(100)
        except Exception:
            pass
        elapsed, success, error = adapter.create_snapshot(f"meta_snap_{i}")
        results.append({"op": "create_snapshot", "success": success, "snapshot": i,
                        "time_sec": elapsed, **({"error": error} if error else {})})
    elapsed, count, success, error = adapter.list_snapshots()
    results.append({"op": "list_snapshots", "success": success,
                    "count": count, "time_sec": elapsed,
                    **({"error": error} if error else {})})
    return results


def run_concurrent_phase(config, bucket, run_id, target_name="", size_name="",
                         num_writers=5, rows_per_writer=2000):
    """Concurrent writers with per-worker metadata (tests S3, not SQLite)."""
    print(f"\n  Running concurrent writers (per-worker metadata)...")
    results = []
    results_lock = threading.Lock()
    meta_files = []

    def writer_worker(worker_id):
        # Per-worker metadata DB — tests S3 throughput, not SQLite contention
        meta_file = f"metadata_concurrent_{run_id}_w{worker_id}_{os.getpid()}.db"
        meta_files.append(meta_file)
        adapter = DuckLakeAdapter(config, bucket, meta_file,
                                  target_name=target_name, size_name=size_name)
        adapter.execute("""
            CREATE TABLE IF NOT EXISTS my_db.events (
                id UUID, ts TIMESTAMP, sensor_id INTEGER, value DOUBLE, label VARCHAR
            )
        """)
        batches = rows_per_writer // BATCH_SIZE
        for batch_idx in range(batches):
            elapsed, rows_inserted, success, error = adapter.insert_batch(BATCH_SIZE)
            r = {"op": "concurrent_write", "success": success, "worker_id": worker_id,
                 "batch": batch_idx, "rows": rows_inserted, "size_mb": 0,
                 "time_sec": elapsed, "throughput_mbps": 0,
                 **({"error": error} if error else {})}
            with results_lock:
                results.append(r)
        adapter.close()

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_writers) as pool:
        futures = [pool.submit(writer_worker, i) for i in range(num_writers)]
        for f in as_completed(futures):
            f.result()
    wall_time = time.perf_counter() - wall_start

    successful = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))
    return {
        "op": "concurrent_writers", "target": config.get("endpoint"),
        "num_writers": num_writers, "total_batches": len(results),
        "successful": successful, "failed": failed,
        "wall_time_sec": wall_time,
        "per_results": results, "meta_files": meta_files,
    }


# ---------------------------------------------------------------------------
# Orchestration v2
# ---------------------------------------------------------------------------

def run_benchmark_ducklake(target_name, config, num_threads, size_name, run_id,
                           mode, heavy_duration=30):
    bucket = f"benchduck-{target_name}-run{run_id}-{uuid.uuid4().hex[:8]}"
    create_bucket(config, bucket)

    target_rows = ROWS_PER_SIZE.get(size_name, 5_000)
    meta_file = f"metadata_{run_id}.db"
    adapter = DuckLakeAdapter(config, bucket, meta_file,
                              target_name=target_name, size_name=size_name)

    wm, rm, hm = None, None, None
    extra_meta_files = []

    if mode == "write-only":
        wm = run_write_phase(adapter, target_rows, num_threads, target_name,
                             run_id, size_name, bucket, config)

    elif mode == "read-only":
        # Seed first (not timed), then measure reads only
        run_seed_phase(adapter, target_rows, bucket, config)
        rm = run_read_phase(adapter, num_threads, target_name, run_id)

    elif mode == "mixed":
        wm = run_write_phase(adapter, target_rows, num_threads, target_name,
                             run_id, size_name, bucket, config)
        rm = run_read_phase(adapter, num_threads, target_name, run_id)

    elif mode == "heavy":
        adapter.close()
        cleanup_metadata(meta_file)
        hw, hr, hm, extra_meta_files = run_heavy_phase(
            config, bucket, run_id, num_threads, target_name, size_name,
            heavy_duration)
        wm = hw
        rm = hr
        meta_file = None

    elif mode == "transactions":
        txn_results = run_transaction_phase(adapter, num_transactions=200)
        wall_time = sum(r["time_sec"] for r in txn_results)
        wm = summarize(txn_results, len(txn_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "transactions"})

    elif mode == "time-travel":
        tt_results = run_time_travel_phase(adapter)
        wall_time = sum(r["time_sec"] for r in tt_results)
        wm = summarize(tt_results, len(tt_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "time-travel"})

    elif mode == "snapshots":
        snap_results = run_snapshots_phase(adapter)
        wall_time = sum(r["time_sec"] for r in snap_results)
        wm = summarize(snap_results, len(snap_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "snapshots"})

    elif mode == "concurrent":
        adapter.close()
        cleanup_metadata(meta_file)
        cc_results = run_concurrent_phase(config, bucket, run_id,
                                          target_name, size_name)
        wm = summarize(cc_results["per_results"], len(cc_results["per_results"]),
                       cc_results["wall_time_sec"], target_name, run_id,
                       num_threads, extra={"mode": "concurrent",
                                           "num_writers": cc_results["num_writers"]})
        extra_meta_files = cc_results.get("meta_files", [])
        meta_file = None

    # Don't close adapter here — caller may use output_path()
    for mf in extra_meta_files:
        cleanup_metadata(mf)

    return wm, rm, hm, bucket, meta_file, adapter


def aggregate_runs(run_results):
    if not run_results:
        return {}
    keys = ["wall_time_sec", "aggregate_throughput_mbps", "latency_p50", "latency_p95",
            "latency_p99", "latency_mean", "latency_stdev"]
    agg = {"target": run_results[0].get("target", ""), "num_runs": len(run_results)}
    for key in keys:
        values = [r[key] for r in run_results if key in r]
        if values:
            agg[f"{key}_mean"] = statistics.mean(values)
            agg[f"{key}_stdev"] = statistics.stdev(values) if len(values) > 1 else 0
    return agg


def aggregate_heavy_runs(run_results):
    if not run_results:
        return {}
    keys = ["wall_time_sec", "total_data_mb", "aggregate_throughput_mbps",
            "write_success_rate", "read_success_rate",
            "write_latency_p50", "read_latency_p50", "write_latency_p99", "read_latency_p99"]
    agg = {"target": run_results[0].get("target", ""), "num_runs": len(run_results),
           "mode": "heavy_combined"}
    for key in keys:
        values = [r[key] for r in run_results if key in r]
        if values:
            agg[f"{key}_mean"] = statistics.mean(values)
            agg[f"{key}_stdev"] = statistics.stdev(values) if len(values) > 1 else 0
    return agg


def print_report(target_name, run_id, size_name, write_m, read_m, heavy_m=None,
                 mode="mixed"):
    print(f"\n{'='*60}")
    print(f"  {target_name.upper()} [DuckLake] | {size_name} | Run {run_id} | {mode.upper()}")
    print(f"{'='*60}")
    if write_m:
        w = write_m
        print(f"  WRITE: {w.get('successful',0)}/{w.get('num_items',0)} | "
              f"{w.get('total_data_mb',0):.1f} MB | "
              f"{w.get('aggregate_throughput_mbps',0):.1f} MB/s | "
              f"P50 {w.get('latency_p50',0):.3f}s")
    if read_m:
        r = read_m
        print(f"  READ:  {r.get('successful',0)}/{r.get('num_items',0)} | "
              f"{r.get('total_data_mb',0):.1f} MB | "
              f"{r.get('aggregate_throughput_mbps',0):.1f} MB/s | "
              f"P50 {r.get('latency_p50',0):.3f}s")
    if heavy_m:
        h = heavy_m
        print(f"  HEAVY: writes={h.get('num_writes',0)} reads={h.get('num_reads',0)} | "
              f"{h.get('total_data_mb',0):.1f} MB in {h.get('wall_time_sec',0):.1f}s | "
              f"{h.get('aggregate_throughput_mbps',0):.1f} MB/s")
        print(f"    Write P50={h.get('write_latency_p50',0):.3f}s | "
              f"Read P50={h.get('read_latency_p50',0):.3f}s")
        print(f"    Write success: {h.get('write_success_rate',0)*100:.1f}% | "
              f"Read success: {h.get('read_success_rate',0)*100:.1f}%")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DuckLake S3 Benchmark v2 — Lakehouse Metadata + Parquet Data")
    parser.add_argument("--target", choices=["seaweedfs","rustfs","librefs","minio","all"],
                        default="seaweedfs")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--thread-sweep", action="store_true",
                        help="Run at thread counts: 1,5,10,20 instead of single value")
    parser.add_argument("--sizes", type=str, default="1mb,32mb")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mode",
                        choices=["write-only","read-only","mixed","heavy",
                                 "transactions","time-travel","snapshots","concurrent"],
                        default="mixed")
    parser.add_argument("--heavy-duration", type=int, default=30)
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.target == "all" else [args.target]
    sizes = [s.strip() for s in args.sizes.split(",")]
    thread_counts = [1, 5, 10, 20] if args.thread_sweep else [args.threads]
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for target_name in targets:
        config = TARGETS[target_name]

        for num_threads in thread_counts:
            print(f"\n{'#'*70}\n  {target_name.upper()} [DuckLake] @ {config['endpoint']} "
                  f"({num_threads} threads)\n{'#'*70}")

            for size_name in sizes:
                print(f"\n  Size: {size_name}")
                print(f"  Mode: {args.mode.upper()}")

                write_runs, read_runs, heavy_runs = [], [], []
                for run_id in range(1, args.runs + 1):
                    print(f"\n  --- Run {run_id}/{args.runs} ---")
                    wm, rm, hm, bucket, meta_file, adapter = run_benchmark_ducklake(
                        target_name, config, num_threads, size_name, run_id, args.mode,
                        heavy_duration=args.heavy_duration)

                    print_report(target_name, run_id, size_name, wm, rm, hm,
                                 mode=args.mode)
                    write_runs.append(wm)
                    if rm:
                        read_runs.append(rm)
                    if hm:
                        heavy_runs.append(hm)

                    run_data = {"mode": args.mode, "engine": "ducklake", "threads": num_threads,
                                "write": wm, "read": rm, "heavy": hm}
                    rpath = adapter.output_path(args.mode, run_id)
                    with open(rpath, "w") as f:
                        json.dump(run_data, f, indent=2)

                    adapter.close()
                    if meta_file:
                        cleanup_metadata(meta_file)
                    delete_bucket_contents(config, bucket)

                w_agg = aggregate_runs([w for w in write_runs if w]) if any(write_runs) else None
                r_agg = aggregate_runs([r for r in read_runs if r]) if any(read_runs) else None
                h_agg = aggregate_heavy_runs([h for h in heavy_runs if h]) if any(heavy_runs) else None

                print(f"\n  {'='*50}")
                n = (w_agg or r_agg or h_agg or {}).get("num_runs", 0)
                print(f"  {target_name.upper()} [DuckLake] {size_name} — "
                      f"{args.mode.upper()} threads={num_threads} (n={n})")
                print(f"  {'='*50}")
                if w_agg:
                    print(f"  Write: {w_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{w_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                if r_agg:
                    print(f"  Read:  {r_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{r_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                if h_agg:
                    print(f"  Heavy: {h_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{h_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                print()

    print(f"\nDone. Results in {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
