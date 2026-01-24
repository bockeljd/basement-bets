import os
from typing import Optional
from dotenv import load_dotenv

# Load env vars from .env and .env.local
load_dotenv()
load_dotenv('.env.local')

class Config:
    def __init__(self):
        self.APP_ENV = os.environ.get("APP_ENV", "local").lower()
        
        # 1. Database URL Resolution (Pooled/Runtime)
        # Priority: DATABASE_URL (Neon/Override) -> POSTGRES_URL -> POSTGRES_PRISMA_URL -> POSTGRES_URL_NON_POOLING
        self.DATABASE_URL = (
            os.environ.get("DATABASE_URL") or 
            os.environ.get("POSTGRES_URL") or 
            os.environ.get("POSTGRES_PRISMA_URL") or 
            os.environ.get("POSTGRES_URL_NON_POOLING")
        )
        
        # 2. Database URL Resolution (Unpooled/Migration)
        # Priority: DATABASE_URL_UNPOOLED (Neon) -> POSTGRES_URL_NON_POOLING -> POSTGRES_URL_UNPOOLED (Backup)
        self.DATABASE_URL_UNPOOLED = (
            os.environ.get("DATABASE_URL_UNPOOLED") or 
            os.environ.get("POSTGRES_URL_NON_POOLING") or
            os.environ.get("POSTGRES_URL_UNPOOLED")
        )

        self.REQUIRE_DATABASE = os.environ.get("REQUIRE_DATABASE", "1") != "0"
        
        self.SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        self.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
        self.BASEMENT_PASSWORD = os.environ.get("BASEMENT_PASSWORD")
        self.CRON_SECRET = os.environ.get("CRON_SECRET")
        
        # Validation
        self._validate()
        self._apply_guards()

    def _validate(self):
        """Ensure critical variables are present based on environment."""
        if self.APP_ENV not in ["local", "preview", "prod"]:
            print(f"[WARNING] Invalid APP_ENV: {self.APP_ENV}. Defaulting to 'local'.")
            self.APP_ENV = "local"

        missing = []
        
        # Fail Fast for Missing DB
        if self.REQUIRE_DATABASE and not self.DATABASE_URL:
            # If strictly required, raise Error (RuntimeError preferred over simple print for fail-fast)
            # But adhering to the current pattern of collecting missing keys first:
            missing.append("DATABASE_URL (or POSTGRES_URL/POSTGRES_PRISMA_URL)")
        
        # In Prod/Preview, we should be noisier about missing keys
        if self.APP_ENV != "local":
            if not self.SUPABASE_SERVICE_ROLE_KEY:
                missing.append("SUPABASE_SERVICE_ROLE_KEY")
            if not self.OPENAI_API_KEY:
                missing.append("OPENAI_API_KEY")

        if missing:
            msg = f"[CRITICAL] Missing required environment variables: {', '.join(missing)}"
            print(msg)
            # If critical DB is missing and required, crash.
            if self.REQUIRE_DATABASE and ("DATABASE_URL" in msg or "POSTGRES_URL" in msg):
                 raise RuntimeError(msg)

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
