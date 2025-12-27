-- ============================================
-- Step 1: Create Kafka Engine Table
-- ============================================
CREATE TABLE IF NOT EXISTS kafka_events_queue
(
    event_id Int32,
    value Int32,
    timestamp String,
    category String
)
ENGINE = Kafka
SETTINGS 
    kafka_broker_list = 'redpanda:29092',
    kafka_topic_list = 'events_topic',
    kafka_group_name = 'clickhouse_consumer_group',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_thread_per_consumer = 1;

-- ============================================
-- Step 2: Create Target Table (ReplacingMergeTree)
-- ============================================
CREATE TABLE IF NOT EXISTS events_target
(
    event_id Int32,
    value Int32,
    timestamp DateTime,
    category String,
    ingestion_time DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingestion_time)
ORDER BY event_id;

-- ============================================
-- Step 3: Create Materialized View to populate target
-- ============================================
CREATE MATERIALIZED VIEW IF NOT EXISTS events_consumer TO events_target
AS
SELECT 
    event_id,
    value,
    parseDateTimeBestEffort(timestamp) as timestamp,
    category
FROM kafka_events_queue;

-- ============================================
-- Step 4: Create Summary Table (SummingMergeTree)
-- ============================================
CREATE TABLE IF NOT EXISTS events_summary
(
    category String,
    event_count SimpleAggregateFunction(sum, UInt64),
    total_value SimpleAggregateFunction(sum, Int64),
    last_updated DateTime DEFAULT now()
)
ENGINE = SummingMergeTree()
ORDER BY category;

-- ============================================
-- Step 5: Create Materialized View for Summary
-- ============================================
CREATE MATERIALIZED VIEW IF NOT EXISTS events_summary_mv TO events_summary
AS
SELECT 
    category,
    1 AS event_count,
    toInt64(value) AS total_value
FROM events_target;

-- ============================================
-- Verification Queries
-- ============================================

-- Check raw data in target table (including duplicates)
-- SELECT event_id, value, category, ingestion_time 
-- FROM events_target 
-- ORDER BY event_id, ingestion_time;

-- Check deduplicated data (this is what ReplacingMergeTree should show after merge)
-- SELECT event_id, value, category, ingestion_time 
-- FROM events_target FINAL 
-- ORDER BY event_id;

-- Count total events (raw)
-- SELECT count() as total_events FROM events_target;

-- Count unique events (deduplicated)
-- SELECT count() as unique_events FROM events_target FINAL;

-- Check summary statistics (will show duplicates if data was reinserted)
-- SELECT 
--     category,
--     event_count,
--     total_value
-- FROM events_summary
-- ORDER BY category;

-- Compare expected vs actual
-- SELECT 
--     'Raw Count' as metric,
--     count() as value
-- FROM events_target
-- UNION ALL
-- SELECT 
--     'Unique Count (FINAL)' as metric,
--     count() as value
-- FROM events_target FINAL
-- UNION ALL
-- SELECT 
--     'Summary Count' as metric,
--     sum(event_count) as value
-- FROM events_summary;