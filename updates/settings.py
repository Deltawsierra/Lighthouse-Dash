from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # -> api/.env


class Settings(BaseSettings):
    # Required settings
    DATABRICKS_HOST: str = Field(min_length=1)
    DATABASE: str = Field(min_length=1)
    SCHEMA: str = Field(min_length=1)
    AZURE_TENANT_ID: str = Field(min_length=1)
    AZURE_CLIENT_ID: str = Field(min_length=1)
    ENDPOINT_NAME: str = Field(min_length=1)
    PGPORT: str = "5432"

    # Optional
    DATABRICKS_CLIENT_ID: Optional[str] = None
    DATABRICKS_CLIENT_SECRET: Optional[str] = None
    DATABRICKS_TOKEN: Optional[str] = None
    VERSION: str = "DEV"
    PGHOST: Optional[str] = None
    PGUSER: Optional[str] = None

    # --- Reference-data model conventions ---------------------------------
    # Structural facts about the lkp_ / hist_lkp_ pattern, centralized here
    # per review (previously module constants in lkp_tables.py). Together
    # these define what the API will accept as a valid lookup table and how
    # each column is classified.
    #
    # These are deliberately NOT deployment config. KEY_COLUMN and the three
    # suffixes also determine which columns feed record_values_hash, so
    # overriding them per environment would make the Python hashes diverge
    # from ddl/load/load_hist_lkp_*.sql. Change them only alongside the DDL.
    LKP_PREFIX: str = "lkp_"
    HIST_PREFIX: str = "hist_"

    KEY_COLUMN: str = "lookup_hk"

    CODE_SUFFIX: str = "_cd"
    DECODE_SUFFIX: str = "_nm"
    DESC_SUFFIX: str = "_desc"

    # Columns present on every lookup table that are bookkeeping rather than
    # business values. LkpTable.column_role() checks KEY_COLUMN before this
    # set, so "lookup_hk" here is never reached today; it is kept so the
    # classification stays correct if KEY_COLUMN is ever renamed.
    AUDIT_COLUMNS: frozenset[str] = frozenset({
        "lookup_hk",
        "modified_by_user_id",
        "published_by_user_id",
        "record_effective_dttm",
        "code_set_nm",
    })

    # Tell Pydantic Settings to read from .env too
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    # Cached: constructed once per process, then reused
    return Settings()
