# RisingWave ETL Tutorial - Section 2: Stream-Stream Joins with PostgreSQL CDC

## Tutorial Overview

This tutorial demonstrates **real-time stream processing with dimensional enrichment** using RisingWave. You'll learn how to:

1. **Set up PostgreSQL CDC** to sync dimension tables (instruments, customers) into RisingWave
2. **Generate streaming trade data** using Kafka producers
3. **Enrich streaming trades** with dimensional data through joins
4. **Create materialized views** for real-time analytics
5. **Monitor and analyze** trading activity with advanced patterns

**Architecture:**

```
PostgreSQL (Dimension Data) → CDC → RisingWave (Dimension Tables)
                                          ↓
Kafka (Trade Stream) ──────────→ RisingWave (Stream Processing)
                                          ↓
                              Enriched Trades (Joins + Analytics)
```

------

## Prerequisites

Ensure your environment is running:

```bash
# Verify services are up
docker ps

# Expected services:
# - postgres (with wal_level=logical)
# - message_queue (Kafka)
# - risingwave
```

**PostgreSQL WAL Configuration:**

Our `compose.yml` already configures PostgreSQL for CDC:

```yaml
postgres:
  image: docker.arvancloud.ir/library/postgres:17
  command: ['postgres', '-c', 'wal_level=logical']
  environment:
    POSTGRES_DB: financial_db
```

The `wal_level=logical` setting enables PostgreSQL to stream changes to RisingWave for real-time data synchronization.

------

## Step 1: Initialize PostgreSQL Dimension Data

### 1.1 Create Dimension Tables in PostgreSQL

Create `init-postgres.sql`:

```sql
-- Financial Instruments (Master Data)
CREATE TABLE instruments (
    instrument_id INT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    currency VARCHAR(3),
    isin VARCHAR(12),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Sample instruments
INSERT INTO instruments VALUES
(1, 'AAPL', 'Apple Inc.', 'Technology', 'USD', 'US0378331005', NOW(), NOW()),
(2, 'MSFT', 'Microsoft Corporation', 'Technology', 'USD', 'US5949181045', NOW(), NOW()),
(3, 'GOOGL', 'Alphabet Inc.', 'Technology', 'USD', 'US02079K3059', NOW(), NOW()),
(4, 'AMZN', 'Amazon.com Inc.', 'Consumer Cyclical', 'USD', 'US0231351067', NOW(), NOW()),
(5, 'TSLA', 'Tesla Inc.', 'Consumer Cyclical', 'USD', 'US88160R1014', NOW(), NOW()),
(6, 'JPM', 'JPMorgan Chase & Co.', 'Financial Services', 'USD', 'US46625H1005', NOW(), NOW()),
(7, 'V', 'Visa Inc.', 'Financial Services', 'USD', 'US92826C8394', NOW(), NOW()),
(8, 'JNJ', 'Johnson & Johnson', 'Healthcare', 'USD', 'US4781601046', NOW(), NOW()),
(9, 'WMT', 'Walmart Inc.', 'Consumer Defensive', 'USD', 'US9311421039', NOW(), NOW()),
(10, 'PG', 'Procter & Gamble Co.', 'Consumer Defensive', 'USD', 'US7427181091', NOW(), NOW());

-- Customer Accounts (Master Data)
CREATE TABLE customer_accounts (
    account_id INT PRIMARY KEY,
    customer_id INT NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    account_type VARCHAR(20),
    status VARCHAR(20),
    balance DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Sample customer accounts
INSERT INTO customer_accounts VALUES
(1001, 1, 'Alice Johnson', 'Checking', 'Active', 5000.00, NOW(), NOW()),
(1002, 2, 'Bob Smith', 'Savings', 'Active', 15000.00, NOW(), NOW()),
(1003, 3, 'Carol Davis', 'Investment', 'Active', 75000.00, NOW(), NOW()),
(1004, 4, 'David Wilson', 'Checking', 'Active', 2500.00, NOW(), NOW()),
(1005, 5, 'Eve Brown', 'Savings', 'Active', 8000.00, NOW(), NOW()),
(1006, 6, 'Frank Miller', 'Investment', 'Active', 120000.00, NOW(), NOW()),
(1007, 7, 'Grace Lee', 'Checking', 'Active', 3500.00, NOW(), NOW()),
(1008, 8, 'Henry Taylor', 'Savings', 'Active', 12000.00, NOW(), NOW()),
(1009, 9, 'Ivy Anderson', 'Investment', 'Active', 45000.00, NOW(), NOW()),
(1010, 10, 'Jack Thompson', 'Checking', 'Active', 6000.00, NOW(), NOW());

-- Risk Categories (Reference Data)
CREATE TABLE risk_categories (
    risk_id INT PRIMARY KEY,
    risk_level VARCHAR(20) NOT NULL,
    description VARCHAR(200),
    threshold_min DECIMAL(10,2),
    threshold_max DECIMAL(10,2)
);

INSERT INTO risk_categories VALUES
(1, 'Low', 'Conservative investment strategy', 0.00, 10000.00),
(2, 'Medium', 'Balanced investment approach', 10000.01, 50000.00),
(3, 'High', 'Aggressive investment strategy', 50000.01, 999999.99);

-- Indexes for better join performance
CREATE INDEX idx_instruments_symbol ON instruments(symbol);
CREATE INDEX idx_instruments_updated_at ON instruments(updated_at);
CREATE INDEX idx_customer_accounts_customer_id ON customer_accounts(customer_id);
CREATE INDEX idx_customer_accounts_updated_at ON customer_accounts(updated_at);
```

### 1.2 Load Data into PostgreSQL

```bash
# Wait for PostgreSQL to be ready
sleep 10

# Initialize dimension tables
docker exec -i postgres psql -U postgres -d financial_db < init-postgres.sql

# Verify data loaded
docker exec -it postgres psql -U postgres -d financial_db -c "SELECT COUNT(*) FROM instruments;"
docker exec -it postgres psql -U postgres -d financial_db -c "SELECT COUNT(*) FROM customer_accounts;"
```

------

## Step 2: Set Up CDC in RisingWave

### 2.1 Create CDC Shared Source

Connect RisingWave to PostgreSQL for real-time change data capture:

```sql
-- Connect to RisingWave
docker exec -it risingwave psql -h localhost -p 4566 -d dev -U root

-- Create shared CDC source for PostgreSQL
CREATE SOURCE financial_cdc WITH (
    connector = 'postgres-cdc',
    hostname = 'postgres-external',
    port = '5432',
    username = 'postgres',
    password = 'postgres',
    database.name = 'external_db',
    schema.name = 'public'
);
```

### 2.2 Create Dimension Tables from CDC Source

Sync PostgreSQL dimension tables into RisingWave:

```sql
-- Instruments dimension table
CREATE TABLE instruments_dim (
    instrument_id INT PRIMARY KEY,
    symbol VARCHAR,
    name VARCHAR,
    category VARCHAR,
    currency VARCHAR,
    isin VARCHAR,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
) FROM financial_cdc TABLE 'public.instruments';

-- Customer accounts dimension table
CREATE TABLE customer_accounts_dim (
    account_id INT PRIMARY KEY,
    customer_id INT,
    customer_name VARCHAR,
    account_type VARCHAR,
    status VARCHAR,
    balance DECIMAL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
) FROM financial_cdc TABLE 'public.customer_accounts';

-- Risk categories reference table
CREATE TABLE risk_categories_dim (
    risk_id INT PRIMARY KEY,
    risk_level VARCHAR,
    description VARCHAR,
    threshold_min DECIMAL,
    threshold_max DECIMAL
) FROM financial_cdc TABLE 'public.risk_categories';
```

### 2.3 Verify CDC Data

```sql
-- Check instruments loaded via CDC
SELECT * FROM instruments_dim LIMIT 5;

-- Check customer accounts
SELECT * FROM customer_accounts_dim LIMIT 5;

-- Check risk categories
SELECT * FROM risk_categories_dim;
```

### 2.4 Troubleshooting CDC Data Type Issues

**Common Issue: Data Type Incompatibility**

If you encounter errors like `Incompatible data type of column`, this is usually due to PostgreSQL data types not mapping directly to RisingWave types.

**Solution:**

1. **Check PostgreSQL column types:**
   ```sql
   -- In PostgreSQL, check the actual column types
   \d instruments
   \d customer_accounts
   ```

2. **Common mappings:**
   - `TIMESTAMPTZ` → `TIMESTAMP`
   - `DECIMAL(p,s)` → `DECIMAL` (without precision)
   - `VARCHAR(n)` → `VARCHAR`
   - `INTEGER` → `INT`

3. **Alternative approach - Create table first, then sync:**
   ```sql
   -- Create table structure manually
   CREATE TABLE instruments_dim (
       instrument_id INT PRIMARY KEY,
       symbol VARCHAR,
       name VARCHAR,
       category VARCHAR,
       currency VARCHAR,
       isin VARCHAR,
       created_at TIMESTAMP,
       updated_at TIMESTAMP
   );

   -- Then sync data using INSERT SELECT
   INSERT INTO instruments_dim 
   SELECT instrument_id, symbol, name, category, currency, isin, created_at, updated_at
   FROM financial_cdc TABLE 'public.instruments';
   ```

**RisingWave Data Type Compatibility Guide:**

When creating sources or tables in RisingWave, use these compatible data types:

| PostgreSQL Type | RisingWave Type | Notes |
|-----------------|-----------------|-------|
| `TIMESTAMPTZ` | `TIMESTAMP` | Timestamp with timezone not supported |
| `NUMERIC(p,s)` | `DECIMAL` | Precision/scale not supported |
| `DECIMAL(p,s)` | `DECIMAL` | Precision/scale not supported |
| `VARCHAR(n)` | `VARCHAR` | Length specification ignored |
| `INTEGER` | `INT` | |
| `BIGINT` | `BIGINT` | |
| `BOOLEAN` | `BOOLEAN` | |
| `TEXT` | `VARCHAR` | |

------

## Step 3: Set Up Kafka Streaming Data

### 3.1 Start Trade Stream Producer

In a **separate terminal**, start the advanced Kafka producer for financial trades:

```bash
# Terminal 1: Generate trade stream
python kafka_producer_advanced.py trades --rate 50 --duration 300

# This generates:
# - 50 trades per second
# - To 'trades' Kafka topic
# - For 5 minutes (300 seconds)
```

**Sample Trade Message:**

```json
{
  "trade_id": 4567891,
  "symbol": "AAPL",
  "price": 152.35,
  "volume": 1250,
  "side": "BUY",
  "exchange": "NASDAQ",
  "trader_id": "trader_0456",
  "ts": "2025-12-31T19:46:15.000Z"
}
```

### 3.2 Create Trade Source in RisingWave

```sql
-- Create Kafka source for trade stream
CREATE SOURCE trades_raw (
    trade_id BIGINT,
    symbol VARCHAR,
    price DECIMAL,
    volume INT,
    side VARCHAR,
    exchange VARCHAR,
    trader_id VARCHAR,
    ts TIMESTAMP
) WITH (
    connector = 'kafka',
    topic = 'trades',
    properties.bootstrap.server = 'message_queue:29092',
    scan.startup.mode = 'earliest'
) FORMAT PLAIN ENCODE JSON;
```

### 3.3 Verify Trade Stream

```sql
-- Check incoming trades
SELECT * FROM trades_raw LIMIT 10;

-- Count trades
SELECT COUNT(*) FROM trades_raw;
```

------

## Step 4: Create Stream-Stream Joins

### 4.1 Basic Stream-Table Join: Enrich Trades with Instrument Data

```sql
-- Join trade stream with instruments dimension
CREATE MATERIALIZED VIEW enriched_trades AS
SELECT 
    t.trade_id,
    t.symbol,
    i.name AS instrument_name,
    i.category AS instrument_category,
    i.currency,
    i.isin,
    t.price,
    t.volume,
    (t.price * t.volume) AS trade_value,
    t.side,
    t.exchange,
    t.trader_id,
    t.ts AS trade_time
FROM trades_raw t
LEFT JOIN instruments_dim i ON t.symbol = i.symbol;
```

### 4.2 Query Enriched Trades

```sql
-- View recent enriched trades
SELECT 
    trade_id,
    instrument_name,
    instrument_category,
    side,
    price,
    volume,
    trade_value,
    exchange,
    trade_time
FROM enriched_trades
ORDER BY trade_time DESC
LIMIT 20;
```

**Expected Output:**

```
 trade_id |    instrument_name    | instrument_category | side | price  | volume | trade_value | exchange |           trade_time
----------+-----------------------+---------------------+------+--------+--------+-------------+----------+-------------------------------
  5582879 | Microsoft Corporation | Technology          | SELL | 206.38 |   7328 |  1512352.64 | CBOE     | 2025-12-31 19:40:02.543881+00
  5323569 | Apple Inc.            | Technology          | SELL | 197.65 |   5431 |  1073437.15 | NYSE     | 2025-12-31 19:40:02.453223+00
```

------

## Step 5: Real-Time Analytics with Materialized Views

### 5.1 Trading Volume by Category

```sql
-- Real-time trading volume by instrument category
CREATE MATERIALIZED VIEW trading_by_category AS
SELECT 
    instrument_category,
    COUNT(*) AS trade_count,
    SUM(volume) AS total_volume,
    SUM(trade_value) AS total_value,
    AVG(price) AS avg_price,
    MIN(price) AS min_price,
    MAX(price) AS max_price
FROM enriched_trades
WHERE trade_time >= NOW() - INTERVAL '1 hour'
GROUP BY instrument_category;
```

### 5.2 Top Traders Analysis

```sql
-- Top traders by trading volume
CREATE MATERIALIZED VIEW top_traders AS
SELECT 
    trader_id,
    COUNT(*) AS trade_count,
    SUM(trade_value) AS total_volume,
    COUNT(DISTINCT symbol) AS instruments_traded,
    AVG(volume) AS avg_trade_size,
    MAX(trade_time) AS last_trade_time
FROM enriched_trades
WHERE trade_time >= NOW() - INTERVAL '24 hours'
GROUP BY trader_id
ORDER BY total_volume DESC
LIMIT 100;
```

### 5.3 Query Analytics

```sql
-- Query trading volume by category
SELECT * FROM trading_by_category ORDER BY total_value DESC;

-- Query top traders
SELECT * FROM top_traders LIMIT 10;
```

**Expected Output:**

```sql
-- Trading by category
 instrument_category | trade_count | total_volume |  total_value  |      avg_price
---------------------+-------------+--------------+---------------+--------------------
 Technology          |        3811 |     19149583 | 5279354354.46 | 275.27

-- Top traders
  trader_id  | trade_count | total_volume | instruments_traded | avg_trade_size
-------------+-------------+--------------+--------------------+----------------
 trader_0310 |          14 |  29066789.24 |                  3 |         6358.07
 trader_0802 |          12 |  27478584.28 |                  3 |         6629.08
```

------

## Step 6: Advanced Stream-Stream Join Patterns

### 6.1 Multi-Table Join: Comprehensive Trade Analysis

```sql
-- Join trades with multiple dimension tables
CREATE MATERIALIZED VIEW comprehensive_trades AS
SELECT 
    t.trade_id,
    t.symbol,
    i.name AS instrument_name,
    i.category AS instrument_category,
    i.currency,
    t.price,
    t.volume,
    (t.price * t.volume) AS trade_value,
    t.side,
    t.exchange,
    t.trader_id,
    -- Risk categorization based on trade value
    CASE 
        WHEN (t.price * t.volume) <= 10000 THEN 'Low'
        WHEN (t.price * t.volume) <= 50000 THEN 'Medium'
        ELSE 'High'
    END AS risk_level,
    t.ts AS trade_time
FROM trades_raw t
LEFT JOIN instruments_dim i ON t.symbol = i.symbol;
```

### 6.2 Risk Analysis

```sql
-- Real-time risk monitoring
CREATE MATERIALIZED VIEW risk_analysis AS
SELECT 
    risk_level,
    COUNT(*) AS trade_count,
    SUM(trade_value) AS total_value,
    AVG(trade_value) AS avg_trade_value,
    COUNT(DISTINCT trader_id) AS unique_traders
FROM comprehensive_trades
WHERE trade_time >= NOW() - INTERVAL '1 hour'
GROUP BY risk_level;
```

### 6.3 Query Risk Analysis

```sql
-- View risk distribution
SELECT * FROM risk_analysis ORDER BY total_value DESC;

-- High-risk trades in last hour
SELECT 
    instrument_name,
    trader_id,
    trade_value,
    side,
    trade_time
FROM comprehensive_trades
WHERE risk_level = 'High'
  AND trade_time >= NOW() - INTERVAL '1 hour'
ORDER BY trade_value DESC
LIMIT 20;
```

------

## Step 7: Testing CDC Updates

### 7.1 Update Dimension Data in PostgreSQL

```bash
# Update instrument name in PostgreSQL
docker exec -it postgres psql -U postgres -d financial_db -c \
  "UPDATE instruments SET name = 'Apple Computer Inc.', updated_at = NOW() WHERE symbol = 'AAPL';"
```

### 7.2 Verify CDC Propagation in RisingWave

```sql
-- Check updated instrument name
SELECT * FROM instruments_dim WHERE symbol = 'AAPL';

-- Verify new trades use updated name
SELECT 
    instrument_name,
    symbol,
    COUNT(*) AS trade_count
FROM enriched_trades
WHERE symbol = 'AAPL'
  AND trade_time >= NOW() - INTERVAL '5 minutes'
GROUP BY instrument_name, symbol;
```

**Expected Result:** The instrument name should update automatically in all subsequent trade enrichments.

------

## Step 8: Stream-Stream Join with Returns Data

### 8.1 Understanding Returns in Financial Context

**Returns** = Trade reversals, refunds, or cancellations (not investment returns)

- Trade cancellations
- Customer-requested refunds
- Compliance-driven corrections

### 8.2 Start Returns Producer

```bash
# Terminal 2: Generate returns stream
python kafka_producer_advanced.py returns --rate 10 --duration 120

# This generates:
# - 10 returns per second
# - To 'returns' Kafka topic
# - For 2 minutes
```

**Sample Return Message:**

```json
{
  "return_id": 1001,
  "order_id": 1234567,
  "refund_amount": 76175.00,
  "reason": "Client requested cancellation",
  "ts": "2025-12-31T19:46:15.000Z"
}
```

### 8.3 Create Returns Source

```sql
-- Create Kafka source for returns
CREATE SOURCE returns_raw (
    return_id BIGINT,
    order_id BIGINT,  -- Links to trade_id
    refund_amount DECIMAL,
    reason VARCHAR,
    ts TIMESTAMP
) WITH (
    connector = 'kafka',
    topic = 'returns',
    properties.bootstrap.server = 'message_queue:29092',
    scan.startup.mode = 'earliest'
) FORMAT PLAIN ENCODE JSON;
```

### 8.4 Net Trading Volume Calculation

```sql
-- Calculate net trading volume (trades - returns)
CREATE MATERIALIZED VIEW net_trading_volume AS
SELECT 
    et.instrument_category,
    COUNT(et.trade_id) AS total_trades,
    COUNT(r.return_id) AS total_returns,
    COUNT(et.trade_id) - COUNT(r.return_id) AS net_trades,
    SUM(et.trade_value) AS gross_volume,
    COALESCE(SUM(r.refund_amount), 0) AS refund_volume,
    SUM(et.trade_value) - COALESCE(SUM(r.refund_amount), 0) AS net_volume
FROM enriched_trades et
LEFT JOIN returns_raw r ON et.trade_id = r.order_id
GROUP BY et.instrument_category;
```

### 8.5 Query Net Volume

```sql
-- View net trading volume by category
SELECT 
    instrument_category,
    net_trades,
    gross_volume,
    refund_volume,
    net_volume,
    ROUND((refund_volume * 100.0 / NULLIF(gross_volume, 0)), 2) AS return_rate_percent
FROM net_trading_volume
ORDER BY net_volume DESC;
```

------

## Step 9: Windowed Aggregations

### 9.1 Tumbling Window: 5-Minute Trade Aggregations

```sql
-- Create 5-minute tumbling window aggregation
CREATE MATERIALIZED VIEW trades_5min_window AS
SELECT 
    symbol,
    window_start,
    window_end,
    COUNT(*) AS trade_count,
    SUM(volume) AS total_volume,
    SUM(price * volume) AS total_value,
    AVG(price) AS avg_price,
    MIN(price) AS min_price,
    MAX(price) AS max_price
FROM TUMBLE(trades_raw, ts, INTERVAL '5 minutes')
GROUP BY symbol, window_start, window_end;
```

### 9.2 Query Windowed Data

```sql
-- View recent 5-minute windows
SELECT 
    symbol,
    window_start,
    window_end,
    trade_count,
    total_value,
    avg_price
FROM trades_5min_window
ORDER BY window_end DESC
LIMIT 20;
```

------

## Summary

### What You've Learned

✅ **PostgreSQL CDC Setup**: Configure `wal_level=logical` and create CDC sources
 ✅ **Dimension Table Sync**: Use CDC to populate RisingWave dimension tables
 ✅ **Stream Processing**: Ingest trade data from Kafka
 ✅ **Stream-Table Joins**: Enrich streaming trades with dimensional data
 ✅ **Multi-Table Joins**: Combine multiple dimension tables for comprehensive analysis
 ✅ **Real-Time Analytics**: Create materialized views for instant insights
 ✅ **Stream-Stream Joins**: Join trades with returns for net volume calculations
 ✅ **Windowed Aggregations**: Use tumbling windows for time-based analytics
 ✅ **CDC Updates**: Automatically propagate PostgreSQL changes to RisingWave

### Key Concepts

1. **CDC (Change Data Capture)**: Automatically sync PostgreSQL tables to RisingWave
2. **Stream-Table Join**: Enrich streaming data with slowly-changing dimensions
3. **Stream-Stream Join**: Combine two real-time streams (trades + returns)
4. **Materialized Views**: Pre-computed results that update automatically
5. **Windowed Aggregations**: Time-based grouping for analytics

### Next Steps

- **Section 3**: Advanced topics including Lakekeeper, production deployment, and performance tuning
- **Explore**: Add more producers (IoT sensors, user activity) for multi-stream joins
- **Optimize**: Implement advanced watermark strategies and sink configurations