from abc import ABC, abstractmethod
from typing import List

from core.models import NormalizedAddress


class IOAdapter(ABC):
    """Абстрактный адаптер для чтения/записи"""

    @abstractmethod
    def read(self, path: str) -> List[dict]:
        """Вернуть список dict с полями id и search_string"""
        ...

    @abstractmethod
    def write(self, path: str, results: List[NormalizedAddress]) -> None:
        """Записать результаты"""
        ...
