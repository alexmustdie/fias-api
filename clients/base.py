from abc import ABC, abstractmethod
from typing import List

from core.models import AddressRequest, NormalizedAddress


class NormalizerClient(ABC):
    """Абстрактный клиент нормализации адресов"""

    @abstractmethod
    async def normalize(self, request: AddressRequest) -> NormalizedAddress:
        """Нормализовать один адрес"""
        ...

    async def normalize_batch(
        self, requests: List[AddressRequest]
    ) -> List[NormalizedAddress]:
        """Нормализовать пачку адресов"""
        results = []
        for req in requests:
            results.append(await self.normalize(req))
        return results

    async def close(self) -> None:
        """Закрыть соединения"""
        ...
