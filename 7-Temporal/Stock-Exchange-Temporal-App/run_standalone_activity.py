import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from temporalio.client import Client

from activities import StockExchangeActivities
from shared import EXCEL_FILE_PATH, EXCEL_FILE_NAME, EXCEL_FILE_EXT_XLSX


async def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run run_standalone_activity.py <YYYY-MM-DD>")
        sys.exit(1)
    ds = sys.argv[1]

    client = await Client.connect("localhost:7233")
    activities = StockExchangeActivities()

    xlsx_path = str(Path(EXCEL_FILE_PATH) / f"{EXCEL_FILE_NAME}_{ds}.{EXCEL_FILE_EXT_XLSX}")
    if not Path(xlsx_path).exists():
        print(f"XLSX not found. Downloading {ds} as a standalone activity...")
        dl_id = f"standalone-download-{uuid.uuid4().hex[:8]}"
        xlsx_path = await client.execute_activity(
            activities.download_xlsx,
            ds,
            id=dl_id,
            task_queue="STOCK_EXCHANGE_TASK_QUEUE",
            schedule_to_close_timeout=timedelta(minutes=5),
        )
        print(f"Downloaded: {xlsx_path}")

    activity_id = f"standalone-preprocess-{uuid.uuid4().hex[:8]}"
    print(f"Executing preprocess activity (id={activity_id}) for {xlsx_path}...")
    result = await client.execute_activity(
        activities.preprocess,
        xlsx_path,
        id=activity_id,
        task_queue="STOCK_EXCHANGE_TASK_QUEUE",
        schedule_to_close_timeout=timedelta(minutes=5),
    )
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
