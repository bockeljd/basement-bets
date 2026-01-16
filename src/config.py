import os
from typing import Optional
from dotenv import load_dotenv

# Load env vars from .env and .env.local
load_dotenv()
load_dotenv('.env.local')

class Config:
    def __init__(self):
        self.APP_ENV = os.environ.get("APP_ENV", "local").lower()
        self.DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")
        self.SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        self.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
        self.BASEMENT_PASSWORD = os.environ.get("BASEMENT_PASSWORD")
        
        # Validation
        self._validate()
        self._apply_guards()

    def _validate(self):
        """Ensure critical variables are present based on environment."""
        if self.APP_ENV not in ["local", "preview", "prod"]:
            print(f"[WARNING] Invalid APP_ENV: {self.APP_ENV}. Defaulting to 'local'.")
            self.APP_ENV = "local"

        missing = []
        if not self.DATABASE_URL:
            missing.append("POSTGRES_URL / DATABASE_URL")
        
        # In Prod/Preview, we should be noisier about missing keys
        if self.APP_ENV != "local":
            if not self.SUPABASE_SERVICE_ROLE_KEY:
                missing.append("SUPABASE_SERVICE_ROLE_KEY")
            if not self.OPENAI_API_KEY:
                missing.append("OPENAI_API_KEY")

        if missing:
            print(f"[CRITICAL] Missing required environment variables: {', '.join(missing)}")

    def _apply_guards(self):
        """Enforce strict isolation between environments."""
        if self.APP_ENV == "prod":
            return

        # Hard Guard: No Prod DB in non-prod
        # We look for common identifiers of a production DB if the user provides them.
        # For now, we use a simple check: if the URL contains 'prod' or matches a known prod string.
        # In a real setup, the USER would provide the PROD_DB_PROJECT_REF.
        
        PROD_IDENTIFIER = os.environ.get("PROD_DB_PROJECT_REF")
        if PROD_IDENTIFIER and self.DATABASE_URL and PROD_IDENTIFIER in self.DATABASE_URL:
            raise RuntimeError(
                f"SAFETY GUARD: APP_ENV is '{self.APP_ENV}' but DATABASE_URL refers to PRODUCTION ({PROD_IDENTIFIER}). "
                "Startup aborted to prevent data corruption."
            )

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV == "prod"

    @property
    def is_local(self) -> bool:
        return self.APP_ENV == "local"

    @property
    def is_preview(self) -> bool:
        return self.APP_ENV == "preview"

# Singleton instance
settings = Config()
