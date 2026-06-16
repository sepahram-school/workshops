# Temporal Python Self-Learning Workshop

A two-part, hands-on workshop that takes you from "what is a Workflow?" to "I run Temporal in production." All code is Python 3.13+ and uses the official [`temporalio`](https://python.temporal.io) SDK.

---

## Workshop structure

This repository is split into two workshops that build on each other. **Start with `Workshop-Basic.md`, then move to `Workshop-Advanced.md`.**

| # | Document | What you'll build | Time |
|---|---|---|---|
| 1 | [`Workshop-Basic.md`](./Workshop-Basic.md) | A Stock Exchange data pipeline (TSETMC download -> transform -> CSV) with backfill, parent/child workflows, schedules, standalone activities, and batch operations | ~2 hours |
| 2 | [`Workshop-Advanced.md`](./Workshop-Advanced.md) | Production patterns: Saga compensations, retry policies, long-running workflows with Continue-As-New, signals/queries/updates, activity heartbeats, versioning, search attributes, anti-patterns | ~3 hours |

The Basic workshop is the **on-ramp**: it teaches the mental model with a real, runnable app. The Advanced workshop is the **deep dive**: it teaches the patterns that distinguish "Temporal users" from "Temporal engineers."

```
+----------------+        +-------------------+
|  Workshop-     |  --->  |  advanced-        |
|  Basic.md      |        |  workshop.md      |
|  (run a real   |        |  (build real      |
|  app)          |        |  production       |
|                |        |  patterns)        |
+----------------+        +-------------------+
       |                          |
       v                          v
  Stock-Exchange-         (apply to your own
  Temporal-App/           use case)
  (runnable code)
```

### Repository layout

```
Temporal/
|-- README.md                            # You are here
|-- Workshop-Basic.md                    # Part 1 tutorial (beginner)
|-- Workshop-Advanced.md                 # Part 2 tutorial (advanced)
|-- AGENTS.md                            # Conventions for AI assistants
|
|-- pyproject.toml                       # ONE project file (root)
|-- uv.lock                              # Locked dependency versions
|-- .python-version                      # Python 3.13
|-- .venv/                               # ONE virtual env (root)
|
|-- temporal.exe                         # Temporal CLI for Windows
|
+-- Stock-Exchange-Temporal-App/         # Part 1 code
    |-- shared.py                        # Constants and dataclasses
    |-- activities.py                    # 4 @activity.defn methods
    |-- workflows.py                     # StockExchangeWorkflow + parent
    |-- run_worker.py                    # Worker entry point
    |-- run_workflow.py                  # Single-day client
    |-- run_backfill.py                  # Per-day backfill (client loop)
    |-- run_parent_backfill.py           # Parent + child backfill
    |-- run_standalone_activity.py       # Standalone-activity client
    |-- run_schedule.py                  # Schedule manager
    |-- __init__.py                      # Module marker
    |-- data/                            # Runtime artifacts (gitignored)
    |-- sample.excalidraw.json           # Reference Excalidraw
    +-- stock_exchange_architecture.excalidraw.json
```

All Python code lives in **one virtual environment at the root**. The scripts inside `Stock-Exchange-Temporal-App/` use the root `.venv` and the root `pyproject.toml`.

---

## 1. Prerequisites

You need:

- **Python 3.13+** (the repo pins it via `.python-version`)
- **uv** (fast Python package manager - replaces pip + venv)
- **Temporal CLI** (the `temporal` binary for running the dev server)
- **Windows PowerShell 5.1+**, macOS, or Linux (any OS Temporal supports)

---

## 2. Install uv (Python package manager)

uv is a single binary that replaces `pip`, `venv`, `pip-tools`, and `pyenv`. It is dramatically faster than pip and is the official recommendation in the Temporal Python community.

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uv --version
```

If you already have Python 3.13+ installed, **do not create a new venv manually** - the next section handles it.

> **Why not pip?** `pip` is slow, does not handle multiple Python versions, and does not manage a lockfile. `uv` is 10-100x faster and is what every recent Temporal Python tutorial uses.

---

## 3. Install the Temporal CLI

The Temporal CLI is a single binary that:

- Runs a local **Temporal dev server** (server + Web UI + SQLite DB).
- Provides the `temporal` command for inspecting workflows, batch operations, schedules, and operators.
- Works offline, no Docker required, perfect for tutorials.

### Option A: download the official binary (recommended)

The repo already ships a `temporal.exe` for Windows at the root. To get the latest version for any OS, use one of these:

**Windows (PowerShell):**

```powershell
curl -o temporal.exe -L https://github.com/temporalio/cli/releases/latest/download/temporal_windows_amd64.exe
```

**macOS (Apple Silicon):**

```bash
curl -L https://github.com/temporalio/cli/releases/latest/download/temporal_darwin_arm64.tar.gz | tar -xz
sudo mv temporal_darwin_arm64/temporal /usr/local/bin/
```

**macOS (Intel):**

```bash
curl -L https://github.com/temporalio/cli/releases/latest/download/temporal_darwin_amd64.tar.gz | tar -xz
sudo mv temporal_darwin_amd64/temporal /usr/local/bin/
```

**Linux (x86_64):**

```bash
curl -L https://github.com/temporalio/cli/releases/latest/download/temporal_linux_amd64.tar.gz | tar -xz
sudo mv temporal_linux_amd64/temporal /usr/local/bin/
```

Verify:

```bash
temporal --version
```

### Option B: install via Homebrew (macOS / Linux)

```bash
brew install temporal
```

### Option C: install via winget (Windows)

```powershell
winget install temporal.cli
```

After install, place the binary on your `PATH` (or move it to the repo root - both work).

> **Don't want to download anything?** You can also use the `temporal` Python SDK's built-in dev server: `pip install temporalio` and then `python -c "import temporalio.testing; ..."` in your test code. For the workshop we use the standalone `temporal` CLI because it gives you the Web UI for free.

---

## 4. Install the project (one command)

From the repo root:

```bash
uv sync
```

This will:

1. Detect Python 3.13 (from `.python-version`).
2. Create `.venv/` at the repo root.
3. Install all dependencies listed in `pyproject.toml` (temporalio, pandas, openpyxl, requests, jdatetime).

Activate the venv (optional - `uv run` does this for you):

**Windows:**

```bash
.venv\Scripts\activate
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

That's it. You don't need separate venvs for the basic and advanced workshops.

---

## 5. Start the Temporal dev server

In **Terminal 1**:

```bash
temporal server start-dev
```

You should see:

```
Temporal server is running on localhost:7233
Web UI is available at http://localhost:8233
```

Open the Web UI: <http://localhost:8233>

It is empty for now. That is expected.

> **What just happened?** Temporal started a single-node, single-namespace (`default`) dev server. By default it stores everything **in memory** - no file is created on disk, so **all workflow history is lost when you stop the server**. That is the right behavior for a tutorial. For production you would use **Temporal Cloud** or a self-hosted cluster with PostgreSQL persistence.
>
> If you want to keep your history across restarts (recommended once you start running real workflows), see [section 5.1](#51-persist-history-across-restarts-optional).

### 5.1 Persist history across restarts (optional)

**Heads up**: by default `temporal server start-dev` is **stateless on disk**. Press Ctrl+C, restart, and your workflows are gone. That is fine for learning, but painful once you start running backfills and schedules you care about.

To keep history between restarts, pass `--db-filename`:

```bash
# Windows PowerShell
temporal server start-dev --db-filename "$PWD\temporal_dev.db"

# macOS / Linux
temporal server start-dev --db-filename ./temporal_dev.db
```

A SQLite file is created at the path you gave. It holds:

- **Workflow history** (every state, event, and timer)
- **Schedules** (the schedule definitions, not just the runs)
- **Tasks** (pending activity, workflow, and timer tasks)
- **Visibility data** (the records you see in the Web UI's "Workflows" list)
- **Namespaces** and their config
- **Custom search attributes** registered with `--search-attribute`

**Always gitignore the DB file.** The repo already ignores `*.db`, but here is the pattern explicitly:

```gitignore
# .gitignore
*.db
temporal_dev.db
temporalite.db
your_temporal.db
```

Once you start running workflows, you can verify the file appears and grows:

```bash
# After running some workflows, the file exists and grows
ls -lh temporal_dev.db       # macOS / Linux
Get-Item temporal_dev.db     # PowerShell
```

**Useful flags to combine with `--db-filename`:**

```bash
# Verbose logging (great for debugging)
temporal server start-dev --db-filename ./temporal_dev.db --log-level warn

# Custom UI port (e.g. you already have something on 8233)
temporal server start-dev --db-filename ./temporal_dev.db --ui-port 8234

# Pre-register a search attribute
temporal server start-dev --db-filename ./temporal_dev.db \
  --search-attribute "CustomKeywordField=Keyword"

# Disable the Web UI entirely (worker-only setup)
temporal server start-dev --db-filename ./temporal_dev.db --headless
```

**Trade-offs vs. the in-memory default:**

| Aspect | In-memory (default) | Persistent (`--db-filename`) |
|---|---|---|
| History across restarts | Lost | Kept |
| Startup time | ~1 second | ~1-3 seconds (SQLite open + replay check) |
| Disk usage | 0 | ~1-2 MB per day of workflow history |
| Default retention | n/a | 1 day (then history is purged - see below) |
| Reset to clean state | Just Ctrl+C | Stop, `rm temporal_dev.db`, restart |
| Best for | Quick experiments, tutorial first run | Real backfills, schedules, debugging |

**Default retention is 1 day in dev.** This means workflow history is kept for 1 day after the workflow closes, then purged. For longer retention, set the namespace config:

```bash
# In a one-off namespace (the 'default' namespace cannot be customized in dev)
temporal operator namespace create long-retention \
  --retention 168h
```

For real workloads, the retention setting is the most common source of "where did my workflow go?" surprises. When in doubt: increase the namespace retention and use the `temporal workflow describe` output to check the workflow's `CloseTime`.

**For comparison with the rest of the workshop:** the cleanup section [10](#10-cleaning-up-resetting-the-dev-server) covers how to wipe a persistent DB. Section [10.4](#104-if-you-want-a-persistent-dev-db) used to be the canonical home for the `--db-filename` flag - it is now a short pointer back to this section.

---

## 6. Verify everything works

From the repo root:

```bash
uv run --project . Stock-Exchange-Temporal-App/run_workflow.py
```

Expected output (after the TSETMC download completes):

```
Result: {'xlsx_path': '.../data/daily_trades_2026-05-18.xlsx', 'csv_path': '.../data/daily_trades_2026-05-18.csv', 'data_found': True, 'status': 'completed'}
```

If you see a `Result:` line, the Temporal server, the Worker, and the Client are all talking to each other.

> **Why `uv run --project .`?** `uv` walks up the directory tree to find a `pyproject.toml`. By being explicit (`--project .`) we make sure the root venv is used regardless of where the script lives. You can also `cd Stock-Exchange-Temporal-App && uv run run_workflow.py` - same effect.

---

## 7. Now read the workshop

Pick one of:

| If you are... | Read this | Then this |
|---|---|---|
| New to Temporal | [`Workshop-Basic.md`](./Workshop-Basic.md) | [`Workshop-Advanced.md`](./Workshop-Advanced.md) |
| Already know Temporal basics | [`Workshop-Advanced.md`](./Workshop-Advanced.md) | - |
| Returning after a break | the **Table of Contents** at the top of either file | the section that matches what you forgot |

### `Workshop-Basic.md` at a glance

- 0. Why Temporal? (When DAGs aren't enough)
- 1. Temporal architecture (with Excalidraw + Mermaid)
- 2. How Workflows, Activities, Workers, and the Server fit together
- 3. Step-by-step build of the Stock Exchange app
  - Steps 0-7: the basic pipeline (download, wait, process, delete)
  - Step 6.5: handle non-trading days (empty XLSX)
  - Step 8: backfill one workflow per day
  - Step 8.5-8.6: parent + child workflows
  - Step 9: standalone activities
  - Step 10: schedules
  - Step 11: batch operations
- 4. Exercises (11 hands-on challenges)
- 5. Glossary

### `Workshop-Advanced.md` at a glance

- 1. The failure-first mindset
- 2. Workflows as durable async event loops
- 3. The Saga pattern in practice
- 4. Retry policies: forward vs. backward recovery
- 5. Long-running workflows and Continue-As-New
- 6. Signals, queries, and updates
- 7. Activity heartbeats
- 8. Versioning safely with patching
- 9. Search attributes and observability
- 10. Production anti-patterns
- 11. Hands-on lab: a resilient order pipeline
- 12. Resources and further reading

Both files are self-contained - you can read either without the other, but reading Basic first is recommended.

---

## 8. The 3-terminal pattern

Every workshop example uses the same three-terminal layout. Open them once and leave them open:

```
+---------------------------+   +--------------------------+   +-------------------------+
|      Terminal 1           |   |      Terminal 2          |   |      Terminal 3         |
|      (server)             |   |      (worker)            |   |      (client / CLI)     |
|                           |   |                          |   |                         |
|  temporal server          |   |  cd Stock-Exchange-      |   |  cd Stock-Exchange-     |
|    start-dev              |   |    Temporal-App          |   |    Temporal-App         |
|                           |   |  uv run run_worker.py    |   |  uv run run_workflow.py |
|  (runs forever)           |   |                          |   |  uv run run_backfill.py |
+---------------------------+   +--------------------------+   +-------------------------+
        :7233 gRPC                     :7233 gRPC                     :7233 gRPC
            \____________ | ____________/
                         \|/
              +-----------------------+
              |   Temporal Server     |
              |   (Web UI :8233)      |
              +-----------------------+
```

You can have multiple workers in Terminal 2 (just run `run_worker.py` in several terminals) - they share the load.

---

## 9. Useful Temporal CLI commands

These work with your local dev server.

```bash
# List recent workflows
temporal workflow list

# Describe one workflow in detail
temporal workflow describe --workflow-id stock-exchange-workflow-001

# Show the full event history as JSON
temporal workflow describe --workflow-id <id> --output json

# List standalone activities
temporal activity list

# List schedules
temporal schedule list

# Count workflows by status
temporal workflow count --query "ExecutionStatus='Failed'"

# Open the Web UI from the terminal
temporal operator namespace list
```

Full CLI reference: <https://docs.temporal.io/cli>.

---

## 10. Cleaning up (resetting the dev server)

The dev server keeps state about every workflow execution, schedule, and namespace you have ever created. Here is how to wipe it, depending on how thorough you want to be.

### 10.1 First, the critical fact: in-memory by default

By default, `temporal server start-dev` uses an **in-memory store** with no SQLite file on disk.

> `Path to file for persistent Temporal state store. By default, Workflow Executions are lost when the server process dies.` - `temporal server start-dev --help`

This means **stopping the server wipes all history for free** - no DB file to delete. Run `temporal server start-dev` again and the Web UI is empty.

You only need a persistent DB if you want to stop and restart the server without losing history (e.g. to test upgrade scenarios, or to share a single dev server across machine restarts). See section 10.4 below.

### 10.2 Wipe everything in one go

The fastest reset, with the server **stopped**:

```bash
# Terminal 1: stop the server
Ctrl+C

# Restart fresh
temporal server start-dev
```

If you have been using `--db-filename` (see 10.4), the DB persists across restarts. In that case you need to delete the file too:

```bash
# Stop the server first, then:
rm -f path/to/your.db       # macOS / Linux
Remove-Item -Force <path>   # PowerShell
temporal server start-dev
```

### 10.3 Wipe things while the server is running

You can clean up **individual resources** without stopping the server. Useful when you want to remove one bad workflow but keep the rest of your test history.

```bash
# Wipe a single workflow
temporal workflow delete --workflow-id stock-exchange-workflow-001

# Wipe ALL workflows of a given type
temporal workflow delete --query 'WorkflowType="StockExchangeWorkflow"'

# Wipe every FAILED workflow
temporal workflow delete --query 'ExecutionStatus="Failed"'

# Wipe every COMPLETED workflow
temporal workflow delete --query 'ExecutionStatus="Completed"'

# Wipe everything in every status
temporal workflow delete --query 'WorkflowType is not null'
```

> The CLI will ask you to confirm with a `y/n` prompt. For non-interactive use (CI / scripts) pipe it: `echo y | temporal workflow delete --query '...'`.

> For very large batches, increase the timeout: `--query-rpc-timeout 60s`. Otherwise the server may stream only a partial set.

Schedules, search attributes, and namespaces each have their own command:

```bash
# Wipe a schedule
temporal schedule delete --schedule-id <id>

# Wipe a namespace (rare; the 'default' namespace cannot be deleted)
temporal operator namespace delete <name>

# Wipe a custom search attribute
temporal operator search-attribute delete --name <attr>
```

### 10.4 If you want a persistent dev DB

See [section 5.1 Persist history across restarts](#51-persist-history-across-restarts-optional) for the full guide. The TL;DR is:

```bash
temporal server start-dev --db-filename ./temporal_dev.db
```

To reset a persistent DB: stop the server, delete the file, restart.

### 10.5 Pre-flight: take inventory before you wipe

Before any destructive cleanup, see what you have:

```bash
# Workflow inventory by status
temporal workflow count --query 'ExecutionStatus="Running"'
temporal workflow count --query 'ExecutionStatus="Failed"'
temporal workflow count --query 'ExecutionStatus="Completed"'

# Everything (slow on big histories, but accurate)
temporal workflow list --limit 1000

# Schedules
temporal schedule list

# Namespaces
temporal operator namespace list
```

The two `temporal workflow count` commands take less than a second and give you a quick gut-check before running a bulk `delete`.

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `temporal: command not found` | The CLI is not on your `PATH`. Move `temporal.exe` to the repo root or add its folder to `PATH`. |
| `Connection refused on localhost:7233` | You forgot Terminal 1 - run `temporal server start-dev`. |
| `Workflow ID conflict` | The previous workflow with this ID is still running. Either wait for it, change the ID, or `temporal workflow terminate --workflow-id <id> --reason "cleanup"`. For a deeper reset see [section 10](#10-cleaning-up-resetting-the-dev-server). |
| `ModuleNotFoundError: temporalio` | Run `uv sync` from the repo root. |
| `uv sync` fails on a corporate network | The repo's `pyproject.toml` uses a mirror (`mirror2.chabokan.net`). If you can reach PyPI directly, remove the `[[tool.uv.index]]` block. |
| TSETMC throttling / SSL errors on backfill | 11+ parallel downloads trigger throttling. Use `run_parent_backfill.py` (caps at 5) or wait between runs. |
| `.venv` got corrupted | Delete it and run `uv sync` again. |
| Web UI shows stale data after server restart | You are using `--db-filename`; either delete the DB (section 10.2) or accept the persistence. |

---

## 12. Where to go from here

- **Build something.** Apply one of the patterns from `Workshop-Advanced.md` to your own use case.
- **Temporal University** (free): <https://learn.temporal.io> - 101, 102, and deep-dive courses.
- **Official Python SDK docs**: <https://python.temporal.io>
- **Community forum**: <https://community.temporal.io>
- **Slack**: <https://t.mp/slack>
- **Production**: When you outgrow the dev server, sign up for **Temporal Cloud** (free $1,000 credit) or self-host a cluster with PostgreSQL persistence.

Happy hacking.
