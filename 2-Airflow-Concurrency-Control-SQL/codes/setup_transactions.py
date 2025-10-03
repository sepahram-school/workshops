# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "faker",
#     "psycopg[binary]",
# ]
# ///
from faker import Faker
from datetime import datetime
import random, psycopg, uuid, time

fake = Faker()
NUM_TX = 100000
BATCH_SIZE = 40
SLEEP_INTERVAL = 5  # seconds

# Postgres connection
conninfo = "dbname=transactions user=airflow host=localhost password=airflow port=5453"

with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cur:
        # Create table if not exists
        cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            transactionId UUID PRIMARY KEY,
            userId TEXT,
            timestamp TIMESTAMP,
            amount NUMERIC,
            currency TEXT,
            city TEXT,
            country TEXT,
            merchantName TEXT,
            paymentMethod TEXT,
            ipAddress TEXT,
            voucherCode TEXT,
            affiliateId UUID,
            processed BOOLEAN DEFAULT FALSE
        );
        """)
        print("✅ Table 'transactions' is ready.")

        for i in range(NUM_TX):
            user = fake.simple_profile()
            transaction = {
                "transactionId": str(uuid.uuid4()),
                "userId": user['username'],
                "timestamp": datetime.now(),
                "amount": round(random.uniform(10, 1000), 2),
                "currency": random.choice(['USD', 'GBP']),
                "city": fake.city(),
                "country": fake.country(),
                "merchantName": fake.company(),
                "paymentMethod": random.choice(['credit_card', 'debit_card', 'online_transfer']),
                "ipAddress": fake.ipv4(),
                "voucherCode": random.choice(['', 'DISCOUNT10', '']),
                "affiliateId": str(uuid.uuid4()),
                "processed": False
            }
            cur.execute("""
            INSERT INTO transactions
            (transactionId, userId, timestamp, amount, currency, city, country, merchantName, paymentMethod, ipAddress, voucherCode, affiliateId, processed)
            VALUES (%(transactionId)s, %(userId)s, %(timestamp)s, %(amount)s, %(currency)s, %(city)s, %(country)s, %(merchantName)s, %(paymentMethod)s, %(ipAddress)s, %(voucherCode)s, %(affiliateId)s, %(processed)s)
            """, transaction)

            # Commit every BATCH_SIZE transactions
            if (i + 1) % BATCH_SIZE == 0:
                conn.commit()
                print(f"✅ Inserted {i+1} transactions (last txId: {transaction['transactionId']}). Sleeping {SLEEP_INTERVAL}s...")
                time.sleep(SLEEP_INTERVAL)

        # Final commit if any remaining
        conn.commit()
        print(f"✅ Final commit done.")

print(f"🎉 Done! Inserted {NUM_TX} transactions.")
