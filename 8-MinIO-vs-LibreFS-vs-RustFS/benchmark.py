#!/usr/bin/env python3
"""
S3 Storage Benchmark v4: SeaweedFS vs RustFS vs libreFS vs MinIO
===============================================================
Benchmarks four workload modes:
  - write-only: Sequential concurrent writes
  - read-only:  Seed bucket, then measure read throughput
  - mixed:      Write phase then read phase (sequential)
  - heavy:      Concurrent reads AND writes simultaneously (mixed data load)

Usage:
    uv run python benchmark.py --target minio --mode heavy
    uv run python benchmark.py --target all --sizes 1mb,32mb --runs 3
"""

import argparse
import json
import os
import statistics
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3


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

DATA_DIR = "data"
RESULTS_DIR = "results"


def make_s3_client(config, num_threads=20):
    return boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name="us-east-1",
        config=boto3.session.Config(
            signature_version="s3v4", max_pool_connections=num_threads
        ),
    )


def upload_one_file(args):
    file_index, file_path, s3_client, bucket = args
    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)
    key = f"benchmark/{os.path.basename(file_path)}"
    with open(file_path, "rb") as f:
        data = f.read()
    start = time.perf_counter()
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")
        elapsed = time.perf_counter() - start
        return {"op": "write", "success": True, "file": key, "size_mb": size_mb, "time_sec": elapsed,
                "throughput_mbps": size_mb / elapsed if elapsed > 0 else 0}
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {"op": "write", "success": False, "file": key, "size_mb": size_mb, "time_sec": elapsed, "error": str(e)}


def download_one_file(args):
    key, s3_client, bucket = args
    start = time.perf_counter()
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        elapsed = time.perf_counter() - start
        size_mb = len(data) / (1024 * 1024)
        return {"op": "read", "success": True, "file": key, "size_mb": size_mb, "time_sec": elapsed,
                "throughput_mbps": size_mb / elapsed if elapsed > 0 else 0}
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {"op": "read", "success": False, "file": key, "size_mb": 0, "time_sec": elapsed, "error": str(e)}


def list_bucket_keys(s3_client, bucket, prefix="benchmark/"):
    keys = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


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


def run_write_phase(s3_client, bucket, files, num_threads, target_name, run_id):
    num_total = len(files)
    warmup_count = min(3, num_total // 2)
    warmup_files = files[:warmup_count]
    measure_files = files[warmup_count:]

    print(f"  Warmup: {warmup_count} files...")
    with ThreadPoolExecutor(max_workers=5) as ex:
        ex.map(upload_one_file, [(i, p, s3_client, bucket) for i, p in enumerate(warmup_files)])

    n = len(measure_files)
    print(f"\n  Writing {n} files, {num_threads} threads...")
    work = [(i, p, s3_client, bucket) for i, p in enumerate(measure_files)]
    w_results = []
    w_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as ex:
        fut = {ex.submit(upload_one_file, item): item for item in work}
        for i, f in enumerate(as_completed(fut), 1):
            r = f.result()
            w_results.append(r)
            if i % 20 == 0 or i == n:
                ok = sum(1 for x in w_results if x["success"])
                print(f"  write [{i:>4}/{n}] {ok} ok, {i-ok} failed, {time.perf_counter()-w_start:.1f}s")
    w_time = time.perf_counter() - w_start
    return summarize(w_results, len(measure_files), w_time, target_name, run_id, num_threads)


def run_read_phase(s3_client, bucket, num_threads, target_name, run_id):
    keys = list_bucket_keys(s3_client, bucket)
    if not keys:
        print("  No keys to read")
        return None
    print(f"\n  Reading back {len(keys)} files, {num_threads} threads...")
    r_work = [(k, s3_client, bucket) for k in keys]
    r_results = []
    r_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as ex:
        fut = {ex.submit(download_one_file, item): item for item in r_work}
        for i, f in enumerate(as_completed(fut), 1):
            r = f.result()
            r_results.append(r)
            if i % 20 == 0 or i == len(keys):
                ok = sum(1 for x in r_results if x["success"])
                print(f"  read  [{i:>4}/{len(keys)}] {ok} ok, {i-ok} failed, {time.perf_counter()-r_start:.1f}s")
    r_time = time.perf_counter() - r_start
    return summarize(r_results, len(keys), r_time, target_name, run_id, num_threads)


def run_heavy_phase(s3_client, bucket, files, num_threads, target_name, run_id, duration_sec=30):
    """
    Heavy mixed workload: concurrent reads AND writes simultaneously.
    - Half the threads write new files (cycling through file pool)
    - Half the threads read existing files (cycling through uploaded keys)
    - Runs for duration_sec seconds
    - Measures throughput and latency for both operations under contention
    """
    print(f"\n  HEAVY MIXED LOAD: {num_threads} threads, {duration_sec}s duration...")
    print(f"  Split: {num_threads//2} writers + {num_threads - num_threads//2} readers")

    stop_event = threading.Event()
    all_results = []
    results_lock = threading.Lock()
    write_counter = [0]
    read_counter = [0]

    def writer_worker(worker_id):
        idx = 0
        while not stop_event.is_set():
            fp = files[idx % len(files)]
            size_bytes = os.path.getsize(fp)
            size_mb = size_bytes / (1024 * 1024)
            key = f"heavy/w{worker_id}_{write_counter[0]}"
            with open(fp, "rb") as f:
                data = f.read()
            start = time.perf_counter()
            try:
                s3_client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")
                elapsed = time.perf_counter() - start
                r = {"op": "write", "success": True, "file": key, "size_mb": size_mb,
                     "time_sec": elapsed, "throughput_mbps": size_mb / elapsed if elapsed > 0 else 0}
            except Exception as e:
                elapsed = time.perf_counter() - start
                r = {"op": "write", "success": False, "file": key, "size_mb": size_mb,
                     "time_sec": elapsed, "error": str(e)}
            with results_lock:
                all_results.append(r)
                write_counter[0] += 1
            idx += 1

    def reader_worker(worker_id, existing_keys):
        s3 = s3_client
        idx = 0
        while not stop_event.is_set():
            if not existing_keys:
                time.sleep(0.01)
                continue
            key = existing_keys[idx % len(existing_keys)]
            start = time.perf_counter()
            try:
                response = s3.get_object(Bucket=bucket, Key=key)
                data = response["Body"].read()
                elapsed = time.perf_counter() - start
                size_mb = len(data) / (1024 * 1024)
                r = {"op": "read", "success": True, "file": key, "size_mb": size_mb,
                     "time_sec": elapsed, "throughput_mbps": size_mb / elapsed if elapsed > 0 else 0}
            except Exception as e:
                elapsed = time.perf_counter() - start
                r = {"op": "read", "success": False, "file": key, "size_mb": 0,
                     "time_sec": elapsed, "error": str(e)}
            with results_lock:
                all_results.append(r)
                read_counter[0] += 1
            idx += 1

    existing_keys = list_bucket_keys(s3_client, bucket)
    num_writers = num_threads // 2
    num_readers = num_threads - num_writers

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        for i in range(num_writers):
            pool.submit(writer_worker, i)
        for i in range(num_readers):
            pool.submit(reader_worker, i, existing_keys)

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


def run_benchmark_write_mixed(target_name, config, num_threads, file_paths, run_id, mode, heavy_duration=30):
    bucket = f"bench-{target_name}-run{run_id}-{int(time.time())}"
    s3_client = make_s3_client(config, num_threads)
    try:
        s3_client.create_bucket(Bucket=bucket)
    except Exception as e:
        if "BucketAlreadyExists" not in str(e) and "BucketAlreadyOwnedByYou" not in str(e):
            print(f"  Bucket creation error: {e}")

    wm = run_write_phase(s3_client, bucket, file_paths, num_threads, target_name, run_id)
    rm = None
    hm = None

    if mode == "mixed":
        rm = run_read_phase(s3_client, bucket, num_threads, target_name, run_id)
    elif mode == "read-only":
        rm = run_read_phase(s3_client, bucket, num_threads, target_name, run_id)
        wm = None
    elif mode == "heavy":
        hw, hr, hm = run_heavy_phase(s3_client, bucket, file_paths, num_threads, target_name, run_id, duration_sec=heavy_duration)

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
    print(f"  {target_name.upper()} | {size_name} | Run {run_id}")
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


def main():
    parser = argparse.ArgumentParser(description="S3 Storage Benchmark v4")
    parser.add_argument("--target", choices=["seaweedfs","rustfs","librefs","minio","all"], default="seaweedfs")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--sizes", type=str, default="1mb,32mb")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--mode", choices=["write-only","read-only","mixed","heavy"], default="mixed",
                        help="write-only=no read, read-only=read after seeding, mixed=write then read, heavy=concurrent read+write")
    parser.add_argument("--heavy-duration", type=int, default=30,
                        help="Duration in seconds for heavy mode (default: 30)")
    args = parser.parse_args()

    targets = list(TARGETS.keys()) if args.target == "all" else [args.target]
    sizes = [s.strip() for s in args.sizes.split(",")]
    os.makedirs(RESULTS_DIR, exist_ok=True)

    for target_name in targets:
        config = TARGETS[target_name]
        num_threads = config.get("threads", args.threads)
        print(f"\n{'#'*70}\n  {target_name.upper()} @ {config['endpoint']} ({num_threads} threads)\n{'#'*70}")

        for size_name in sizes:
            tier_dir = os.path.join(DATA_DIR, size_name)
            if not os.path.exists(tier_dir):
                print(f"\n  Skip {size_name}: no data dir")
                continue

            files = sorted([os.path.join(tier_dir, f) for f in os.listdir(tier_dir)
                           if os.path.isfile(os.path.join(tier_dir, f))])[:args.files]
            if not files:
                print(f"\n  Skip {size_name}: no files")
                continue

            print(f"\n  Size: {size_name} ({len(files)} x {SIZE_MAP[size_name]//(1024*1024)} MB)")
            print(f"  Mode: {args.mode.upper()}")

            write_runs, read_runs, heavy_runs = [], [], []
            for run_id in range(1, args.runs + 1):
                print(f"\n  --- Run {run_id}/{args.runs} ---")
                wm, rm, hm, bucket = run_benchmark_write_mixed(
                    target_name, config, num_threads, files, run_id, args.mode,
                    heavy_duration=args.heavy_duration)

                print_report(target_name, run_id, size_name, wm, rm, hm)
                write_runs.append(wm)
                if rm:
                    read_runs.append(rm)
                if hm:
                    heavy_runs.append(hm)

                run_data = {"mode": args.mode, "write": wm, "read": rm, "heavy": hm}
                rpath = os.path.join(RESULTS_DIR, args.mode, size_name, target_name, f"run-{run_id}.json")
                os.makedirs(os.path.dirname(rpath), exist_ok=True)
                with open(rpath, "w") as f:
                    json.dump(run_data, f, indent=2)

            w_agg = aggregate_runs([w for w in write_runs if w]) if any(write_runs) else None
            r_agg = aggregate_runs([r for r in read_runs if r]) if any(read_runs) else None
            h_agg = aggregate_heavy_runs([h for h in heavy_runs if h]) if any(heavy_runs) else None

            print(f"\n  {'='*50}")
            print(f"  {target_name.upper()} {size_name} — {args.mode.upper()} (n={w_agg.get('num_runs',0) if w_agg else r_agg.get('num_runs',0) if r_agg else h_agg.get('num_runs',0) if h_agg else 0})")
            print(f"  {'='*50}")
            if w_agg:
                print(f"  Write: {w_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- {w_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
            if r_agg:
                print(f"  Read:  {r_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- {r_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
            if h_agg:
                print(f"  Heavy combined: {h_agg.get('aggregate_throughput_mbps_mean',0):.1f} +/- {h_agg.get('aggregate_throughput_mbps_stdev',0):.1f} MB/s")
                print(f"  Heavy write P50: {h_agg.get('write_latency_p50_mean',0):.3f}s | Read P50: {h_agg.get('read_latency_p50_mean',0):.3f}s")
                print(f"  Heavy write success: {h_agg.get('write_success_rate_mean',0)*100:.1f}% | Read success: {h_agg.get('read_success_rate_mean',0)*100:.1f}%")
            print()

    print(f"\nDone. Results in {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
