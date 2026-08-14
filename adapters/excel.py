import logging
from typing import List, Optional

import pandas as pd

from core.models import NormalizedAddress
from adapters.base import IOAdapter

logger = logging.getLogger(__name__)


class ExcelAdapter(IOAdapter):

    def __init__(
        self,
        id_column: str = "debt_id",
        address_column: str = "address",
        result_column: str = "normalized_address",
        status_column: str = "status",
        error_column: str = "error",
    ):
        self.id_column = id_column
        self.address_column = address_column
        self.result_column = result_column
        self.status_column = status_column
        self.error_column = error_column

    def read(self, path: str) -> List[dict]:
        df = pd.read_excel(path)

        if self.id_column not in df.columns:
            raise ValueError(f"Колонка '{self.id_column}' не найдена в {path}")
        if self.address_column not in df.columns:
            raise ValueError(f"Колонка '{self.address_column}' не найдена в {path}")

        records = []
        for _, row in df.iterrows():
            addr = row[self.address_column]
            if pd.isna(addr) or not str(addr).strip():
                continue
            records.append({
                "id": str(row[self.id_column]),
                "search_string": str(addr).strip(),
            })
        return records

    def write(self, path: str, results: List[NormalizedAddress]) -> None:
        df = pd.DataFrame([{
            self.id_column: r.id,
            self.result_column: r.full_address or "",
            self.status_column: r.status, 
            self.error_column: r.error or "",
        } for r in results])
        df.to_excel(path, index=False, engine="openpyxl")
