import re, statistics
from pathlib import Path
from collections import defaultdict

pat_hdr = re.compile(r'Fetch-speed benchmark \((\w+)\):')
pat_row = re.compile(r'\s+([\d,]+) rows: ([\d.]+)s')
data = defaultdict(lambda: defaultdict(list))

for f in sorted(Path('logs').glob('benchmark-fetch-run*-fetch-*.log')):
    cur = None
    for line in f.read_text().splitlines():
        m = pat_hdr.search(line)
        if m:
            cur = m.group(1).lower()
        m2 = pat_row.search(line)
        if m2 and cur:
            rows = int(m2.group(1).replace(',', ''))
            secs = float(m2.group(2))
            data[cur][rows].append(secs)

print("Fetch Speed - Aggregated across 5 runs")
print()
rows_sorted = sorted({r for d in data.values() for r in d})
print(f"{'Rows':>10} | {'psycopg3':>20} | {'ADBC':>20} | {'Ratio':>8}")
print("-" * 65)
for rows in rows_sorted:
    p = data.get('psycopg3', {}).get(rows, [])
    a = data.get('adbc', {}).get(rows, [])
    p_avg = statistics.mean(p) if p else 0
    a_avg = statistics.mean(a) if a else 0
    p_rate = rows / p_avg if p_avg else 0
    a_rate = rows / a_avg if a_avg else 0
    ratio = a_rate / p_rate if p_rate else 0
    print(f"{rows:>10,} | {p_avg:.3f}s ({p_rate:>6,.0f}/s) | {a_avg:.3f}s ({a_rate:>6,.0f}/s) | {ratio:>5.1f}x")
