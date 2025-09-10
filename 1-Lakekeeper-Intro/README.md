# Iceberg Ingestion Pipeline - Complete Guide

**🚀 Quick Workflow:**

1. **Start the Infrastructure**
   - Open a terminal and run:
     ```bash
     cd docker
     docker-compose -f compose-lakekeeper-pyiceberg.yaml up -d
     ```
   - See [Infrastructure Setup](#infrastructure-setup) for details.

2. **Access Jupyter Notebooks**
   - Go to [http://localhost:8889](http://localhost:8889) in your browser.
   - Use the notebooks in the `notebooks` folder (visible in the Jupyter UI) to set up the Iceberg tables (e.g., `setup_query_fake_seclink_table.ipynb`).
   - See [Table Setup and Configuration](#table-setup-and-configuration) for more info.

3. **Test Kafka Consumer**
   - In the Jupyter UI, open and run `test_kafka_consumer.ipynb` (provided in the notebooks folder) to verify you can connect to your Kafka broker and see messages.
   - See [Testing the Kafka Consumer](#testing-the-kafka-consumer) for more info.

4. **Start Ingestion**
   - Once tables are set up and Kafka is verified, run the main ingestion script from Docker:
     ```bash
     python debezium_kafka_consumer.py
     ```
   - (You can do this inside the appropriate Docker container or from your host if dependencies are installed.)
   - See [Data Ingestion with Debezium](#data-ingestion-with-debezium) for details.

---

## 📋 Prerequisites

1. **Docker & Docker Compose**: For running Lakekeeper, MinIO, and PostgreSQL
2. **Python 3.8+**: For running the Python scripts and notebooks
3. **Jupyter**: For interactive data analysis
4. **Kafka**: For real-time data streaming (optional for testing)

## Infrastructure Setup

Start all services including Lakekeeper, MinIO, and PostgreSQL:
```bash
cd docker
docker-compose -f compose-lakekeeper-pyiceberg.yaml up -d
```

## 📊 Table Setup and Configuration

### Table Schema

The `fake_seclink` table has the following schema:
```sql
CREATE TABLE fake_seclink (
    Id INT,
    TelegramCode INT,
    Source INT,
    Destination INT,
    DateIn TIMESTAMP,
    DateOut TIMESTAMP,
    Body VARCHAR(max)
);
```

- **Primary Partition**: `month(DateIn)` - Time-based partitioning
- **Benefits**: Efficient time-based queries and data organization

### Configuration
```python
# Iceberg Configuration
CATALOG_URL = "http://lakekeeper:8181/catalog"
WAREHOUSE = "irisa-ot"
NAMESPACE = "irisa"
TABLE_NAME = "fake_seclink"
```

### Setting Up the Table

**Recommended:**
- Access Jupyter at [http://localhost:8889](http://localhost:8889)
- Open and run `setup_query_fake_seclink_table.ipynb` (or other notebooks in the notebooks folder)
- This will:
  1. Connect to the Lakekeeper catalog
  2. Create the `irisa` namespace if it doesn't exist
  3. Create the `fake_seclink` table with proper schema and partitioning
  4. Generate and insert 10,000 sample records
  5. Run test queries to verify the setup
  6. Provide interactive data exploration

**Alternative:**
- Convert the notebook to a Python script and run it:
  ```bash
  jupyter nbconvert --to python setup_query_fake_seclink_table.ipynb
  python setup_query_fake_seclink_table.py
  ```

#### Expected Output
```
🔧 Configuration:
   - Catalog URL: http://lakekeeper:8181/catalog
   - Warehouse: irisa-ot
   - Namespace: irisa
   - Table: fake_seclink

✅ Table created successfully!
   - Table: irisa.fake_seclink
   - Location: s3://irisa-warehouse/irisa/fake_seclink
   - Format: 2
   - Partitioning: 1 fields

✅ Generated 10000 fake records
📅 Date range: 2024-01-01 to 2024-06-30
```

### Querying the Data

See the notebook for full examples, or use DuckDB directly:
```python
import duckdb

con = duckdb.connect(":memory:")
con.install_extension("iceberg")
con.load_extension("iceberg")
con.sql("""
    ATTACH 'irisa-ot' AS irisa_datalake (
        TYPE ICEBERG,
        ENDPOINT 'http://lakekeeper:8181/catalog',
        TOKEN ''
    )
""")
result = con.sql("SELECT COUNT(*) FROM irisa_datalake.irisa.fake_seclink").fetchone()
print(f"Total records: {result[0]}")
```

## Testing the Kafka Consumer

- In Jupyter, open and run `test_kafka_consumer.ipynb` (in the notebooks folder)
- Update the configuration cell with your Kafka broker and topic
- Run all cells to see messages printed in real-time
- Use this to verify connectivity and topic data before running the main ingestion

## Data Ingestion with Debezium

### Understanding Debezium Messages

The consumer expects Debezium messages in this format:
```json
{
  "source": { ... },
  "payload": {
    "before": null,
    "after": { ... },
    "op": "c"
  }
}
```

### Running the Consumer

1. **Configure Kafka Settings** in `debezium_kafka_consumer.py`:
   ```python
   KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
   KAFKA_TOPIC = "fake_sl.dbo.fake_seclink"
   KAFKA_GROUP_ID = "iceberg-consumer-group"
   ```
2. **Start the Consumer**:
   ```bash
   python debezium_kafka_consumer.py
   ```
3. **Monitor the Logs** for ingestion status and errors

## 🧪 Testing and Validation

- **Table Setup Test**: Use the Jupyter notebook to create and verify the table
- **Consumer Test**: Use `test_kafka_consumer.ipynb` to verify Kafka connectivity
- **Ingestion Test**: Use `test_debezium_consumer.py` or the main consumer for end-to-end testing

## ⚙️ Configuration Options

- See the code and notebooks for batch size, timeout, and other settings
- Example:
  ```python
  BATCH_SIZE = 100
  BATCH_TIMEOUT_SECONDS = 30
  ```

## 🛠️ Troubleshooting

- **Lakekeeper Connection Failed**: Check Docker services and network
- **Table Not Found**: Rerun the setup notebook
- **Kafka Issues**: Check broker, topic, and network
- **Timestamp Parsing Errors**: Check message format and timezone
- **Debug Mode**: Set logging to DEBUG in the scripts

## 📁 File Structure

```
ingestion-pipeline/
├── docker/
│   ├── jupyter/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── compose-lakekeeper-pyiceberg.yaml
│   ├── create-default-warehouse.json
│   └── requirements.txt
├── notebooks/
│   ├── setup_query_fake_seclink_table.ipynb
│   └── test_kafka_consumer.ipynb
├── debezium_kafka_consumer.py
├── test_debezium_consumer.py
├── README.md
├── requirements.txt
```

## 🔗 Related Resources

- [Apache Iceberg Documentation](https://iceberg.apache.org/docs/)
- [Debezium Documentation](https://debezium.io/documentation/)
- [PyIceberg Documentation](https://py.iceberg.apache.org/)
- [Kafka Python Client](https://kafka-python.readthedocs.io/)
- [DuckDB Documentation](https://duckdb.org/docs/)

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the logs for error messages
3. Verify all services are running correctly
4. Test with the provided test scripts 