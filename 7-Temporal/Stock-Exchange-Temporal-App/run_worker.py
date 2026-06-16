import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from activities import StockExchangeActivities
from shared import STOCK_EXCHANGE_TASK_QUEUE
from workflows import StockExchangeBackfillParentWorkflow, StockExchangeWorkflow


async def main() -> None:
    client = await Client.connect("localhost:7233", namespace="default")
    activities = StockExchangeActivities()
    worker = Worker(
        client,
        task_queue=STOCK_EXCHANGE_TASK_QUEUE,
        workflows=[StockExchangeWorkflow, StockExchangeBackfillParentWorkflow],
        activities=[
            activities.download_xlsx,
            activities.wait_for_file,
            activities.preprocess,
            activities.delete_xlsx,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
