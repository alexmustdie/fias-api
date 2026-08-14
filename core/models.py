from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AddressRequest:
    """Запрос на нормализацию"""
    id: str
    search_string: str
    address_type: int = 1


@dataclass(frozen=True)
class NormalizedAddress:
    """Результат нормализации"""
    id: str
    search_string: str
    full_address: Optional[str] = None   # postal_code + full_name
    region_code: Optional[int] = None
    postal_code: Optional[str] = None
    is_active: bool = True
    error: Optional[str] = None
    status: str = "OK"

    @classmethod
    def with_error(cls, id: str, search_string: str, error: str,
                   status: str = "Ошибка") -> "NormalizedAddress":
        return cls(id=id, search_string=search_string, error=error, status=status)
