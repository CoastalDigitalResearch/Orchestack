"""Loop Runner configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    nats_url: str = "nats://localhost:4222"
    database_url: str = "postgresql://orchestack:orchestack-dev@localhost:5432/orchestack"
    minio_endpoint: str = "http://localhost:9000"
    otel_service_name: str = "loop-runner"
    max_iterations: int = 20
    max_tool_calls: int = 50
    default_wall_time_s: int = 3600

    model_config = {"env_prefix": "", "case_sensitive": False}
