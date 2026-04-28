"""
Centralised settings loaded from environment variables or .env file.
"""

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class Settings(BaseModel):
    """Immutable application settings."""

    ia_access_key: str = os.getenv("IA_ACCESS_KEY", "")
    ia_secret_key: str = os.getenv("IA_SECRET_KEY", "")
    api_secret_key: str = os.getenv("API_SECRET_KEY", "")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    def validate_ia_credentials(self) -> None:
        if not self.ia_access_key or not self.ia_secret_key:
            raise RuntimeError(
                "Internet Archive credentials not configured. "
                "Set IA_ACCESS_KEY and IA_SECRET_KEY in .env"
            )


settings = Settings()
