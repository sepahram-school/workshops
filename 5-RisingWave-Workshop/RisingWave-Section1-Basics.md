# RisingWave Stream Processing - Complete Tutorial

## Production-Ready Real-Time ETL in Pure SQL

> **Version:** 2.0 | **Updated:** Dec 2025 | **Level:** Beginner → Advanced

------

## 📑 Quick Navigation

**Getting Started (30 min)**

- [What is RisingWave?](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#what-is-risingwave) - Core concepts
- [Environment Setup](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#environment-setup) - Docker setup
- [First Pipeline](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#first-pipeline) - E-commerce example

**Core Concepts (45 min)**

- [Source vs Table vs MV](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#core-objects) - When to use what
- [Data Transformation](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#transformations) - Clean & enrich data
- [Time Windows](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#time-windows) - Tumbling, hopping, session

**Production Ready (60 min)**

- [Export Patterns](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#export-patterns) - ClickHouse, Parquet, Kafka
- [Best Practices](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#best-practices) - Performance, monitoring
- [Advanced Examples](https://claude.ai/chat/7115ca7f-decf-40de-bf1f-28489a572c5b#advanced) - CDC, joins, fraud detection

------

## What is RisingWave?

RisingWave is a **streaming SQL database** - think "PostgreSQL for real-time data." Write SQL, process millions of events/second.

### Why Stream Processing?

| Traditional Batch        | RisingWave Stream             |
| ------------------------ | ----------------------------- |
| Process every hour/day   | Process as data arrives       |
| Minutes to hours latency | Sub-second latency            |
| Spark/Flink complexity   | Pure SQL                      |
| Manual state management  | Automatic incremental updates |

### Key Benefits

- **🚀 Speed:** Sub-second event-to-insight latency
- **💾 Reliability:** Exactly-once delivery guarantees
- **🔄 Efficiency:** Only processes changes (incremental)
- **📊 Simplicity:** Standard PostgreSQL-compatible SQL
- **🔗 Integration:** Rich connectors (Kafka, CDC, S3, ClickHouse)

### Real-World Architecture



```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌─────────────┐
│   Kafka     │───▶│  RisingWave  │───▶│   Materialized  │───▶│   Export    │
│   Events    │    │   Sources    │    │     Views       │    │  ClickHouse │
│             │    │              │    │  (Incremental)  │    │  Parquet    │
└─────────────┘    └──────────────┘    └─────────────────┘    └─────────────┘
```

**Example: E-Commerce Pipeline**

1. **Orders stream** from Kafka (1000s/sec)
2. **Deduplicate** in real-time (remove duplicates)
3. **Enrich** with product catalog (add names, categories)
4. **Aggregate** revenue by category every minute
5. **Export** to ClickHouse for dashboards

**Traditional approach:** Hourly batch job, 1-hour delay
 **RisingWave approach:** Continuous processing, <1 second delay

![risingwave-sample-pipeline](images\risingwave-sample-pipeline.png)

------

## Core Objects

RisingWave has 4 building blocks:

### 1. SOURCE - Data Ingestion

**Purpose:** Connect to external systems (Kafka, S3) without storing data internally.

```sql
CREATE SOURCE orders_raw (
    order_id BIGINT,
    user_id BIGINT,
    item_id BIGINT,
    qty INT,
    price NUMERIC,
    amount NUMERIC,
    discount_pct NUMERIC,
    ts TIMESTAMP
) WITH (
    connector = 'kafka',
    topic = 'orders',
    properties.bootstrap.server = 'message_queue:29092'
) FORMAT PLAIN ENCODE JSON;

-- Can query directly
SELECT * FROM orders_raw LIMIT 10;
```

**When to use:**

- ✅ Kafka, Pulsar, Kinesis, S3
- ✅ Ad-hoc exploration
- ✅ Input for materialized views
- ❌ CDC sources (use TABLE instead)

### 2. TABLE - Persistent Storage

**Purpose:** Store data internally with ACID guarantees.

```sql
-- Static dimension table
CREATE TABLE items (
    item_id INT PRIMARY KEY,
    item_name VARCHAR,
    category VARCHAR
);

INSERT INTO items VALUES (1, 'Laptop', 'Electronics');

-- CDC table (auto-synced with PostgreSQL)
CREATE TABLE postgres_users WITH (
    connector = 'postgres-cdc',
    hostname = 'localhost',
    database = 'mydb',
    table = 'items'
);
```

**When to use:**

- ✅ CDC from PostgreSQL, MySQL
- ✅ Dimension tables
- ✅ Reference data

### 3. MATERIALIZED VIEW - Real-Time Computation

**Purpose:** Continuously compute and store query results.

```sql
-- Automatically refreshes as new data arrives
CREATE MATERIALIZED VIEW daily_revenue AS
SELECT 
    DATE_TRUNC('day', ts) AS day,
    SUM(amount) AS total_revenue,
    COUNT(*) AS order_count
FROM orders_raw
GROUP BY DATE_TRUNC('day', ts);

-- Query pre-computed results (fast!)
SELECT * FROM daily_revenue ORDER BY day DESC;
```

**When to use:**

- ✅ Aggregations (SUM, COUNT, AVG)
- ✅ Complex transformations
- ✅ Stream enrichment (JOINs)
- ✅ Input for sinks

### 4. SINK - Data Export

**Purpose:** Export results to external systems.

```sql
CREATE SINK revenue_to_clickhouse
FROM daily_revenue
WITH (
    connector = 'clickhouse',
    clickhouse.url = 'http://clickhouse:8123',
    clickhouse.database = 'default',
    clickhouse.table = 'revenue'
);
```

**When to use:**

- ✅ Export to ClickHouse, Kafka, S3
- ✅ Downstream integrations
- ✅ Multi-destination pipelines

### Decision Tree

```
What's your goal?

├─ Read from Kafka/S3 for exploration
│  └─ Use SOURCE
│
├─ Sync with PostgreSQL/MySQL (CDC)
│  └─ Use TABLE
│
├─ Store dimension data (items, users)
│  └─ Use TABLE
│
├─ Calculate aggregations
│  └─ Use MATERIALIZED VIEW
│
└─ Export to external system
   └─ Use SINK (from MV)
```

------

## Environment Setup

### Prerequisites

- Docker Desktop (4GB+ RAM)
- Python 3.9+ (for data generation)
- Basic SQL knowledge

### Quick Start

```bash
# Clone repository
git clone https://github.com/risingwavelabs/risingwave
cd risingwave

# Start all services
docker compose up -d

# Wait for services to be ready (including bucket initialization)
sleep 60

# Verify all services are healthy
docker compose ps

# Test RisingWave connection
docker exec -it risingwave-standalone psql -h localhost -p 4566 -d dev -U root
# Type \q to exit
```

**💡 Important:** The `rustfs-bucket-init` service automatically creates required S3 buckets during startup. This process takes ~30-60 seconds. Ensure all services show "healthy" status before proceeding.

### Service Overview

| Service               | Port       | Purpose                  |
| --------------------- | ---------- | ------------------------ |
| RisingWave            | 4566       | Stream processing engine |
| RisingWave Console    | 8020       | Web UI (recommended)     |
| Redpanda (Kafka)      | 9092       | Message streaming        |
| ClickHouse            | 8123       | Analytics destination    |
| RustFS(S3 Compatible) | 9000, 9001 | Object storage           |
| Grafana               | 3001       | Monitoring               |

### Access Methods

**🌟 Best: RisingWave Console** (http://localhost:8020)

- Visual source/MV management
- Lineage diagrams
- Real-time metrics
- **Username:** root, **Password:** 123456

**CLI:**

```bash
docker exec -it risingwave-standalone psql -h localhost -p 4566 -d dev -U root
```

**DBeaver:**

- Driver: RisingWave (or PostgreSQL)
- Host: localhost:4566
- Database: dev, User: root

------

## First Pipeline

Let's build an end-to-end pipeline in 10 minutes!

### Goal

Process Kafka orders → Calculate category revenue → Export to ClickHouse

### Step 1: Generate Data

**Install dependencies:**

```bash
pip install kafka-python faker
```

**Start producer:**

```bash
python kafka_producer_advanced.py
# Select: 1 (E-commerce Orders)
# Rate: 10 records/second
# Duration: (press Enter for unlimited)
```

Output:

```
🛒 E-commerce order generator started
✅ Orders sent: 100
✅ Orders sent: 200
```

### Step 2: Create Source

```sql
-- Connect to RisingWave
docker exec -it postgres_rw psql -h risingwave-standalone -p 4566 -d dev -U root

-- Create Kafka source
CREATE SOURCE orders_raw (
    order_id BIGINT,
    user_id BIGINT,
    item_id BIGINT,
    qty INT,
    price NUMERIC,
    amount NUMERIC,
    discount_pct NUMERIC,
    ts TIMESTAMP
) WITH (
    connector = 'kafka',
    topic = 'orders',
    properties.bootstrap.server = 'message_queue:29092',
    scan.startup.mode = 'earliest'
) FORMAT PLAIN ENCODE JSON;

-- Verify
SELECT COUNT(*) FROM orders_raw;
SELECT * FROM orders_raw LIMIT 5;
```

### Step 3: Add Dimension Table

```sql
CREATE TABLE items (
    item_id INT PRIMARY KEY,
    item_name VARCHAR,
    category VARCHAR
);

INSERT INTO items VALUES
(1, 'Laptop', 'Electronics'),
(2, 'Mouse', 'Accessories'),
(3, 'Monitor', 'Electronics'),
(4, 'Keyboard', 'Accessories'),
(5, 'Headphones', 'Electronics');
```

### Step 4: Enrich Orders

```sql
CREATE MATERIALIZED VIEW orders_enriched AS
SELECT
    o.order_id,
    o.user_id,
    i.item_name,
    i.category,
    o.qty,
    o.price,
    (o.qty * o.price) AS total_amount,
    o.ts
FROM orders_raw o
LEFT JOIN items i ON o.item_id = i.item_id;

-- Check enrichment
SELECT * FROM orders_enriched LIMIT 10;
```

### Step 5: Calculate Revenue

```sql
CREATE MATERIALIZED VIEW revenue_by_category AS
SELECT 
    category,
    window_start,
    window_end,
    SUM(total_amount) AS revenue,
    COUNT(*) AS order_count
FROM TUMBLE(orders_enriched, ts, INTERVAL '1 minute')
GROUP BY category, window_start, window_end;

-- Latest revenue
SELECT * FROM revenue_by_category
ORDER BY window_start DESC
LIMIT 10;
```

### Step 6: Export to ClickHouse

**Create ClickHouse table:**

```bash
docker exec -it clickhouse clickhouse-client -q "
CREATE TABLE default.revenue_by_category (
    category String,
    window_start DateTime64(6),
    window_end DateTime64(6),
    revenue Decimal(18,2),
    order_count Int64
) ENGINE = MergeTree()
ORDER BY (window_start, category)"
```

**For EMIT ON WINDOW CLOSE (revenue_emit_close table):**

```bash
docker exec -it clickhouse clickhouse-client -q "
CREATE TABLE default.revenue_emit_close (
    category String,
    window_start DateTime64(6),
    window_end DateTime64(6),
    revenue Decimal(18,2),
    order_count Decimal(18,0)
) ENGINE = MergeTree()
ORDER BY (window_start, category)"
```

**Key differences for EMIT ON WINDOW CLOSE:**
- `order_count` uses `Decimal(18,0)` instead of `Int64` to match RisingWave's `numeric` type
- This prevents "Column type can not match" errors when using EMIT ON WINDOW CLOSE

**Create NULL-safe view for sink:**

```sql
-- Handle NULL categories by converting to empty strings
CREATE MATERIALIZED VIEW revenue_by_category_sink AS
SELECT 
    COALESCE(category, '') AS category,
    window_start,
    window_end,
    revenue,
    order_count
FROM revenue_by_category;
```

**Create sink with append-only configuration:**

```sql
CREATE SINK revenue_to_clickhouse
FROM revenue_by_category_sink
WITH (
    connector = 'clickhouse',
    clickhouse.url = 'http://clickhouse:8123',
    clickhouse.user = 'default',
    clickhouse.password = '',
    clickhouse.database = 'default',
    clickhouse.table = 'revenue_by_category',
    type = 'append-only',
    force_append_only='true'
);
```

**💡 Important Notes:**
- Use `DateTime64(6)` instead of `DateTime` for TIMESTAMP compatibility
- Use `Int64` instead of `UInt32` for bigint compatibility  
- `force_append_only='true'` converts UPDATE messages to INSERT (required for tumbling windows)
- NULL handling prevents ClickHouse "column can not insert null" errors

### Step 7: Verify

**RisingWave:**

```sql
SELECT category, revenue, order_count
FROM revenue_by_category
WHERE window_start >= NOW() - INTERVAL '5 minutes'
ORDER BY revenue DESC;
```

**ClickHouse Verification (Run in DBeaver):**

```sql
-- 1. Check total records in ClickHouse
SELECT COUNT(*) as total_records FROM default.revenue_by_category;

-- 2. Compare RisingWave vs ClickHouse record counts
SELECT 
    'RisingWave' as source,
    COUNT(*) as record_count
FROM revenue_by_category

SELECT 
    'ClickHouse' as source,
    COUNT(*) as record_count
FROM default.revenue_by_category;

-- 3. Check latest data in ClickHouse
SELECT 
    category,
    window_start,
    window_end,
    revenue,
    order_count,
    now() - window_start as age
FROM default.revenue_by_category
ORDER BY window_start DESC
LIMIT 20;

-- 4. Verify data quality - check for NULL categories
SELECT 
    category,
    COUNT(*) as record_count
FROM default.revenue_by_category
GROUP BY category
ORDER BY record_count DESC;

-- 5. Check revenue trends by category
SELECT 
    category,
    DATE(window_start) as date,
    HOUR(window_start) as hour,
    SUM(revenue) as hourly_revenue,
    SUM(order_count) as hourly_orders
FROM default.revenue_by_category
WHERE window_start >= now() - interval 1 hour
GROUP BY category, DATE(window_start), HOUR(window_start)
ORDER BY date DESC, hour DESC, hourly_revenue DESC;

-- 6. Verify append-only behavior (multiple records per window)
SELECT 
    window_start,
    window_end,
    COUNT(*) as duplicate_records,
    COUNT(DISTINCT category) as unique_categories
FROM default.revenue_by_category
GROUP BY window_start, window_end
HAVING COUNT(*) > 1
ORDER BY window_start DESC
LIMIT 10;

-- 7. Check for data consistency between RisingWave and ClickHouse
WITH rw_data AS (
    SELECT category, window_start, revenue, order_count
    FROM revenue_by_category
    WHERE window_start >= now() - interval 30 minute
),
ch_data AS (
    SELECT category, window_start, revenue, order_count
    FROM default.revenue_by_category
    WHERE window_start >= now() - interval 30 minute
)
SELECT 
    'RisingWave' as source,
    COUNT(*) as record_count,
    SUM(revenue) as total_revenue
FROM rw_data
UNION ALL
SELECT 
    'ClickHouse' as source,
    COUNT(*) as record_count,
    SUM(revenue) as total_revenue
FROM ch_data;
```

### 📁 Export to Parquet (Data Lake)

**Prerequisites:**
- ✅ RustFS service running (S3-compatible storage)
- ✅ Required buckets created (see compose.yml `rustfs-bucket-init` service)
- ✅ RisingWave connected to RustFS via S3 endpoint

**Best for:** Long-term storage, data lake analytics, batch processing

**Create Parquet sink:**

```sql
CREATE SINK orders_to_parquet FROM orders_enriched
WITH (
    connector = 's3',
    s3.region_name = 'us-east-1',
    s3.bucket_name = 'hummock001',
    s3.path = 'orders',
    s3.credentials.access = 'admin',
    s3.credentials.secret = 'admin',
    s3.endpoint_url = 'http://rustfs:9000',
    type = 'append-only'
) FORMAT PLAIN ENCODE PARQUET(force_append_only='true');
```

**Key Configuration Notes:**
- Uses S3 connector with RustFS (S3-compatible storage)
- `force_append_only='true'` in FORMAT ENCODE section (required for tumbling windows)
- Files are automatically partitioned by time and distributed across volumes
- Supports time-based partitioning with `path_partition_prefix` option

**Verify Parquet sink:**

```bash
# Check file creation in RustFS
docker exec -it rustfs-server /bin/sh -c "find /data -name '*.parquet' -type d | wc -l"

# Check file sizes and distribution
docker exec -it rustfs-server /bin/sh -c "du -sh /data/*/hummock001/orders/"

# Monitor data flow
docker exec -it postgres_rw psql -h risingwave-standalone -p 4566 -d dev -U root -c "SELECT COUNT(*) FROM orders_enriched;"
```

**Expected Results:**
- ✅ Parquet directories created every few seconds
- ✅ Files distributed across all RustFS volumes
- ✅ Continuous data flow from RisingWave to S3 storage
- ✅ Automatic partitioning and batching

**Data Lake Integration:**
```sql
-- Query Parquet files using file_scan (when available)
SELECT * FROM file_scan('s3://data-lake/orders/*.parquet')
WHERE category = 'Electronics'
ORDER BY ts DESC
LIMIT 100;
```

**🎉 Success!** You now have data flowing to both ClickHouse (real-time analytics) and Parquet (data lake storage)!

### � Parquet Sink Troubleshooting

**Common Issues & Solutions:**

| Issue | Error Message | Solution |
|-------|---------------|----------|
| Bucket not found | "The specified bucket does not exist" | Ensure `rustfs-bucket-init` service ran successfully |
| Access denied | "Access Denied" | Verify S3 credentials match RustFS configuration |
| Connection failed | "Unable to connect to endpoint" | Check RustFS service is running and accessible |
| File creation failed | "Sink creation failed" | Verify bucket permissions and storage space |

**Bucket Creation Verification:**

```bash
# Check if required buckets exist
docker exec -it rustfs-server /bin/sh -c "ls -la /data/*/hummock001/"

# Verify RustFS service status
docker exec -it rustfs-server /bin/sh -c "curl -f http://localhost:9000/health"

# Test S3 connectivity
docker exec -it rustfs-server /bin/sh -c "aws --endpoint-url http://rustfs:9000 s3 ls s3://hummock001"

# Check bucket initialization logs
docker logs risingwave-rustfs-bucket-init
```

### 🪣 Bucket Creation Guide

**Automatic Bucket Creation (Recommended):**

The `rustfs-bucket-init` service in your `compose.yml` automatically creates required buckets:

```yaml
rustfs-bucket-init:
    container_name: risingwave-rustfs-bucket-init
    image: docker.arvancloud.ir/amazon/aws-cli:latest
    depends_on:
      rustfs:
        condition: service_healthy
    environment:
      AWS_ACCESS_KEY_ID: admin
      AWS_SECRET_ACCESS_KEY: admin
      AWS_DEFAULT_REGION: us-east-1
    entrypoint: >
      /bin/sh -c "
      echo 'Waiting for rustfs to be ready...';
      sleep 5;
      echo 'Creating bucket hummock001...';
      aws --endpoint-url http://rustfs:9000 s3 mb s3://hummock001 || echo 'Bucket may already exist';
      echo 'Verifying bucket exists...';
      aws --endpoint-url http://rustfs:9000 s3 ls s3://hummock001 && echo 'Bucket hummock001 is ready!' || echo 'Warning: Could not verify bucket';
      exit 0;
      "
```

**Manual Bucket Creation:**

If automatic creation fails, create buckets manually:

```bash
# 1. Access RustFS container
docker exec -it rustfs-server /bin/sh

# 2. Install aws-cli if not available
apk add --no-cache aws-cli

# 3. Create required buckets
aws --endpoint-url http://rustfs:9000 s3 mb s3://hummock001
aws --endpoint-url http://rustfs:9000 s3 mb s3://data-lake

# 4. Verify buckets
aws --endpoint-url http://rustfs:9000 s3 ls

# 5. Exit container
exit
```

**Required Buckets for Parquet Sink:**
- `hummock001` - Default bucket for RisingWave state store and Parquet files
- `data-lake` - Optional bucket for additional data lake storage

**Bucket Permissions:**
- Access Key: `admin`
- Secret Key: `admin`
- Region: `us-east-1`
- Endpoint: `http://rustfs:9000`

### ⏰ Alternative: EMIT ON WINDOW CLOSE (Recommended for Append-Only Sinks)

**Problem:** Regular tumbling windows generate UPDATE messages that require `force_append_only='true'` for append-only sinks.

**Solution:** Use `EMIT ON WINDOW CLOSE` to emit only final, immutable results when windows close.

**⚠️ Important:** When using `EMIT ON WINDOW CLOSE`, RisingWave requires the watermark column to be included in the `GROUP BY` clause. If you get the error "Not supported: Emit-On-Window-Close mode requires a watermark column in GROUP BY", make sure to include the watermark column (e.g., `ts`) in your GROUP BY clause.

**Benefits:**
- ✅ No need for `force_append_only='true'`
- ✅ Cleaner data flow (no duplicate records)
- ✅ Better performance for append-only destinations
- ✅ Final, immutable results only

**Implementation:**

1. **Create source with watermark:**
```sql
CREATE SOURCE orders_raw_with_watermark (
    order_id BIGINT,
    user_id BIGINT,
    item_id BIGINT,
    qty INT,
    price NUMERIC,
    amount NUMERIC,
    discount_pct NUMERIC,
    ts TIMESTAMP,
    WATERMARK FOR ts AS ts - INTERVAL '5 minutes'
) WITH (
    connector = 'kafka',
    topic = 'orders',
    properties.bootstrap.server = 'message_queue:29092'
) FORMAT PLAIN ENCODE JSON;
```

2. **Create materialized view with EMIT ON WINDOW CLOSE:**

**⚠️ Important:** When using `EMIT ON WINDOW CLOSE` with JOINs, RisingWave has specific requirements. The recommended approach is to use a two-step process:

**Step 1: Create windowed aggregation without JOIN**
```sql
CREATE MATERIALIZED VIEW revenue_by_item_window AS
SELECT 
    item_id,
    window_start,
    window_end,
    SUM(qty * price) AS revenue,
    COUNT(*) AS order_count
FROM TUMBLE(orders_raw_with_watermark, ts, INTERVAL '1 minute')
GROUP BY item_id, window_start, window_end, ts
EMIT ON WINDOW CLOSE;
```

**Step 2: Join with dimension table**
```sql
CREATE MATERIALIZED VIEW revenue_by_category_emit_close AS
SELECT 
    COALESCE(i.category, '') AS category,
    r.window_start,
    r.window_end,
    SUM(r.revenue) AS revenue,
    SUM(r.order_count) AS order_count
FROM revenue_by_item_window r
LEFT JOIN items i ON r.item_id = i.item_id
GROUP BY i.category, r.window_start, r.window_end;
```

**Why this approach works:**
- ✅ Avoids EMIT ON WINDOW CLOSE limitations with JOINs
- ✅ Follows RisingWave patterns for clean separation of concerns
- ✅ Provides final, immutable results for append-only sinks
- ✅ Better performance than regular tumbling windows

3. **Create append-only sink (no force_append_only needed):**
```sql
--- create the destination table in clickhouse
CREATE TABLE default.revenue_emit_close
(
    `category` String,
    `window_start` DateTime64(6),
    `window_end` DateTime64(6),
    `revenue` Decimal(18, 2),
    `order_count` Decimal(18, 0)
)
ENGINE = MergeTree
ORDER BY (window_start, category)
SETTINGS index_granularity = 8192;


-- ClickHouse sink
CREATE SINK revenue_to_clickhouse_emit_close FROM revenue_by_category_emit_close
WITH (
    connector = 'clickhouse',
    clickhouse.url = 'http://clickhouse:8123',
    clickhouse.user = 'default',
    clickhouse.password = '',
    clickhouse.database = 'default',
    clickhouse.table = 'revenue_emit_close',
    type = 'append-only'  -- No force_append_only needed!
);

-- Parquet sink

CREATE SINK orders_to_parquet_emit_close FROM revenue_by_category_emit_close
WITH (
    connector = 's3',
    s3.region_name = 'us-east-1',
    s3.bucket_name = 'hummock001',
    s3.path = 'orders_emit_close',
    s3.credentials.access = 'admin',
    s3.credentials.secret = 'admin',
    s3.endpoint_url = 'http://rustfs:9000',
    type = 'append-only'  
) FORMAT PLAIN ENCODE parquet (force_append_only='true');

```

**Note:** Before creating the Parquet sink, you need to create the appropriate materialized view. For category-based data, use the two-step approach:

**For Simple Orders (No Category):**
```sql
CREATE MATERIALIZED VIEW orders_simple_emit_close AS
SELECT 
    order_id,
    user_id,
    item_id,
    qty,
    price,
    (qty * price) AS total_amount,
    ts
FROM orders_raw_with_watermark
EMIT ON WINDOW CLOSE;
```

**For Category-Based Orders (Recommended):**
```sql
-- Step 1: Windowed aggregation by item
CREATE MATERIALIZED VIEW orders_by_item_window AS
SELECT 
    item_id,
    window_start,
    window_end,
    order_id,
    user_id,
    qty,
    price,
    (qty * price) AS total_amount,
    ts
FROM TUMBLE(orders_raw_with_watermark, ts, INTERVAL '1 minute')
GROUP BY item_id, window_start, window_end, ts, order_id, user_id, qty, price
EMIT ON WINDOW CLOSE;

-- Step 2: Enrich with category
CREATE MATERIALIZED VIEW orders_with_category_emit_close AS
SELECT 
    i.category,
    o.window_start,
    o.window_end,
    o.order_id,
    o.user_id,
    o.qty,
    o.price,
    o.total_amount,
    o.ts
FROM orders_by_item_window o
LEFT JOIN items i ON o.item_id = i.item_id;
```

**Create Parquet sink using the category-based view:**
```sql
CREATE SINK orders_to_parquet_emit_close FROM orders_with_category_emit_close
WITH (
    connector = 's3',
    s3.region_name = 'us-east-1',
    s3.bucket_name = 'data-lake',
    s3.path = 'orders_with_category_emit_close',
    s3.credentials.access = 'admin',
    s3.credentials.secret = 'admin',
    s3.endpoint_url = 'http://rustfs:9000',
    type = 'append-only'  -- No force_append_only needed!
) FORMAT PLAIN ENCODE PARQUET;
```

**Key Differences:**

| Aspect | Regular Window | EMIT ON WINDOW CLOSE |
|--------|---------------|---------------------|
| **Data Flow** | Updates every barrier (1s) | Final results only |
| **Sink Configuration** | Requires `force_append_only='true'` | No special configuration needed |
| **Data Volume** | Multiple records per window | One record per input per window |
| **Data Quality** | Partial aggregations | Final, immutable results |
| **Use Case** | Real-time dashboards | Data lake, batch processing |
| **JOIN Support** | Full JOIN support | Limited JOIN support (use two-step approach) |

**When to Use EMIT ON WINDOW CLOSE:**
- ✅ Append-only destinations (S3, Kafka, Parquet files)
- ✅ Data lake storage where final results are preferred
- ✅ Batch processing workflows
- ✅ When you want cleaner, immutable data
- ✅ When using the two-step approach for dimension enrichment

**When to Use Regular Windows:**
- ✅ Real-time dashboards requiring frequent updates
- ✅ Applications needing partial aggregations
- ✅ When immediate visibility into partial results is important
- ✅ Complex JOINs that need to happen within the windowed aggregation

**Two-Step Pattern Benefits:**
- ✅ Clean separation of time-based aggregation and dimension enrichment
- ✅ Follows RisingWave best practices for stream processing
- ✅ Enables EMIT ON WINDOW CLOSE even with dimension lookups
- ✅ Better performance and maintainability

**Real-World Example:**
The two-step approach we implemented successfully processes e-commerce orders:
1. **Step 1:** Window orders by item_id every minute with EMIT ON WINDOW CLOSE
2. **Step 2:** Join with items table to get category information
3. **Result:** Final, immutable revenue data by category ready for append-only sinks

This pattern is production-ready and handles the complexity of time-based aggregations with dimension lookups while maintaining the benefits of EMIT ON WINDOW CLOSE.

### �📋 Append-Only Sink Best Practices

**When to Use Append-Only vs Upsert Sinks:**

| Sink Type | Use Case | Example |
|-----------|----------|---------|
| **Append-Only** | Tumbling windows, event streams, time-series data | `revenue_by_category`, `user_activity_5min` |
| **Upsert** | CDC from databases, slowly changing dimensions | `orders_clean`, `user_profiles` |

**Key Considerations:**

1. **Tumbling Windows**: Always use `append-only` with `force_append_only='true'`
   
   - Windows update as new data arrives → UPDATE messages
   - `force_append_only` converts UPDATEs to INSERTs
   - Results in multiple records per time window (expected behavior)
   
2. **Data Deduplication**: Use ClickHouse's `ReplacingMergeTree` engine
   
   ```sql
   CREATE TABLE revenue_by_category (
       category String,
       window_start DateTime64(6),
       window_end DateTime64(6),
       revenue Decimal(18,2),
       order_count Int64
   ) ENGINE = ReplacingMergeTree()
   ORDER BY (window_start, category);
   ```
   
3. **Final Data Queries**: Use `FINAL` keyword or `GROUP BY` for deduplicated results
   
   ```sql
   -- Option 1: Use FINAL (slower but simpler)
   SELECT category, window_start, window_end, 
          sum(revenue) as revenue, sum(order_count) as order_count
   FROM default.revenue_by_category FINAL
   GROUP BY category, window_start, window_end
   ORDER BY window_start DESC;
   
   -- Option 2: Use GROUP BY (faster for large datasets)
   SELECT category, window_start, window_end,
          max(revenue) as revenue, max(order_count) as order_count
   FROM default.revenue_by_category
   GROUP BY category, window_start, window_end
   ORDER BY window_start DESC;
   ```
   
4. **Data Type Compatibility**: Always match RisingWave types with ClickHouse equivalents
   - `TIMESTAMP` → `DateTime64(6)`
   - `bigint` → `Int64` (not `UInt32`)
   - `numeric` → `Decimal(18,2)`
   - Handle NULLs: `COALESCE(column, '')` for String columns

5. **Performance Optimization**:
   - Use appropriate partitioning: `PARTITION BY toYYYYMM(window_start)`
   - Set merge tree settings: `index_granularity = 8192`
   - Consider TTL for old data: `TTL window_start + INTERVAL 30 DAY`

**Common Issues & Solutions:**

| Issue | Error Message | Solution |
|-------|---------------|----------|
| Data type mismatch | "Column type can not match" | Use correct ClickHouse types |
| NULL insertion | "clickhouse column can not insert null" | Handle NULLs in RisingWave view |
| Sink creation fails | "The sink cannot be append-only" | Add `force_append_only='true'` |
| Duplicate data | Multiple records per window | Use `ReplacingMergeTree` + `FINAL` |

**💡 Tip:** For detailed troubleshooting, see the [Troubleshooting Guide](#troubleshooting-guide) section at the end of this document.

------

## Transformations

### Deduplication

Kafka uses at-least-once delivery → duplicates happen.

```sql
-- Keep latest version of each order
CREATE MATERIALIZED VIEW orders_clean AS
SELECT DISTINCT ON (order_id)
    order_id,
    user_id,
    item_id,
    qty,
    price,
    ts
FROM orders_raw
ORDER BY order_id, ts DESC;

-- Verify
SELECT 
    (SELECT COUNT(*) FROM orders_raw) AS raw_count,
    (SELECT COUNT(*) FROM orders_clean) AS clean_count;
```

### Data Validation

```sql
CREATE MATERIALIZED VIEW orders_validated AS
SELECT *
FROM orders_clean
WHERE 
    qty > 0 
    AND price > 0
    AND ts <= NOW()
    AND user_id IS NOT NULL;
```

### Calculated Fields

```sql
CREATE MATERIALIZED VIEW orders_transformed AS
SELECT
    order_id,
    user_id,
    qty,
    price,
    (qty * price) AS total_amount,
    DATE_TRUNC('day', ts) AS order_date,
    EXTRACT(DOW FROM ts) AS day_of_week,
    CASE 
        WHEN total_amount < 50 THEN 'Small'
        WHEN total_amount < 200 THEN 'Medium'
        ELSE 'Large'
    END AS order_size,
    ts
FROM orders_clean;
```

### Stream Enrichment

```sql
-- Multi-table JOIN
CREATE TABLE users (
    user_id INT PRIMARY KEY,
    user_name VARCHAR,
    user_tier VARCHAR
);

CREATE MATERIALIZED VIEW orders_fully_enriched AS
SELECT
    o.order_id,
    u.user_name,
    u.user_tier,
    i.item_name,
    i.category,
    o.qty,
    o.price,
    (o.qty * o.price) AS total_amount
FROM orders_clean o
LEFT JOIN items i ON o.item_id = i.item_id
LEFT JOIN users u ON o.user_id = u.user_id;
```

------

## Time Windows

### Window Types

**TUMBLING:** Fixed, non-overlapping buckets

```
┌───┐┌───┐┌───┐┌───┐
│ W1││W2 ││W3 ││W4 │
└───┘└───┘└───┘└───┘
0   1   2   3   4
```

Use for: Periodic reports (hourly, daily)

**HOPPING:** Overlapping windows

```
┌──────┐
│  W1  │
└──────┘
  ┌──────┐
  │  W2  │
  └──────┘
    ┌──────┐
    │  W3  │
    └──────┘
0   1   2   3   4
```

Use for: Moving averages, trend detection

**SESSION:** Activity-based grouping

```
┌────┐    ┌─┐   ┌──────┐
│ S1 │gap │S2│gap│  S3  │
└────┘    └─┘   └──────┘
```

Use for: User sessions, activity analysis

### Tumbling Windows

```sql
-- Revenue per minute
CREATE MATERIALIZED VIEW revenue_1min AS
SELECT 
    window_start,
    window_end,
    SUM(qty * price) AS revenue,
    COUNT(*) AS order_count
FROM TUMBLE(orders_clean, ts, INTERVAL '1 minute')
GROUP BY window_start, window_end;

-- Revenue by category per hour
CREATE MATERIALIZED VIEW category_revenue_hourly AS
SELECT 
    i.category,
    window_start,
    SUM(o.qty * o.price) AS revenue,
    COUNT(*) AS orders
FROM TUMBLE(orders_clean o, ts, INTERVAL '1 hour')
LEFT JOIN items i ON o.item_id = i.item_id
GROUP BY i.category, window_start;
```

### Hopping Windows

```sql
-- 5-minute sliding window, 1-minute hop
CREATE MATERIALIZED VIEW user_activity_5min AS
SELECT 
    user_id,
    window_start,
    SUM(qty * price) AS total_spent,
    COUNT(*) AS order_count
FROM HOP(orders_clean, ts, INTERVAL '1 minute', INTERVAL '5 minutes')
GROUP BY user_id, window_start;

-- Fraud detection
CREATE MATERIALIZED VIEW fraud_alerts AS
SELECT 
    user_id,
    window_start,
    COUNT(*) AS order_count,
    SUM(qty * price) AS total_spent,
    CASE 
        WHEN COUNT(*) > 10 THEN 'Suspicious: Too many orders'
        WHEN SUM(qty * price) > 5000 THEN 'Suspicious: High spending'
        ELSE 'Normal'
    END AS risk_level
FROM HOP(orders_clean, ts, INTERVAL '1 minute', INTERVAL '5 minutes')
GROUP BY user_id, window_start
HAVING COUNT(*) > 5;

-- Active alerts
SELECT * FROM fraud_alerts
WHERE risk_level LIKE 'Suspicious%'
AND window_start >= NOW() - INTERVAL '10 minutes';
```

### Session Windows

**⚠️ Important:** Session windows require EMIT ON WINDOW CLOSE mode in RisingWave.

```sql
-- User sessions (5-minute inactivity gap)
CREATE MATERIALIZED VIEW user_sessions AS
SELECT DISTINCT
    user_id,
    session_start,
    session_end,
    orders_in_session,
    session_revenue
FROM (
    SELECT
        user_id,
        FIRST_VALUE(ts) OVER w AS session_start,
        LAST_VALUE(ts) OVER w AS session_end,
        COUNT(*) OVER w AS orders_in_session,
        SUM(qty * price) OVER w AS session_revenue
    FROM orders_raw_with_watermark
    WINDOW w AS (
        PARTITION BY user_id 
        ORDER BY ts
        SESSION WITH GAP INTERVAL '5 MINUTES'
    )
) 
EMIT ON WINDOW CLOSE;
```

**Why EMIT ON WINDOW CLOSE is required:**
- Session windows need to know when a session is complete
- EMIT ON WINDOW CLOSE provides final, immutable session results
- Watermark ensures proper session closure detection

------

## Export to Kafka

**Best for:** Event streaming, downstream services

```sql
CREATE SINK high_value_orders
AS SELECT * FROM orders_enriched WHERE total_amount > 1000
WITH (
    connector = 'kafka',
    topic = 'high_value_orders',
    properties.bootstrap.server = 'message_queue:29092',
    format = 'json'
);
```

### Multi-Destination Pipeline

```sql
-- Same data to 3 destinations
CREATE SINK orders_to_clickhouse FROM orders_enriched WITH (...);
CREATE SINK orders_to_parquet FROM orders_enriched WITH (...);
CREATE SINK orders_to_kafka FROM orders_enriched WITH (...);
```

------

## Best Practices

### Performance

**1. Use materialized views for complex queries:**

```sql
-- ❌ Slow: Recompute every query
SELECT category, SUM(amount) FROM orders GROUP BY category;

-- ✅ Fast: Pre-computed
CREATE MATERIALIZED VIEW category_revenue AS
SELECT category, SUM(amount) AS revenue FROM orders GROUP BY category;
```

**2. Add indexes to dimension tables/MV:**

```sql
CREATE TABLE items (
    item_id INT PRIMARY KEY,  -- Automatic index
    category VARCHAR
);
CREATE INDEX idx_category ON items(category);
```

**3. Use appropriate window sizes:**

- Small windows (1 min) → More overhead, finer granularity
- Large windows (1 hour) → Less overhead, coarser granularity

### Data Quality

```sql
-- Detect data gaps
SELECT 
    window_start,
    COUNT(*) AS record_count
FROM revenue_1min
WHERE window_start >= NOW() - INTERVAL '2 hours'
GROUP BY window_start
HAVING COUNT(*) = 0;

-- Monitor enrichment success
SELECT 
    COUNT(*) AS total_orders,
    COUNT(item_name) AS enriched_orders,
    COUNT(*) - COUNT(item_name) AS missing_enrichment
FROM orders_enriched;
```

------

## Advanced Examples

### CDC from PostgreSQL

Connect RisingWave to PostgreSQL for real-time change data capture (CDC). This allows automatic synchronization of PostgreSQL tables with RisingWave.

**Prerequisites: WAL Level Configuration**

CDC requires PostgreSQL's Write-Ahead Log (WAL) level to be set to `logical` for streaming replication. This is already configured in our `compose.yml`:

```yaml
postgres-external:
  image: docker.arvancloud.ir/library/postgres:18
  command: [ 'postgres', '-c', 'wal_level=logical' ]
```

The `wal_level=logical` setting enables PostgreSQL to stream changes to RisingWave, allowing it to listen to and replicate data changes in real-time.

**Step 1: Create Items Table in PostgreSQL**

First, create the items table in PostgreSQL external database:

```sql
-- Connect to PostgreSQL external
docker exec -it postgres-external psql -U postgres -d external_db

-- Create items table
CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert sample data
INSERT INTO items (name, price) VALUES 
('Laptop', 999.99),
('Mouse', 29.99),
('Keyboard', 79.99),
('Monitor', 299.99),
('Headphones', 149.99);
```

**Step 2: Create Shared Source**

Next, create a shared source that establishes the connection to PostgreSQL:

```sql
-- Create shared CDC source
CREATE SOURCE items_cdc WITH (
    connector = 'postgres-cdc',
    hostname = 'postgres-external',
    port = '5432',
    username = 'postgres',
    password = 'postgres',
    database.name = 'external_db',
    schema.name = 'public'
);
```

**Step 3: Create Table from Source**

Create a table that syncs with the PostgreSQL items table:

```sql
-- Create table that syncs with PostgreSQL items table
CREATE TABLE items_from_postgres (
    id INTEGER PRIMARY KEY,
    name VARCHAR,
    price DECIMAL,
    created_at TIMESTAMP
) FROM items_cdc TABLE 'public.items';
```

**Step 4: Use CDC Data in Stream Processing**

Now you can join CDC data with streaming data:

```sql
-- Create materialized view that combines streaming orders with CDC items
CREATE MATERIALIZED VIEW orders_enriched_v2 AS
SELECT
    o.order_id,
    o.user_id,
    i.name AS item_name,
    i.price AS item_price,
    o.qty,
    o.price AS order_price,
    (o.qty * i.price) AS total_amount,
    o.ts
FROM orders_raw o
LEFT JOIN items_from_postgres i ON o.item_id = i.id;

-- Query the enriched data
SELECT * FROM orders_enriched_v2 ORDER BY ts DESC LIMIT 10;
```

**Testing CDC Updates**

1. Update data in PostgreSQL:
```sql
-- In PostgreSQL
UPDATE items SET name = 'Gaming Laptop' WHERE name = 'Laptop';
```

2. Verify the update appears in RisingWave:
```sql
-- In RisingWave
SELECT * FROM items_from_postgres WHERE name LIKE '%Gaming%';
```

The CDC automatically captures INSERT, UPDATE, and DELETE operations from PostgreSQL and reflects them in real-time in RisingWave through the streaming replication enabled by `wal_level=logical`.

### CDC Monitoring

Monitor the CDC replication status to ensure everything is working correctly:

**Check Replication Slots:**
```bash
# View replication slots in PostgreSQL
docker exec -it postgres-external psql -U postgres -d external_db -c "
SELECT slot_name, active, restart_lsn, confirmed_flush_lsn 
FROM pg_replication_slots;"
```

**Check Publications:**
```bash
# View publications
docker exec -it postgres-external psql -U postgres -d external_db -c "
SELECT pubname, pubinsert, pubupdate, pubdelete 
FROM pg_publication;"
```

**Check Replication Status:**
```bash
# View replication connections
docker exec -it postgres-external psql -U postgres -d external_db -c "
SELECT client_addr, state, sent_lsn, write_lsn 
FROM pg_stat_replication;"
```

**Expected Output:**
```bash
# Replication slots output
slot_name                | active | restart_lsn | confirmed_flush_lsn 
-------------------------+--------+-------------+---------------------
rw_cdc_2cdba1199e244a049a15641780ce64d3 | t      | 0/194C4A0   | 0/194C4A0

# Publications output  
pubname     | pubinsert | pubupdate | pubdelete 
------------+-----------+-----------+-----------
rw_publication | t         | t         | t

# Replication status output
client_addr |   state   | sent_lsn  | write_lsn 
------------+-----------+-----------+-----------
172.18.0.2  | streaming | 0/194C6A8 | 0/194C6A8
```

**Key Indicators:**
- `active: t` - Replication slot is active
- `pubinsert/pubupdate/pubdelete: t` - All operations enabled
- `state: streaming` - Replication is streaming data
- LSN values should be progressing (increasing)

### Complex Fraud Detection

```sql
CREATE MATERIALIZED VIEW fraud_score AS
SELECT 
    user_id,
    window_start,
    
    -- Behavioral signals
    COUNT(*) AS order_count,
    SUM(total_amount) AS total_spent,
    COUNT(DISTINCT item_id) AS unique_items,
    AVG(total_amount) AS avg_order_value,
    
    -- Velocity checks
    COUNT(*) FILTER (WHERE total_amount > 500) AS high_value_orders,
    COUNT(DISTINCT DATE_TRUNC('hour', ts)) AS active_hours,
    
    -- Risk score
    (
        CASE WHEN COUNT(*) > 10 THEN 30 ELSE 0 END +
        CASE WHEN SUM(total_amount) > 5000 THEN 40 ELSE 0 END +
        CASE WHEN COUNT(DISTINCT item_id) > 15 THEN 20 ELSE 0 END +
        CASE WHEN AVG(total_amount) > 500 THEN 10 ELSE 0 END
    ) AS risk_score,
    
    -- Classification
    CASE 
        WHEN (
            COUNT(*) > 10 OR
            SUM(total_amount) > 5000 OR
            COUNT(DISTINCT item_id) > 15
        ) THEN 'HIGH_RISK'
        WHEN COUNT(*) > 5 OR SUM(total_amount) > 2000 THEN 'MEDIUM_RISK'
        ELSE 'LOW_RISK'
    END AS risk_category
    
FROM HOP(orders_enriched, ts, INTERVAL '1 minute', INTERVAL '10 minutes')
GROUP BY user_id, window_start;

-- Alert on high-risk users
SELECT * FROM fraud_score
WHERE risk_category = 'HIGH_RISK'
AND window_start >= NOW() - INTERVAL '15 minutes'
ORDER BY risk_score DESC;
```

------

## Quick Reference

### Common Patterns

```sql
-- Deduplication
SELECT DISTINCT ON (key) * FROM stream ORDER BY key, ts DESC;

-- Enrichment
SELECT s.*, d.field FROM stream s LEFT JOIN dimension d ON s.key = d.key;

-- Tumbling window
SELECT window_start, SUM(value) FROM TUMBLE(stream, ts, INTERVAL '1 min') GROUP BY window_start;

-- Hopping window
SELECT window_start, AVG(value) FROM HOP(stream, ts, INTERVAL '1 min', INTERVAL '5 min') GROUP BY window_start;

-- Session window (requires watermark)
SELECT user_id, COUNT(*) OVER w FROM stream WINDOW w AS (PARTITION BY user_id ORDER BY ts SESSION WITH GAP INTERVAL '5 min');
```

### Useful Commands

```sql
-- List objects
SHOW SOURCES;
SHOW TABLES;
SHOW MATERIALIZED VIEWS;
SHOW SINKS;

-- Describe schema
DESCRIBE SOURCE orders_raw;
DESCRIBE MATERIALIZED VIEW revenue_by_category;

-- Drop objects
DROP SOURCE orders_raw;
DROP MATERIALIZED VIEW revenue_by_category CASCADE;  -- Also drops dependent objects
DROP SINK revenue_to_clickhouse;

-- Check performance
EXPLAIN SELECT * FROM orders_enriched WHERE user_id = 123;
```

### Troubleshooting

```bash
# Check Docker services
docker compose ps

# View RisingWave logs
docker logs risingwave-standalone

# Restart services
docker compose restart risingwave-standalone

# Clean restart (deletes data)
docker compose down -v
docker compose up -d
```

------

## Next Steps

1. **Practice:** Modify the first pipeline example
2. **Explore:** Try different window types
3. **Integrate:** Connect to your own Kafka/PostgreSQL
4. **Learn More:** [RisingWave Documentation](https://docs.risingwave.com/)
5. **Join Community:** [RisingWave Slack](https://risingwave.com/slack)

**Happy Streaming! 🚀**