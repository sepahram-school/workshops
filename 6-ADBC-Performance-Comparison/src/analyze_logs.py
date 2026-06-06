"""Aggregate benchmark results from multiple log files and produce averaged summary."""
import re
import sys
from pathlib import Path
from collections import defaultdict
import statistics

LOG_DIR = Path("logs")

PAT_RUN = re.compile(
    r"Driver: (\w+) \| Wall clock: ([\d.]+)s\n"
    r".*?Queries:\s+(\d+)\n"
    r".*?Avg:\s+([\d.]+)s\n"
    r".*?p50 \(median\): ([\d.]+)s\n"
    r".*?p95:\s+([\d.]+)s\n"
    r".*?p99:\s+([\d.]+)s\n"
    r".*?Min:\s+([\d.]+)s\n"
    r".*?Max:\s+([\d.]+)s\n"
    r".*?Throughput:\s+([\d.]+) q/s",
    re.DOTALL
)

PAT_MODE_HEADER = re.compile(r"MODE: (.+?)(?: -|$)")
PAT_SUMMARY = re.compile(
    r"(\w+) across (\d+) runs:\n"
    r".*?Mean of averages: ([\d.]+)s\n"
    r".*?Best avg run:\s+([\d.]+)s\n"
    r".*?Worst avg run:\s+([\d.]+)s\n"
    r".*?Stability:\s+([\d.]+)s",
    re.DOTALL
)

PAT_FETCH = re.compile(
    r"Fetch-speed benchmark \((\w+)\):\n"
    r"(?:\s+([\d,]+) rows: ([\d.]+)s \(([\d,]+) rows/sec\)\n?)+"
)

def parse_log(path):
    text = path.read_text(encoding="utf-8")
    results = {"runs": []}

    for m in PAT_RUN.finditer(text):
        results["runs"].append({
            "driver": m.group(1),
            "wall": float(m.group(2)),
            "queries": int(m.group(3)),
            "avg": float(m.group(4)),
            "p50": float(m.group(5)),
            "p95": float(m.group(6)),
            "p99": float(m.group(7)),
            "min": float(m.group(8)),
            "max": float(m.group(9)),
            "qps": float(m.group(10)),
        })

    for m in PAT_SUMMARY.finditer(text):
        summary_key = f"{m.group(1).lower()}_summary"
        results[summary_key] = {
            "count": int(m.group(2)),
            "mean_avg": float(m.group(3)),
            "best_avg": float(m.group(4)),
            "worst_avg": float(m.group(5)),
            "stability": float(m.group(6)),
        }

    mode_m = PAT_MODE_HEADER.search(text)
    results["mode"] = mode_m.group(1) if mode_m else "unknown"

    return results

def main(tag_pattern="*"):
    log_dir = LOG_DIR
    files = sorted(log_dir.glob(f"benchmark-{tag_pattern}*.log"))
    if not files:
        files = sorted(log_dir.glob("benchmark*.log"))

    if not files:
        print(f"No log files found in {log_dir.resolve()}")
        sys.exit(1)

    by_mode = defaultdict(lambda: defaultdict(list))

    for f in files:
        parsed = parse_log(f)
        mode = parsed.get("mode", "unknown")
        for r in parsed.get("runs", []):
            d = r["driver"]
            by_mode[mode][d].append(r)

    for mode, drivers in sorted(by_mode.items()):
        print(f"\n{'='*65}")
        print(f"  Mode: {mode}")
        print(f"{'='*65}")
        for driver, runs in sorted(drivers.items()):
            avgs = [r["avg"] for r in runs]
            p95s = [r["p95"] for r in runs]
            p99s = [r["p99"] for r in runs]
            walls = [r["wall"] for r in runs]
            mins = [r["min"] for r in runs]
            maxes = [r["max"] for r in runs]
            qps_list = [r["qps"] for r in runs]
            print(f"\n  {driver.upper()} ({len(runs)} runs):")
            print(f"    Avg:          {statistics.mean(avgs):.4f}s  (stdev: {statistics.stdev(avgs):.4f}s)")
            print(f"    p50:          {statistics.median(avgs):.4f}s")
            print(f"    p95:          {statistics.mean(p95s):.4f}s  (range: {min(p95s):.4f}–{max(p95s):.4f}s)")
            print(f"    p99:          {statistics.mean(p99s):.4f}s  (range: {min(p99s):.4f}–{max(p99s):.4f}s)")
            print(f"    Min:          {statistics.mean(mins):.4f}s")
            print(f"    Max:          {statistics.mean(maxes):.4f}s")
            print(f"    Wall:         {statistics.mean(walls):.2f}s")
            print(f"    Throughput:   {statistics.mean(qps_list):.1f} q/s")

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "*"
    main(tag)
