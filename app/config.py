from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Environment variables use the field name in upper case."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///./arogyadesk.db"
    jwt_secret: str = "dev-only-change-me-before-any-shared-deployment"
    jwt_ttl_minutes: int = 120
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    kafka_enabled: bool = False
    kafka_bootstrap: str = "localhost:9092"
    kafka_topic: str = "arogyadesk.appointments"
    cancel_cutoff_hours: int = 2
    cache_ttl_seconds: int = 60
    seed: bool = False
    password_iterations: int = 120_000

    def validate_runtime(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")
        if self.environment == "production" and "change-me" in self.jwt_secret:
            raise RuntimeError("Refusing to start in production with the sample JWT secret")
