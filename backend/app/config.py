from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"
    upload_dir: str = "./data/uploads"
    max_video_size_mb: int = 2048

    model_config = {"env_file": ".env", "extra": "ignore"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        os.makedirs(self.upload_dir, exist_ok=True)


settings = Settings()
