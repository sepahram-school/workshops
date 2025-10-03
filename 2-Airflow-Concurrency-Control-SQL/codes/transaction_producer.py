# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "faker",
#     "kafka-python",
# ]
# ///
from datetime import datetime
import json
from kafka import KafkaProducer
import random
import time
import uuid
from faker import Faker

fake = Faker()

NUM_TX = 10000       # total number of transactions to produce
SLEEP_INTERVAL = 1   # seconds between batches/events
TOPIC_NAME = "transactions_topic"

producer = KafkaProducer(
    value_serializer=lambda msg: json.dumps(msg).encode("utf-8"),
    bootstrap_servers=["localhost:9092"],
    key_serializer=str.encode
)

def _produce_transaction():
    """
    Produce a single transaction event
    """
    user = fake.simple_profile()
    transaction = {
        "transactionId": str(uuid.uuid4()),
        "userId": user['username'],
        "timestamp": datetime.now().isoformat(),
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
    return transaction

def send_transactions():
    for i in range(NUM_TX):
        tx = _produce_transaction()
        producer.send(TOPIC_NAME, value=tx, key=tx["transactionId"])
        
        if (i + 1) % 10 == 0:  # batch info every 10 transactions
            print(f"✅ Sent {i+1} transactions (last txId: {tx['transactionId']})")
            time.sleep(SLEEP_INTERVAL)

    producer.flush()
    print("All transactions sent!")

if __name__ == "__main__":
    send_transactions()
