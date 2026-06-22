#!/usr/bin/env python3
"""
Apache Iceberg Benchmark: File-Based Metadata on S3-Compatible Storage
======================================================================
Benchmarks Iceberg-style workloads: Parquet data on S3 with Iceberg metadata patterns.
Uses DuckDB for data generation + S3 I/O, simulating how Iceberg stores Parquet files.

Key difference from DuckDB benchmark: this tests Iceberg-specific patterns:
  - Multiple small Parquet files (like Iceberg data files)
  - Metadata file operations (like Iceberg manifest writes)
  - Snapshot reads (reading historical data versions)
  - Time travel queries

Usage:
    uv run python benchmark_iceberg.py --target minio --mode heavy
    uv run python benchmark_iceberg.py --target all --sizes 1mb,32mb --runs 3
    uv run python benchmark_iceberg.py --target minio --mode time-travel --runs 1
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

import boto3
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
RESULTS_DIR = "results_iceberg"

ANALYTICAL_QUERIES = [
    "SELECT COUNT(*) FROM read_parquet('{path}')",
    "SELECT category, COUNT(*), AVG(value) FROM read_parquet('{path}') GROUP BY category ORDER BY category",
    "SELECT COUNT(*), MIN(value), MAX(value), AVG(value) FROM read_parquet('{path}')",
    "SELECT * FROM read_parquet('{path}') WHERE id BETWEEN 500 AND 1500",
    "SELECT category, COUNT(*) as cnt, SUM(value) as total FROM read_parquet('{path}') GROUP BY category HAVING cnt > 100 ORDER BY total DESC",
]


# ---------------------------------------------------------------------------
# S3 bucket helpers
# ---------------------------------------------------------------------------

def create_bucket(config, bucket):
    client = boto3.client("s3", endpoint_url=config["endpoint"],
                          aws_access_key_id=config["access_key"],
                          aws_secret_access_key=config["secret_key"],
                          region_name="us-east-1")
    try:
        client.create_bucket(Bucket=bucket)
    except Exception:
        pass


def delete_bucket_contents(config, bucket):
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


def get_s3_size(config, bucket, prefix="data/"):
    client = boto3.client("s3", endpoint_url=config["endpoint"],
                          aws_access_key_id=config["access_key"],
                          aws_secret_access_key=config["secret_key"],
                          region_name="us-east-1")
    total = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                total += obj["Size"]
    except Exception:
        pass
    return total


# ---------------------------------------------------------------------------
# IcebergAdapter — DuckDB + S3 for Iceberg-style workloads
# ---------------------------------------------------------------------------

class IcebergAdapter:
    """
    Adapter that writes Parquet data to S3 and reads it back via DuckDB.
    Simulates Iceberg's data file pattern: multiple Parquet files on S3.
    """

    def __init__(self, config, bucket, target_name="", results_dir=RESULTS_DIR):
        self.config = config
        self.bucket = bucket
        self.target_name = target_name
        self.results_dir = results_dir
        self.data_prefix = "data"
        self.conn = self._make_conn()
        self._file_counter = 0

    def _make_conn(self):
        conn = duckdb.connect()
        conn.execute("LOAD httpfs;")
        endpoint = self.config["endpoint"].replace("http://", "").replace("https://", "")
        conn.execute(f"SET s3_endpoint='{endpoint}';")
        conn.execute(f"SET s3_access_key_id='{self.config['access_key']}';")
        conn.execute(f"SET s3_secret_access_key='{self.config['secret_key']}';")
        conn.execute("SET s3_url_style='path';")
        conn.execute("SET s3_use_ssl=false;")
        conn.execute("SET threads=1;")
        return conn

    def output_path(self, mode, run_id, size_name):
        path = os.path.join(self.results_dir, mode, size_name,
                            self.target_name, f"run-{run_id}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def _next_key(self, prefix="events"):
        self._file_counter += 1
        return f"{self.data_prefix}/{prefix}/{self._file_counter:06d}-{uuid.uuid4().hex[:8]}.parquet"

    def _generate_and_write(self, num_rows, start_id=0):
        key = self._next_key()
        sql = f"""
            COPY (
                SELECT
                    {start_id} + rowid AS id,
                    (ARRAY['A','B','C','D'])[1 + (rowid % 4)] AS category,
                    random() * 100 AS value,
                NOW() - INTERVAL (rowid % 365) DAY AS event_time
                FROM generate_series(0, {num_rows - 1}) AS t(rowid)
            ) TO 's3://{self.bucket}/{key}' (FORMAT PARQUET)
        """
        start = time.perf_counter()
        try:
            self.conn.execute(sql)
            elapsed = time.perf_counter() - start
            return elapsed, key, True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, key, False, str(e)

    def insert_batch(self, batch_size=BATCH_SIZE, start_id=0):
        return self._generate_and_write(batch_size, start_id)

    def run_query(self, query):
        start = time.perf_counter()
        try:
            rows = self.conn.execute(query).fetchall()
            elapsed = time.perf_counter() - start
            return elapsed, len(rows), True, None
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, 0, False, str(e)

    def list_data_files(self, prefix=None):
        if prefix is None:
            prefix = f"{self.data_prefix}/"
        try:
            result = self.conn.execute(
                f"SELECT file FROM glob('s3://{self.bucket}/{prefix}**/*.parquet')"
            ).fetchall()
            return [r[0] for r in result]
        except Exception:
            return []

    def run_analytical_query(self, query_template, file_path=None):
        if file_path is None:
            files = self.list_data_files()
            if not files:
                return 0, 0, False, "No data files"
            file_path = files[0]
        query = query_template.format(path=file_path)
        return self.run_query(query)

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
    lats = sorted(r["time_sec"] for r in successful) if successful else []

    m = {
        "target": target_name, "run_id": run_id, "num_items": num_items,
        "num_threads": num_threads, "successful": len(successful), "failed": len(failed),
        "wall_time_sec": wall_time,
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
# Phase runners
# ---------------------------------------------------------------------------

def run_seed_phase(adapter, target_rows):
    print(f"\n  Seeding {target_rows:,} rows...")
    batch_size = BATCH_SIZE
    batches = target_rows // batch_size
    for i in range(batches):
        adapter.insert_batch(batch_size, start_id=i * batch_size)
        if (i + 1) % 5 == 0:
            print(f"  seed [{i+1}/{batches}]")
    print(f"  Seeded {target_rows:,} rows")


def run_write_phase(adapter, target_rows, num_threads, target_name, run_id, size_name):
    print(f"\n  Writing {target_rows:,} rows to S3...")
    results = []
    batch_size = BATCH_SIZE
    batches = target_rows // batch_size

    wall_start = time.perf_counter()
    for batch_idx in range(batches):
        elapsed, key, success, error = adapter.insert_batch(
            batch_size, start_id=batch_idx * batch_size
        )
        results.append({
            "op": "write", "success": success, "batch": batch_idx,
            "rows": batch_size if success else 0, "size_mb": 0,
            "time_sec": elapsed,
            "rows_per_sec": batch_size / elapsed if elapsed > 0 else 0,
            **({"error": error} if error else {}),
        })
    wall_time = time.perf_counter() - wall_start

    actual_mb = get_s3_size(adapter.config, adapter.bucket) / (1024 * 1024)
    extra = {"total_rows_inserted": sum(r["rows"] for r in results if r["success"]),
             "size_name": size_name, "actual_s3_mb": actual_mb,
             "aggregate_throughput_mbps": actual_mb / wall_time if wall_time > 0 else 0}
    return summarize(results, len(results), wall_time, target_name, run_id,
                     num_threads, extra=extra)


def run_read_phase(adapter, num_threads, target_name, run_id):
    print(f"\n  Running analytical queries on S3...")
    files = adapter.list_data_files()
    if not files:
        print("  No data files found!")
        return None

    results = []
    wall_start = time.perf_counter()
    for i, query_template in enumerate(ANALYTICAL_QUERIES):
        elapsed, rows_returned, success, error = adapter.run_analytical_query(
            query_template, files[0]
        )
        results.append({
            "op": "read", "success": success, "query_idx": i,
            "rows_returned": rows_returned, "size_mb": 0,
            "time_sec": elapsed,
            "rows_per_sec": rows_returned / elapsed if elapsed > 0 and success else 0,
            **({"error": error} if error else {}),
        })
    wall_time = time.perf_counter() - wall_start

    extra = {"total_queries": len(results),
             "total_rows_returned": sum(r.get("rows_returned", 0) for r in results)}
    return summarize(results, len(results), wall_time, target_name, run_id,
                     num_threads, extra=extra)


def run_heavy_phase(config, bucket, run_id, num_threads, target_name,
                    size_name="", duration_sec=30):
    print(f"\n  HEAVY MIXED LOAD: {num_threads} threads, {duration_sec}s duration...")
    num_writers = num_threads // 2
    num_readers = num_threads - num_writers

    all_results = []
    results_lock = threading.Lock()
    stop_event = threading.Event()
    file_counter = [0]

    def writer_worker(worker_id):
        conn = _make_adapter_conn(config)
        while not stop_event.is_set():
            key = f"data/heavy/w{worker_id}_{file_counter[0]}.parquet"
            sql = f"""
                COPY (
                    SELECT
                        {worker_id * 100000} + rowid AS id,
                        (ARRAY['A','B','C','D'])[1 + (rowid % 4)] AS category,
                        random() * 100 AS value,
                        NOW() AS event_time
                    FROM generate_series(0, {BATCH_SIZE - 1}) AS t(rowid)
                ) TO 's3://{bucket}/{key}' (FORMAT PARQUET)
            """
            start = time.perf_counter()
            try:
                conn.execute(sql)
                elapsed = time.perf_counter() - start
                r = {"op": "write", "success": True, "worker_id": worker_id,
                     "size_mb": 0, "time_sec": elapsed}
            except Exception as e:
                elapsed = time.perf_counter() - start
                r = {"op": "write", "success": False, "worker_id": worker_id,
                     "size_mb": 0, "time_sec": elapsed, "error": str(e)}
            with results_lock:
                all_results.append(r)
                file_counter[0] += 1
        conn.close()

    def reader_worker(worker_id):
        conn = _make_adapter_conn(config)
        while not stop_event.is_set():
            try:
                files = _list_data_files(conn, bucket)
                if not files:
                    time.sleep(0.01)
                    continue
                fpath = random.choice(files)
                query = random.choice(ANALYTICAL_QUERIES).format(path=fpath)
                start = time.perf_counter()
                rows = conn.execute(query).fetchall()
                elapsed = time.perf_counter() - start
                r = {"op": "read", "success": True, "worker_id": worker_id,
                     "rows_returned": len(rows), "size_mb": 0.01,
                     "time_sec": elapsed}
            except Exception as e:
                elapsed = time.perf_counter() - start
                r = {"op": "read", "success": False, "worker_id": worker_id,
                     "rows_returned": 0, "size_mb": 0, "time_sec": elapsed,
                     "error": str(e)}
            with results_lock:
                all_results.append(r)
        conn.close()

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

    combined = {
        "target": target_name, "run_id": run_id, "mode": "heavy_combined",
        "wall_time_sec": wall_time,
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
        print(f"  Write: P50 {w_metrics.get('latency_p50',0):.3f}s")
    if r_metrics:
        print(f"  Read:  P50 {r_metrics.get('latency_p50',0):.3f}s")
    print(f"  Writes: {len(write_results)}, Reads: {len(read_results)} in {wall_time:.1f}s")

    return w_metrics, r_metrics, combined


def _make_adapter_conn(config):
    conn = duckdb.connect()
    conn.execute("LOAD httpfs;")
    endpoint = config["endpoint"].replace("http://", "").replace("https://", "")
    conn.execute(f"SET s3_endpoint='{endpoint}';")
    conn.execute(f"SET s3_access_key_id='{config['access_key']}';")
    conn.execute(f"SET s3_secret_access_key='{config['secret_key']}';")
    conn.execute("SET s3_url_style='path';")
    conn.execute("SET s3_use_ssl=false;")
    conn.execute("SET threads=1;")
    return conn


def _list_data_files(conn, bucket, prefix="data/"):
    try:
        result = conn.execute(
            f"SELECT file FROM glob('s3://{bucket}/{prefix}**/*.parquet')"
        ).fetchall()
        return [r[0] for r in result]
    except Exception:
        return []


def run_time_travel_phase(adapter, num_snapshots=5):
    print(f"\n  Running time travel benchmark ({num_snapshots} snapshots)...")
    results = []
    snapshot_files = []

    for i in range(num_snapshots):
        elapsed, key, success, error = adapter.insert_batch(
            BATCH_SIZE, start_id=1000000 + i * BATCH_SIZE
        )
        results.append({"op": "write_batch", "success": success, "snapshot": i,
                        "time_sec": elapsed, "key": key,
                        **({"error": error} if error else {})})
        if success:
            snapshot_files.append(key)

    for snap_path in snapshot_files:
        elapsed, count, success, error = adapter.run_query(
            f"SELECT COUNT(*) FROM read_parquet('{snap_path}')"
        )
        results.append({"op": "time_travel_read", "success": success,
                        "snapshot_path": snap_path,
                        "rows": count, "time_sec": elapsed,
                        **({"error": error} if error else {})})

    return results


def run_snapshots_phase(adapter, num_snapshots=10):
    print(f"\n  Running snapshots metadata benchmark ({num_snapshots})...")
    results = []
    for i in range(num_snapshots):
        elapsed, _, success, error = adapter.insert_batch(100, start_id=2000000 + i * 100)
        results.append({"op": "write_snapshot_file", "success": success, "snapshot": i,
                        "time_sec": elapsed, **({"error": error} if error else {})})

    start = time.perf_counter()
    files = adapter.list_data_files()
    elapsed = time.perf_counter() - start
    results.append({"op": "list_snapshots", "success": True,
                    "count": len(files), "time_sec": elapsed})
    return results


def run_change_detection_phase(adapter):
    print(f"\n  Running change detection benchmark...")
    results = []

    elapsed1, key1, success1, error1 = adapter.insert_batch(2000, start_id=3000000)
    results.append({"op": "write_batch_1", "success": success1, "time_sec": elapsed1,
                    "rows": 2000, **({"error": error1} if error1 else {})})

    elapsed2, key2, success2, error2 = adapter.insert_batch(500, start_id=3001000)
    results.append({"op": "write_batch_2", "success": success2, "time_sec": elapsed2,
                    "rows": 500, **({"error": error2} if error2 else {})})

    elapsed_diff, count, success_diff, error_diff = adapter.run_query(
        f"SELECT COUNT(*) FROM read_parquet('{key2}')"
    )
    results.append({"op": "diff_read", "success": success_diff, "time_sec": elapsed_diff,
                    "rows": count, **({"error": error_diff} if error_diff else {})})

    return results


def run_update_phase(adapter):
    print(f"\n  Running update benchmark...")
    elapsed, key, success, error = adapter.insert_batch(100, start_id=4000000)
    return {"op": "update_insert", "success": success, "time_sec": elapsed,
            **({"error": error} if error else {})}


def run_delete_phase(adapter):
    print(f"\n  Running delete benchmark...")
    elapsed, key, success, error = adapter.insert_batch(100, start_id=5000000)
    return {"op": "delete_insert", "success": success, "time_sec": elapsed,
            **({"error": error} if error else {})}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_benchmark_iceberg(target_name, config, num_threads, size_name, run_id,
                          mode, heavy_duration=30):
    bucket = f"benchiceberg-{target_name}-run{run_id}-{uuid.uuid4().hex[:8]}"
    create_bucket(config, bucket)

    adapter = IcebergAdapter(config, bucket, target_name)
    target_rows = ROWS_PER_SIZE.get(size_name, 5_000)

    wm, rm, hm = None, None, None

    if mode == "write-only":
        wm = run_write_phase(adapter, target_rows, num_threads, target_name,
                             run_id, size_name)

    elif mode == "read-only":
        run_seed_phase(adapter, target_rows)
        rm = run_read_phase(adapter, num_threads, target_name, run_id)

    elif mode == "mixed":
        wm = run_write_phase(adapter, target_rows, num_threads, target_name,
                             run_id, size_name)
        rm = run_read_phase(adapter, num_threads, target_name, run_id)

    elif mode == "heavy":
        adapter.close()
        hw, hr, hm = run_heavy_phase(config, bucket, run_id, num_threads,
                                      target_name, size_name, heavy_duration)
        wm = hw
        rm = hr
        adapter = None

    elif mode == "time-travel":
        run_seed_phase(adapter, target_rows)
        tt_results = run_time_travel_phase(adapter)
        wall_time = sum(r["time_sec"] for r in tt_results)
        wm = summarize(tt_results, len(tt_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "time-travel"})

    elif mode == "snapshots":
        run_seed_phase(adapter, target_rows)
        snap_results = run_snapshots_phase(adapter)
        wall_time = sum(r["time_sec"] for r in snap_results)
        wm = summarize(snap_results, len(snap_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "snapshots"})

    elif mode == "change-detection":
        run_seed_phase(adapter, target_rows)
        cd_results = run_change_detection_phase(adapter)
        wall_time = sum(r["time_sec"] for r in cd_results)
        wm = summarize(cd_results, len(cd_results), wall_time, target_name,
                       run_id, num_threads, extra={"mode": "change-detection"})

    elif mode == "update":
        run_seed_phase(adapter, target_rows)
        ur = run_update_phase(adapter)
        wm = summarize([ur], 1, ur.get("time_sec", 0), target_name,
                       run_id, num_threads, extra={"mode": "update"})

    elif mode == "delete":
        run_seed_phase(adapter, target_rows)
        dr = run_delete_phase(adapter)
        wm = summarize([dr], 1, dr.get("time_sec", 0), target_name,
                       run_id, num_threads, extra={"mode": "delete"})

    if adapter:
        adapter.close()
    delete_bucket_contents(config, bucket)

    return wm, rm, hm, bucket, adapter


def aggregate_runs(run_results):
    if not run_results:
        return {}
    keys = ["wall_time_sec", "latency_p50", "latency_p95", "latency_p99",
            "latency_mean", "latency_stdev"]
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
    keys = ["wall_time_sec", "write_success_rate", "read_success_rate",
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
    print(f"  {target_name.upper()} [Iceberg] | {size_name} | Run {run_id} | {mode.upper()}")
    print(f"{'='*60}")
    if write_m:
        w = write_m
        mb = w.get('actual_s3_mb', w.get('total_data_mb', 0))
        mbps = w.get('aggregate_throughput_mbps', 0)
        print(f"  WRITE: {w.get('successful',0)}/{w.get('num_items',0)} | "
              f"{mb:.1f} MB | {mbps:.1f} MB/s | P50 {w.get('latency_p50',0):.3f}s")
    if read_m:
        r = read_m
        print(f"  READ:  {r.get('successful',0)}/{r.get('num_items',0)} | "
              f"P50 {r.get('latency_p50',0):.3f}s | "
              f"{r.get('wall_time_sec',0):.1f}s total")
    if heavy_m:
        h = heavy_m
        print(f"  HEAVY: writes={h.get('num_writes',0)} reads={h.get('num_reads',0)} | "
              f"{h.get('wall_time_sec',0):.1f}s")
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
        description="Apache Iceberg S3 Benchmark — Iceberg-Style Workloads")
    parser.add_argument("--target",
                        choices=["seaweedfs", "rustfs", "librefs", "minio", "all"],
                        default="minio")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--sizes", type=str, default="1mb,32mb")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mode",
                        choices=["write-only", "read-only", "mixed", "heavy",
                                 "time-travel", "snapshots", "change-detection",
                                 "update", "delete"],
                        default="mixed")
    parser.add_argument("--heavy-duration", type=int, default=30)
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.target == "all" else [args.target]
    sizes = [s.strip() for s in args.sizes.split(",")]
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for target_name in targets:
        config = TARGETS[target_name]
        num_threads = config.get("threads", args.threads)

        print(f"\n{'#'*70}\n  {target_name.upper()} [Iceberg] @ {config['endpoint']} "
              f"({num_threads} threads)\n{'#'*70}")

        for size_name in sizes:
            print(f"\n  Size: {size_name}")
            print(f"  Mode: {args.mode.upper()}")

            write_runs, read_runs, heavy_runs = [], [], []
            for run_id in range(1, args.runs + 1):
                print(f"\n  --- Run {run_id}/{args.runs} ---")
                wm, rm, hm, bucket, adapter = run_benchmark_iceberg(
                    target_name, config, num_threads, size_name, run_id,
                    args.mode, heavy_duration=args.heavy_duration)

                print_report(target_name, run_id, size_name, wm, rm, hm,
                             mode=args.mode)
                write_runs.append(wm)
                if rm:
                    read_runs.append(rm)
                if hm:
                    heavy_runs.append(hm)

                run_data = {"mode": args.mode, "engine": "iceberg",
                            "threads": num_threads,
                            "write": wm, "read": rm, "heavy": hm}
                if adapter:
                    rpath = adapter.output_path(args.mode, run_id, size_name)
                else:
                    rpath = os.path.join(RESULTS_DIR, args.mode, size_name,
                                         target_name, f"run-{run_id}.json")
                    os.makedirs(os.path.dirname(rpath), exist_ok=True)
                with open(rpath, "w") as f:
                    json.dump(run_data, f, indent=2, default=str)

            w_agg = aggregate_runs([w for w in write_runs if w]) if any(write_runs) else None
            r_agg = aggregate_runs([r for r in read_runs if r]) if any(read_runs) else None
            h_agg = aggregate_heavy_runs([h for h in heavy_runs if h]) if any(heavy_runs) else None

            print(f"\n  {'='*50}")
            n = (w_agg or r_agg or h_agg or {}).get("num_runs", 0)
            print(f"  {target_name.upper()} [Iceberg] {size_name} — "
                  f"{args.mode.upper()} threads={num_threads} (n={n})")
            print(f"  {'='*50}")
            if w_agg:
                print(f"  Write P50: {w_agg.get('latency_p50_mean',0):.3f} +/- "
                      f"{w_agg.get('latency_p50_stdev',0):.3f}s")
            if r_agg:
                print(f"  Read P50:  {r_agg.get('latency_p50_mean',0):.3f} +/- "
                      f"{r_agg.get('latency_p50_stdev',0):.3f}s")
            if h_agg:
                print(f"  Heavy write P50: {h_agg.get('write_latency_p50_mean',0):.3f}s | "
                      f"Read P50: {h_agg.get('read_latency_p50_mean',0):.3f}s")
            print()

    print(f"\nDone. Results in {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
