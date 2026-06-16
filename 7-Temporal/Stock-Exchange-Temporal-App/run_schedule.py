import asyncio
import sys
from datetime import datetime, timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)

from shared import STOCK_EXCHANGE_TASK_QUEUE, StockExchangeInput
from workflows import StockExchangeWorkflow

SCHEDULE_ID = "daily-stock-exchange"


async def create_schedule(client: Client) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    await client.create_schedule(
        SCHEDULE_ID,
        Schedule(
            action=ScheduleActionStartWorkflow(
                StockExchangeWorkflow.run,
                StockExchangeInput(execution_date=today),
                id=f"scheduled-stock-exchange-{today}",
                task_queue=STOCK_EXCHANGE_TASK_QUEUE,
            ),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=24))]),
            state=ScheduleState(note="Daily stock exchange workflow (Iran trading days)"),
        ),
    )
    print(f"Schedule '{SCHEDULE_ID}' created (runs every 24h).")


async def list_schedules(client: Client) -> None:
    async for s in await client.list_schedules():
        next_time = s.info.next_action_times[0] if s.info.next_action_times else "no upcoming"
        print(f"  {s.id}: next run = {next_time}")


async def pause_schedule(client: Client) -> None:
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.pause(note="Paused for maintenance")
    print(f"Schedule '{SCHEDULE_ID}' paused.")


async def unpause_schedule(client: Client) -> None:
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.unpause(note="Resuming")
    print(f"Schedule '{SCHEDULE_ID}' unpaused.")


async def trigger_schedule(client: Client) -> None:
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.trigger()
    print(f"Schedule '{SCHEDULE_ID}' triggered.")


async def delete_schedule(client: Client) -> None:
    handle = client.get_schedule_handle(SCHEDULE_ID)
    await handle.delete()
    print(f"Schedule '{SCHEDULE_ID}' deleted.")


ACTIONS = {
    "create": create_schedule,
    "list": list_schedules,
    "pause": pause_schedule,
    "unpause": unpause_schedule,
    "trigger": trigger_schedule,
    "delete": delete_schedule,
}


async def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    if action not in ACTIONS:
        print(f"Usage: uv run run_schedule.py [{'|'.join(ACTIONS)}]")
        sys.exit(1)
    client = await Client.connect("localhost:7233")
    await ACTIONS[action](client)


if __name__ == "__main__":
    asyncio.run(main())
