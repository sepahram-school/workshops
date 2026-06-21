# DuckLake from Theory to Practice: A Hands‑On Tutorial for Building a Lakehouse with ACID and Time Travel

*Learn how DuckLake simplifies lakehouse operations with database‑backed metadata, ACID transactions, and powerful features like snapshots and time travel — all through practical, step‑by‑step examples.*

---

## TL;DR

This hands‑on tutorial demonstrates DuckLake’s practical capabilities through step‑by‑step examples. We’ll install DuckLake, create schemas and tables, perform CRUD operations, explore file organisation, and use advanced features like snapshots and time travel. The tutorial showcases how DuckLake’s database‑backed metadata approach simplifies lakehouse operations while providing enterprise‑grade capabilities like ACID transactions and automatic conflict resolution.

---

## From Theory to Practice

In [Part 1](https://example.com) *(link to a hypothetical previous article)*, we explored DuckLake’s architectural philosophy and its elegant solution to lakehouse complexity. Now it’s time to get our hands dirty and see how these concepts translate into practice.

This tutorial will walk you through DuckLake’s core functionality, from installation to advanced features like time travel. Whether you’re evaluating DuckLake for your organisation or simply curious about how it works, this hands‑on exploration will give you the practical foundation you need.

> **Code Availability** – All code examples in this tutorial are available in the `example_3_ducklake_basics.ipynb` Jupyter notebook in our [endjin‑duckdb‑examples GitHub repository](https://github.com/endjin/endjin-duckdb-examples).

---

## Prerequisites and Setup

Before we begin, you’ll need:

- Python (3.8 or later)
- DuckDB Python package (version 1.3.0 or later)
- Basic familiarity with SQL

Let’s start by importing the packages we need and deciding where we want to persist metadata and data files.

```python
import duckdb
from pathlib import Path

# Define our working directories
DUCKLAKE_FOLDER = Path("../ducklake_basic")
ducklake_metadata = DUCKLAKE_FOLDER / "metadata"
ducklake_files = DUCKLAKE_FOLDER / "data_files"
```

---

## Installing the DuckLake Extension

The first step is installing the DuckLake extension. DuckDB’s extension system makes this remarkably simple:

```python
duckdb.sql("INSTALL ducklake")
```

That’s it! The extension is now available for use. This single command gives you access to DuckLake’s full functionality.

---

## Understanding DuckLake’s Architecture Choices

DuckLake requires you to make two fundamental technology choices:

### Metadata Backend Options

- **DuckDB** – for local development and small‑scale deployments
- **SQLite** – lightweight, single‑file database
- **PostgreSQL** – enterprise‑scale with full ACID compliance
- **MySQL** – widely deployed, mature ecosystem

### Storage Backend Options

- **Local filesystem** – development and small deployments
- **Amazon S3** – cloud‑scale object storage
- **Azure Blob Storage** – Microsoft cloud ecosystem
- **Google Cloud Storage** – Google cloud ecosystem

For this tutorial, to keep things simple, we’re using **DuckDB as the metadata backend** and the **local filesystem for data storage** — the simplest possible configuration that still demonstrates all of DuckLake’s capabilities.

---

## Creating Your First DuckLake Instance

Now let’s create and connect to our DuckLake instance:

```python
duckdb.sql(f"""
    ATTACH 'ducklake:{ducklake_metadata}' AS ducklake_basic_db (DATA_PATH '{ducklake_files}');
    USE ducklake_basic_db;
""")
```

This command does several important things:

- Creates a DuckLake instance with metadata stored in our specified directory
- Sets up the data files location for Parquet storage
- Attaches to DuckLake as a database called `ducklake_basic_db`
- Switches our context to use this database

---

## Building Your First Schema

DuckLake supports multiple schemas within a single database, enabling logical organisation of related tables. Let’s create a schema for a simple retail analytics use case:

```python
duckdb.sql("""
    CREATE SCHEMA IF NOT EXISTS retail_sales;
    USE retail_sales;
""")
```

This creates a schema called `retail_sales` and switches our context to work within it.

---

## Creating Tables and Understanding Constraints

Let’s create our first table. DuckLake currently has some limitations around constraints that are worth understanding:

> **Constraint Support** – DuckLake currently supports only `NOT NULL` constraints. `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, and `CHECK` constraints are not yet implemented, though this may change as the format matures.

```python
duckdb.sql("""
    CREATE TABLE IF NOT EXISTS customer (
        customer_id INTEGER NOT NULL,
        first_name VARCHAR NOT NULL,
        last_name VARCHAR NOT NULL,
        date_joined DATE NOT NULL
    );
""")
```

---

## Basic Data Operations

Now let’s perform some basic CRUD (Create, Read, Update, Delete) operations to see how DuckLake handles data changes.

### Inserting Data

```python
duckdb.sql("""
    INSERT INTO customer (customer_id, first_name, last_name, date_joined) VALUES
    (1, 'Jane', 'Dunbar', '2023-01-11'),
    (2, 'Jimmy', 'Smith', '2024-08-26'),
    (3, 'Alice', 'Johnston', '2023-05-05');
""")
```

### Reading Data

```python
duckdb.sql("""
    SELECT * FROM customer;
""")
```

**Output:**

```
┌─────────────┬────────────┬───────────┬─────────────┐
│ customer_id │ first_name │ last_name │ date_joined │
│    int32    │  varchar   │  varchar  │    date     │
├─────────────┼────────────┼───────────┼─────────────┤
│           1 │ Jane       │ Dunbar    │ 2023-01-11  │
│           2 │ Jimmy      │ Smith     │ 2024-08-26  │
│           3 │ Alice      │ Johnston  │ 2023-05-05  │
└─────────────┴────────────┴───────────┴─────────────┘
```

---

## Exploring File Organisation

One of DuckLake’s distinctive features is its file organisation approach. Let’s examine how it stores data behind the scenes:

```python
duckdb.sql(f"""
    FROM glob('{ducklake_files}/*');
""")
```

**Output:**

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                                        file                                        │
│                                      varchar                                       │
├────────────────────────────────────────────────────────────────────────────────────┤
│ ../ducklake_basic/data_files/ducklake-01978495-e183-7763-bf40-d9a85988eed9.parquet │
└────────────────────────────────────────────────────────────────────────────────────┘
```

Notice the flat file structure with UUID‑based naming. This is quite different from hierarchical folder structures used by other lakehouse formats. Let’s examine the actual content:

```python
# Extract the parquet file name
parquet_file = duckdb.sql(f"""
    SELECT file FROM glob('{ducklake_files}/*.parquet') LIMIT 1;
""").fetchone()[0]

# Inspect the file contents
duckdb.sql(f"""
    SELECT * FROM read_parquet('{parquet_file}');
""")
```

**Output:**

```
┌─────────────┬────────────┬───────────┬─────────────┐
│ customer_id │ first_name │ last_name │ date_joined │
│    int32    │  varchar   │  varchar  │    date     │
├─────────────┼────────────┼───────────┼─────────────┤
│           1 │ Jane       │ Dunbar    │ 2023-01-11  │
│           2 │ Jimmy      │ Smith     │ 2024-08-26  │
│           3 │ Alice      │ Johnston  │ 2023-05-05  │
└─────────────┴────────────┴───────────┴─────────────┘
```

The data is stored as standard Parquet files, making it fully compatible with other tools and systems that can read Parquet format.

---

## Understanding DuckLake Snapshots

Every operation in DuckLake creates a snapshot — a point‑in‑time view of the database state. Let’s explore how this works:

```python
duckdb.sql("""
    SELECT * FROM ducklake_snapshots('ducklake_basic_db');
""")
```

**Output:**

```
┌─────────────┬────────────────────────────┬────────────────┬─────────────────────────────────────────────────────────────────────────┐
│ snapshot_id │       snapshot_time        │ schema_version │                                 changes                                 │
│    int64    │  timestamp with time zone  │     int64      │                         map(varchar, varchar[])                         │
├─────────────┼────────────────────────────┼────────────────┼─────────────────────────────────────────────────────────────────────────┤
│           0 │ 2025-06-18 19:48:24.41+00  │              0 │ {schemas_created=[main]}                                                │
│           1 │ 2025-06-18 19:48:24.489+00 │              1 │ {schemas_created=[retail_sales]}                                        │
│           2 │ 2025-06-18 19:48:24.533+00 │              2 │ {tables_created=[retail_sales.customer]}                                │
│           3 │ 2025-06-18 19:48:24.554+00 │              2 │ {tables_inserted_into=[2]}                                              │
└─────────────┴────────────────────────────┴────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

This shows the complete history of our DuckLake instance:

- Snapshot 0 – Default `main` schema created
- Snapshot 1 – Our `retail_sales` schema created
- Snapshot 2 – `customer` table created
- Snapshot 3 – Data inserted into the table

---

## Data Modification and Delete Operations

Let’s explore how DuckLake handles updates and deletes.

### Updating Data

```python
duckdb.sql("""
    UPDATE customer SET first_name = 'Alice', last_name = 'Fraser' WHERE customer_id = 3;
""")
```

### Deleting Data

```python
duckdb.sql("""
    DELETE FROM customer WHERE customer_id = 2;
""")

duckdb.sql("""
    SELECT * FROM customer;
""")
```

**Output:**

```
┌─────────────┬────────────┬───────────┬─────────────┐
│ customer_id │ first_name │ last_name │ date_joined │
│    int32    │  varchar   │  varchar  │    date     │
├─────────────┼────────────┼───────────┼─────────────┤
│           1 │ Jane       │ Dunbar    │ 2023-01-11  │
│           3 │ Alice      │ Fraser    │ 2023-05-05  │
└─────────────┴────────────┴───────────┴─────────────┘
```

### How DuckLake Handles Deletes

DuckLake uses a sophisticated approach for delete operations. Let’s examine how deletes are stored:

```python
duckdb.sql(f"""
    FROM glob('{ducklake_files}/*-delete.parquet');
""")
```

**Output:**

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                           file                                            │
│                                          varchar                                          │
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ ../ducklake_basic/data_files/ducklake-01978495-e274-7dde-9587-ea01a9697457-delete.parquet │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

DuckLake creates separate “delete files” that reference the original data files and specify which rows should be considered deleted:

```python
# Extract the delete file name
delete_file = duckdb.sql(f"""
    SELECT file FROM glob('{ducklake_files}/*delete.parquet') LIMIT 1;
""").fetchone()[0]

# Inspect the delete file contents
duckdb.sql(f"""
    SELECT * FROM read_parquet('{delete_file}');
""")
```

**Output:**

```
┌────────────────────────────────────────────────────────────────────────────────────┬───────┐
│                                     file_path                                      │  pos  │
│                                      varchar                                       │ int64 │
├────────────────────────────────────────────────────────────────────────────────────┼───────┤
│ ../ducklake_basic/data_files/ducklake-01978495-e183-7763-bf40-d9a85988eed9.parquet │     1 │
└────────────────────────────────────────────────────────────────────────────────────┴───────┘
```

This shows that row position 1 (Jimmy Smith) in the original Parquet file should be considered deleted. This approach allows for efficient deletes without rewriting large data files.

---

## Time Travel: Querying Historical Data

One of DuckLake’s most powerful features is **time travel** — the ability to query your data as it existed at any previous point in time.

Let’s get our current snapshot ID and then query historical states:

```python
# Get the current maximum snapshot ID
max_snapshot_id = duckdb.sql("""
    SELECT MAX(snapshot_id) FROM ducklake_snapshots('ducklake_basic_db');
""").fetchone()[0]

print(f"Current snapshot ID: {max_snapshot_id}")
```

**Output:**

```
Current snapshot ID: 5
```

Now let’s query the table as it existed *before* we deleted the customer:

```python
duckdb.sql(f"""
    SELECT * FROM customer AT (VERSION => {max_snapshot_id - 1});
""")
```

**Output:**

```
┌─────────────┬────────────┬───────────┬─────────────┐
│ customer_id │ first_name │ last_name │ date_joined │
│    int32    │  varchar   │  varchar  │    date     │
├─────────────┼────────────┼───────────┼─────────────┤
│           1 │ Jane       │ Dunbar    │ 2023-01-11  │
│           3 │ Alice      │ Fraser    │ 2023-05-05  │
└─────────────┴────────────┴───────────┴─────────────┘
```

We can go even further back to see the table before our update:

```python
duckdb.sql(f"""
    SELECT * FROM customer AT (VERSION => {max_snapshot_id - 2});
""")
```

**Output:**

```
┌─────────────┬────────────┬───────────┬─────────────┐
│ customer_id │ first_name │ last_name │ date_joined │
│    int32    │  varchar   │  varchar  │    date     │
├─────────────┼────────────┼───────────┼─────────────┤
│           1 │ Jane       │ Dunbar    │ 2023-01-11  │
│           2 │ Jimmy      │ Smith     │ 2024-08-26  │
│           3 │ Alice      │ Johnston  │ 2023-05-05  │
└─────────────┴────────────┴───────────┴─────────────┘
```

This time travel capability is invaluable for debugging, auditing, and understanding how your data has evolved over time.

---

## Working with Multiple Tables

Let’s create a second table to demonstrate multi‑table operations:

```python
duckdb.sql("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        order_date DATE NOT NULL,
        product_id INTEGER NOT NULL,
        product_name VARCHAR NOT NULL,
        amount DECIMAL(10, 2) NOT NULL
    );
""")

duckdb.sql("""
    INSERT INTO orders (order_id, customer_id, product_id, product_name, order_date, amount) VALUES
    (1, 1, 101, 'Widget A', '2023-01-15', 19.50),
    (2, 1, 102, 'Widget B', '2023-01-20', 29.99),
    (3, 3, 103, 'Widget A', '2023-02-10', 19.50);
""")
```

---

## Atomic Transactions Across Multiple Tables

One of DuckLake’s key advantages over table‑level formats is **true multi‑table transactions**. Let’s demonstrate this by adding a new customer and their orders in a single atomic operation:

```python
duckdb.sql("""
    BEGIN TRANSACTION;
    INSERT INTO customer (customer_id, first_name, last_name, date_joined) VALUES
    (4, 'Bob', 'Brown', '2023-03-01');
    INSERT INTO orders (order_id, customer_id, product_id, product_name, order_date, amount) VALUES
    (4, 4, 104, 'Widget B', '2023-03-05', 29.99),
    (5, 4, 105, 'Widget C', '2023-02-15', 59.99),
    (6, 4, 106, 'Widget A', '2023-01-25', 19.50);
    COMMIT;
""")
```

This entire operation — adding a customer and three orders — appears as a single snapshot in our change history. If any part of the transaction had failed, the entire operation would have been rolled back, ensuring data consistency.

---

## Change Tracking and Incremental Analysis

DuckLake provides powerful capabilities for tracking changes between snapshots. This is particularly valuable for incremental data processing and change data capture scenarios:

```python
# Get changes to the customer table in the latest snapshot
duckdb.sql(f"""
    SELECT * FROM ducklake_table_changes('ducklake_basic_db', 'retail_sales', 'customer', {max_snapshot_id}, {max_snapshot_id})
    ORDER BY snapshot_id;
""")
```

**Output:**

```
┌─────────────┬───────┬─────────────┬─────────────┬────────────┬───────────┬─────────────┬─────────┐
│ snapshot_id │ rowid │ change_type │ customer_id │ first_name │ last_name │ date_joined │  email  │
│    int64    │ int64 │   varchar   │    int32    │  varchar   │  varchar  │    date     │ varchar │
├─────────────┼───────┼─────────────┼─────────────┼────────────┼───────────┼─────────────┼─────────┤
│           9 │     6 │ insert      │           4 │ Bob        │ Brown     │ 2023-03-01  │ NULL    │
└─────────────┴───────┴─────────────┴─────────────┴────────────┴───────────┴─────────────┴─────────┘
```

This shows exactly what changed in our latest transaction — a new customer (Bob Brown) was inserted.

---

## Flexibility in Deployment

While we’ve used a local setup for this tutorial, DuckLake’s architecture allows seamless scaling. The same operations we’ve performed locally would work identically with:

- **PostgreSQL** as the metadata backend for enterprise‑scale deployments
- **S3 or Azure Blob Storage** for cloud‑native data storage
- **Multiple concurrent users** across different geographic locations
- A mix of **personal devices, edge computing, and cloud infrastructure**

The transition between these deployment models requires only changing connection strings — your application code remains unchanged.

---

## Summary

In this tutorial, you’ve learned how to:

- Install and set up DuckLake with a local filesystem and DuckDB metadata
- Create schemas, tables, and perform CRUD operations
- Understand DuckLake’s flat file organisation with UUID‑named Parquet files
- List and inspect snapshots – the history of your lakehouse
- Perform updates and deletes, and see how they are stored as delete markers
- Query your data as it existed at any previous point in time (time travel)
- Execute atomic multi‑table transactions
- Track changes between snapshots for incremental processing

DuckLake brings the simplicity of a database to the lakehouse, giving you ACID transactions, snapshot isolation, and time travel without sacrificing the flexibility of Parquet and object storage. Whether you’re building a small analytics project or an enterprise‑scale data platform, DuckLake offers a compelling foundation.

---

## Next Steps

- Try running these examples with a remote metadata backend (e.g., PostgreSQL) and an S3‑compatible storage to experience the same capabilities at scale.
- Explore more advanced features like automatic conflict resolution and concurrent writes in a distributed setting.
- Check out the [endjin-duckdb-examples repository](https://github.com/endjin/endjin-duckdb-examples) for additional notebooks and use cases.

Happy lakehousing!

---

*This article was originally published as part of the endjin DuckDB series. If you found it useful, please share and leave a clap!*