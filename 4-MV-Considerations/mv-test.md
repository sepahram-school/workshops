# ClickHouse Kafka Deduplication Test

This hands-on example demonstrates the duplicate data issue with ClickHouse's ReplacingMergeTree and cascading materialized views.

## 📋 Setup Instructions

### 1. Start the Docker Cluster

```bash
docker-compose up -d
```

Wait for all services to be healthy:

```bash
docker-compose ps
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Create Kafka Topic

```bash
docker exec -it redpanda rpk topic create events_topic --partitions 3
```

Verify the topic was created:

```bash
docker exec -it redpanda rpk topic list
```

### 4. Setup ClickHouse Tables

Execute the SQL setup script:

```bash
docker exec -it clickhouse clickhouse-client < clickhouse_setup.sql
```

Or connect to ClickHouse client and paste the SQL:

```bash
docker exec -it clickhouse clickhouse-client
```

Verify tables were created:

```sql
SHOW TABLES;
```

You should see:

- `kafka_events_queue`
- `events_target`
- `events_consumer` (MV)
- `events_summary`
- `events_summary_mv` (MV)

## 🧪 Running the Test

### Test Scenario 1: Normal Flow (No Duplicates)

1. **Run the producer** (send 1000 events):

```bash
python kafka_producer.py
```

Expected output:

```
Starting Kafka producer...
Sent 100 events...
Sent 200 events...
...
✅ Successfully sent 1000 events!
```

1. **Check statistics** using the verification script:

```bash
python verification_script.py
```

Choose option `1` to wait for data and check statistics.

**Expected Results:**

- Raw Count: 1000
- Unique Count (FINAL): 1000
- Summary Count: 1000
- ✅ No duplicates

### Test Scenario 2: Simulating Duplicate Data (The Problem!)

Now let's simulate stopping and restarting the producer, which might re-send data:

1. **Reset the Kafka consumer offset** to re-read messages:

First, stop ClickHouse to disconnect the Kafka consumer:

```bash
docker-compose stop clickhouse
```

Wait a few seconds for the consumer to disconnect, then seek to start:

```bash
docker exec -it redpanda rpk group seek clickhouse_consumer_group --to start --topics events_topic
```

You should see output like:

```
TOPIC         PARTITION  PRIOR-OFFSET  CURRENT-OFFSET
events_topic  0          1000          0
events_topic  1          1000          0
events_topic  2          1000          0
```

Now restart ClickHouse to re-consume the messages:

```bash
docker-compose start clickhouse
```

1. **Wait for ClickHouse to re-consume** the same data (automatic):

The Kafka engine will automatically start reading from the beginning and re-insert the same events!

1. **Check statistics again**:

```bash
python verification_script.py
```

Choose option `2` to check current statistics.

**Expected Results (THE PROBLEM):**

- Raw Count: 2000 (duplicates!)
- Unique Count (FINAL): 1000 (ReplacingMergeTree will eventually deduplicate)
- Summary Count: 2000 ⚠️ **WRONG! Statistics are DOUBLED!**

This demonstrates that the SummingMergeTree summary table has **unreliable statistics** because the materialized view counted the duplicates before ReplacingMergeTree could deduplicate them.

### Test Scenario 3: Alternative - Restart Producer with Same Data

1. **Truncate tables**:

```bash
python verification_script.py
```

Choose option `4` to reset tables.

1. **Run producer twice** with same logic:

```bash
python kafka_producer.py
# Wait for it to complete
python kafka_producer.py  # Run again
```

Since we're using `event_id` as both the Kafka key and the ReplacingMergeTree ORDER BY key, the second run sends the same IDs but they'll be inserted as duplicates initially.

1. **Check statistics** - you'll see the same problem!

## 🔍 Understanding the Results

### What You'll Observe:

1. **Raw count** shows ALL inserted rows (including duplicates)
2. **FINAL count** shows deduplicated data (after merge)
3. **Summary table** shows INFLATED statistics because:
   - The MV fired for each insert
   - It doesn't respect ReplacingMergeTree deduplication
   - It counted the same event multiple times

### Force a Merge to See Deduplication:

```bash
python verification_script.py
```

Choose option `3` to force optimization. This will:

- Trigger ReplacingMergeTree to merge and remove old versions
- Make the raw count closer to the FINAL count
- **BUT the summary table remains wrong!**

## 📊 Monitoring with Redpanda Console

Open Redpanda Console: http://localhost:9100

You can:

- View the `events_topic`
- See messages
- Monitor consumer group `clickhouse_consumer_group`
- Check lag and offsets

## 🎯 Key Takeaways

1. **ReplacingMergeTree deduplicates only AFTER merges**, not on insert
2. **Materialized Views see raw inserted data**, before deduplication
3. **Cascading MVs create unreliable statistics** when duplicates exist
4. **The summary table can't "fix itself"** - it has already counted duplicates

## 🛠️ Solutions to Test

### Solution 1: Better Kafka Configuration

Ensure proper offset management so data isn't re-consumed:

```sql
-- In the Kafka engine, make sure kafka_commit_every_batch is enabled
-- and consumer group is stable
```

### Solution 2: Add Version Column

Modify the producer to include a version/timestamp that increases with updates:

```python
event = {
    'event_id': event_id,
    'value': random.randint(1, 1000),
    'timestamp': datetime.now().isoformat(),
    'version': int(time.time() * 1000)  # millisecond timestamp
}
```

Then use it in ReplacingMergeTree:

```sql
ENGINE = ReplacingMergeTree(version)
```

### Solution 3: Use FINAL in Summary MV (Not Recommended - Slow!)

```sql
CREATE MATERIALIZED VIEW events_summary_mv TO events_summary
AS
SELECT 
    category,
    1 AS event_count,
    toInt64(value) AS total_value
FROM events_target FINAL;  -- Very slow!
```

## 🧹 Cleanup

```bash
docker-compose down -v
```

## 📚 Additional Queries to Try

```sql
-- See all versions of a specific event
SELECT event_id, value, ingestion_time 
FROM events_target 
WHERE event_id = 1 
ORDER BY ingestion_time;

-- Compare raw vs deduplicated aggregations
SELECT 
    'Raw' as source,
    category,
    count() as cnt,
    sum(value) as total
FROM events_target
GROUP BY category
UNION ALL
SELECT 
    'FINAL' as source,
    category,
    count() as cnt,
    sum(value) as total
FROM events_target FINAL
GROUP BY category
ORDER BY source, category;
```

### New Kafka Engine Settings

```sql
SET allow_experimental_kafka_offsets_storage_in_keeper = 1; 
CREATE TABLE  ......
ENGINE = Kafka( 'localhost:19092', 'topic', 'consumer', 'JSONEachRow’) 
SETTINGS kafka_keeper_path = '/clickhouse/{database}/kafka’,
 kafka_replica_name = 'r1';

```

