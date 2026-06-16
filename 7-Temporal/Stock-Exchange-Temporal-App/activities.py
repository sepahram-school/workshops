import asyncio
import os
from datetime import datetime
from pathlib import Path

import jdatetime
import pandas as pd
import requests

from temporalio import activity

from shared import EXCEL_FILE_PATH, EXCEL_FILE_NAME, EXCEL_FILE_EXT_XLSX, EXCEL_FILE_EXT_CSV


def is_symbol(row):
    try:
        return int("".join(filter(str.isdigit, row["نماد"]))) < 20
    except Exception:
        return True


class StockExchangeActivities:

    @activity.defn
    async def download_xlsx(self, ds: str) -> str:
        file_path = str(Path(EXCEL_FILE_PATH) / f"{EXCEL_FILE_NAME}_{ds}.{EXCEL_FILE_EXT_XLSX}")
        activity.logger.info(f"Downloading XLSX from TSETMC for date {ds}")
        response = await asyncio.to_thread(
            requests.get,
            f"https://members.tsetmc.com/tsev2/excel/MarketWatchPlus.aspx?d={ds}",
            headers={"User-Agent": "Chrome/61.0"},
        )
        response.raise_for_status()
        Path(EXCEL_FILE_PATH).mkdir(parents=True, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(response.content)
        return file_path

    @activity.defn
    async def wait_for_file(self, file_path: str) -> None:
        while not await asyncio.to_thread(Path(file_path).exists):
            activity.logger.info(f"Waiting for file {file_path}...")
            await asyncio.sleep(10)

    @activity.defn
    async def preprocess(self, xlsx_path: str) -> str | None:
        ds = Path(xlsx_path).stem.split("_")[-1]
        csv_path = str(Path(EXCEL_FILE_PATH) / f"{EXCEL_FILE_NAME}_{ds}.{EXCEL_FILE_EXT_CSV}")

        en_date = datetime.strptime(ds, "%Y-%m-%d").date()
        fa_date = jdatetime.date.fromgregorian(date=en_date)

        activity.logger.info(f"Processing {xlsx_path} -> {csv_path}")
        df = await asyncio.to_thread(
            pd.read_excel, xlsx_path, header=0, skiprows=2, engine="openpyxl"
        )
        if df.empty:
            activity.logger.info(f"Empty XLSX for {ds} (non-trading day). Skipping CSV.")
            return None
        df = df.assign(fa_date=fa_date.strftime("%Y-%m-%d"), en_date=ds, fa_year=fa_date.year)
        df = df[df.apply(is_symbol, axis=1)]
        await asyncio.to_thread(df.to_csv, csv_path, index=False, header=True, encoding="utf-8")
        return csv_path

    @activity.defn
    async def delete_xlsx(self, xlsx_path: str) -> None:
        activity.logger.info(f"Deleting {xlsx_path}")
        try:
            await asyncio.to_thread(os.remove, xlsx_path)
        except FileNotFoundError:
            pass
