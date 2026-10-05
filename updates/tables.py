from fastapi import Request, HTTPException, Query, Response
from api.v1.middleware import (
    get_connection_pool,
    get_schema,
    get_settings,
    require_permission_or_403,
)
from api.v1.middleware.lkp_tables import get_lkp_tables, require_lkp_table
from fastapi import APIRouter
from psycopg import sql
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# NOTE ON SCOPE
# Only current-state lookup tables are exposed here. History tables and
# source_reference_map are excluded on purpose. The registry in
# api/v1/middleware/lkp_tables.py owns that decision and its cache, so the
# list endpoint and the detail endpoints can never disagree about which
# tables exist. Naming conventions come from Settings.


@router.get("/tables/list")
async def get_all_tables(request: Request, response: Response):
    """Lists the current-state lookup tables available in the schema."""

    settings = get_settings()
    scope = f"{settings.SCHEMA}"
    user = getattr(request.state, "user", None) or {}
    permissions = user.get("permissions", {}) or {}

    require_permission_or_403(
        permissions,
        "schema",
        scope,
        "table:list",
    )

    schema_path = get_schema()

    # Caching, the TTL, and the stampede lock all live in the registry now.
    registry = get_lkp_tables(schema_path)

    table_names = sorted(registry)

    return {
        "count": len(table_names),
        "tables": table_names,
        # Richer view for clients that want to build navigation without a
        # follow-up call per table. `tables` is kept as-is for compatibility.
        "datasets": [
            {
                "table": registry[n].name,
                "code_set": registry[n].code_set,
                "key_column": registry[n].key_column,
            }
            for n in table_names
        ],
    }


@router.get("/tables/{table_name}")
def get_table(
    request: Request,
    response: Response,
    table_name: str,
    limit: int = Query(1000, ge=1, le=1000, description="Max rows to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
):
    """Pulls rows from a current-state lookup table."""

    schema_name = get_schema()

    # Allowlist first: an unknown or non-lookup table is a 404 before
    # permissions are consulted, so the response cannot be used to probe
    # which tables exist.
    lkp = require_lkp_table(table_name, schema_name)

    settings = get_settings()
    scope = f"{settings.SCHEMA}.{table_name}"
    user = getattr(request.state, "user", None) or {}
    permissions = user.get("permissions", {}) or {}

    require_permission_or_403(
        permissions,
        "table",
        scope,
        "table:read",
    )

    try:
        pool = get_connection_pool()
    except ConnectionError as e:
        logger.error(f"Failed to get connection pool: {e}")
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again later.",
        )

    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                # Explicit column list rather than SELECT *, so response
                # column order is stable and comes from the registry.
                # ORDER BY is required: LIMIT/OFFSET without one gives no
                # guaranteed row order, so paging can repeat or skip rows.
                query = sql.SQL("""
                    SELECT {cols}
                    FROM {schema}.{table}
                    ORDER BY {primary_code}
                    LIMIT %s OFFSET %s
                """).format(
                    cols=sql.SQL(", ").join(
                        sql.Identifier(c) for c in lkp.columns
                    ),
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(lkp.name),
                    primary_code=sql.Identifier(lkp.primary_code),
                )

                cursor.execute(query, (limit, offset))
                rows = cursor.fetchall()

                results = [dict(zip(lkp.columns, r)) for r in rows]

                return {
                    "limit": limit,
                    "offset": offset,
                    "row_count": len(results),
                    "data": results,
                    # Lets the frontend render and edit any lookup table
                    # without hardcoding per-area column names.
                    "code_set": lkp.code_set,
                    "key_column": lkp.key_column,
                    "columns": lkp.describe_columns(),
                }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Read failed for %s.%s", schema_name, table_name)
        raise HTTPException(status_code=500, detail=f"Postgres query failed: {e}")


@router.get("/tables/{table_name}/info")
def get_table_metadata(
    request: Request,
    response: Response,
    table_name: str,
):
    """
    Returns table metadata only:
      - columns (name, data type, role, editable)
      - total row count
    No actual table rows are returned.
    """

    schema_name = get_schema()  # postgres schema name only

    lkp = require_lkp_table(table_name, schema_name)

    table_path = f"{schema_name}.{table_name}"

    settings = get_settings()
    scope = f"{settings.SCHEMA}.{table_name}"
    user = getattr(request.state, "user", None) or {}
    permissions = user.get("permissions", {}) or {}

    require_permission_or_403(
        permissions,
        "table",
        scope,
        "table:read",
    )

    try:
        pool = get_connection_pool()
    except ConnectionError as e:
        logger.error(f"Failed to get connection pool: {e}")
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again later.",
        )

    try:
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                # Column metadata comes from the registry, which already
                # read information_schema. Only the row count needs a query.
                columns = lkp.describe_columns()

                rowcount_query = sql.SQL("""
                    SELECT COUNT(*) AS total_rows
                    FROM {schema}.{table}
                """).format(
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(lkp.name),
                )

                cursor.execute(rowcount_query)
                count_row = cursor.fetchone()
                total_rows = count_row[0] if count_row else 0

                return {
                    "table": table_path,
                    "code_set": lkp.code_set,
                    "key_column": lkp.key_column,
                    "total_rows": total_rows,
                    "column_count": len(columns),
                    "columns": columns,
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Metadata query failed for %s", table_path)
        raise HTTPException(
            status_code=500, detail=f"Postgres metadata query failed: {e}"
        )
