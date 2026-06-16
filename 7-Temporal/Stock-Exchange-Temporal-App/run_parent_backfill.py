import asyncio
import sys
from datetime import datetime, timedelta

from temporalio.client import Client

from shared import STOCK_EXCHANGE_TASK_QUEUE, StockExchangeBackfillInput
from workflows import StockExchangeBackfillParentWorkflow


def get_default_dates():
    """Return (start, end) defaulting to last 30 days ending today."""
    end = datetime.now().date()
    start = end - timedelta(days=30)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


async def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None

    if not start and not end:
        # Neither provided: default to last 30 days
        start, end = get_default_dates()
        print(f"No date range provided. Using default (last 30 days): {start} -> {end}")
    elif start and not end:
        # Only start provided: default end to today
        end = datetime.now().date().strftime("%Y-%m-%d")
        print(f"End date not provided. Using today as end: {start} -> {end}")

    if end < start:
        start, end = end, start
        print(f"Dates reversed — swapping to: {start} -> {end}")

    client = await Client.connect("localhost:7233")

    print(f"Launching parent backfill ({start} -> {end})...")
    handle = await client.start_workflow(
        StockExchangeBackfillParentWorkflow.run,
        StockExchangeBackfillInput(start_date=start, end_date=end),
        id=f"parent-stock-exchange-backfill-{start}-{end}",
        task_queue=STOCK_EXCHANGE_TASK_QUEUE,
    )
    print(f"Parent started: {handle.id}")
    print("Open the Web UI to watch parent + child workflows in real time.")

    result = await handle.result()
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())