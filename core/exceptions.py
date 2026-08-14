class NormalizationError(Exception):
    """Базовое исключение нормализации"""


class ServiceUnavailableError(NormalizationError):
    """Сервис недоступен"""


class InvalidResponseError(NormalizationError):
    """Некорректный ответ от сервиса"""


class RateLimitError(NormalizationError):
    """Превышен лимит запросов"""
