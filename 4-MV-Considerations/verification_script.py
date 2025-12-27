import clickhouse_connect
import time
from tabulate import tabulate

def get_client():
    """Create ClickHouse client"""
    return clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        username='default',
        password=''
    )

def wait_for_data(client, timeout=30):
    """Wait for Kafka consumer to process data"""
    print(f"⏳ Waiting up to {timeout} seconds for data to be consumed...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        result = client.query("SELECT count() FROM events_target")
        count = result.result_rows[0][0]
        
        if count > 0:
            print(f"✅ Data found! Current count: {count}")
            return True
        
        time.sleep(2)
        print(".", end="", flush=True)
    
    print("\n⚠️  Timeout waiting for data")
    return False

def check_statistics(client):
    """Check and display current statistics"""
    
    print("\n" + "="*80)
    print("📊 CURRENT STATISTICS")
    print("="*80)
    
    # 1. Raw count (including duplicates)
    raw_count = client.query("SELECT count() FROM events_target").result_rows[0][0]
    print(f"\n1️⃣  Raw Event Count (with duplicates): {raw_count}")
    
    # 2. Unique count using FINAL
    unique_count = client.query("SELECT count() FROM events_target FINAL").result_rows[0][0]
    print(f"2️⃣  Unique Event Count (FINAL): {unique_count}")
    
    # 3. Summary table statistics
    summary = client.query("""
        SELECT 
            category,
            event_count,
            total_value
        FROM events_summary
        ORDER BY category
    """)
    
    print(f"\n3️⃣  Summary Table (SummingMergeTree):")
    if summary.result_rows:
        headers = ['Category', 'Event Count', 'Total Value']
        print(tabulate(summary.result_rows, headers=headers, tablefmt='grid'))
        
        total_summary_count = client.query("SELECT sum(event_count) FROM events_summary").result_rows[0][0]
        total_summary_value = client.query("SELECT sum(total_value) FROM events_summary").result_rows[0][0]
        print(f"\n   Total Summary Count: {total_summary_count}")
        print(f"   Total Summary Value: {total_summary_value}")
    else:
        print("   No data in summary table yet")
    
    # 4. Comparison
    print(f"\n4️⃣  Comparison:")
    print(f"   Expected Events: 1000")
    print(f"   Actual Raw Count: {raw_count}")
    print(f"   Actual Unique Count (FINAL): {unique_count}")
    
    if unique_count == 1000:
        print("   ✅ Unique count matches expected!")
    else:
        print(f"   ⚠️  Unique count doesn't match (difference: {abs(1000 - unique_count)})")
    
    # 5. Duplicate detection
    if raw_count > unique_count:
        print(f"\n5️⃣  ⚠️  DUPLICATES DETECTED!")
        print(f"   Number of duplicate inserts: {raw_count - unique_count}")
        print(f"   This means the summary table statistics are INFLATED!")
        
        # Show some duplicate examples
        duplicates = client.query("""
            SELECT event_id, count() as occurrences
            FROM events_target
            GROUP BY event_id
            HAVING occurrences > 1
            ORDER BY occurrences DESC
            LIMIT 10
        """)
        
        if duplicates.result_rows:
            print(f"\n   Examples of duplicated event_ids:")
            headers = ['Event ID', 'Occurrences']
            print(tabulate(duplicates.result_rows, headers=headers, tablefmt='grid'))
    else:
        print(f"\n5️⃣  ✅ No duplicates detected")
    
    print("\n" + "="*80)

def force_merge(client):
    """Force merge to trigger deduplication"""
    print("\n🔄 Forcing table optimization (merge)...")
    client.command("OPTIMIZE TABLE events_target FINAL")
    time.sleep(2)
    print("✅ Merge completed")

def reset_tables(client):
    """Reset all tables for fresh test"""
    print("\n🗑️  Resetting tables...")
    client.command("TRUNCATE TABLE events_target")
    client.command("TRUNCATE TABLE events_summary")
    print("✅ Tables truncated")

def main():
    client = get_client()
    
    print("="*80)
    print("🔍 ClickHouse Kafka Deduplication Test")
    print("="*80)
    
    while True:
        print("\n📋 Options:")
        print("1. Wait for data and check statistics")
        print("2. Check current statistics")
        print("3. Force table merge (OPTIMIZE)")
        print("4. Reset tables (TRUNCATE)")
        print("5. Exit")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == '1':
            if wait_for_data(client):
                time.sleep(5)  # Give some time for MV to process
                check_statistics(client)
        elif choice == '2':
            check_statistics(client)
        elif choice == '3':
            force_merge(client)
            check_statistics(client)
        elif choice == '4':
            reset_tables(client)
        elif choice == '5':
            print("\n👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")