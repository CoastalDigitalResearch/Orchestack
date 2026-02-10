"""Budget Accounting configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    nats_url: str = "nats://localhost:4222"
    database_url: str = "postgresql://orchestack:orchestack-dev@localhost:5432/orchestack"
    otel_service_name: str = "budget-accounting"

    model_config = {"env_prefix": "", "case_sensitive": False}
