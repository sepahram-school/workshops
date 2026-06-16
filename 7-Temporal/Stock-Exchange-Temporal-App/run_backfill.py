import asyncio
import sys
from datetime import datetime, timedelta

from temporalio.client import Client

from shared import STOCK_EXCHANGE_TASK_QUEUE, StockExchangeInput
from workflows import StockExchangeWorkflow


def date_range(start: str, end: str):
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()
    current = start_d
    while current <= end_d:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


async def launch_one(client, date: str):
    handle = await client.start_workflow(
        StockExchangeWorkflow.run,
        StockExchangeInput(execution_date=date),
        id=f"stock-exchange-backfill-{date}",
        task_queue=STOCK_EXCHANGE_TASK_QUEUE,
    )
    return handle


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
    dates = list(date_range(start, end))
    print(f"Launching {len(dates)} workflows ({start} -> {end})")

    handles = [await launch_one(client, d) for d in dates]
    results = await asyncio.gather(*(h.result() for h in handles))

    trading = sum(1 for r in results if r.get("data_found"))
    empty = len(results) - trading
    print(f"Done: {trading} trading days, {empty} empty days")


if __name__ == "__main__":
    asyncio.run(main())