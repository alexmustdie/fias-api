from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    fias_base_url: str = "https://fias-public-service.nalog.ru/api/spas/v2.0"
    fias_master_token: str = ""
    fias_timeout: float = 30.0
    fias_max_retries: int = 3
    fias_rate_limit_per_second: int = 1  # ограничение запросов (100 запросов/мин от API ФИАС)

    default_address_type: int = 1
    batch_size: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()