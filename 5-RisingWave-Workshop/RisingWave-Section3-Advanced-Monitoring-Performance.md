# RisingWave ETL Tutorial - Section 3: Production Essentials

## Table of Contents

1. [Subscriptions](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#subscriptions)
2. [Performance Monitoring & Tuning](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#performance-monitoring--tuning)
3. [Indexes](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#indexes)
4. [Production Deployment](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#production-deployment)
5. [Troubleshooting](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#troubleshooting)
6. [Advanced Use Cases](https://claude.ai/chat/a159a3e8-576a-490d-b82c-e357e36c1719#advanced-use-cases)

------

## Subscriptions

### What is a Subscription?

A **subscription** in RisingWave is a mechanism for consuming change data from tables or materialized views. Think of it as a "listening channel" that captures and delivers data changes as they happen.

![](images\Subscription.png)

### Subscriptions vs Tables vs Materialized Views

| Feature         | Table                | Materialized View             | Subscription                          |
| --------------- | -------------------- | ----------------------------- | ------------------------------------- |
| **Purpose**     | Store data           | Compute & cache query results | Capture & stream changes              |
| **Query**       | Pull on-demand       | Pull pre-computed results     | Push changes to consumers             |
| **Updates**     | Manual INSERT/UPDATE | Automatic incremental updates | Event stream of changes               |
| **Use Case**    | Data storage         | Fast query responses          | Real-time alerting, CDC, event-driven |
| **Data Access** | SELECT queries       | SELECT queries                | Change stream consumption             |

**Key Difference:** Tables and MVs are **pull-based** (you query them), while subscriptions are **push-based** (they send you changes).

### SELECT vs. Subscriptions: From Polling Snapshots to Streaming Changes

To understand why subscriptions are a more effective tool for this task, it's useful to compare them directly with traditional SELECT statements.

| Aspect | SELECT Statement | RisingWave Subscription |
|--------|------------------|-------------------------|
| **Execution Model** | Pull / Request-Response | Persistent Stream |
| | A stateless, one-time query for data. | A stateful, durable stream that a client can connect to and consume from over time. |
| **Data Scope** | Point-in-Time Snapshot | Continuous Incremental Changes |
| | Returns the entire state of the data. | Delivers a stream of individual change events (inserts, updates, deletes) as they happen. |
| **Efficiency for Detecting Changes** | Inefficient | Highly Efficient |
| | Requires re-querying the full dataset. | The database tracks and pushes only the delta, minimizing data transfer and processing. |
| **Primary Use Case** | Ad-hoc querying and reporting. | Building event-driven applications. |

In short, using SELECT to poll for changes is inefficient and complex. A subscription provides a purpose-built, efficient, and reliable mechanism for consuming a continuous stream of updates.

### Building a Real-Time Order Tracker with Subscriptions

Let's walk through a common use case: streaming the results of a materialized view that tracks e-commerce order status updates.

**Order Status Field:**

The orders data includes a `status` field with the following possible values:
- `pending`: Order received but not yet processed
- `processing`: Order is being prepared
- `shipped`: Order has been shipped to customer
- `delivered`: Order has been delivered to customer
- `cancelled`: Order was cancelled

This status field enables real-time tracking of order lifecycle changes through RisingWave subscriptions.

#### Step 0: Create Orders Clean Table with Status Field

First, we need to create a clean orders table with status information. Since the original orders data may not include status, we'll create a materialized view that adds status information:

```sql
-- Create orders_clean materialized view with status field
CREATE MATERIALIZED VIEW orders_clean AS 
SELECT 
    order_id, 
    user_id, 
    item_id, 
    qty, 
    price, 
    total_amount, 
    ts, 
    category, 
    item_name,
    -- Randomly assign status based on order_id for demonstration
    CASE (order_id % 5) 
        WHEN 0 THEN 'pending'
        WHEN 1 THEN 'processing'
        WHEN 2 THEN 'shipped'
        WHEN 3 THEN 'delivered'
        WHEN 4 THEN 'cancelled'
    END AS status
FROM orders_enriched;
```

#### Step 1: Set Up a Materialized View for Live Order Status

Now, let's create a materialized view in RisingWave. This view will always contain the latest status for every single order.

```sql
-- Create a materialized view to track the latest order status
CREATE MATERIALIZED VIEW order_status_updates AS
SELECT order_id, status
FROM orders_clean;
```

#### Step 2: Create a Subscription to Watch for Changes

Now, we can create a subscription on this view. This tells RisingWave we want to be notified of any changes to any order's status.

```sql
-- Create a subscription on our view
CREATE SUBSCRIPTION order_sub 
FROM order_status_updates
WITH ( retention = '24h' );
```

#### Step 3: Fetch the Updates

With our subscription ready, we can start listening for changes. We use a cursor to read the stream of updates. When an order's status is updated, our subscription catches it immediately.

**Note:** In RisingWave, materialized views are read-only and cannot be directly updated with SQL UPDATE statements. Instead, order status changes come from the streaming data source. To test order status updates, use the Kafka producer to generate updated order data.

**Testing Order Status Updates:**

```bash
# Run the order updater to simulate order status changes
python kafka_producer_advanced.py order_updates --max-order-id 1000000 --duration 60 --rate 5
```

This will generate order updates with different status values (pending, processing, shipped, delivered, cancelled) that will flow through your data pipeline and trigger subscription events.

**Example of what you'll see in the subscription:**

```sql
-- First, we declare a cursor to read from our position
DECLARE cur SUBSCRIPTION CURSOR FOR order_sub;

-- Then, we fetch the change
FETCH NEXT FROM cur;

---- RESULT 
order_id | status | op | rw_timestamp
----------+-------------+--------------+----------------- 
90160 | Processing | UpdateDelete | 1678886400000 
90160 | Shipped | UpdateInsert | 1678886400000
(2 rows)
```

As you can see, we didn't get a list of all orders. We only got the exact change that happened—the old status was deleted and the new one was inserted. This is exactly the information our application needs to send a "Your order has shipped!" notification.

**Important:** The order status changes you see in the subscription come from the streaming data source (Kafka), not from direct SQL updates. The order updater tool generates these status changes that flow through your data pipeline.

### Powering an Application: A Python Example

Because subscriptions use the standard Postgres protocol, connecting them to a backend service is easy. Here's how a Python application could listen for these order updates to power a notification service.

```python
import psycopg2
import time

def order_notification_service():
    # Connect to RisingWave
    conn = psycopg2.connect(
        host="localhost", port="4566", user="root", database="dev"
    )
    try:
        cur = conn.cursor()

        # Create a cursor to read from our order subscription
        cur.execute("DECLARE cur SUBSCRIPTION CURSOR FOR order_sub;")

        print("Listening for order updates...")
        while True:
            cur.execute("FETCH NEXT FROM cur;")
            change = cur.fetchone()

            if change:
                # Example change: ('ORD123', 'Shipped', 'UpdateInsert', ...)
                order_id, status, operation = change[0], change[1], change[2]

                # We only care about the new status
                if operation == 'UpdateInsert':
                    print(f"Update detected for {order_id}: status is now {status}. Triggering notification!")
                    # TODO: Add logic here to send an email or push notification
            else:
                # No new updates, wait a second
                time.sleep(1)

    finally:
        print("Closing connection.")
        cur.close()
        conn.close()

if __name__ == "__main__":
    order_notification_service()
```

Save this script as `order_service.py` and run it from your terminal: `python order_service.py`. It will start printing the initial data and then wait for new changes. To see real-time updates, run the order updater tool in another terminal:

```bash
# Terminal 1: Start the notification service
python order_service.py

# Terminal 2: Generate order status updates
python kafka_producer_advanced.py order_updates --max-order-id 1000000 --duration 60 --rate 5
```

You'll see output like this in the notification service:

```
# output in the terminal
Update detected for 90160: status is now Shipped. Triggering notification!
Update detected for 123456: status is now Delivered. Triggering notification!
Update detected for 789012: status is now Cancelled. Triggering notification!
```

### Key Benefits of Using Subscriptions

- **Reduced Architectural Complexity**: Stream data directly from tables or materialized views without needing a separate message broker.
- **Configurable Data Retention**: Changes are retained persistently by the subscription object, with configurable time- or size-based retention policies to ensure even offline clients don't miss data.
- **Built-in State Initialization**: The default cursor behavior provides a full data snapshot, allowing new applications to reliably initialize their state.
- **Client-Controlled Batching**: Efficiently fetch data in batches of any size with the FETCH command, giving you full control over throughput.
- **Broad Compatibility**: Integrates with your existing applications using any language with a standard PostgreSQL driver.

### Order Status Change Subscriptions

You can create subscriptions for order status changes. Note: RisingWave subscriptions capture all changes from the source table/view. To filter by status, you would typically filter the data in your application when consuming from the subscription:

```sql
-- Track all order status changes
CREATE SUBSCRIPTION shipped_orders
FROM order_status_updates
WITH (retention = '24h');

-- Track order completions (filter in application: delivered or cancelled)
CREATE SUBSCRIPTION order_completions
FROM order_status_updates
WITH (retention = '24h');

-- Track high-priority order updates (filter in application: processing or shipped with high value)
CREATE SUBSCRIPTION priority_order_updates
FROM orders_enriched
WITH (retention = '24h');
```

**Note:** To filter subscription data by status or other conditions, apply the filtering logic in your application when consuming from the subscription cursor.

### Basic Subscription Commands

**View All Subscriptions:**

```sql
SHOW SUBSCRIPTIONS;
```

**Check Subscription Status:**

```sql
SELECT 
    subscription_name,
    status,
    consumer_count,
    last_event_time,
    event_count
FROM rw_catalog.rw_subscriptions;
```

**Create a Subscription:**

```sql
CREATE SUBSCRIPTION subscription_name
FROM source_table_or_mv
WHERE condition;
```

**Drop a Subscription:**

```sql
DROP SUBSCRIPTION subscription_name;
```

### Common Use Cases

#### Real-Time Alerting

**High-Value Order Alerts:**

```sql
-- Create subscription
CREATE SUBSCRIPTION high_value_order_alerts
FROM orders_enriched
WHERE total_amount > 10000;

-- Monitor activity
SELECT subscription_name, last_event_time, event_count
FROM rw_catalog.rw_subscriptions
WHERE subscription_name = 'high_value_order_alerts';
```

**Fraud Detection:**

```sql
CREATE SUBSCRIPTION fraud_detection_alerts
FROM user_sessions
WHERE orders_in_session > 10;
```

**Revenue Spikes:**

```sql
CREATE SUBSCRIPTION revenue_spike_alerts
FROM item_revenue_1min
WHERE revenue > 50000;
```

**Customer Risk Monitoring:**

```sql
CREATE SUBSCRIPTION high_risk_trade_alerts
FROM comprehensive_trades
WHERE risk_level = 'High' AND trade_value > 100000;
```



------

## Performance Monitoring & Tuning

### Key Monitoring Queries

**System Health Check:**

```sql
-- Note: Status monitoring may vary by RisingWave version
-- Use SHOW commands for current system status
SHOW MATERIALIZED VIEWS;
SHOW SOURCES;
SHOW SINKS;

-- Alternative: Count available components
SELECT 
    'Materialized Views' AS component,
    COUNT(*) AS total
FROM pg_matviews
UNION ALL
SELECT 'Sources', COUNT(*)
FROM rw_catalog.rw_sources
UNION ALL
SELECT 'Sinks', COUNT(*)
FROM rw_catalog.rw_sinks;
```

**Query Performance:**

```sql
-- Note: Query performance monitoring may vary by RisingWave version
-- Use RisingWave dashboard or system views for query monitoring
-- Alternative: Use EXPLAIN for individual query performance analysis
EXPLAIN SELECT COUNT(*) FROM orders_enriched WHERE ts >= NOW() - INTERVAL '1 hour';
```

**Memory Usage:**

```sql
-- Note: Memory usage monitoring may vary by RisingWave version
-- Check available system views for memory information
SELECT 
    fragment_id,
    parallelism,
    max_parallelism,
    distribution_type
FROM rw_catalog.rw_fragments
ORDER BY fragment_id;
```

**Materialized View Status:**

```sql
-- Note: Materialized view status monitoring may vary by RisingWave version
-- Use SHOW MATERIALIZED VIEWS for current status
SHOW MATERIALIZED VIEWS;

-- Alternative: Check materialized view details
-- Note: Size functions (pg_size_pretty, pg_total_relation_size) not available in current RisingWave version
SELECT 
    matviewname AS view_name,
    schemaname,
    matviewowner,
    hasindexes,
    ispopulated
FROM pg_matviews
ORDER BY matviewname;
```

### Performance Tuning

**Query Optimization:**

```sql
-- Use CTEs instead of subqueries
WITH recent_orders AS (
    SELECT * FROM orders_clean WHERE ts >= NOW() - INTERVAL '1 hour'
)
SELECT user_id, COUNT(*), SUM(total_amount)
FROM recent_orders
GROUP BY user_id;

-- Use window functions
SELECT 
    order_id,
    total_amount,
    LAG(total_amount) OVER (PARTITION BY user_id ORDER BY ts) AS prev_amount
FROM orders_clean;
```

**Materialized View Optimization:**

```sql
-- Design for incremental updates
CREATE MATERIALIZED VIEW user_stats AS
SELECT 
    user_id,
    COUNT(*) AS order_count,
    SUM(total_amount) AS total_spent,
    MAX(ts) AS last_order_time
FROM orders_clean
GROUP BY user_id;

-- Use appropriate window sizes (avoid large windows)
CREATE MATERIALIZED VIEW hourly_revenue AS
SELECT 
    DATE_TRUNC('hour', ts) AS hour,
    SUM(amount) AS revenue
FROM orders
GROUP BY DATE_TRUNC('hour', ts);
```

**CPU Monitoring:**

```sql
-- Note: CPU monitoring may vary by RisingWave version
-- Use RisingWave dashboard or container metrics for CPU monitoring
-- Alternative: Use EXPLAIN for individual query analysis
EXPLAIN SELECT COUNT(*) FROM orders_enriched WHERE ts >= NOW() - INTERVAL '1 hour';
```

### Monitoring Best Practices

**Set Up Alerts For:**

- Materialized view status = FAILED
- Sink delivery failure rate > 5%
- Memory usage > 80% for extended periods
- Query latency exceeds thresholds

**Weekly Performance Review:**

```sql
-- Note: Weekly performance review may vary by RisingWave version
-- Use RisingWave dashboard for comprehensive performance monitoring
-- Alternative: Manual query timing with EXPLAIN ANALYZE
SELECT 
    'Manual monitoring required' AS monitoring_method,
    'Use RisingWave dashboard for performance metrics' AS recommendation;
```

------

## Indexes

### When to Create Indexes

Create indexes for:

1. Frequent WHERE clause filters
2. JOIN operations on non-primary keys
3. ORDER BY on large datasets
4. Range queries on timestamps

### Index Examples

**Orders Table:**

```sql
-- Single column indexes
CREATE INDEX idx_orders_user_id ON orders_clean(user_id);
CREATE INDEX idx_orders_ts ON orders_clean(ts);

-- Composite index for common patterns
CREATE INDEX idx_orders_user_ts ON orders_clean(user_id, ts);

-- Query using the index
SELECT user_id, COUNT(*) as order_count, SUM(qty * price) as total_spent
FROM orders_clean
WHERE user_id = 12345 AND ts >= NOW() - INTERVAL '7 days'
GROUP BY user_id;
```

**Enriched Orders:**

```sql
CREATE INDEX idx_orders_enriched_category ON orders_enriched(category);
CREATE INDEX idx_orders_enriched_item_name ON orders_enriched(item_name);
CREATE INDEX idx_orders_enriched_category_time ON orders_enriched(category, ts);

-- Query using indexes
SELECT category, COUNT(*) as order_count, SUM(total_amount) as revenue
FROM orders_enriched
WHERE category = 'Electronics' AND ts >= NOW() - INTERVAL '1 hour'
GROUP BY category;
```

**Trades Table:**

```sql
CREATE INDEX idx_trades_customer_name ON comprehensive_trades(customer_name);
CREATE INDEX idx_trades_risk_level ON comprehensive_trades(risk_level);
CREATE INDEX idx_trades_trade_time ON comprehensive_trades(trade_time);
CREATE INDEX idx_trades_customer_risk_time 
ON comprehensive_trades(customer_name, risk_level, trade_time);

-- Query using indexes
SELECT customer_name, risk_level, COUNT(*) as trade_count, SUM(trade_value) as total_value
FROM comprehensive_trades
WHERE customer_name = 'Alice Johnson' AND risk_level = 'High'
  AND trade_time >= NOW() - INTERVAL '24 hours'
GROUP BY customer_name, risk_level;
```

### Index Maintenance

**Monitor Effectiveness:**

```sql
SELECT indexname, idx_tup_read, idx_tup_fetch, idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'public';
```

**Find Unused Indexes:**

```sql
SELECT indexname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0;
```

**Rebuild Index:**

```sql
REINDEX INDEX idx_orders_ts;
```

------

## Production Deployment

### High Availability Setup

**Multi-Node Docker Compose:**

```yaml
version: '3.8'
services:
  risingwave-meta:
    image: risingwavelabs/risingwave:latest
    command: 
      - "meta-node"
      - "--listen-addr=0.0.0.0:5690"
      - "--advertise-addr=risingwave-meta:5690"
    ports:
      - "5690:5690"
      - "5691:5691"
    environment:
      - RW_BACKEND_STORAGE_TYPE=postgres
      - RW_BACKEND_STORAGE_CONFIG="host=postgres port=5432 user=postgres password=postgres dbname=risingwave"

  risingwave-compute:
    image: risingwavelabs/risingwave:latest
    command:
      - "compute-node"
      - "--listen-addr=0.0.0.0:5688"
      - "--advertise-addr=risingwave-compute:5688"
      - "--meta-addr=risingwave-meta:5690"
    deploy:
      replicas: 3  # Multiple nodes for HA

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: risingwave
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### Load Balancing

**Nginx Configuration:**

```nginx
upstream risingwave_sql {
    server risingwave-compute:4566;
    server risingwave-compute2:4566;
    server risingwave-compute3:4566;
}

server {
    listen 4566;
    location / {
        proxy_pass http://risingwave_sql;
        proxy_set_header Host $host;
    }
}
```

### Backup & Recovery

**Automated Backup:**

```bash
#!/bin/bash
BACKUP_DIR="/backups/risingwave"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/risingwave_backup_$DATE.sql"

mkdir -p $BACKUP_DIR
docker exec risingwave-meta pg_dump -h postgres -U postgres -d risingwave > $BACKUP_FILE
gzip $BACKUP_FILE
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete
```

**Recovery:**

```bash
#!/bin/bash
BACKUP_FILE="/backups/risingwave/risingwave_backup_20251231_120000.sql.gz"

docker-compose down
gunzip -c $BACKUP_FILE | docker exec -i postgres psql -U postgres -d risingwave
docker-compose up -d
```

### Security

**Network Security:**

```bash
ufw allow 22    # SSH
ufw allow 4566  # RisingWave SQL
ufw allow 5691  # Dashboard
ufw deny 5432   # PostgreSQL (internal only)
```

**User Management:**

```sql
-- Application user
CREATE USER app_user WITH PASSWORD 'secure_password';
GRANT SELECT ON orders_clean TO app_user;
GRANT SELECT ON item_revenue_1min TO app_user;

-- Read-only monitoring user
CREATE USER monitor_user WITH PASSWORD 'monitor_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO monitor_user;
```

### Monitoring

**Prometheus Alerts:**

```yaml
groups:
  - name: risingwave_alerts
    rules:
      - alert: HighMemoryUsage
        expr: risingwave_memory_usage_percent > 80
        for: 5m
        labels:
          severity: warning
      
      - alert: MaterializedViewFailed
        expr: risingwave_materialized_view_status != 1
        for: 1m
        labels:
          severity: critical
```

------

## Troubleshooting

### Performance Issues

**Slow Queries:**

```sql
-- Identify slow queries (use EXPLAIN for individual queries)
-- Note: Query stats may vary by RisingWave version
EXPLAIN SELECT COUNT(*) FROM orders_enriched WHERE ts >= NOW() - INTERVAL '1 hour';

-- Solution: Add indexes
CREATE INDEX idx_slow_query_columns ON table_name(column1, column2);
```

**High Memory:**

```sql
-- Note: Memory monitoring may vary by RisingWave version
-- Use system views or RisingWave dashboard for memory monitoring
SELECT fragment_id, parallelism, max_parallelism, distribution_type
FROM rw_catalog.rw_fragments
ORDER BY fragment_id;
```

### Connectivity Issues

**Source Failures:**

```sql
SELECT source_name, status, error_message, last_error_time
FROM rw_catalog.rw_sources
WHERE status != 'RUNNING';
```

**Sink Failures:**

```sql
SELECT sink_name, status, error_message, delivery_rate
FROM rw_catalog.rw_sinks
WHERE status != 'RUNNING';
```

### Data Quality

**Check for Duplicates:**

```sql
SELECT order_id, COUNT(*) as duplicate_count
FROM orders_clean
GROUP BY order_id
HAVING COUNT(*) > 1;
```

**Check for Gaps:**

```sql
SELECT DATE_TRUNC('hour', ts) as hour, COUNT(*) as record_count
FROM orders_clean
GROUP BY DATE_TRUNC('hour', ts)
ORDER BY hour;
```

### Debugging Tools

**Query Analysis:**

```sql
EXPLAIN ANALYZE 
SELECT item_id, SUM(amount) as total_revenue
FROM orders_clean
WHERE ts >= NOW() - INTERVAL '1 hour'
GROUP BY item_id;
```

**Fragment Analysis:**

```sql
-- Note: Fragment stats may vary by RisingWave version
-- Use system views or RisingWave dashboard for fragment monitoring
SELECT fragment_id, parallelism, max_parallelism, distribution_type
FROM rw_catalog.rw_fragments
ORDER BY fragment_id;
```

**View Logs:**

```bash
docker logs risingwave-standalone
docker logs risingwave-standalone | grep -i error
```

**Monitor Resources:**

```bash
docker stats risingwave-standalone
```

------

## Advanced Use Cases

### Real-Time Dashboards

**Sales Metrics:**

```sql
CREATE MATERIALIZED VIEW dashboard_sales AS
SELECT 
    DATE_TRUNC('minute', ts) AS minute,
    COUNT(*) AS orders_per_minute,
    SUM(qty * price) AS revenue_per_minute,
    AVG(qty * price) AS avg_order_value,
    COUNT(DISTINCT user_id) AS unique_customers
FROM orders_enriched
GROUP BY DATE_TRUNC('minute', ts);
```

**Top Products:**

```sql
CREATE MATERIALIZED VIEW dashboard_top_products AS
SELECT 
    item_name,
    category,
    COUNT(*) AS order_count,
    SUM(qty * price) AS total_revenue
FROM orders_enriched
WHERE ts >= NOW() - INTERVAL '1 hour'
GROUP BY item_name, category
ORDER BY total_revenue DESC
LIMIT 10;
```

### Machine Learning Features

**User Features:**

```sql
CREATE MATERIALIZED VIEW ml_user_features AS
SELECT 
    user_id,
    COUNT(*) AS total_orders,
    SUM(qty * price) AS total_spent,
    AVG(qty * price) AS avg_order_value,
    MAX(ts) - MIN(ts) AS customer_lifetime,
    COUNT(DISTINCT DATE_TRUNC('day', ts)) AS active_days,
    COUNT(*) FILTER (WHERE qty * price > 1000) AS high_value_orders
FROM orders_enriched
GROUP BY user_id;
```

**Product Features:**

```sql
CREATE MATERIALIZED VIEW ml_product_features AS
SELECT 
    item_id,
    item_name,
    category,
    COUNT(*) AS total_orders,
    SUM(qty) AS total_quantity_sold,
    AVG(price) AS avg_price,
    COUNT(DISTINCT user_id) AS unique_customers,
    -- Note: STDDEV not available in current RisingWave version
    -- Alternative: Use range calculation for price volatility
    MAX(price) - MIN(price) AS price_range
FROM orders_enriched
GROUP BY item_id, item_name, category;
```

### Anomaly Detection

**User Spending Anomalies:**

```sql
CREATE MATERIALIZED VIEW anomaly_user_spending AS
SELECT 
    user_id,
    DATE_TRUNC('day', ts) AS day,
    SUM(qty * price) AS daily_spending,
    AVG(SUM(qty * price)) OVER (
        PARTITION BY user_id 
        ORDER BY DATE_TRUNC('day', ts) 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS avg_7day_spending,
    -- Note: STDDEV window function not available in current RisingWave version
    -- Alternative: Use range-based anomaly detection
    MAX(SUM(qty * price)) OVER (
        PARTITION BY user_id 
        ORDER BY DATE_TRUNC('day', ts) 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) - MIN(SUM(qty * price)) OVER (
        PARTITION BY user_id 
        ORDER BY DATE_TRUNC('day', ts) 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS spending_range_7day
FROM orders_enriched
GROUP BY user_id, DATE_TRUNC('day', ts);

-- Flag anomalies (using range-based detection)
CREATE MATERIALIZED VIEW anomaly_flags AS
SELECT 
    user_id,
    day,
    daily_spending,
    avg_7day_spending,
    CASE 
        -- Note: Using range-based detection instead of standard deviation
        WHEN daily_spending > avg_7day_spending + (spending_range_7day * 0.5)
        THEN 'HIGH_ANOMALY'
        WHEN daily_spending < GREATEST(0, avg_7day_spending - (spending_range_7day * 0.5))
        THEN 'LOW_ANOMALY'
        ELSE 'NORMAL'
    END AS anomaly_type
FROM anomaly_user_spending;
```

### Multi-Tenant Architecture

**Tenant-Specific Views:**

```sql
CREATE MATERIALIZED VIEW tenant_sales AS
SELECT 
    -- Note: tenant_id column not available in current data
    -- Alternative: Use default tenant or user segmentation
    'default_tenant' AS tenant_id,
    DATE_TRUNC('day', ts) AS day,
    COUNT(*) AS orders,
    SUM(total_amount) AS revenue,
    COUNT(DISTINCT user_id) AS unique_users
FROM orders_enriched
GROUP BY DATE_TRUNC('day', ts);
```

**Resource Usage Monitoring:**

```sql
CREATE MATERIALIZED VIEW tenant_resource_usage AS
SELECT 
    'default_tenant' AS tenant_id,
    COUNT(*) AS order_count,
    SUM(total_amount) AS revenue,
    COUNT(DISTINCT user_id) AS user_count,
    -- Note: pg_size_pretty not available in current RisingWave version
    -- Alternative: Simple size calculation
    COUNT(*) * 100 AS estimated_storage_bytes
FROM orders_enriched
GROUP BY 'default_tenant';
```

------

## Summary & Best Practices

### Key Concepts

1. **Subscriptions**: Push-based change streams for real-time alerting and event-driven architectures
2. **Performance**: Monitor queries, memory, and fragments; optimize with indexes and efficient MVs
3. **Indexes**: Create for frequent filters, joins, and sorts
4. **Production**: Multi-node setup, backups, security, and monitoring
5. **Troubleshooting**: Use system catalogs, logs, and EXPLAIN ANALYZE

### Production Checklist

**Development:**

- [ ] Use adaptive parallelism
- [ ] Create appropriate indexes
- [ ] Design incremental MVs
- [ ] Monitor fragment graphs

**Testing:**

- [ ] Validate data quality
- [ ] Test under load
- [ ] Verify monitoring
- [ ] Test backup/recovery

**Production:**

- [ ] Multi-node cluster
- [ ] Load balancing
- [ ] Automated backups
- [ ] Alerting configured
- [ ] Security hardened
- [ ] Documentation complete

### Get Started with RisingWave

RisingWave Subscriptions are a game-changer for building modern, event-driven applications. By efficiently streaming only what has changed, you can easily build features like live order tracking, financial data feeds, or real-time monitoring dashboards.

For more detailed information, please refer to the official RisingWave Subscription documentation.

Try RisingWave Today:

- Download the open-sourced version of RisingWave to deploy on your own infrastructure.
- Get started quickly with RisingWave Cloud for a fully managed experience.
- Talk to Our Experts: Have a complex use case or want to see a personalized demo? Contact us to discuss how RisingWave can address your specific challenges.
- Join Our Community: Connect with fellow developers, ask questions, and share your experiences in our vibrant Slack community.
- If you'd like to see a personalized demo or discuss how this could work for your use case, please contact our sales team.

### Next Steps

- RisingWave documentation: https://docs.risingwave.com
- Community forums
- Advanced topics: Lakekeeper, custom connectors
- Performance optimization for scale

**Congratulations!** You now have the knowledge to build and manage production-grade real-time data pipelines with RisingWave.