from airflow.sdk import dag, task, Variable
from airflow.providers.common.sql.sensors.sql import SqlSensor
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator
from minio import Minio
from datetime import datetime
import os, json
from airflow.providers.postgres.hooks.postgres import PostgresHook

MINIO_BUCKET = "staged"
MINIO_FINAL_FOLDER = "final"

default_args = {
    'owner': 'Sepahram',
    'depends_on_past': True
}

# ------------------- DAG Definition -------------------
@dag(
    schedule="*/5 * * * *",  # continuous scheduling style
    start_date=datetime(2025, 10, 3),
    catchup=False,
    tags=["transactions"],
    description="Process unprocessed transactions and save to lakehouse",
    default_args=default_args,
    max_active_runs=1    
)
def transaction_pipeline():

    # ------------------- Sensor: Wait for unprocessed transactions -------------------
    wait_for_transactions = SqlSensor(
        task_id="wait_for_unprocessed_tx",
        conn_id="postgres_dev",
        sql="""
            SELECT 1
            WHERE (SELECT COUNT(*) FROM transactions WHERE processed = FALSE) > 100;
        """,
        poke_interval=60,
        timeout=300,
        soft_fail=True    
    )

    # ------------------- Transform: Produce new transactions -------------------
    @task
    def produce_transactions():
        hook = PostgresHook(postgres_conn_id="postgres_dev")
        conn = hook.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM transactions WHERE processed = FALSE LIMIT 100;")
            colnames = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        
        transactions = []
        for row in rows:
            tx = dict(zip(colnames, row))
            tx["transactionId"] = str(tx.pop("transactionid"))
            tx["affiliateId"] = str(tx.pop("affiliateid"))
            transactions.append(tx)
        
        print(f"Produced {len(transactions)} transactions")
        return transactions


    raw_transactions = produce_transactions()

    # ------------------- Load: Save transactions to Lakehouse (MinIO) -------------------
    @task
    def save_to_lakehouse(transactions):
        import decimal  
        if not transactions:
            print("No transactions to save")
            return []

        # Flatten nested lists if needed
        if isinstance(transactions[0], list):
            flat_transactions = [tx for sublist in transactions for tx in sublist]
        else:
            flat_transactions = transactions

        client = Minio(
            Variable.get("MINIO_ENDPOINT", "minio:9000"),
            access_key=Variable.get("MINIO_ACCESS_KEY"),
            secret_key=Variable.get("MINIO_SECRET_KEY"),
            secure=False
        )

        final_files = []
        for tx in flat_transactions:
            # Convert non-JSON serializable types
            if isinstance(tx.get("amount"), decimal.Decimal):
                tx["amount"] = float(tx["amount"])
            # Convert datetime to ISO string
            if isinstance(tx.get("timestamp"), datetime):
                tx["timestamp"] = tx["timestamp"].isoformat()

            filename = f"tx_{tx['transactionId']}.json"
            local_json = f"/tmp/{filename}"
            with open(local_json, "w") as f:
                json.dump(tx, f)

            final_object_path = f"{MINIO_FINAL_FOLDER}/{filename}"
            client.fput_object(MINIO_BUCKET, final_object_path, local_json)
            os.remove(local_json)
            final_files.append(final_object_path)

        print(f"Saved {len(final_files)} transactions to lakehouse")
        # Return transaction IDs
        tx_ids = [tx["transactionId"] for tx in flat_transactions]
        return tx_ids

    finalized_tx_ids = save_to_lakehouse(raw_transactions)

    # ------------------- Update: Mark transactions as processed in Postgres -------------------
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

    # ------------------- DAG Dependencies -------------------
    wait_for_transactions >> raw_transactions >> finalized_tx_ids >> update_processed


transaction_pipeline()
