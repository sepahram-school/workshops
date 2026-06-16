import asyncio
import sys

from temporalio.client import Client

from shared import STOCK_EXCHANGE_TASK_QUEUE, StockExchangeInput
from workflows import StockExchangeWorkflow


async def main() -> None:
    client = await Client.connect("localhost:7233")

    ds = sys.argv[1] if len(sys.argv) > 1 else "2026-05-18"
    input_data = StockExchangeInput(execution_date=ds)

    result = await client.execute_workflow(
        StockExchangeWorkflow.run,
        input_data,
        id="stock-exchange-workflow-001",
        task_queue=STOCK_EXCHANGE_TASK_QUEUE,
    )

    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
