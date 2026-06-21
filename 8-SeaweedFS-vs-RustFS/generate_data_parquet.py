#!/usr/bin/env python3
"""
Parquet Test Data Generator for DuckDB Benchmark
=================================================
Pre-generates Parquet files in data_parquet/{size}/ directories.
Used by benchmark_duckdb.py for analytical S3 workloads.

Usage:
    uv run python generate_data_parquet.py --size all
    uv run python generate_data_parquet.py --size 1mb
    uv run python generate_data_parquet.py --size 32mb --files 50
"""

import argparse
import os
import time

import duckdb


SIZES = {
    "1mb": 1 * 1024 * 1024,
    "16mb": 16 * 1024 * 1024,
    "32mb": 32 * 1024 * 1024,
}

DATA_DIR = "data_parquet"


def generate_parquet(path: str, target_size_bytes: int) -> None:
    """Generate a single Parquet file of approximate target size."""
    conn = duckdb.connect()
    # ~100 bytes per row uncompressed; Parquet compression ~3x, so target 3x rows
    num_rows = max(1000, int(target_size_bytes * 3 / 100))
    conn.execute(f"""
        COPY (
            SELECT
                i AS id,
                concat('payload_', lpad(cast(i % 1000000 as varchar), 7, '0'), '_', repeat('x', 80)) AS payload,
                now() + (i || ' seconds')::interval AS timestamp,
                i % 10 AS category,
                (random() * 1000)::double AS value
            FROM generate_series(1, {num_rows}) t(i)
        ) TO '{path}' (FORMAT PARQUET, ROW_GROUP_SIZE 100000)
    """)
    conn.close()


def generate_size_tier(size_name: str, size_bytes: int, num_files: int) -> None:
    """Generate all Parquet files for a given size tier."""
    tier_dir = os.path.join(DATA_DIR, size_name)
    os.makedirs(tier_dir, exist_ok=True)

    print(f"\n  Generating {num_files} x {size_name} Parquet files ({size_bytes / (1024*1024):.0f} MB each)")
    print(f"  Directory: {tier_dir}/")

    start = time.perf_counter()
    for i in range(num_files):
        path = os.path.join(tier_dir, f"file_{i:06d}.parquet")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            print(f"  [{i+1:>4}/{num_files}] skipping (exists): {os.path.basename(path)}")
            continue
        generate_parquet(path, size_bytes)
        actual_mb = os.path.getsize(path) / (1024 * 1024)
        if (i + 1) % 10 == 0 or i == num_files - 1:
            elapsed = time.perf_counter() - start
            rate = (i + 1) * size_bytes / (1024 * 1024) / elapsed if elapsed > 0 else 0
            print(f"  [{i+1:>4}/{num_files}] generated: {os.path.basename(path)} ({actual_mb:.1f} MB, {rate:.1f} MB/s)")

    elapsed = time.perf_counter() - start
    total_mb = num_files * size_bytes / (1024 * 1024)
    print(f"  Done: {total_mb:.1f} MB in {elapsed:.1f}s ({total_mb / elapsed:.1f} MB/s)")


def main():
    parser = argparse.ArgumentParser(description="Generate Parquet test data for DuckDB benchmark")
    parser.add_argument(
        "--size",
        choices=list(SIZES.keys()) + ["all"],
        default="all",
        help="File size tier to generate (default: all)",
    )
    parser.add_argument("--files", type=int, default=100, help="Number of files per tier (default: 100)")
    args = parser.parse_args()

    sizes_to_generate = list(SIZES.items()) if args.size == "all" else [(args.size, SIZES[args.size])]

    print(f"Parquet Test Data Generator")
    print(f"{'=' * 50}")

    for size_name, size_bytes in sizes_to_generate:
        generate_size_tier(size_name, size_bytes, args.files)

    print(f"\n{'=' * 50}")
    print(f"All data generated in {DATA_DIR}/")
    for size_name, size_bytes in SIZES.items():
        tier_dir = os.path.join(DATA_DIR, size_name)
        if os.path.exists(tier_dir):
            count = len([f for f in os.listdir(tier_dir) if os.path.isfile(os.path.join(tier_dir, f))])
            total = count * size_bytes / (1024 * 1024 * 1024)
            print(f"  {size_name:>5}: {count} files, {total:.2f} GB")


if __name__ == "__main__":
    main()
