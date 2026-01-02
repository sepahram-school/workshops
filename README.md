# Sepahram Data Eng School - Short Workshops

Welcome to the **Short Workshops for Data Engineers** repository!  

Sepahram Data Eng Website: [Sepahram.ir](https://Sepahram.ir)

Youtube Channel : [Sepahram Data Engineering School](https://www.youtube.com/@Sepahram.School)

This repo is designed to help you explore a variety of tools, technologies, and projects in the data engineering ecosystem through hands-on exercises.



## Purpose

- Learn and practice key data engineering tools in short, focused workshops.
- Each workshop has its own folder with a README and all necessary code/materials.
- Try out projects and setups without having to start from scratch.

## How to Use

1. **Clone the repository**:
   
   ```bash
   git clone https://github.com/your-org/data-eng-workshops.git
   ```

or **update your local copy** if already cloned:

```bash
git pull
```

2. Navigate to the folder of the workshop you want to try:
   
   ```
   cd workshops/1-Great-Expectations
   ```

3. Follow the instructions in the README of that folder to set up and run the exercises.

## Workshop List

| Sequence | Workshop Topic                                                         | Status        | Description                                                     | Tools/DBs |
| -------- | ---------------------------------------------------------------------- | ------------- | --------------------------------------------------------------- | --------- |
| 1        | [Postgres Physical Address](1-Postgres-Page-Heap-Concepts)             | **Published** | Understanding PostgreSQL's base directory structure and how database files are organized on disk | PostgreSQL |
| 2        | [2-Airflow-Concurrency-Control-SQL](2-Airflow-Concurrency-Control-SQL) | **Published** | Solving concurrency issues in Airflow DAGs when processing shared database state | Apache Airflow, PostgreSQL |
| 3        | [3-Postgres-Data-Archiving-With-FDW](3-Postgres-Data-Archiving-With-FDW) | **Published** | Building distributed data archive systems using PostgreSQL Foreign Data Wrappers | PostgreSQL, FDW |
| 4        | [4-MV-Considerations](4-MV-Considerations)                             | **Published** | Understanding ClickHouse materialized views and handling duplicate data issues | ClickHouse, Kafka, Redpanda |
| 5        | [5-RisingWave-Workshop](5-RisingWave-Workshop)                         | **Published** | Building real-time streaming pipelines with RisingWave using pure SQL | RisingWave, Kafka, Redpanda, ClickHouse, PostgreSQL, RustFS |

---
