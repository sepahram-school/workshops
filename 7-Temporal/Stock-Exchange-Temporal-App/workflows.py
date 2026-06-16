import asyncio
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import StockExchangeActivities
    from shared import StockExchangeBackfillInput, StockExchangeInput


@workflow.defn
class StockExchangeWorkflow:
    @workflow.run
    async def run(self, input: StockExchangeInput) -> dict:
        ds = input.execution_date
        retry_policy = RetryPolicy(
            maximum_attempts=3,
            maximum_interval=timedelta(seconds=10),
        )

        xlsx_path = await workflow.execute_activity_method(
            StockExchangeActivities.download_xlsx,
            ds,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        await workflow.execute_activity_method(
            StockExchangeActivities.wait_for_file,
            xlsx_path,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=retry_policy,
        )

        csv_path = await workflow.execute_activity_method(
            StockExchangeActivities.preprocess,
            xlsx_path,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        await workflow.execute_activity_method(
            StockExchangeActivities.delete_xlsx,
            xlsx_path,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        return {
            "xlsx_path": xlsx_path,
            "csv_path": csv_path,
            "data_found": csv_path is not None,
            "status": "completed",
        }


@workflow.defn
class StockExchangeBackfillParentWorkflow:
    @workflow.run
    async def run(self, input: StockExchangeBackfillInput) -> dict:
        start = datetime.strptime(input.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(input.end_date, "%Y-%m-%d").date()
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        sem = asyncio.Semaphore(5)

        async def run_one(d):
            async with sem:
                return await workflow.execute_child_workflow(
                    StockExchangeWorkflow.run,
                    StockExchangeInput(execution_date=d),
                    id=f"child-stock-exchange-{d}",
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )

        results = await asyncio.gather(*(run_one(d) for d in dates), return_exceptions=True)

        successes = [r for r in results if isinstance(r, dict)]
        failures = [
            {"date": d, "error": str(r)}
            for d, r in zip(dates, results)
            if not isinstance(r, dict)
        ]
        trading = sum(1 for r in successes if r.get("data_found"))
        return {
            "start_date": input.start_date,
            "end_date": input.end_date,
            "dates_processed": len(dates),
            "trading_days": trading,
            "empty_days": sum(1 for r in successes if not r.get("data_found")),
            "failures": failures,
            "status": "completed" if not failures else "completed_with_failures",
        }
