import argparse
import psycopg
from faker import Faker
from tqdm import tqdm

fake = Faker()

DB_URI = "host=localhost port=5454 dbname=postgres user=postgres password=password123"
TABLE = "products"
TARGET_COLUMNS = "name, category, price, stock_quantity, description"

def ensure_table(cur):
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            price DECIMAL(10,2) NOT NULL,
            stock_quantity INTEGER NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_category ON {TABLE}(category)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_price ON {TABLE}(price)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_stock_qty ON {TABLE}(stock_quantity)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_created_at ON {TABLE}(created_at)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_category_price ON {TABLE}(category, price)")

def current_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        return cur.fetchone()[0]

def generate_products_table(target: int) -> None:
    with psycopg.connect(DB_URI) as conn:
        ensure_table(conn.cursor())
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
            existing = cur.fetchone()[0]
        remaining = target - existing

        if remaining <= 0:
            print(f"Target {target:,} already reached ({existing:,} rows). Nothing to do.")
            return

        print(f"Existing: {existing:,}  Need: {remaining:,} new rows")

        insert_sql = f"INSERT INTO {TABLE} ({TARGET_COLUMNS}) VALUES (%s, %s, %s, %s, %s)"
        batch_size = 5000
        batches = (remaining + batch_size - 1) // batch_size

        for _ in tqdm(range(batches), desc="Generating data"):
            data = []
            with conn.cursor() as cur:
                for _ in range(batch_size):
                    data.append((
                        fake.word().capitalize() + " " + fake.word(),
                        fake.random_element(elements=("Electronics", "Clothing", "Books", "Home", "Toys")),
                        round(fake.random_number(digits=4, fix_len=False) / 100, 2),
                        fake.random_int(min=0, max=1000),
                        fake.text(max_nb_chars=200)
                    ))
                cur.executemany(insert_sql, data)
            conn.commit()

    total = current_count(psycopg.connect(DB_URI))
    print(f"Done. Total rows in {TABLE}: {total:,}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=100000, help="Target number of records")
    args = parser.parse_args()
    print(f"Target: {args.records:,} product records")
    generate_products_table(args.records)
