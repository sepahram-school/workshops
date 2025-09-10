Perfect! I can now update the **Medium-style tutorial** to include your **actual Spark setup code** and make the guide fully aligned with a hands-on workflow. Here's the complete revised post:

---

# Building a Lakehouse with LakeKeeper, MinIO, Spark / PySpark, StarRocks, and Trino

In this guide, we’ll walk through the complete process of setting up a **modern Lakehouse** environment from scratch. We will use **LakeKeeper** as our catalog service, **MinIO** as object storage, **Spark / PySpark** for data processing, and **StarRocks / Trino** for querying and analytics. This setup provides a full end-to-end environment to **insert, query, and explore data** in a transactional, schema-aware Lakehouse.

---

## 1. Prerequisites

Before you start, ensure you have:

- Docker and Docker Compose installed

- Basic familiarity with SQL and Python

- At least 8–16GB RAM for running multiple containers

Our environment uses containers for all services, making it easy to reproduce on any machine.

---

## 2. Docker Compose Overview

Key services in the Compose setup:

- **Jupyter Notebook**: Runs Spark + PySpark notebooks for experimentation (port `8889`).

- **LakeKeeper**: Catalog service managing Iceberg metadata, backed by Postgres (port `8181`).

- **PostgreSQL**: Stores catalog metadata (port `5454`).

- **MinIO**: S3-compatible object storage for Iceberg table data (ports `9000` API, `9001` Console).

- **Trino**: SQL query engine for Iceberg tables (port `9999`).

- **StarRocks**: Analytical engine for Iceberg-managed data (ports `8030`, `9030`).

The Compose file orchestrates service dependencies, ensures readiness, and persists data using volumes.

---

## 3. Bootstrapping the Lakehouse

1. **Start Docker Compose**:

```bash
docker-compose up -d
```

2. **Run migrations**: The `migrate` service initializes the Postgres metadata database.

3. **Bootstrap LakeKeeper**: Accept terms and initialize the catalog (`bootstrap` service).

4. **Create default warehouse**: The `initialwarehouse` service sets up the S3 bucket for Iceberg tables in MinIO.

---

## 4. Spark / PySpark Setup

Here’s a complete PySpark configuration for connecting to **LakeKeeper and Iceberg**:

```python
import pyspark
from pyspark.conf import SparkConf
from pyspark.sql import SparkSession
import pandas as pd

# LakeKeeper catalog and warehouse URL
CATALOG_URL = "http://lakekeeper:8181/catalog"
WAREHOUSE = "sepahram"

SPARK_VERSION = pyspark.__version__
SPARK_MINOR_VERSION = '.'.join(SPARK_VERSION.split('.')[:2])
ICEBERG_VERSION = "1.9.2"
HADOOP_VERSION = "3.4.2"

spark_config = SparkConf().setMaster('local[*]').setAppName("Iceberg-REST-Cluster")

# Catalog configuration
config = {
    "spark.sql.catalog.lakekeeper": "org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.lakekeeper.type": "rest",
    "spark.sql.catalog.lakekeeper.uri": CATALOG_URL,
    "spark.sql.catalog.lakekeeper.warehouse": WAREHOUSE,
    "spark.sql.defaultCatalog": "lakekeeper",
}

for k, v in config.items():
    spark_config = spark_config.set(k, v)

# Create SparkSession
spark = SparkSession.builder.config(conf=spark_config).getOrCreate()

# Use the catalog
spark.sql("USE lakekeeper")
```

---

### 4.1 Querying Data with PySpark

Example: Top 10 merchants by total sales:

```python
df = spark.sql("""
SELECT 
    merchantName, 
    SUM(amount) AS total_sales, 
    COUNT(*) AS transaction_count
FROM banking.source_transactions
GROUP BY merchantName
ORDER BY total_sales DESC
LIMIT 10
""").toPandas()

# Display nicely
df
```

This converts the Spark SQL result to a pandas DataFrame for easy viewing in Jupyter.

---

## 5. Querying with Trino and StarRocks

**Trino example:**

```python
# This CATALOG_URL works for the "docker compose" testing and development environment
# Change 'lakekeeper' if you are not running on "docker compose" (f. ex. 'localhost' if Lakekeeper is running locally).
CATALOG_URL = "http://lakekeeper:8181/catalog"
TRINO_URI = "http://trino:8080"
WAREHOUSE = "sepahram"

from trino.dbapi import connect

conn = connect(host=TRINO_URI, user="trino")
cur = conn.cursor()
cur.execute("SELECT * FROM lakekeeper.banking.source_transactions LIMIT 10")
rows = cur.fetchall()
```

**StarRocks example:**

```python

CATALOG_URL = "http://lakekeeper:8181/catalog"
STARROCKS_URI = "starrocks://root@starrocks:9030"
WAREHOUSE = "sepahram" 

from sqlalchemy import create_engine, text
engine = create_engine(STARROCKS_URI)

with engine.connect() as connection:
    connection.execute(text("DROP CATALOG IF EXISTS lakekeeper"))
    connection.execute(
        text(f"""
        CREATE EXTERNAL CATALOG lakekeeper
        PROPERTIES
        (
            "type" = "iceberg",
            "iceberg.catalog.type" = "rest",
            "iceberg.catalog.uri" = "{CATALOG_URL}",
            "iceberg.catalog.warehouse" = "{WAREHOUSE}",
            "aws.s3.region" = "local",
            "aws.s3.enable_path_style_access" = "true",
            "aws.s3.endpoint" = "http://minio:9000",
            "aws.s3.access_key" = "minio-root-user",
            "aws.s3.secret_key" = "minio-root-password"
        )
        """)
    )
    connection.execute(text("SET CATALOG lakekeeper"))

import pandas as pd

with engine.connect() as connection:
    # Use the catalog and namespace
    connection.execute(text("SET CATALOG lakekeeper"))
    connection.execute(text("USE banking"))
    
    # Execute the query
    result = connection.execute(
        text("SELECT * FROM source_transactions LIMIT 10")
    ).fetchall()
    
    # Get column names
    columns = [col[0] for col in connection.execute(text("SELECT * FROM source_transactions LIMIT 1")).keys()]

# Convert to pandas DataFrame
df = pd.DataFrame(result, columns=columns)

# Display the DataFrame nicely (works in Jupyter/console)
df
```

Both engines query the Iceberg tables registered in LakeKeeper.

---

## 6. Exploring Storage in MinIO

- Access MinIO Console at `http://localhost:9001` using the root credentials.

- Browse bucket `sepahram-warehouse` to see **Iceberg files organized by namespace/table/snapshot**.

- Iceberg’s layout ensures **schema evolution, snapshots, and atomic updates**.

---

## 7. Exploring Metadata in LakeKeeper

- Connect to Postgres via DBeaver: `postgres://postgres:postgres@localhost:5454/postgres`

- Inspect tables like `catalog_namespace`, `catalog_table`, `catalog_snapshot` to explore inserted data.

- Snapshots match the Iceberg data stored in MinIO, ensuring full traceability.

---

## 8. Best Practices

- Use **catalog-aware engines** (Spark, Trino, StarRocks) to query Iceberg tables.

- Enable **S3 path-style access** in MinIO for compatibility with Iceberg.

- Backup the Postgres metadata database regularly.

- Monitor container logs to troubleshoot ingestion and query issues.

---

This setup provides a **fully functional Lakehouse environment**, combining:

- **Metadata management**: LakeKeeper

- **Object storage**: MinIO

- **Processing**: Spark / PySpark

- **Query engines**: Trino and StarRocks

It’s ideal for experimentation, analytics, and production-grade workflows.

---