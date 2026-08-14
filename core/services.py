import asyncio
import logging
from typing import List, Optional

from core.models import AddressRequest, NormalizedAddress
from clients.base import NormalizerClient

logger = logging.getLogger(__name__)


class AddressNormalizer:

    def __init__(
        self,
        client: NormalizerClient,
        default_address_type: int = 1,
        concurrency: int = 1,
    ):
        self.client = client
        self.default_address_type = default_address_type
        self.semaphore = asyncio.Semaphore(concurrency)

    async def normalize_one(
        self, id: str, address: str, address_type: Optional[int] = None,
    ) -> NormalizedAddress:
        request = AddressRequest(
            id=id,
            search_string=address,
            address_type=address_type if address_type is not None else self.default_address_type,
        )
        async with self.semaphore:
            try:
                return await self.client.normalize(request)
            except Exception as e:
                logger.error("Ошибка нормализации id=%s: %s", id, e)
                return NormalizedAddress.with_error(id, address, str(e))

    async def normalize_many(
        self, records: List[dict], address_type: Optional[int] = None,
        on_progress: Optional[callable] = None,
    ) -> List[NormalizedAddress]:
        """Параллельная нормализация списка записей"""
        results: List[NormalizedAddress] = [None] * len(records)
        processed = 0
        total = len(records)

        async def process(idx: int, record: dict):
            nonlocal processed
            result = await self.normalize_one(
                record["id"], record["search_string"], address_type,
            )
            results[idx] = result
            processed += 1
            if on_progress:
                on_progress(processed, total)

        await asyncio.gather(*[
            process(i, rec) for i, rec in enumerate(records)
        ])
        return results
