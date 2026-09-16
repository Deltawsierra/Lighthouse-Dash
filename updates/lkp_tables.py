"""
api/v1/middleware/lkp_tables.py

Current-state lookup table registry.

Single source of truth for which tables the API may expose. Only `lkp_*`
tables are served. `hist_lkp_*` and `source_reference_map` are deliberately
excluded: history is written by the write endpoints but never listed or read
directly, and the crosswalk gets its own endpoints if it ever needs them.

Any route that takes a table name from the request MUST resolve it through
`require_lkp_table()` before building SQL. Identifiers cannot be bound as
parameters, so the allowlist -- not psycopg's quoting -- is what makes a
caller-supplied name safe to use as an identifier.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from api.v1.middleware.get_connection import get_connection_pool

logger = logging.getLogger(__name__)

LKP_PREFIX = "lkp_"
HIST_PREFIX = "hist_"

KEY_COLUMN = "lookup_hk"

# Columns every lookup table carries that are not business values.
AUDIT_COLUMNS = frozenset({
    "lookup_hk",
    "modified_by_user_id",
    "published_by_user_id",
    "record_effective_dttm",
    "code_set_nm",
})

_CACHE: dict[str, dict[str, "LkpTable"]] = {}
_CACHE_TS: dict[str, float] = {}
_CACHE_TTL = 3600  # seconds
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class LkpTable:
    """One current-state lookup table and its conventional columns."""

    table: str          # "lkp_geography"
    code_set: str       # "geography"
    code_col: str       # "geography_cd"
    name_col: str       # "geography_nm"
    desc_col: str       # "geography_desc"
    columns: tuple[str, ...]          # every column, in ordinal order
    column_types: dict[str, str]      # column name -> data_type

    @property
    def hist_table(self) -> str:
        return HIST_PREFIX + self.table

    @property
    def editable_columns(self) -> tuple[str, ...]:
        """Columns a steward may change.

        The code and code set are excluded on purpose: lookup_hk is derived
        from them, so changing either makes it a different concept. That is a
        retire-and-create, not an update.
        """
        return (self.name_col, self.desc_col)

    @property
    def tracked_columns(self) -> tuple[str, ...]:
        """Columns that feed record_values_hash, in hash order."""
        return (self.name_col, self.desc_col)

    def column_role(self, column: str) -> str:
        if column == KEY_COLUMN:
            return "key"
        if column == self.code_col:
            return "code"
        if column == self.name_col:
            return "name"
        if column == self.desc_col:
            return "description"
        if column in AUDIT_COLUMNS:
            return "audit"
        return "other"

    def describe_columns(self) -> list[dict]:
        """Column descriptor for API responses, so the frontend can render any
        lookup table generically instead of hardcoding column names."""
        return [
            {
                "name": c,
                "data_type": self.column_types.get(c),
                "role": self.column_role(c),
                "editable": c in self.editable_columns,
            }
            for c in self.columns
        ]


# ---------------------------------------------------------------------------
# Hashing -- must match ddl/load/*.sql exactly
# ---------------------------------------------------------------------------

def canonicalize(value) -> str:
    """UPPER(COALESCE(NULLIF(TRIM(CAST(col AS STRING)), ''), '__NULL__'))

    Two deliberate details:
      - strip(" ") not strip(): Postgres trim() removes spaces only, so
        stripping tabs or newlines here would diverge from the SQL.
      - Non-ASCII casing can differ between Python's full Unicode upper()
        and Postgres's locale-dependent upper(). Reference codes are ASCII
        today; this is where it would break if that changes.
    """
    if value is None:
        return "__NULL__"
    text = str(value).strip(" ")
    if text == "":
        return "__NULL__"
    return text.upper()


def sha256_hex(*parts) -> str:
    """SHA2(CONCAT_WS('|', <canonicalized parts>), 256) as lowercase hex."""
    joined = "|".join(canonicalize(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def format_dttm_for_hash(value: datetime) -> str:
    """Mirror to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US+00')."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f") + "+00"


def lookup_hk(code_set: str, code: str) -> str:
    return sha256_hex(code_set, code)


def historic_record_hk(lookup_key: str, effective: datetime) -> str:
    return sha256_hex(lookup_key, format_dttm_for_hash(effective))


def record_values_hash(*tracked_values) -> str:
    return sha256_hex(*tracked_values)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discover(schema: str) -> dict[str, LkpTable]:
    query = """
        SELECT c.table_name, c.column_name, c.data_type
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON  t.table_schema = c.table_schema
          AND t.table_name   = c.table_name
        WHERE c.table_schema = %s
          AND t.table_type = 'BASE TABLE'
        ORDER BY c.table_name, c.ordinal_position
    """

    try:
        pool = get_connection_pool()
    except ConnectionError as e:
        logger.error(f"Failed to get connection pool: {e}")
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again later.",
        )

    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (schema,))
            rows = cursor.fetchall()

    columns_by_table: dict[str, list[str]] = {}
    types_by_table: dict[str, dict[str, str]] = {}
    for table_name, column_name, data_type in rows:
        columns_by_table.setdefault(table_name, []).append(column_name)
        types_by_table.setdefault(table_name, {})[column_name] = data_type

    registry: dict[str, LkpTable] = {}
    for table_name, columns in columns_by_table.items():
        # Prefix match on "lkp_" excludes hist_lkp_* and source_reference_map.
        # Filtering in Python rather than with LIKE avoids the escaping trap
        # where an unescaped underscore matches any single character.
        if not table_name.startswith(LKP_PREFIX):
            continue

        area = table_name[len(LKP_PREFIX):]
        code_col = f"{area}_cd"
        name_col = f"{area}_nm"
        desc_col = f"{area}_desc"

        required = (code_col, name_col, desc_col, KEY_COLUMN, "code_set_nm")
        missing = [c for c in required if c not in columns]
        if missing:
            logger.warning(
                "Skipping %s.%s: does not follow the lookup pattern (missing %s)",
                schema, table_name, ", ".join(missing),
            )
            continue

        if HIST_PREFIX + table_name not in columns_by_table:
            logger.warning(
                "Skipping %s.%s: no matching history table %s%s",
                schema, table_name, HIST_PREFIX, table_name,
            )
            continue

        registry[table_name] = LkpTable(
            table=table_name,
            code_set=area,
            code_col=code_col,
            name_col=name_col,
            desc_col=desc_col,
            columns=tuple(columns),
            column_types=types_by_table[table_name],
        )

    logger.info(
        "Lookup registry for schema %s: %s",
        schema, ", ".join(sorted(registry)) or "(none)",
    )
    return registry


def get_lkp_tables(schema: str, *, force_refresh: bool = False) -> dict[str, LkpTable]:
    """Registry for a schema, cached with a TTL.

    Keyed by schema so a multi-schema deployment can never serve one schema's
    table list for another.
    """
    now = time.time()

    if not force_refresh:
        cached = _CACHE.get(schema)
        if cached is not None and (now - _CACHE_TS.get(schema, 0.0)) < _CACHE_TTL:
            return cached

    with _CACHE_LOCK:
        cached = _CACHE.get(schema)
        if (not force_refresh and cached is not None
                and (now - _CACHE_TS.get(schema, 0.0)) < _CACHE_TTL):
            return cached

        registry = _discover(schema)
        _CACHE[schema] = registry
        _CACHE_TS[schema] = time.time()
        return registry


def require_lkp_table(table_name: str, schema: str) -> LkpTable:
    """Resolve a caller-supplied table name, or 404.

    404 rather than 403 on purpose: a 403 would confirm that
    hist_lkp_geography exists, which is information a caller has no business
    getting from a table they are not permitted to address at all.
    """
    table = get_lkp_tables(schema).get(table_name)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return table


def warm_cache(schema: str) -> None:
    """Build the registry at startup so the first request does not pay for it.

    Never raises: a cold start with no database should still come up and let
    the health endpoint report the problem.
    """
    try:
        get_lkp_tables(schema, force_refresh=True)
    except Exception as e:  # noqa: BLE001 - startup must not crash here
        logger.warning("Could not warm lookup registry for %s: %s", schema, e)
