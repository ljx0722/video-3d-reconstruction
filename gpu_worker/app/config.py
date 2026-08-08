import os


class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "video-3d")
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    model_path: str = os.getenv("MODEL_PATH", "/models/checkpoint.pt")


settings = Settings()
