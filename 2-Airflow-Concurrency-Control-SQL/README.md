### Airflow Concurrency Concerns: Lessons from a Transaction Pipeline

When we design pipelines with Apache Airflow, it’s tempting to assume that DAG scheduling is the only challenge. But once you start running multiple DAG runs on shared state (like a database table), you quickly discover concurrency pitfalls.

Recently, I built a pipeline that consumes raw financial transactions, stores them in a **lakehouse** (MinIO → Parquet later), and marks them as processed in Postgres. Sounds straightforward? It was — until I hit concurrency issues.

---

## 🛠 The Setup

We first simulated raw transactions using Python and **Faker**:

- A table `transactions` in Postgres with a boolean `processed` flag.

- A generator script inserting 100,000 fake transactions in small batches.

- An Airflow DAG that:
  
  1. Waits until there are at least 100 unprocessed transactions.
  
  2. Fetches them.
  
  3. Saves each one as JSON in MinIO.
  
  4. Marks them as processed in Postgres.

The DAG looked like this (simplified):

```python
wait_for_transactions = SqlSensor(
    task_id="wait_for_unprocessed_tx",
    conn_id="postgres_dev",
    sql="SELECT 1 WHERE (SELECT COUNT(*) FROM transactions WHERE processed = FALSE) > 100;"
)

@task
def produce_transactions():
    hook = PostgresHook(postgres_conn_id="postgres_dev")
    conn = hook.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM transactions WHERE processed = FALSE LIMIT 100;")
        rows = cur.fetchall()
    return rows

raw_transactions = produce_transactions()

finalized_tx_ids = save_to_lakehouse(raw_transactions)

update_processed = SQLExecuteQueryOperator(
    task_id="mark_transactions_processed",
    conn_id="postgres_dev",
    sql="""
        UPDATE transactions
        SET processed = TRUE
        WHERE transactionId = ANY(%(tx_ids)s::uuid[]);
    """,
    parameters={"tx_ids": finalized_tx_ids},
)

wait_for_transactions >> raw_transactions >> finalized_tx_ids >> update_processed
```

---

## ❌ The Problem

If you trigger this DAG multiple times in quick succession, something surprising happens:

- **Each DAG run processes the same set of transactions.**

- That means duplicate JSON objects in MinIO, double work, and inconsistent state.

Why? Because:

1. The `SELECT * FROM transactions WHERE processed = FALSE LIMIT 100` query is not atomic with the `UPDATE`.

2. Airflow runs each task in its own transaction.

3. Multiple DAG runs happily see the same “unprocessed” rows before any of them marks them as processed.

---

## ⚙️ Solutions We Tried

### 1. **`depends_on_past=True`**

Airflow allows tasks to run only if their previous run **succeeded**.

- ✅ Prevents overlapping runs from working on the same batch.

- ❌ It serializes DAG runs completely. If one run fails or lags, the whole pipeline stalls.

- ❌ Doesn’t solve the problem if you *want concurrency* but just need safe row assignment.

---

### 2. **`max_active_runs=1`**

DAG-level concurrency limit. Only one run of the DAG is active at a time.

- ✅ Simple and effective.

- ✅ Ensures no overlap.

- ❌ If you need higher throughput (say, multiple workers consuming transactions in parallel), this throttles you unnecessarily.

---

### 3. **SQL-level Concurrency Control (`FOR UPDATE SKIP LOCKED`)**

This is the more scalable, database-driven approach.

```sql
SELECT * 
FROM transactions
WHERE processed = FALSE
FOR UPDATE SKIP LOCKED
LIMIT 100;
```

How it works:

- `FOR UPDATE` locks the selected rows in the current transaction.

- `SKIP LOCKED` ensures that if another session already locked them, they’re skipped.

- This allows **multiple concurrent consumers** to fetch distinct sets of rows without collisions.

But there’s a catch:

- You must **update the rows inside the same transaction** that fetched them. Otherwise, other sessions won’t know they’re taken.

- That means our Airflow “fetch task” and “update task” need to be merged into a **single atomic task**: fetch → process → mark processed.

---

## 💡 Takeaways

- Airflow provides DAG-level concurrency control (`depends_on_past`, `max_active_runs`) — great for serialization, but not for true parallel consumers.

- For real concurrent pipelines, **push concurrency control into your database**. Postgres’s `FOR UPDATE SKIP LOCKED` is a perfect fit for queue-like workloads.

- Design your DAG tasks to reflect transactional boundaries:
  
  - Don’t split “fetch” and “update” if they must be atomic.
  
  - Instead, implement “fetch-and-update” in one Python task with a Postgres transaction.

---

## 🚀 Final Thought

Concurrency problems in Airflow are less about Airflow itself and more about **shared mutable state**. The moment multiple DAG runs or tasks operate on the same resource (like a Postgres table), you need to decide:

- Do I want **strict serialization**? → Use Airflow configs (`depends_on_past`, `max_active_runs`).

- Do I want **scalable concurrent consumers**? → Use database primitives (`FOR UPDATE SKIP LOCKED`).

Airflow orchestrates; your database enforces consistency. Mixing both is where the real engineering comes in.


