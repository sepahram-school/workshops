"""Aggregate 10 runs (runs 1-10) for mixed/large, 10 runs for fetch."""
import re, statistics
from pathlib import Path
from collections import defaultdict

LOG_DIR = Path("logs")

def clean_line(line):
    """Remove loguru timestamp prefix if present."""
    m = re.match(r'^\d{2}:\d{2}:\d{2}\s+\|\s+\w+\s+\|', line)
    if m:
        return line[m.end():]
    return line

def parse_suite_log(text):
    results = {}
    mode_match = re.search(r'MODE: (\w+)', text)
    mode = mode_match.group(1) if mode_match else "unknown"

    for driver in ("PSYCOPG3", "ADBC"):
        # Find Driver: XXX block
        idx = text.find(f"Driver: {driver} | Wall clock:")
        if idx == -1:
            continue
        block = text[idx:]
        # Extract values
        stats = {}
        for key, pat in [("queries", r"Queries:\s+(\d+)"),
                         ("avg", r"Avg:\s+([\d.]+)s"),
                         ("p50", r"p50 \(median\):\s+([\d.]+)s"),
                         ("p95", r"p95:\s+([\d.]+)s"),
                         ("p99", r"p99:\s+([\d.]+)s"),
                         ("min", r"Min:\s+([\d.]+)s"),
                         ("max", r"Max:\s+([\d.]+)s")]:
            m = re.search(pat, block)
            if m:
                stats[key] = float(m.group(1)) if key != "queries" else int(m.group(1))
        if stats:
            results[driver] = stats
    return mode, results

def parse_fetch_log(text):
    results = {"PSYCOPG3": {}, "ADBC": {}}
    cur_driver = None
    for line in text.splitlines():
        cl = clean_line(line)
        m = re.search(r'Fetch-speed benchmark \((\w+)\):', cl)
        if m:
            cur_driver = m.group(1).upper()
        m2 = re.search(r'([\d,]+) rows: ([\d.]+)s', cl)
        if m2 and cur_driver and cur_driver in results:
            rows = int(m2.group(1).replace(',', ''))
            secs = float(m2.group(2))
            results[cur_driver][rows] = secs
    return results

# Collect
suite_data = defaultdict(lambda: defaultdict(list))
suite_full = defaultdict(lambda: defaultdict(list))
fetch_data = {"PSYCOPG3": defaultdict(list), "ADBC": defaultdict(list)}

for f in sorted(LOG_DIR.glob("benchmark-*.log")):
    text = f.read_text(encoding="utf-8")

    if "Pure fetch-speed benchmark" in text:
        r = parse_fetch_log(text)
        for drv in ("PSYCOPG3", "ADBC"):
            for rows, secs in r.get(drv, {}).items():
                fetch_data[drv][rows].append(secs)
    elif "MODE:" in text:
        mode, r = parse_suite_log(text)
        if r:
            for drv, stats in r.items():
                suite_data[mode][drv].append(stats["avg"])
                suite_full[mode][drv].append(stats)

# Print suite results
suite_order = [
    ("Mixed", "Mixed workload"),
    ("Large-result", "Large-result ADBC"),
]

print("=" * 72)
print("  10-RUN ANALYSIS (runs 1-10)")
print("=" * 72)

for display_key, mode_substr in suite_order:
    key = next((k for k in suite_data if mode_substr.lower()[:8] in k.lower() or display_key.lower()[:4] in k.lower()), None)
    if not key:
        continue
    d = suite_data[key]
    f = suite_full[key]
    n_runs = len(d.get("PSYCOPG3", []))

    print(f"\n{'='*72}")
    print(f"  {display_key} — {n_runs} runs")
    print(f"{'='*72}")

    for drv in ("PSYCOPG3", "ADBC"):
        avgs = d.get(drv, [])
        if not avgs:
            continue
        all_s = f.get(drv, [])

        print(f"\n  {drv}:")
        print(f"    Averages:   {', '.join(f'{a:.3f}s' for a in avgs)}")
        print(f"    Mean:       {statistics.mean(avgs):.4f}s"
              + (f"  (stdev: {statistics.stdev(avgs):.4f}s)" if len(avgs) > 1 else ""))
        if len(avgs) > 1:
            print(f"    p50 range:  {min(s['p50'] for s in all_s):.3f}s - {max(s['p50'] for s in all_s):.3f}s")
            print(f"    p95 range:  {min(s['p95'] for s in all_s):.3f}s - {max(s['p95'] for s in all_s):.3f}s")
            print(f"    Max range:  {min(s['max'] for s in all_s):.3f}s - {max(s['max'] for s in all_s):.3f}s")

    p_avgs = d.get("PSYCOPG3", [])
    a_avgs = d.get("ADBC", [])
    if p_avgs and a_avgs:
        p_mean = statistics.mean(p_avgs)
        a_mean = statistics.mean(a_avgs)
        winner = "ADBC" if a_mean < p_mean else "psycopg3"
        diff = abs(a_mean - p_mean)
        pct = (diff / max(p_mean, a_mean)) * 100
        print(f"\n  >>> {winner} wins by {pct:.1f}% ({winner}: {min(p_mean,a_mean):.3f}s vs "
              f"{'psycopg3' if winner=='ADBC' else 'ADBC'}: {max(p_mean,a_mean):.3f}s)")

# Print fetch results
print(f"\n{'='*72}")
print(f"  Fetch Speed — all available runs across all logs")
print(f"{'='*72}")

rows_sorted = sorted(set().union(*(
    set(fetch_data[drv].keys()) for drv in ("PSYCOPG3", "ADBC")
)))

# Summary table
print(f"\n{'Rows':>10} | {'psycopg3 avg':>24} | {'ADBC avg':>24} | {'Ratio':>8}")
print("-" * 72)
for rows in rows_sorted:
    p = fetch_data.get("PSYCOPG3", {}).get(rows, [])
    a = fetch_data.get("ADBC", {}).get(rows, [])
    if not p or not a:
        continue
    p_avg = statistics.mean(p)
    a_avg = statistics.mean(a)
    p_rate = rows / p_avg
    a_rate = rows / a_avg
    ratio = a_rate / p_rate
    print(f"{rows:>10,} | {p_avg:.3f}s ({p_rate:>6,.0f}/s) | {a_avg:.3f}s ({a_rate:>6,.0f}/s) | {ratio:>5.2f}x")

# Individual runs
print(f"\n{'='*72}")
print(f"  Fetch Speed — per-driver per-size individual times")
print(f"{'='*72}")
for drv in ("PSYCOPG3", "ADBC"):
    print(f"\n  {drv}:")
    for rows in rows_sorted:
        vals = fetch_data.get(drv, {}).get(rows, [])
        if vals:
            print(f"    {rows:>8,}: {', '.join(f'{v:.3f}s' for v in vals)}"
                  f"  -> mean {statistics.mean(vals):.3f}s, stdev {statistics.stdev(vals):.3f}s" if len(vals) > 1 else f"    {rows:>8,}: {vals[0]:.3f}s")
