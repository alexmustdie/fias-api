import asyncio
import logging
import re
from typing import Optional, Dict, Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config import settings
from core.models import AddressRequest, NormalizedAddress
from core.exceptions import ServiceUnavailableError, InvalidResponseError, RateLimitError
from clients.base import NormalizerClient

logger = logging.getLogger(__name__)

STATUS_OK = "OK"
STATUS_REQUIRES_ATTENTION = "Требует внимания"
STATUS_MULTIPLE_RESULTS = "Требует проверки"
STATUS_NOT_FOUND = "Адрес не найден"


class FiasClient(NormalizerClient):

    def __init__(
        self,
        base_url: Optional[str] = None,
        master_token: Optional[str] = None,
        timeout: Optional[float] = None,
        rate_limit: Optional[int] = None,
    ):
        self.base_url = base_url or settings.fias_base_url
        self.master_token = master_token or settings.fias_master_token
        self.timeout = timeout or settings.fias_timeout
        self.rate_limit = rate_limit or settings.fias_rate_limit_per_second

        if not self.master_token:
            raise ValueError("FIAS master_token не задан")

        # self._client = httpx.AsyncClient(timeout=self.timeout)
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            verify=False,
        )
        self._rate_lock = asyncio.Lock()
        self._min_interval = 1.0 / self.rate_limit
        self._last_request_time = 0.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _wait_rate_limit(self) -> None:
        async with self._rate_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    async def _make_request(self, endpoint: str, request: AddressRequest) -> Dict[str, Any]:
        """Низкоуровневый запрос к API"""
        await self._wait_rate_limit()

        try:
            response = await self._client.get(
                f"{self.base_url}/{endpoint}",
                params={
                    "search_string": request.search_string,
                    "address_type": request.address_type,
                },
                headers={
                    "accept": "application/json",
                    "master-token": self.master_token,
                },
            )
        except httpx.RequestError as e:
            logger.warning("Сетевая ошибка для id=%s endpoint=%s: %s",
                           request.id, endpoint, e)
            raise ServiceUnavailableError(f"Сетевая ошибка: {e}") from e

        if response.status_code == 429:
            raise RateLimitError("Превышен лимит запросов")

        if response.status_code >= 500:
            raise ServiceUnavailableError(f"Сервер вернул {response.status_code}")

        if response.status_code != 200:
            raise ServiceUnavailableError(
                f"HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            return response.json()
        except Exception as e:
            raise ServiceUnavailableError(f"Не удалось распарсить JSON: {e}") from e

    @retry(
        stop=stop_after_attempt(settings.fias_max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(ServiceUnavailableError),
        reraise=True,
    )

    async def normalize(self, request: AddressRequest) -> NormalizedAddress:
        # Шаг 1: основной запрос
        try:
            data = await self._make_request("SearchAddressItem", request)
        except ServiceUnavailableError as e:
            return NormalizedAddress.with_error(
                request.id, request.search_string, str(e)
            )

        # Шаг 2: если основной запрос вернул данные — используем их
        if self._has_address_data(data):
            return self._parse_response(request, data, status=STATUS_OK)

        # Шаг 3: ответ пустой {} — делаем дополнительный запрос
        logger.info(
            "Основной запрос вернул пустой ответ для id=%s, "
            "выполняю дополнительный запрос SearchAddressItems",
            request.id,
        )

        try:
            fallback_data = await self._make_request("SearchAddressItems", request)
        except ServiceUnavailableError as e:
            return NormalizedAddress.with_error(
                request.id, request.search_string,
                f"Ошибка fallback-запроса: {e}",
            )

        addresses = fallback_data.get("addresses") or []

        # Шаг 4: анализируем результат дополнительного запроса
        if not addresses:
            logger.warning("Адрес не найден даже в fallback для id=%s", request.id)
            return NormalizedAddress.with_error(
                request.id, request.search_string,
                STATUS_NOT_FOUND, status=STATUS_NOT_FOUND,
            )

        result_count = len(addresses)
        
        # выбираем лучший адрес
        selected_address, found_house = self._select_best_address(addresses)
        
        if found_house:
            logger.info(
                "Fallback для id=%s: выбран адрес с 'домом' из %d вариантов",
                request.id, result_count,
            )
        elif result_count > 1:
            logger.info(
                "Fallback для id=%s: ни один из %d адресов не содержит 'дом', "
                "берём первый",
                request.id, result_count,
            )

        # Определяем статус
        if result_count == 1:
            status = STATUS_REQUIRES_ATTENTION
            logger.info(
                "Fallback вернул 1 адрес для id=%s — требует внимания",
                request.id,
            )
        else:
            status = STATUS_MULTIPLE_RESULTS
            logger.info(
                "Fallback вернул %d адресов для id=%s — множественный результат",
                result_count, request.id,
            )

        return self._parse_response(request, selected_address, status=status)

    @staticmethod
    def _has_address_data(data: Dict[str, Any]) -> bool:
        """Проверка, что в ответе есть полезные данные"""
        if not data:  # пустой dict {}
            return False
        if not data.get("full_name"):
            return False
        if "object_id" not in data:
            return False
        return True

    @staticmethod
    def _select_best_address(addresses: list) -> tuple[Dict[str, Any], bool]:
        """
        Выбирает лучший адрес из списка
        
        Приоритет: адрес со словом "дом" или сокращением "д.".
        
        Returns:
            (выбранный_адрес, был_ли_найден_с_домом)
        """
        
        house_pattern = re.compile(r'\bдом\b|\bд\.|домовладение\b', re.IGNORECASE)
        
        for address in addresses:
            full_name = address.get("full_name", "")
            if house_pattern.search(full_name):
                return address, True
        
        # Если адресов с "домом" нет — возвращаем первый
        return addresses[0], False

    def _parse_response(
        self,
        request: AddressRequest,
        data: Dict[str, Any],
        status: str = STATUS_OK,
    ) -> NormalizedAddress:
        try:
            full_name = data.get("full_name", "")
            details = data.get("address_details", {}) or {}
            postal_code = details.get("postal_code")
            if not postal_code:
                status = STATUS_REQUIRES_ATTENTION

            if postal_code and full_name:
                full_address = f"{postal_code}, {full_name}"
            else:
                full_address = full_name or None

            return NormalizedAddress(
                id=request.id,
                search_string=request.search_string,
                full_address=full_address,
                region_code=data.get("region_code"),
                postal_code=postal_code,
                is_active=data.get("is_active", True),
                status=status,
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.error("Ошибка парсинга для id=%s: %s", request.id, e)
            return NormalizedAddress.with_error(
                request.id, request.search_string, f"Ошибка парсинга: {e}",
            )

    async def close(self) -> None:
        await self._client.aclose()
