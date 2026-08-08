from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "video-3d"
    minio_secure: bool = False
    jwt_secret: str = "dev-secret-change-in-production"
    max_video_size_mb: int = 2048

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
