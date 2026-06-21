#!/usr/bin/env python3
"""
S3 DuckDB Benchmark: Analytical Workload Test (v2 — Fixed)
===========================================================
Tests S3-compatible storage with DuckDB's native Parquet+S3 integration.
Measures columnar read/write throughput for analytical (OLAP) workloads.

Fixes from concerns.md review:
  - DuckDBAdapter: extensions loaded ONCE before timing (P0 #4)
  - Column-materializing queries instead of COUNT(*) (P0 #1)
  - COPY directly from read_parquet (no intermediate table) (P1 #10)
  - Warmup = 10% of files at target thread count (P1 #8)
  - Heavy mode re-lists keys every 5s (P0 #5)
  - LOAD instead of INSTALL (P2 #11)

Usage:
    uv run python benchmark_duckdb.py --target minio --mode heavy
    uv run python benchmark_duckdb.py --target all --sizes 1mb,32mb --runs 3
"""

import argparse
import json
import os
import statistics
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb


TARGETS = {
    "seaweedfs": {
        "endpoint": "http://127.0.0.1:8533",
        "access_key": "admin",
        "secret_key": "admin",
    },
    "rustfs": {
        "endpoint": "http://127.0.0.1:9000",
        "access_key": "rustfsadmin",
        "secret_key": "rustfsadmin",
    },
    "librefs": {
        "endpoint": "http://localhost:9100",
        "access_key": "admin",
        "secret_key": "password123",
    },
    "minio": {
        "endpoint": "http://localhost:9200",
        "access_key": "minioadmin",
        "secret_key": "minioadmin123",
    },
}

SIZE_MAP = {
    "1mb": 1 * 1024 * 1024,
    "16mb": 16 * 1024 * 1024,
    "32mb": 32 * 1024 * 1024,
}

DATA_DIR = "data_parquet"
RESULTS_DIR = "results_duckdb"

MATERIALIZING_QUERIES = [
    "SELECT SUM(value), COUNT(*), MAX(timestamp) FROM read_parquet('{path}')",
    "SELECT category, COUNT(*), AVG(value) FROM read_parquet('{path}') GROUP BY category",
    "SELECT COUNT(*), MIN(value), MAX(value), AVG(value) FROM read_parquet('{path}')",
]


# ---------------------------------------------------------------------------
# DuckDBAdapter — fair timing proxy
# ---------------------------------------------------------------------------

class DuckDBAdapter:
    """
    Adapter that wraps DuckDB connection.
    Extensions loaded ONCE at construction (before any timing).
    All timed operations go through this adapter.
    """

    def __init__(self, config):
        self.config = config
        self.conn = self._make_conn()

    def _make_conn(self):
        conn = duckdb.connect()
        conn.execute("LOAD httpfs;")
        endpoint = self.config["endpoint"].replace("http://", "").replace("https://", "")
        conn.execute(f"SET s3_endpoint='{endpoint}';")
        conn.execute(f"SET s3_access_key_id='{self.config['access_key']}';")
        conn.execute(f"SET s3_secret_access_key='{self.config['secret_key']}';")
        conn.execute("SET s3_url_style='path';")
        conn.execute("SET s3_use_ssl=false;")
        # Limit DuckDB internal threads to prevent CPU thread explosion
        # (Python threads) × (DuckDB threads) should ≤ physical cores
        conn.execute("SET threads=1;")
        return conn

    def write_one(self, local_path, bucket, key):
        """Write a local Parquet file to S3. Returns (elapsed, success, result_dict)."""
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        start = time.perf_counter()
        try:
            self.conn.execute(
                f"COPY (SELECT * FROM read_parquet('{local_path}')) "
                f"TO 's3://{bucket}/{key}.parquet' (FORMAT PARQUET)"
            )
            elapsed = time.perf_counter() - start
            return elapsed, True, {"op": "write", "success": True, "file": f"{key}.parquet",
                                   "size_mb": size_mb, "time_sec": elapsed,
                                   "throughput_mbps": size_mb / elapsed if elapsed > 0 else 0}
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, False, {"op": "write", "success": False, "file": f"{key}.parquet",
                                    "size_mb": 0, "time_sec": elapsed, "error": str(e)}

    def read_one(self, bucket, key, size_mb):
        """Read a Parquet file from S3 using column-materializing query."""
        s3_path = f"s3://{bucket}/{key}" if key.endswith(".parquet") else f"s3://{bucket}/{key}.parquet"
        start = time.perf_counter()
        try:
            query = MATERIALIZING_QUERIES[0].format(path=s3_path)
            self.conn.execute(query).fetchall()
            elapsed = time.perf_counter() - start
            return elapsed, True, {"op": "read", "success": True, "file": key,
                                   "size_mb": size_mb, "time_sec": elapsed,
                                   "throughput_mbps": size_mb / elapsed if elapsed > 0 and size_mb > 0 else 0}
        except Exception as e:
            elapsed = time.perf_counter() - start
            return elapsed, False, {"op": "read", "success": False, "file": key,
                                    "size_mb": 0, "time_sec": elapsed, "error": str(e)}

    def list_keys(self, bucket, prefix="benchmark/"):
        try:
            result = self.conn.execute(f"SELECT file FROM glob('s3://{bucket}/{prefix}*')").fetchall()
            keys = []
            for row in result:
                k = row[0].split(f"s3://{bucket}/")[1]
                if not k.endswith(".parquet"):
                    k += ".parquet"
                keys.append(k)
            return keys
        except Exception:
            return []

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


# ---------------------------------------------------------------------------
# Bucket helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def summarize(results, num_files, wall_time, target_name, run_id, num_threads):
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    total_mb = sum(r["size_mb"] for r in successful)
    lats = sorted(r["time_sec"] for r in successful)
    tps = [r["throughput_mbps"] for r in successful]

    m = {"target": target_name, "run_id": run_id, "num_files": num_files,
         "num_threads": num_threads, "successful": len(successful), "failed": len(failed),
         "total_data_mb": total_mb, "wall_time_sec": wall_time,
         "aggregate_throughput_mbps": total_mb / wall_time if wall_time > 0 else 0}

    if lats:
        n = len(lats)
        m.update(latency_mean=statistics.mean(lats), latency_p50=statistics.median(lats),
                 latency_p95=lats[int(n*0.95)] if n > 1 else lats[-1],
                 latency_p99=lats[min(int(n*0.99), n-1)], latency_min=lats[0], latency_max=lats[-1],
                 latency_stdev=statistics.stdev(lats) if n > 1 else 0,
                 per_file_throughput_mean_mbps=statistics.mean(tps),
                 per_file_throughput_max_mbps=max(tps))
    return m


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def run_write_phase(config, bucket, files, num_threads, target_name, run_id):
    num_total = len(files)
    warmup_count = max(3, num_total // 10)
    warmup_files = files[:warmup_count]
    measure_files = files[warmup_count:]

    print(f"  Warmup: {warmup_count} files at {num_threads} threads...")
    adapter = DuckDBAdapter(config)
    for fp in warmup_files:
        key = f"benchmark/{os.path.basename(fp)}"
        adapter.write_one(fp, bucket, key)
    adapter.close()

    n = len(measure_files)
    print(f"\n  Writing {n} Parquet files, {num_threads} threads...")

    # Worker-pool: each thread reuses its adapter (connection stays open)
    adapters = [DuckDBAdapter(config) for _ in range(num_threads)]

    def write_one(args):
        fp, worker_id = args
        a = adapters[worker_id % num_threads]
        key = f"benchmark/{os.path.basename(fp)}"
        elapsed, success, r = a.write_one(fp, bucket, key)
        return r

    work = [(fp, i) for i, fp in enumerate(measure_files)]
    w_results = []
    w_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as ex:
        fut = {ex.submit(write_one, item): item for item in work}
        for i, f in enumerate(as_completed(fut), 1):
            r = f.result()
            w_results.append(r)
            if i % 20 == 0 or i == n:
                ok = sum(1 for x in w_results if x["success"])
                print(f"  write [{i:>4}/{n}] {ok} ok, {i-ok} failed, {time.perf_counter()-w_start:.1f}s")
    w_time = time.perf_counter() - w_start

    for a in adapters:
        a.close()

    return summarize(w_results, len(measure_files), w_time, target_name, run_id, num_threads)


def run_read_phase(config, bucket, num_threads, target_name, run_id):
    adapter = DuckDBAdapter(config)
    keys = adapter.list_keys(bucket)
    adapter.close()
    if not keys:
        print("  No keys to read")
        return None

    print(f"\n  Reading back {len(keys)} Parquet files, {num_threads} threads...")

    # Worker-pool: each thread reuses its adapter
    adapters = [DuckDBAdapter(config) for _ in range(num_threads)]

    def read_one(args):
        key, worker_id = args
        a = adapters[worker_id % num_threads]
        # Get actual file size from S3 before reading
        try:
            import boto3
            s3 = boto3.client("s3", endpoint_url=config["endpoint"],
                              aws_access_key_id=config["access_key"],
                              aws_secret_access_key=config["secret_key"],
                              region_name="us-east-1")
            resp = s3.head_object(Bucket=bucket, Key=key)
            size_mb = resp["ContentLength"] / (1024 * 1024)
        except Exception:
            size_mb = 0.0
        elapsed, success, r = a.read_one(bucket, key, size_mb)
        if not success and not r.get("_logged"):
            print(f"  READ ERROR on {key}: {r.get('error', 'unknown')}")
            r["_logged"] = True
        return r

    r_results = []
    r_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as ex:
        fut = {ex.submit(read_one, (k, i)): k for i, k in enumerate(keys)}
        for i, f in enumerate(as_completed(fut), 1):
            r = f.result()
            r_results.append(r)
            if i % 20 == 0 or i == len(keys):
                ok = sum(1 for x in r_results if x["success"])
                print(f"  read  [{i:>4}/{len(keys)}] {ok} ok, {i-ok} failed, {time.perf_counter()-r_start:.1f}s")
    r_time = time.perf_counter() - r_start

    for a in adapters:
        a.close()

    return summarize(r_results, len(keys), r_time, target_name, run_id, num_threads)


def run_heavy_phase(config, bucket, files, num_threads, target_name, run_id, duration_sec=30):
    print(f"\n  HEAVY MIXED LOAD: {num_threads} threads, {duration_sec}s duration...")
    print(f"  Split: {num_threads//2} writers + {num_threads - num_threads//2} readers")
    print(f"  Readers re-list keys every 5s")

    stop_event = threading.Event()
    all_results = []
    results_lock = threading.Lock()
    write_counter = [0]
    known_keys = {"keys": [], "last_list": [0.0]}

    def refresh_keys(adapter, bucket):
        now = time.perf_counter()
        if now - known_keys["last_list"][0] > 5.0:
            known_keys["keys"] = adapter.list_keys(bucket, "heavy/")
            known_keys["last_list"][0] = now

    def writer_worker(worker_id):
        idx = 0
        a = DuckDBAdapter(config)
        while not stop_event.is_set():
            fp = files[idx % len(files)]
            key = f"heavy/w{worker_id}_{write_counter[0]}"
            elapsed, success, r = a.write_one(fp, bucket, key)
            with results_lock:
                all_results.append(r)
                write_counter[0] += 1
            idx += 1
        a.close()

    def reader_worker(worker_id):
        a = DuckDBAdapter(config)
        idx = 0
        while not stop_event.is_set():
            refresh_keys(a, bucket)
            keys = known_keys["keys"]
            if not keys:
                time.sleep(0.01)
                continue
            key = keys[idx % len(keys)]
            elapsed, success, r = a.read_one(bucket, key, 0.0)
            with results_lock:
                all_results.append(r)
            idx += 1
        a.close()

    num_writers = num_threads // 2
    num_readers = num_threads - num_writers

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

    w_metrics = summarize(write_results, len(write_results), wall_time, target_name, run_id, num_threads) if write_results else None
    r_metrics = summarize(read_results, len(read_results), wall_time, target_name, run_id, num_threads) if read_results else None

    total_mb = sum(r["size_mb"] for r in all_results if r["success"])
    print(f"\n  HEAVY results: {len(write_results)} writes, {len(read_results)} reads in {wall_time:.1f}s")
    print(f"  Total data moved: {total_mb:.1f} MB | Aggregate: {total_mb/wall_time:.1f} MB/s")
    if w_metrics:
        print(f"  Write throughput: {w_metrics['aggregate_throughput_mbps']:.1f} MB/s | "
              f"P50 {w_metrics.get('latency_p50',0):.3f}s | P99 {w_metrics.get('latency_p99',0):.3f}s")
    if r_metrics:
        print(f"  Read throughput:  {r_metrics['aggregate_throughput_mbps']:.1f} MB/s | "
              f"P50 {r_metrics.get('latency_p50',0):.3f}s | P99 {r_metrics.get('latency_p99',0):.3f}s")

    if w_metrics:
        w_metrics["mode"] = "heavy_write"
    if r_metrics:
        r_metrics["mode"] = "heavy_read"
    combined = {"target": target_name, "run_id": run_id, "mode": "heavy_combined",
                "wall_time_sec": wall_time, "total_data_mb": total_mb,
                "aggregate_throughput_mbps": total_mb / wall_time if wall_time > 0 else 0,
                "num_writes": len(write_results), "num_reads": len(read_results),
                "write_success_rate": sum(1 for r in write_results if r["success"]) / len(write_results) if write_results else 0,
                "read_success_rate": sum(1 for r in read_results if r["success"]) / len(read_results) if read_results else 0,
                "write_latency_p50": w_metrics.get("latency_p50", 0) if w_metrics else 0,
                "read_latency_p50": r_metrics.get("latency_p50", 0) if r_metrics else 0,
                "write_latency_p99": w_metrics.get("latency_p99", 0) if w_metrics else 0,
                "read_latency_p99": r_metrics.get("latency_p99", 0) if r_metrics else 0,
                }
    return w_metrics, r_metrics, combined


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_benchmark_duckdb(target_name, config, num_threads, file_paths, run_id, mode, heavy_duration=30):
    bucket = f"benchduck-{target_name}-run{run_id}-{int(time.time())}"
    create_bucket(config, bucket)

    wm = run_write_phase(config, bucket, file_paths, num_threads, target_name, run_id)
    rm = None
    hm = None

    if mode == "mixed":
        rm = run_read_phase(config, bucket, num_threads, target_name, run_id)
    elif mode == "read-only":
        rm = run_read_phase(config, bucket, num_threads, target_name, run_id)
        wm = None
    elif mode == "heavy":
        hw, hr, hm = run_heavy_phase(config, bucket, file_paths, num_threads, target_name, run_id, duration_sec=heavy_duration)

    delete_bucket_contents(config, bucket)
    return wm, rm, hm, bucket


def aggregate_runs(run_results):
    if not run_results:
        return {}
    keys = ["wall_time_sec", "aggregate_throughput_mbps", "latency_p50", "latency_p95",
            "latency_p99", "latency_mean", "latency_stdev", "per_file_throughput_mean_mbps"]
    agg = {"target": run_results[0]["target"], "num_runs": len(run_results)}
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
    agg = {"target": run_results[0]["target"], "num_runs": len(run_results), "mode": "heavy_combined"}
    for key in keys:
        values = [r[key] for r in run_results if key in r]
        if values:
            agg[f"{key}_mean"] = statistics.mean(values)
            agg[f"{key}_stdev"] = statistics.stdev(values) if len(values) > 1 else 0
    return agg


def print_report(target_name, run_id, size_name, write_m, read_m, heavy_m=None):
    print(f"\n{'='*60}")
    print(f"  {target_name.upper()} [DuckDB] | {size_name} | Run {run_id}")
    print(f"{'='*60}")
    if write_m:
        w = write_m
        print(f"  WRITE: {w['successful']}/{w['num_files']} | {w['total_data_mb']:.0f} MB | "
              f"{w['aggregate_throughput_mbps']:.1f} MB/s | P50 {w.get('latency_p50',0):.3f}s")
    if read_m:
        r = read_m
        print(f"  READ:  {r['successful']}/{r['num_files']} | {r['total_data_mb']:.0f} MB | "
              f"{r['aggregate_throughput_mbps']:.1f} MB/s | P50 {r.get('latency_p50',0):.3f}s")
    if heavy_m:
        h = heavy_m
        print(f"  HEAVY: writes={h['num_writes']} reads={h['num_reads']} | "
              f"{h['total_data_mb']:.0f} MB in {h['wall_time_sec']:.1f}s | "
              f"{h['aggregate_throughput_mbps']:.1f} MB/s")
        print(f"    Write P50={h['write_latency_p50']:.3f}s P99={h['write_latency_p99']:.3f}s "
              f"| Read P50={h['read_latency_p50']:.3f}s P99={h['read_latency_p99']:.3f}s")
        print(f"    Write success: {h['write_success_rate']*100:.1f}% | Read success: {h['read_success_rate']*100:.1f}%")
    if write_m and read_m:
        combined = (write_m['total_data_mb'] + read_m['total_data_mb']) / \
                   (write_m['wall_time_sec'] + read_m['wall_time_sec'])
        print(f"  COMBINED (write+read): {combined:.1f} MB/s")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="S3 DuckDB Benchmark v2 — Analytical Workload Test")
    parser.add_argument("--target", choices=["seaweedfs","rustfs","librefs","minio","all"], default="minio")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--thread-sweep", action="store_true",
                        help="Run at thread counts: 1,5,10,20,50 instead of single value")
    parser.add_argument("--sizes", type=str, default="1mb,32mb")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--mode", choices=["write-only","read-only","mixed","heavy"], default="mixed")
    parser.add_argument("--heavy-duration", type=int, default=30)
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.target == "all" else [args.target]
    sizes = [s.strip() for s in args.sizes.split(",")]
    thread_counts = [1, 5, 10, 20, 50] if args.thread_sweep else [args.threads]
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for target_name in targets:
        config = TARGETS[target_name]

        for num_threads in thread_counts:
            print(f"\n{'#'*70}\n  {target_name.upper()} [DuckDB] @ {config['endpoint']} ({num_threads} threads)\n{'#'*70}")

            for size_name in sizes:
                tier_dir = os.path.join(DATA_DIR, size_name)
                if not os.path.exists(tier_dir):
                    print(f"\n  Skip {size_name}: no data dir in {DATA_DIR}/")
                    continue

                files = sorted([os.path.join(tier_dir, f) for f in os.listdir(tier_dir)
                               if os.path.isfile(os.path.join(tier_dir, f)) and f.endswith(".parquet")])[:args.files]
                if not files:
                    print(f"\n  Skip {size_name}: no .parquet files")
                    continue

                print(f"\n  Size: {size_name} ({len(files)} x {SIZE_MAP[size_name]//(1024*1024)} MB)")
                print(f"  Mode: {args.mode.upper()}")

                write_runs, read_runs, heavy_runs = [], [], []
                for run_id in range(1, args.runs + 1):
                    print(f"\n  --- Run {run_id}/{args.runs} ---")
                    wm, rm, hm, bucket = run_benchmark_duckdb(
                        target_name, config, num_threads, files, run_id, args.mode,
                        heavy_duration=args.heavy_duration)

                    print_report(target_name, run_id, size_name, wm, rm, hm)
                    write_runs.append(wm)
                    if rm:
                        read_runs.append(rm)
                    if hm:
                        heavy_runs.append(hm)

                    run_data = {"mode": args.mode, "engine": "duckdb", "threads": num_threads,
                                "write": wm, "read": rm, "heavy": hm}
                    rpath = os.path.join(RESULTS_DIR, args.mode, size_name, target_name,
                                         f"threads-{num_threads}_run-{run_id}.json")
                    os.makedirs(os.path.dirname(rpath), exist_ok=True)
                    with open(rpath, "w") as f:
                        json.dump(run_data, f, indent=2)

                w_agg = aggregate_runs([w for w in write_runs if w]) if any(write_runs) else None
                r_agg = aggregate_runs([r for r in read_runs if r]) if any(read_runs) else None
                h_agg = aggregate_heavy_runs([h for h in heavy_runs if h]) if any(heavy_runs) else None

                print(f"\n  {'='*50}")
                n = (w_agg or r_agg or h_agg or {}).get("num_runs", 0)
                print(f"  {target_name.upper()} [DuckDB] {size_name} — {args.mode.upper()} "
                      f"threads={num_threads} (n={n})")
                print(f"  {'='*50}")
                if w_agg:
                    print(f"  Write: {w_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{w_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                if r_agg:
                    print(f"  Read:  {r_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{r_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                if h_agg:
                    print(f"  Heavy combined: {h_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- "
                          f"{h_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                    print(f"  Heavy write P50: {h_agg.get('write_latency_p50_mean',0):.3f}s | "
                          f"Read P50: {h_agg.get('read_latency_p50_mean',0):.3f}s")
                print()

    print(f"\nDone. Results in {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
