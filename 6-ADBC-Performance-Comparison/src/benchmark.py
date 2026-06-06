import concurrent.futures
import time
import json
import psycopg
from adbc_driver_postgresql import dbapi as adbc_dbapi
from contextlib import contextmanager
import argparse
import statistics
from loguru import logger
import sys
from datetime import datetime
from pathlib import Path

DB_URI = "postgresql://postgres:password123@localhost:5454/postgres"
ADBC_URI = "postgresql://postgres:password123@localhost:5454/postgres"

MIXED_QUERIES = [
    "SELECT category, COUNT(*) FROM products GROUP BY category",
    "SELECT category, AVG(price) FROM products GROUP BY category",
    "SELECT category, SUM(stock_quantity) FROM products GROUP BY category",
    "SELECT * FROM products WHERE price > 100 LIMIT 100",
    "SELECT * FROM products WHERE price > 500 LIMIT 100",
    "SELECT * FROM products WHERE category = 'Electronics' LIMIT 1000",
    "SELECT * FROM products WHERE category = 'Books' LIMIT 1000",
    "SELECT * FROM products WHERE price BETWEEN 50 AND 200 LIMIT 500",
    "SELECT COUNT(*) FROM products WHERE stock_quantity < 500",
    "SELECT name, price, category FROM products ORDER BY price DESC LIMIT 50",
]

LARGE_RESULT_QUERIES = [
    "SELECT category, COUNT(*) as cnt, AVG(price) as avg_price, "
    "SUM(stock_quantity) as total_stock, MIN(price), MAX(price) "
    "FROM products GROUP BY category ORDER BY category",
    "SELECT id, name, category, price, stock_quantity, description, created_at "
    "FROM products WHERE price > 50 LIMIT 20000",
    "SELECT * FROM products WHERE category IN ('Electronics', 'Books', 'Home') LIMIT 20000",
    "SELECT name, category, price, "
    "RANK() OVER (PARTITION BY category ORDER BY price DESC) as rank_in_category "
    "FROM products WHERE price > 10 LIMIT 10000",
]

FETCH_SIZES = [10000, 50000, 100000, 500000]

@contextmanager
def get_connection(driver):
    if driver == "psycopg3":
        with psycopg.connect(DB_URI, autocommit=True) as conn:
            yield conn
    elif driver == "adbc":
        with adbc_dbapi.connect(ADBC_URI, autocommit=True) as conn:
            yield conn
    else:
        raise ValueError("Driver not supported")

def percentile(data, p):
    if not data:
        return 0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = k - f
    if c == 0:
        return s[f]
    return s[f] * (1 - c) + s[f + 1] * c

def check_explain(queries, label):
    logger.info(f"=== EXPLAIN analysis for {label} ===")
    with psycopg.connect(DB_URI, autocommit=True) as conn:
        for i, q in enumerate(queries, 1):
            try:
                with conn.cursor() as cur:
                    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + q)
                    plan = cur.fetchone()[0][0]
                node = plan.get("Plan", plan)
                nt = node.get("Node Type", "?")
                rows = node.get("Actual Rows", "?")
                hit = node.get("Shared Hit Blocks", 0)
                read = node.get("Shared Read Blocks", 0)
                temp = node.get("Temp Written Blocks", 0)
                has_seq = "Seq Scan" in json.dumps(plan)
                has_idx = "Index Scan" in json.dumps(plan) or "Index Only Scan" in json.dumps(plan)
                q_short = q[:60].replace("\n", " ")
                status = "SEQ SCAN" if has_seq else ("INDEX SCAN" if has_idx else "OTHER")
                temp_info = f" | TEMP SPILL: {temp} blocks" if temp else ""
                logger.info(f"  Q{i:2d} [{status:10s}] {nt:20s} | rows={rows:>8,} | buffers: {hit:>6,} hit, {read:>6,} read{temp_info}")
                logger.debug(f"    Query: {q_short}...")
                if has_seq and not has_idx:
                    logger.warning(f"    Q{i} has Seq Scan — consider adding an index")
            except Exception as e:
                logger.error(f"  Q{i:2d} EXPLAIN failed: {e}")

        logger.info(f"  Current indexes on products:")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='products' ORDER BY indexname")
                for row in cur.fetchall():
                    logger.info(f"    {row[0]}: {row[1]}")
        except Exception as e:
            logger.error(f"  Could not fetch indexes: {e}")

def consume_result(driver, cursor):
    if not cursor.description:
        return
    if driver == "adbc":
        cursor.fetch_arrow_table()
    else:
        cursor.fetchall()

def run_benchmark(driver, num_threads, queries, run_label=""):
    for q in queries:
        try:
            with get_connection(driver) as conn:
                with conn.cursor() as cur:
                    cur.execute(q)
                    consume_result(driver, cur)
        except Exception:
            pass

    results = []
    start_wall = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for _ in range(num_threads):
            for query in queries:
                futures.append(executor.submit(execute_query, driver, query))

        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                logger.error(f"  Error: {e}")
    wall = time.perf_counter() - start_wall

    if not results:
        logger.warning(f"  No queries succeeded for {driver.upper()}")
        return []

    total_times = [t for t, _ in results]
    slowest_t, slowest_q = max(results, key=lambda x: x[0])

    logger.info(f"  {'-'*48}")
    logger.info(f"  Driver: {driver.upper()} | Wall clock: {wall:.2f}s")
    qps = len(total_times) / wall
    print_stats("Query latencies", total_times, qps)
    logger.info(f"  Slowest query ({slowest_t:.2f}s): {slowest_q[:120]}...")
    try:
        plan = explain_query(slowest_q)
        diagnose_plan(plan, "Plan")
    except Exception as e:
        logger.error(f"  (EXPLAIN skipped: {e})")

    return total_times

def execute_query(driver, query):
    start = time.perf_counter()
    with get_connection(driver) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            consume_result(driver, cur)
    return time.perf_counter() - start, query

def explain_query(query):
    with psycopg.connect(DB_URI, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query)
            plan = cur.fetchone()[0]
            return plan[0]

def diagnose_plan(plan, label):
    node = plan.get("Plan", plan)
    nt = node.get("Node Type", "?")
    rows = node.get("Actual Rows", "?")
    hit = node.get("Shared Hit Blocks", 0)
    read = node.get("Shared Read Blocks", 0)
    temp = node.get("Temp Written Blocks", 0)
    logger.info(f"    {label}: {nt} | rows={rows} | buffers: {hit} hit, {read} read"
           + (f" | TEMP SPILL: {temp} blocks" if temp else ""))

def fetch_speed_benchmark(driver, sizes):
    logger.info(f"  Fetch-speed benchmark ({driver.upper()}):")
    for n in sizes:
        q = f"SELECT * FROM products LIMIT {n}"
        start = time.perf_counter()
        with get_connection(driver) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
                consume_result(driver, cur)
        elapsed = time.perf_counter() - start
        rate = n / elapsed if elapsed else 0
        logger.info(f"    {n:>7,} rows: {elapsed:.3f}s ({rate:,.0f} rows/sec)")

def print_stats(label, times, qps):
    logger.info(f"    Queries:      {len(times)}")
    logger.info(f"    Avg:          {statistics.mean(times):.4f}s")
    logger.info(f"    p50 (median): {statistics.median(times):.4f}s")
    logger.info(f"    p95:          {percentile(times, 95):.4f}s")
    logger.info(f"    p99:          {percentile(times, 99):.4f}s")
    logger.info(f"    Min:          {min(times):.4f}s")
    logger.info(f"    Max:          {max(times):.4f}s")
    logger.info(f"    Throughput:   {qps:.1f} q/s")

def run_suite(num_threads, queries, runs, drivers):
    all_results = {}
    for r in range(runs):
        logger.info(f"\n{'='*60}")
        logger.info(f"  Run {r + 1}/{runs}")
        logger.info(f"{'='*60}")
        for driver in drivers:
            all_results.setdefault(driver, []).append(
                run_benchmark(driver, num_threads, queries)
            )

    logger.info(f"\n{'='*60}")
    logger.info(f"  FINAL SUMMARY - {runs} runs each")
    logger.info(f"{'='*60}")
    for driver in drivers:
        avgs = [statistics.mean(r) for r in all_results[driver] if r]
        if not avgs:
            continue
        logger.info(f"\n  {driver.upper()} across {len(avgs)} runs:")
        logger.info(f"    Mean of averages: {statistics.mean(avgs):.4f}s")
        logger.info(f"    Best avg run:     {min(avgs):.4f}s")
        logger.info(f"    Worst avg run:    {max(avgs):.4f}s")
        if len(avgs) > 1:
            logger.info(f"    Stability:        {statistics.stdev(avgs):.4f}s (stdev)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", choices=["psycopg3", "adbc", "both"], default="both")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--queries", type=int, default=10)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mode", choices=["mixed", "large", "fetch", "all"], default="all")
    parser.add_argument("--analyze", action="store_true", help="Run EXPLAIN analysis and suggest indexes")
    parser.add_argument("--log-file", type=str, default="", help="Log file path (default: auto-named)")
    parser.add_argument("--tag", type=str, default="", help="Tag to append to log filename")
    args = parser.parse_args()

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    tag_part = f"-{args.tag}" if args.tag else ""
    log_path = args.log_file or str(log_dir / f"benchmark{tag_part}-{args.mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
    logger.remove()
    logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")
    logger.add(log_path, format="{time:HH:mm:ss} | {level:<7} | {message}", level="DEBUG")
    logger.info(f"Log file: {log_path}")

    logger.info(f"PostgreSQL ADBC vs psycopg3 Benchmark")
    logger.info(f"  Mode:        {args.mode}")
    logger.info(f"  Threads:     {args.threads}")
    logger.info(f"  Runs:        {args.runs}")

    if args.analyze:
        if args.mode in ("mixed", "all"):
            check_explain(MIXED_QUERIES[:args.queries], "Mixed workload queries")
        if args.mode in ("large", "all"):
            check_explain(LARGE_RESULT_QUERIES[:args.queries], "Large-result queries")
        if args.mode in ("fetch", "all"):
            logger.info("Fetch benchmark has no WHERE clauses — no index analysis needed")
        sys.exit(0)

    drivers = []
    if args.driver in ("psycopg3", "both"):
        drivers.append("psycopg3")
    if args.driver in ("adbc", "both"):
        drivers.append("adbc")
    logger.info(f"  Drivers:     {', '.join(drivers)}")

    if args.mode in ("mixed", "all"):
        logger.info(f"\n{'#'*60}")
        logger.info(f"  MODE: Mixed workload (small + analytical queries)")
        logger.info(f"{'#'*60}")
        run_suite(args.threads, MIXED_QUERIES[:args.queries], args.runs, drivers)

    if args.mode in ("large", "all"):
        logger.info(f"\n{'#'*60}")
        logger.info(f"  MODE: Large-result ADBC-favouring queries")
        logger.info(f"{'#'*60}")
        run_suite(args.threads, LARGE_RESULT_QUERIES[:args.queries], args.runs, drivers)

    if args.mode in ("fetch", "all"):
        logger.info(f"\n{'#'*60}")
        logger.info(f"  MODE: Pure fetch-speed benchmark")
        logger.info(f"{'#'*60}")
        for driver in drivers:
            fetch_speed_benchmark(driver, FETCH_SIZES)
