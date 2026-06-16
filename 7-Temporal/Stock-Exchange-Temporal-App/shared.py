from dataclasses import dataclass
from pathlib import Path

STOCK_EXCHANGE_TASK_QUEUE = "STOCK_EXCHANGE_TASK_QUEUE"

EXCEL_FILE_PATH = str(Path(__file__).parent / "data")
EXCEL_FILE_NAME = "daily_trades"
EXCEL_FILE_EXT_XLSX = "xlsx"
EXCEL_FILE_EXT_CSV = "csv"


@dataclass
class StockExchangeInput:
    execution_date: str


@dataclass
class StockExchangeBackfillInput:
    start_date: str
    end_date: str
