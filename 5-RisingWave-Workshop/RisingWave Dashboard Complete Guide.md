# RisingWave Dashboard Complete Guide (Port 5691)

## Table of Contents

1. [Overview](https://claude.ai/chat/e71852b3-85c8-4f3e-9791-29364718937d#overview)
2. [Catalog Menu Items](https://claude.ai/chat/e71852b3-85c8-4f3e-9791-29364718937d#catalog-menu-items)
3. [Understanding Fragments](https://claude.ai/chat/e71852b3-85c8-4f3e-9791-29364718937d#understanding-fragments)
4. [Fragment Details Deep Dive](https://claude.ai/chat/e71852b3-85c8-4f3e-9791-29364718937d#fragment-details-deep-dive)
5. [Quick Reference](https://claude.ai/chat/e71852b3-85c8-4f3e-9791-29364718937d#quick-reference)

------

## Overview

The RisingWave Dashboard at `http://localhost:5691` provides a web-based UI for monitoring and managing your streaming database. The **Catalog** section shows all objects in your RisingWave cluster.

------

## Catalog Menu Items

### 1. 🔌 Sources

**What it is:** External data ingestion points that continuously read data into RisingWave.

**Purpose:**

- Connect to external systems (Kafka, PostgreSQL, MySQL, S3, etc.)
- Define schemas for incoming streaming data
- Configure how data is read (format, encoding, starting position)

**What you'll see:**

- List of all active sources
- Source type (Kafka, PostgreSQL, Kinesis, etc.)
- Schema/columns defined
- Connection properties

**Example from your tutorial:**

```sql
CREATE SOURCE orders_raw (
    order_id BIGINT,
    user_id BIGINT,
    ...
) WITH (
    connector = 'kafka',
    topic = 'orders',
    properties.bootstrap.server = 'message_queue:29092'
) FORMAT PLAIN ENCODE JSON;
```

**Use this page to:**

- Verify sources are connected and running
- Check source schemas
- Monitor ingestion status
- Debug connection issues

------

### 2. 📋 Tables

**What it is:** Traditional database tables that store persistent data (not streaming).

**Purpose:**

- Store static/reference data (dimension tables)
- Manual data insertion/updates
- Join with streaming data for enrichment

**What you'll see:**

- List of all tables
- Table schemas
- Row counts (if applicable)
- Primary keys and indexes

**Example from your tutorial:**

```sql
CREATE TABLE items (
    item_id INT PRIMARY KEY,
    item_name VARCHAR,
    category VARCHAR
);
```

**Use this page to:**

- View table structures
- Check dimension tables
- Verify static reference data
- See table dependencies

**Key difference from Sources:** Tables are static storage; Sources are streaming inputs.

------

### 3. 🔄 Materialized Views

**What it is:** **The core of RisingWave!** Continuously updated query results that are incrementally maintained.

**Purpose:**

- Define real-time transformations
- Perform aggregations, joins, windowing
- Store preprocessed results for fast queries
- Automatically update as source data changes

**What you'll see:**

- List of all materialized views
- SQL definitions
- Dependencies (what sources/tables they use)
- Update status and progress

**Examples from your tutorial:**

```sql
-- Deduplication
CREATE MATERIALIZED VIEW orders_clean AS ...

-- Windowed aggregation
CREATE MATERIALIZED VIEW item_revenue_1min AS ...

-- Session detection
CREATE MATERIALIZED VIEW true_sessions AS ...
```

**Use this page to:**

- **Monitor view health** - Check if views are updating properly
- **View dependencies** - See what upstream sources/tables each view uses
- **Debug performance** - Identify slow or stuck views
- **Understand data flow** - Visualize your transformation pipeline

**💡 This is your most important page** - materialized views are where the magic happens!

------

### 4. 🔍 Indexes

**What it is:** Secondary indexes to speed up queries on tables and materialized views.

**Purpose:**

- Improve query performance
- Enable faster lookups on specific columns
- Similar to traditional database indexes

**What you'll see:**

- List of all indexes
- Which table/view they index
- Indexed columns
- Index type

**Example:**

```sql
CREATE INDEX idx_user_orders ON orders_clean(user_id);
```

**Use this page to:**

- Check existing indexes
- Verify index creation
- Monitor index status

**Note:** RisingWave automatically optimizes many queries, so you may not need many indexes.

------

### 5. 🔧 Internal Tables

**What it is:** System tables used internally by RisingWave for state management.

**Purpose:**

- Store intermediate computation states
- Maintain materialized view states
- Internal RisingWave bookkeeping

**What you'll see:**

- System-generated table names (often with prefixes)
- Internal state storage
- Memory/storage usage

**Use this page to:**

- **Debug state issues** - Check if internal state is growing unexpectedly
- **Monitor resource usage** - See how much storage your views consume
- **Advanced troubleshooting** - Investigate state-related problems

**⚠️ Warning:** Generally, you don't manually interact with internal tables. They're managed automatically by RisingWave.

------

### 6. 📤 Sinks

**What it is:** Destinations where RisingWave writes processed data to external systems.

**Purpose:**

- Export results to Kafka, PostgreSQL, MySQL, ClickHouse, etc.
- Send alerts or notifications
- Integrate with downstream systems
- Build data pipelines

**What you'll see:**

- List of all sinks
- Sink type (Kafka, PostgreSQL, etc.)
- Which materialized view/table is being exported
- Connection configuration

**Example:**

```sql
CREATE SINK orders_to_clickhouse FROM orders_enriched
WITH (
    connector = 'jdbc',
    jdbc.url = 'jdbc:clickhouse://clickhouse:8123/analytics'
);
```

**Use this page to:**

- Verify sinks are running
- Monitor export status
- Check connection health
- Debug delivery issues

**Data flow:** `Source → Materialized View → Sink → External System`

------

### 7. 👁️ Views

**What it is:** Regular SQL views (non-materialized) that define virtual tables.

**Purpose:**

- Create logical abstractions over data
- Simplify complex queries
- No data is stored (computed on-the-fly)

**What you'll see:**

- List of regular views
- View definitions (SQL)
- Dependencies

**Example:**

```sql
CREATE VIEW recent_orders AS
SELECT * FROM orders_clean
WHERE ts >= NOW() - INTERVAL '1 hour';
```

**Key difference from Materialized Views:**

- **Views:** Query is executed each time you SELECT from it (not stored)
- **Materialized Views:** Results are pre-computed and continuously updated (stored)

**Use this page to:**

- Check view definitions
- See logical abstractions
- Verify view queries

**💡 Tip:** In RisingWave, you'll mostly use Materialized Views for performance.

------

### 8. 📮 Subscriptions

**What it is:** A way to consume changes from materialized views or tables as a stream.

**Purpose:**

- Subscribe to data changes
- Consume updates as they happen
- Build event-driven applications
- Get notifications of new/changed data

**What you'll see:**

- Active subscriptions
- Which view/table is being subscribed to
- Subscription configuration

**Example:**

```sql
CREATE SUBSCRIPTION high_value_orders_sub
FROM orders_enriched
WHERE total_amount > 1000;
```

**Use this page to:**

- Monitor active subscriptions
- Check subscription consumers
- Verify change data capture (CDC) setup

**Use case:** When you want to react to data changes in real-time (e.g., send alerts when high-value orders appear).

------

## Understanding Fragments

### What are Fragments?

**Fragments** are the fundamental units of distributed execution in RisingWave. Think of them as **pieces of your query execution plan** that are distributed across compute nodes for parallel processing.

#### Simple Analogy

Imagine you have a factory assembly line:

- The **entire assembly line** = Your materialized view
- Each **workstation** = A fragment
- Each workstation can have **multiple workers** = Parallelism within fragments

### Why Fragments Exist

RisingWave breaks down your SQL queries into fragments to:

1. **Enable parallelism** - Process data in parallel across multiple CPU cores
2. **Distribute work** - Spread computation across multiple compute nodes
3. **Scale horizontally** - Add more nodes to handle more data
4. **Optimize performance** - Each fragment handles a specific part of the query

### How Fragments Are Created

When you create a materialized view, RisingWave:

1. **Parses your SQL query**
2. **Creates an execution plan** (like a traditional database)
3. **Breaks the plan into fragments** based on operators (scan, filter, join, aggregate, etc.)
4. **Distributes fragments** across available compute nodes

#### Example: Simple Aggregation

```sql
CREATE MATERIALIZED VIEW item_revenue_1min AS
SELECT 
    item_id,
    window_start,
    SUM(qty * price) AS revenue,
    COUNT(*) AS order_count
FROM TUMBLE(orders_clean, ts, INTERVAL '1 minute')
GROUP BY item_id, window_start;
```

**This might create 3 fragments:**

```
Fragment 1: Source Scan
    ↓ (reads from orders_clean)
    
Fragment 2: Window Operation + Local Aggregation
    ↓ (assigns windows, computes partial aggregates)
    
Fragment 3: Global Aggregation + Materialize
    ↓ (combines partial results, stores final output)
```

### Fragment Properties You See in the UI

#### 1. **Fragment ID**

- Unique identifier for each fragment
- Usually shown as `Fragment #1234`

#### 2. **Fragment Type**

Common fragment types:

- **Source** - Reads data from external sources (Kafka, PostgreSQL, etc.)
- **Materialize** - Writes results to storage for query access
- **StreamScan** - Reads from upstream materialized views
- **StreamFilter** - Applies WHERE conditions
- **StreamProject** - Selects/transforms columns
- **StreamHashAgg** - Hash-based aggregation (GROUP BY)
- **StreamHashJoin** - Hash join operations
- **StreamTopN** - Limits results (ORDER BY ... LIMIT)
- **StreamDynamicFilter** - Runtime filters

#### 3. **Parallelism (Degree of Parallelism - DOP)**

- Number of parallel workers for this fragment
- Higher parallelism = more CPU cores used
- Example: "Parallelism: 4" means 4 concurrent workers

#### 4. **State Size**

- Amount of data stored by this fragment
- Important for stateful operators (aggregations, joins, windows)
- Large state = more memory/storage usage

#### 5. **Distribution Strategy**

How data is distributed across parallel workers:

- **Hash** - Data partitioned by key (common for GROUP BY)
- **Single** - All data goes to one worker (no parallelism)
- **Broadcast** - All data sent to all workers (small tables in joins)

### Fragment States

Each fragment can be in different states:

- **RUNNING** ✅ - Processing data normally
- **CREATING** 🔄 - Being initialized
- **PAUSED** ⏸️ - Temporarily stopped
- **FAILED** ❌ - Error occurred
- **CANCELLED** 🚫 - Manually stopped

### Why You Should Care About Fragments

#### 1. **Performance Tuning**

- See where bottlenecks occur
- Check if parallelism is properly utilized
- Identify expensive operations

#### 2. **Resource Monitoring**

- Track memory usage per fragment
- See CPU utilization across fragments
- Understand state storage requirements

#### 3. **Debugging**

- Identify which fragment is failing
- Check data flow between fragments
- Diagnose performance issues

#### 4. **Scalability Planning**

- Understand how queries distribute across nodes
- Plan for horizontal scaling
- Optimize parallelism settings

------

## Fragment Details Deep Dive

When you click on a materialized view, table, or sink in the dashboard and click "Fragments", you see the **complete execution plan** and **distributed architecture** for that object.

### Section 1: Streaming Jobs

```
Streaming Jobs
(6) orders_raw
(8) orders_clean
(11) items
(12) orders_enriched
(19) item_revenue_1min
...
```

**What it means:**

- **List of all related streaming jobs** in your cluster
- **Numbers in parentheses** = Job IDs (internal identifiers)
- **Clickable links** to navigate between related objects

**Why it's useful:**

- See all materialized views, sources, and tables in your pipeline
- Understand dependencies between objects
- Quick navigation between related streaming jobs

------

### Section 2: Information

```
Type: Table / MV
Status: Created
Parallelism: Adaptive
Max Parallelism: 256
```

#### Fields Explained:

**Type:**

- **Table** - Static storage table
- **MV** (Materialized View) - Continuously updated query result
- **Source** - External data connector
- **Sink** - External data export
- **Index** - Secondary index

**Status:**

- **Created** ✅ - Successfully created and running
- **Creating** 🔄 - Currently being initialized
- **Failed** ❌ - Error occurred during creation
- **Paused** ⏸️ - Temporarily stopped

**Parallelism:**

- **Adaptive** - RisingWave automatically adjusts based on load (recommended)
- **Fixed** - Manually set parallelism (e.g., 4, 8, 16)
- **Custom** - Advanced custom configuration

**Adaptive is best** - RisingWave dynamically scales workers based on:

- Data volume
- Available CPU cores
- Cluster resources

**Max Parallelism:**

- Maximum number of parallel workers allowed
- Default: Usually 256
- Prevents excessive resource consumption

------

### Section 3: Fragments List

```
Fragments
Fragment 3
Fragment 2
```

**What it means:**

- **List of execution fragments** that make up this object
- Each fragment is a **distinct processing stage**
- Click on individual fragments to see details

------

### Section 4: Fragment Graph (The Most Important!)

```
Fragment Graph

Fragment 2
  Actor 5, 6, 7, 8
  hash
  Dispatchers
    materialize
    appendOnly
    groupTopN
    merge

Fragment 3
  Actor 10, 11, 12, 9
  hash
  Dispatcher
    project
    rowIdGen
    source
    Backfill
```

This is a **visual representation** of how data flows through your execution plan.

#### Understanding Fragment Graph Components:

##### **Actors**

```
Actor 5, 6, 7, 8
```

- **Actors** = Individual parallel workers executing the fragment
- In this case: **4 actors** = parallelism of 4
- Each actor processes a partition of the data

**Think of actors as:**

- Multiple checkout lanes at a grocery store
- Each lane (actor) processes different customers (data) in parallel

##### **Distribution Strategy**

```
hash
```

Common strategies:

- **hash** - Data distributed by hash of a key (for GROUP BY, JOIN)
- **broadcast** - All data sent to all actors (small dimension tables)
- **single** - All data goes to one actor (no parallelism)
- **simple** - Round-robin distribution

##### **Dispatchers**

```
Dispatchers
  materialize
  appendOnly
  groupTopN
  merge
```

**Dispatchers send data to the next fragment.** Common types:

- **Hash Dispatcher** - Distributes by hash key
- **Broadcast Dispatcher** - Sends to all downstream actors
- **Simple Dispatcher** - Round-robin
- **No Dispatcher** - Terminal fragment (no downstream)

##### **Operators**

These are the **actual operations** performed in each fragment:

**Source Operators:**

- **source** - Read from external source (Kafka, PostgreSQL, etc.)
- **streamScan** - Read from upstream materialized view
- **Backfill** - Initial historical data load

**Transformation Operators:**

- **project** - SELECT columns, apply expressions
- **filter** - WHERE conditions
- **rowIdGen** - Generate unique row IDs

**Aggregation Operators:**

- **hashAgg** - Hash-based aggregation (GROUP BY)
- **merge** - Combine partial aggregates
- **groupTopN** - Top-N within groups (ORDER BY ... LIMIT per group)
- **topN** - Global top-N (ORDER BY ... LIMIT)

**Join Operators:**

- **hashJoin** - Hash join
- **lookup** - Lookup join (for tables)
- **dynamicFilter** - Runtime filter optimization

**Window Operators:**

- **window** - Window function evaluation
- **watermark** - Watermark generation for event time

**Output Operators:**

- **materialize** - Write results to storage
- **appendOnly** - Append-only sink (no updates)
- **sink** - External sink output

------

### Real-World Example Interpretation

Let's decode the example:

```
Fragment 2 (Output)
  Actor 5, 6, 7, 8
  hash
  Dispatchers
    materialize
    appendOnly
    groupTopN
    merge

Fragment 3 (Input)
  Actor 10, 11, 12, 9
  hash
  Dispatcher
    project
    rowIdGen
    source
    Backfill
```

#### What's happening:

**Fragment 3 (Bottom/Source):**

1. **Operators:** `source`, `Backfill`, `rowIdGen`, `project`
   - Reads data from a source (Kafka/DB)
   - Backfills historical data
   - Generates row IDs
   - Projects/selects columns
2. **Actors:** 10, 11, 12, 9 (4 parallel workers)
3. **Distribution:** `hash` - data partitioned by key
4. **Sends data to:** Fragment 2 (via hash dispatcher)

**Fragment 2 (Top/Output):**

1. **Receives data from:** Fragment 3
2. **Operators:** `merge`, `groupTopN`, `appendOnly`, `materialize`
   - Merges data from Fragment 3's actors
   - Performs top-N aggregation per group
   - Appends results (no updates)
   - Materializes final results to storage
3. **Actors:** 5, 6, 7, 8 (4 parallel workers)
4. **Distribution:** `hash` - results partitioned by group key
5. **Output:** Stored as queryable materialized view

#### Data Flow:

```
External Source (Kafka/DB)
         ↓
Fragment 3: Read → Transform → Partition by hash
         ↓ (hash dispatch)
Fragment 2: Merge → Aggregate (TopN) → Store
         ↓
Materialized View (queryable results)
```

------

### How to Read the Fragment Graph

#### Step-by-Step:

1. **Start from the bottom** - Usually source fragments
2. **Follow the arrows/connections** - Data flow direction
3. **Read operators bottom-to-up** - Order of execution
4. **Count actors** - Parallelism level
5. **Check distribution** - How data is partitioned
6. **Identify bottlenecks** - Single-actor fragments or large states

#### Example Analysis:

```
Fragment 2 (4 actors, hash)
├── hashAgg      ← Aggregation (stateful, may use memory)
├── merge        ← Combines partial results
└── materialize  ← Writes to storage

Fragment 3 (4 actors, hash)  
├── streamScan   ← Reads from upstream MV
├── filter       ← Applies WHERE clause
└── project      ← Selects columns
```

**Interpretation:**

- 4-way parallelism throughout
- Hash distribution ensures same keys go to same actors
- Aggregation happens in Fragment 2 (watch memory here)
- Good parallelism balance (both fragments have 4 actors)

------

### Common Fragment Patterns

#### Pattern 1: Simple Table Scan

```
Fragment 1
  source → rowIdGen → materialize
```

#### Pattern 2: Aggregation

```
Fragment 2: merge → hashAgg → materialize
           ↑
Fragment 1: source → project → filter
```

#### Pattern 3: Join

```
Fragment 3: hashJoin → project → materialize
           ↑         ↑
Fragment 1: source   Fragment 2: streamScan
```

#### Pattern 4: Window Aggregation

```
Fragment 3: merge → hashAgg → materialize
           ↑
Fragment 2: window → project
           ↑
Fragment 1: source → watermark
```

------

### Performance Insights from Fragment Graph

#### 🔍 What to Look For:

**✅ Good Signs:**

- Balanced parallelism across fragments
- Hash distribution for large data
- Multiple actors for heavy operations
- Clear data flow from source to sink

**⚠️ Warning Signs:**

- **Single actor on large data** - Bottleneck!
- **Very large state in hashAgg** - Memory pressure
- **Many fragments** (10+) - Complex query, may be slow
- **Broadcast on large tables** - Network overhead

**🚨 Red Flags:**

- **Failed status** - Critical error
- **Stuck in creating** - Initialization problem
- **Huge state size** (GBs) - OOM risk
- **Unbalanced parallelism** - Resource waste

------

### Practical Use Cases

#### Use Case 1: Debugging Slow Queries

1. Click on the slow materialized view
2. Check fragment graph
3. Look for single-actor bottlenecks
4. Check state sizes in aggregations
5. Optimize parallelism or query

#### Use Case 2: Memory Issues

1. Find the MV using excessive memory
2. Check fragment operators
3. Identify stateful operators (hashAgg, hashJoin)
4. Check state sizes
5. Consider query optimization or more memory

#### Use Case 3: Understanding Data Flow

1. Start from source
2. Follow fragment graph
3. See each transformation step
4. Understand pipeline complexity
5. Identify optimization opportunities

------

## Quick Reference

### Catalog Objects Comparison

| Object                 | Stores Data? | Updates?      | Purpose                    |
| ---------------------- | ------------ | ------------- | -------------------------- |
| **Sources**            | ❌ No         | ✅ Streams in  | Read external data         |
| **Tables**             | ✅ Yes        | Manual        | Static reference data      |
| **Materialized Views** | ✅ Yes        | ✅ Auto        | Real-time transformations  |
| **Indexes**            | ✅ Yes        | ✅ Auto        | Speed up queries           |
| **Internal Tables**    | ✅ Yes        | ✅ Auto        | System state management    |
| **Sinks**              | ❌ No         | ✅ Streams out | Write to external systems  |
| **Views**              | ❌ No         | ❌ No          | Logical query abstractions |
| **Subscriptions**      | ❌ No         | ✅ Streams out | Subscribe to changes       |

### Typical Data Flow

```
External Kafka (orders topic)
         ↓
    📥 SOURCE (orders_raw)
         ↓
    🔄 MATERIALIZED VIEW (orders_clean) - Deduplication
         ↓
    🔄 MATERIALIZED VIEW (orders_enriched) - Join with items TABLE
         ↓
    🔄 MATERIALIZED VIEW (item_revenue_1min) - Windowed aggregation
         ↓
    📤 SINK (to ClickHouse) - Export results
```

### Fragment Components Quick Reference

| Element          | What It Is            | Example                               |
| ---------------- | --------------------- | ------------------------------------- |
| **Fragment**     | Execution stage       | Fragment 2, Fragment 3                |
| **Actor**        | Parallel worker       | Actor 5, 6, 7, 8                      |
| **Distribution** | Partitioning strategy | hash, broadcast, single               |
| **Operator**     | Processing operation  | source, filter, hashAgg, materialize  |
| **Dispatcher**   | Data routing          | Hash dispatcher, broadcast dispatcher |
| **State**        | Stored data           | Aggregation results, join tables      |

### Dashboard Tips

**Navigation:**

- Click any object to see detailed information
- View SQL definitions and schemas
- Check dependencies (what feeds into what)

**Monitoring:**

- **Sources:** Green = healthy, Red = connection issues
- **Materialized Views:** Check for stalled or failed updates
- **Sinks:** Verify delivery is working

**Debugging:**

1. **No data in materialized view?** Check the source first
2. **View not updating?** Check internal tables for state issues
3. **Sink not delivering?** Verify connection configuration

**Performance:**

- **Internal Tables page:** Shows state storage size
- Large internal tables might indicate inefficient queries
- Monitor memory usage of materialized views

### Most Important Pages for Your Tutorial

1. **📥 Sources** - Verify Kafka connection is working
2. **🔄 Materialized Views** - Monitor all your transformations
3. **📋 Tables** - Check your `items` dimension table
4. **📤 Sinks** - If exporting to ClickHouse/other systems

### When to Look at Fragments

1. ✅ **Performance issues** - Identify bottlenecks
2. ✅ **High memory usage** - Check fragment state sizes
3. ✅ **Query not updating** - Check fragment status
4. ✅ **Scaling decisions** - Understand parallelism needs
5. ✅ **Learning RisingWave internals** - See how queries execute

------

## Key Takeaways

✅ **Dashboard at port 5691** - Your central monitoring hub 

✅ **Materialized Views page** - Most important for streaming pipelines 

✅ **Fragments = Distributed execution units** of your SQL queries 

✅ **Actors = Parallel workers** (more = faster processing) 

✅ **Fragment Graph** - Visual execution plan for understanding and debugging 

✅ **Check fragments for performance tuning and troubleshooting**

The RisingWave Dashboard gives you complete visibility into your streaming data pipelines. Start by exploring **Materialized Views**, then dive into **Fragment details** when you need to optimize or debug!