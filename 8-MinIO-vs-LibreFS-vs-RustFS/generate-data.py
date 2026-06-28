#!/usr/bin/env python3
"""
Test Data Generator for v2 Benchmark
=====================================
Pre-generates files in data/{size}/ directories for benchmark runs.
Separates data generation time from upload measurement.

Usage:
    uv run python generate-data.py --size all
    uv run python generate-data.py --size 1mb
    uv run python generate-data.py --size 32mb --files 50
"""

import argparse
import os
import time


SIZES = {
    "1mb": 1 * 1024 * 1024,
    "16mb": 16 * 1024 * 1024,
    "32mb": 32 * 1024 * 1024,
}

DATA_DIR = "data"


def generate_file(path: str, size_bytes: int) -> None:
    """Generate a single file with random bytes."""
    with open(path, "wb") as f:
        remaining = size_bytes
        chunk_size = min(1024 * 1024, remaining)
        while remaining > 0:
            write_size = min(chunk_size, remaining)
            f.write(os.urandom(write_size))
            remaining -= write_size


def generate_size_tier(size_name: str, size_bytes: int, num_files: int) -> None:
    """Generate all files for a given size tier."""
    tier_dir = os.path.join(DATA_DIR, size_name)
    os.makedirs(tier_dir, exist_ok=True)

    print(f"\n  Generating {num_files} x {size_name} files ({size_bytes / (1024*1024):.0f} MB each)")
    print(f"  Directory: {tier_dir}/")
    print(f"  Total: {num_files * size_bytes / (1024*1024*1024):.2f} GB")

    start = time.perf_counter()
    for i in range(num_files):
        path = os.path.join(tier_dir, f"file_{i:06d}.bin")
        if os.path.exists(path) and os.path.getsize(path) == size_bytes:
            print(f"  [{i+1:>4}/{num_files}] skipping (exists): {os.path.basename(path)}")
            continue
        generate_file(path, size_bytes)
        if (i + 1) % 10 == 0 or i == num_files - 1:
            elapsed = time.perf_counter() - start
            rate = (i + 1) * size_bytes / (1024 * 1024) / elapsed if elapsed > 0 else 0
            print(f"  [{i+1:>4}/{num_files}] generated: {os.path.basename(path)} ({rate:.1f} MB/s)")

    elapsed = time.perf_counter() - start
    total_mb = num_files * size_bytes / (1024 * 1024)
    print(f"  Done: {total_mb:.1f} MB in {elapsed:.1f}s ({total_mb / elapsed:.1f} MB/s)")


def main():
    parser = argparse.ArgumentParser(description="Generate test data for v2 benchmark")
    parser.add_argument(
        "--size",
        choices=list(SIZES.keys()) + ["all"],
        default="all",
        help="File size tier to generate (default: all)",
    )
    parser.add_argument("--files", type=int, default=100, help="Number of files per tier (default: 100)")
    args = parser.parse_args()

    sizes_to_generate = list(SIZES.items()) if args.size == "all" else [(args.size, SIZES[args.size])]

    print(f"Test Data Generator")
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
