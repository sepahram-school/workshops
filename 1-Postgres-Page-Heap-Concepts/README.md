### 🔍 Understanding the `base` Directory in PostgreSQL

When PostgreSQL runs, each database and table is stored as files under the **data directory (`PGDATA`)**.  
The folder you’re seeing, e.g.:

```
.../base/
│
├── 1
├── 4
├── 5
└── 16384
```

represents the **database storage directories**, where each subfolder name (like `16384`) is a **database OID**.  
Inside those folders are files named by **relfilenode numbers**, which represent actual tables, indexes, or other relations.

Let’s map those numbers back to human-readable database, schema, and table names.

---

## 🧩 Step 1 - Find which database each folder (OID) belongs to

```sql
SELECT oid, datname
FROM pg_database
ORDER BY oid;
```

**Explanation:**  
Each row shows:

- `oid`: The numeric identifier of the database (matches the folder name under `base/`)

- `datname`: The human-readable name of that database

Example result:

```
  oid  |  datname
-------+-----------
     1 | template0
     4 | template1
 16384 | postgres
 16385 | myappdb
```

So in your case, `base/16384` corresponds to the `postgres` database.

---

## 🧩 Step 2 - List all relations (tables, indexes, etc.) with their file numbers

```sql
SELECT
    n.nspname     AS schema,
    c.relname     AS object_name,
    c.oid         AS rel_oid,
    c.relfilenode AS file_id,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned table'
        WHEN 'i' THEN 'index'
        WHEN 'S' THEN 'sequence'
        WHEN 't' THEN 'toast table'
        WHEN 'm' THEN 'materialized view'
        ELSE c.relkind
    END AS object_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relfilenode IS NOT NULL AND c.relfilenode <> 0
ORDER BY c.relfilenode;
```

**Explanation:**

- Each **table or index** is represented by a row here.

- The column `relfilenode` corresponds to the **file name** on disk under `base/<db_oid>/`.

- For example, if you see a file `base/16384/24576`, you can search for `24576` in this output.

---

## 🧩 Step 3 - Find which table or index a specific file belongs to

If you see a file `base/16384/24576` on disk, you can find out what it is:

```sql
SELECT
    n.nspname AS schema,
    c.relname AS object_name,
    c.relfilenode AS file_id,
    pg_relation_filepath(c.oid::regclass) AS filepath,
    CASE c.relkind
        WHEN 'r' THEN 'table'
        WHEN 'i' THEN 'index'
        WHEN 't' THEN 'toast'
        ELSE c.relkind
    END AS object_type
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relfilenode = 24576;
```

**Explanation:**

- Replace `24576` with the file number you saw in your data folder.

- The function `pg_relation_filepath()` shows the **exact storage path** relative to `PGDATA`.

- The result tells you which schema/table that file belongs to.

---

## 🧩 Step 4 - Get file path directly from a table name

To go the other way (find which file stores a table):

```sql
SELECT
    'pg_catalog.pg_class'::regclass::oid AS table_oid,
    pg_relation_filepath('pg_catalog.pg_class'::regclass) AS file_path;
```

**Example result:**

```bash
 table_oid |      file_path
------------+----------------------
      24576 | base/16384/24576
```

So `base/16384/24576` is the file storing the `public.my_table` table.

---

## 🧩 Step 5 - (Optional) Check physical files for indexes, toast, etc. -> Local or Global?

A single logical table may have several files:

- `base/<db_oid>/<relfilenode>` → the main table heap

- `base/<db_oid>/<relfilenode>_fsm` → free space map

- `base/<db_oid>/<relfilenode>_vm` → visibility map

- Toast and index relations each have their own relfilenodes

You can inspect them all:

```sql
SELECT
  n.nspname AS schema,
  c.relname AS table_name,
  c.relfilenode,
  pg_relation_filepath(c.oid) AS path
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
ORDER BY n.nspname, c.relname;
```

You can check which ones are **shared** (in `global/`) vs **per database** by this query:

```sql
SELECT relname, relisshared
FROM pg_class
WHERE relname LIKE 'pg_%'
ORDER BY relisshared DESC, relname;
```

- `relisshared = true` → catalog is in `global/`

- `relisshared = false` → catalog is local (in `base/<db_oid>/`)

Example output:

```bash
 relname        | relisshared 
----------------+-------------
 pg_authid      | t
 pg_database    | t
 pg_tablespace  | t
 pg_shdepend    | t
 pg_shdescription | t
 pg_class       | f
 pg_namespace   | f
 pg_proc        | f
 ...
```

---

## 🧠 Summary

| Type             | SQL Source               | Filesystem Mapping              |
| ---------------- | ------------------------ | ------------------------------- |
| Database         | `pg_database.oid`        | `base/<oid>/`                   |
| Schema           | `pg_namespace.oid`       | Logical (inside DB)             |
| Table / Index    | `pg_class.relfilenode`   | `base/<db_oid>/<relfilenode>`   |
| File path helper | `pg_relation_filepath()` | Returns full internal file path |

---

### ✅ Quick Cheat Sheet

```sql
-- Database OIDs
SELECT oid, datname FROM pg_database;

-- Relation files in current DB
SELECT n.nspname, c.relname, c.relfilenode, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relfilenode IS NOT NULL;

-- Lookup file → table
SELECT n.nspname, c.relname, pg_relation_filepath(c.oid::regclass)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE c.relfilenode = <file_number>;

-- Lookup table → file
SELECT pg_relation_filepath('public.my_table'::regclass);
```

--- 

### 🏗️ Tutorial: Physical Structure Deep Dive

⚠️ **Important**: You need access to the server’s PostgreSQL data directory (not just psql). For local installs, it’s often:

- Linux: `/var/lib/postgresql/<version>/main/base/`

- macOS (Homebrew): `/usr/local/var/postgres/base/`

- Windows: `C:\Program Files\PostgreSQL\<version>\data\base\`

Inside `base/`, each **database** is a folder named with its **OID**. Inside that folder, each table/index is a file named with its **OID**.

---

## 1️⃣ Check Database OID

Run inside `psql`:

```sql
SELECT oid, datname FROM pg_database;
```

👉 You’ll see something like:

```bash
  oid  |   datname
-------+------------
  13763 | postgres
  16384 | job_app
```

So your database folder will be in:

```bash
.../base/16384/
```

---

## 2️⃣ Check Table OIDs

For your schema:

```sql
SELECT oid, relname, relkind 
FROM pg_class
WHERE relname IN ('users','job_seekers','employers','job_listings','applications');
```

- `relkind = r` → table

- `relkind = i` → index

👉 Example output:

```bash
 oid  |relname     |relkind|
-----+------------+-------+
16386|users       |r      |
16402|job_seekers |r      |
16416|employers   |r      |
16430|job_listings|r      |
16449|applications|r      |
```

That means `users` table data lives in a file named `16386` inside your DB’s folder.

```sql
SELECT                   
  n.nspname AS schema,
  c.relname AS table_name,
  c.relfilenode,
  pg_relation_filepath(c.oid) AS path
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
ORDER BY n.nspname, c.relname;
```

---

## 3️⃣ Locate Physical File

Example path (Linux):

```bash
ls -lh /var/lib/postgresql/18/main/base/16384/16386
```

This is your **users** table file. Its size starts at 0KB .

This happens **because your tables have no data yet**.

- PostgreSQL **allocates pages on demand**.

- A new table starts **empty**, with no real disk pages allocated.

- `pg_relation_size()` only measures the **main heap file** (`relfilenode`) size - if no rows exist, it’s minimal (often 0 bytes).

---

## 4️⃣ Check Table Size from PSQL

Instead of going to the OS, you can also check via SQL:

```sql
-- Size in bytes
SELECT pg_relation_size('users');

-- Human-readable
SELECT pg_size_pretty(pg_relation_size('users'));
```

👉 Typically:

```bash
 pg_size_pretty
----------------
 0 bytes
```

## Confirm the actual table pages

Check the number of pages allocated:

```sql
SELECT relname, relpages, reltuples
FROM pg_class
WHERE relname = 'users';
```

Example output:

| relname | relpages | reltuples |
| ------- | -------- | --------- |
| users   | 0        | -1        |

- `relpages` = number of 8 KB pages in the table.

- `reltuples` = estimated row count.

If `relpages = 0`, your table is **truly empty**, which matches your `0 bytes` on disk.

---

## 5️⃣ Insert 50 Sample Rows

We’ll generate rows with `generate_series`:

```sql
INSERT INTO users (username, password, email, user_type)
SELECT 'user_' || g, 'pw_' || g, 'user' || g || '@example.com',
       CASE WHEN g % 2 = 0 THEN 'job_seeker' ELSE 'employer' END
FROM generate_series(1,50) g;
```

## Let us to check the result

`SELECT ctid, xmin, xmax, * FROM users;`

Here’s what each column means:

| Column   | Meaning                                                                             |
| -------- | ----------------------------------------------------------------------------------- |
| **ctid** | Tuple ID: physical location of the row in the table (`(block_number, tuple_index)`) |
| **xmin** | Transaction ID that **inserted this row**                                           |
| **xmax** | Transaction ID that **deleted or updated this row** (0 if not deleted)              |
| `*`      | All normal user columns (username, password, etc.)                                  |

---

### 🔹 2a - `ctid`

- Shows **exact physical location** of each row in the heap.

- Format: `(block, offset)`, e.g., `(0,1)` = first row in first page.

- Useful for:
  
  - Debugging
  
  - Low-level updates/deletes
  
  - Understanding row storage

> Note: `ctid` can **change** if the row is **updated** (because PostgreSQL creates a new version in a new tuple).

---

### 🔹 2b - `xmin`

- **Transaction ID** that inserted the row.

- All 50 rows likely share the same `xmin` if inserted in a **single transaction**, e.g., your `INSERT ... SELECT` statement.

- PostgreSQL uses `xmin` for **MVCC visibility**: which transactions can see this row.

---

### 🔹 2c - `xmax`

- Transaction ID that **deleted or updated** this row.

- 0 means the row is **still live** (not deleted or updated).

- If you later delete or update the row, a new transaction ID appears here, and `xmin/xmax` help PostgreSQL determine which version is visible to which transaction.

---

### 🔹 2d - `*`

- Your **user columns**: `username`, `password`, `email`, `user_type`.

So the output will look like:

| ctid  | xmin  | xmax | username | password | email | user_type  |
| ----- | ----- | ---- | -------- | -------- | ----- | ---------- |
| (0,1) | 12345 | 0    | user_1   | pw_1     | ...   | employer   |
| (0,2) | 12345 | 0    | user_2   | pw_2     | ...   | job_seeker |
| ...   | ...   | ...  | ...      | ...      | ...   | ...        |
| (1,2) | 12345 | 0    | user_50  | pw_50    | ...   | job_seeker |

> `xmin` is same for all rows if inserted in a single statement.  
> `ctid` increments as tuples are inserted across heap pages.

---

## 6️⃣ Recheck Size

```sql
SELECT pg_size_pretty(pg_relation_size('users'));
```

👉 Output should jump to **8KB** or higher depending on row size.  
Since PostgreSQL allocates space in **8KB pages**, the file grows in increments of 8192 bytes.

![Page structure](https://rachbelaid.com/assets/posts/heap_file_page.png)

---

## 7️⃣ Check All Tables + Index Sizes

```sql
SELECT relname, relkind,
       pg_size_pretty(pg_relation_size(oid)) AS size
FROM pg_class
WHERE relname IN ('users','job_seekers','employers','job_listings','applications','idx_job_listings');
```

---

# ✅ Recap

- Every **database** → one folder in `base/` named after its OID

- Every **table/index** → one file inside that folder, named after its OID

- PostgreSQL stores data in **8KB pages** (default)

- Even empty tables take **1 page (8KB)**

- As you insert rows, the file grows in multiples of 8KB

---

## 1️⃣ What is a Heap in PostgreSQL?

In PostgreSQL, a **heap** is the **basic storage structure for tables**.

- Every table is stored in a **heap file** on disk.

- A heap is **unordered** - PostgreSQL does **not guarantee any order of rows**.

- Each row in a heap is called a **tuple**.

So when you do:

`CREATE TABLE users (...);`

PostgreSQL creates a **heap file** on disk:

`/base/<db_oid>/<relfilenode>`

- `<db_oid>` → the database’s internal ID.

- `<relfilenode>` → the file that stores the table’s tuples.

---

## 2️⃣ Heap Pages and Tuples

PostgreSQL stores data in **8 KB pages (blocks)** by default.

- Each page contains multiple **tuples** (rows).

- Each tuple has:
  
  - **User data** (columns)
  
  - **System metadata** (xmin, xmax, ctid, t_infomask, etc.)

### Example:

```bash
Heap (users table)
┌───────────── page 0 ─────────────┐
│ tuple 0 | tuple 1 | tuple 2 | ...│
└─────────────────────────────────┘
┌───────────── page 1 ─────────────┐
│ tuple 8 | tuple 9 | ...          │
└─────────────────────────────────┘
```

- `ctid` = `(page_number, tuple_index)` → e.g., `(0,1)` for page 0, 2nd tuple.

---

## 3️⃣ Key Properties of Heaps

| Property             | Description                                                                        |
| -------------------- | ---------------------------------------------------------------------------------- |
| **Unordered**        | Rows are not stored in any logical order; queries use indexes or sequential scans. |
| **MVCC support**     | Each tuple stores `xmin` and `xmax` for **multi-version concurrency control**.     |
| **Expandable**       | More tuples → new pages allocated automatically.                                   |
| **Physical storage** | Heap files live in `base/<db_oid>/` directories.                                   |
| **TOAST**            | Large column values may be stored externally in `pg_toast` tables.                 |

---

## 4️⃣ Why it’s called a “Heap”

- PostgreSQL calls it a **heap** because rows are **added wherever space is available**.

- It’s not a heap in the algorithmic sense (like a heap tree).

- New rows are inserted into the first available page with free space.

## 1️⃣ What you have on disk

Directory for your table (`users`):

`/base/16475/16477`

Files:

| File        | Size  | Purpose                                                       |
| ----------- | ----- | ------------------------------------------------------------- |
| `16477`     | 24 KB | **Main heap file**: stores the actual table tuples (rows)     |
| `16477_fsm` | 24 KB | **Free Space Map (FSM)**: tracks free space in the heap pages |

---

## 2️⃣ Main Heap File

- Named exactly like the table’s `relfilenode` (here: `16477`)

- Stores **all table tuples** in 8 KB pages by default.

- When you insert rows:
  
  - Tuples are written to heap pages
  
  - Each page is 8 KB

- `pg_relation_size('users')` → returns size of this main heap file **only** (ignores FSM and TOAST files by default).

---

## 3️⃣ Free Space Map (`_fsm` file)

- Named as `relfilenode_fsm` (here: `16477_fsm`)

- Purpose: **track which pages in the heap have free space** for inserts or updates

- Each heap page has metadata in FSM:
  
  - How many tuples/pages are available
  
  - How much free space exists for new tuples

- PostgreSQL uses FSM to **avoid scanning all pages** when inserting new rows

> Think of it as a **directory of free spots** in your heap.

- `_fsm` grows dynamically as the heap grows (so its size may equal or exceed heap size early on).

- It **does not store row data** — only page availability info.

---

## 4️⃣ Other related files

PostgreSQL may also create:

| File suffix | Purpose                                                                                                                                 |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `_vm`       | Visibility Map: tracks which pages are **all-visible** (all tuples are visible to all transactions). Helps VACUUM and index-only scans. |
| `_toast`    | Stores large column values (TOASTed data).                                                                                              |
| `_fsm`      | Free Space Map                                                                                                                          |

So a table can have:

`16477 → heap (tuples) 16477_fsm → free space map 16477_vm → visibility map 16477_toast → if large values exist`

---

## 5️⃣ 6️⃣ How they work together

- When you `INSERT` a new row:
  
  1. PostgreSQL checks `_fsm` to find a page with enough free space
  
  2. Writes the row to that heap page
  
  3. Updates `_fsm` if space changes

- When you `UPDATE` a row and the new tuple doesn’t fit in the old page:
  
  - PostgreSQL writes it to a **new page** in the heap
  
  - Updates `_fsm` to reflect the free space

---

## 7️⃣ Key Takeaways

| File        | What it contains     | Size behavior                                                            |
| ----------- | -------------------- | ------------------------------------------------------------------------ |
| `16477`     | Heap (actual tuples) | Grows with inserted/updated rows                                         |
| `16477_fsm` | Free Space Map       | Grows as heap pages are allocated; may initially be similar to heap size |
| `16477_vm`  | Visibility Map       | Grows as pages become all-visible; optimizes index-only scans            |

- `_fsm` is **metadata only**, not counted in `pg_relation_size()` unless you explicitly use `pg_total_relation_size('users')`.

```sql
SELECT pg_relation_size('users');           -- heap only
SELECT pg_total_relation_size('users');     -- heap + FSM + TOAST + VM
```
