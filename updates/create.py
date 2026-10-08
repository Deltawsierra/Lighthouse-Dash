"""
api/v1/routes/create.py

Create one record in a current-state lookup table.

Rewritten for the lkp_ / hist_lkp_ data model. The previous version inserted
`_current_`, `_status_` and `_action_` columns that no longer exist and never
computed lookup_hk, so it could not succeed against the current tables.

One create performs two writes in a single transaction:
  1. insert the current row into lkp_<area>
  2. insert the opening history version into hist_lkp_<area>

lookup_hk is derived from (code_set_nm, <area>_cd), so it is computed here
rather than supplied by the caller. That also means a code is an identity,
not an editable value: changing it later is a retire-and-create, not an
update.
"""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Body, HTTPException, Request, Response
from psycopg import errors as pg_errors
from psycopg import sql

from api.v1.middleware import (
    get_connection_pool,
    get_schema,
    get_settings,
    require_permission_or_403,
)
from api.v1.controllers import (
    historic_record_hk,
    lookup_hk,
    record_values_hash,
    require_lkp_table,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Mirror the column widths in ddl/reference.sql so an oversized value comes
# back as a 400 instead of a 500 from the database.
MAX_CODE_LEN = 50
MAX_DECODE_LEN = 255
MAX_CODE_SET_LEN = 100


@router.post("/tables/{table_name}", status_code=201)
def create_record(
    request: Request,
    response: Response,
    table_name: str,
    body: dict = Body(
        ...,
        description="{'values': {'<area>_cd': ..., '<area>_nm': ..., '<area>_desc': ...}}",
    ),
):
    """
    Insert a single record into a current-state lookup table.

    Path params:
        table_name: a lkp_* table in the configured schema.

    Body:
        {
          "values": {
            "<area>_cd":   "US-CA",          # required
            "<area>_nm":   "California",     # required
            "<area>_desc": "US state",       # optional
            "code_set_nm": "geography"       # optional, defaults to the area
          }
        }

    Permissions:
        Requires `table:insert` on `{SCHEMA}.{table_name}`.

    Returns:
        201 with { "status", "message", "data", "record_values_hash",
                   "record_effective_dttm" }

    Raises HTTPException:
        400 - missing/invalid `values`, blank code or decode, or a field that
              is not settable on create.
        403 - caller lacks `table:insert` on this table.
        404 - unknown table.
        409 - that code already exists in this code set.
        503 - connection pool unavailable.
        500 - unexpected database error.
    """

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
        "table:insert",
    )

    # Identity comes from the validated token via AuthMiddleware, never from
    # the request body. A caller must not be able to forge the audit trail.
    actor = user.get("username") or user.get("id")
    if not actor:
        raise HTTPException(status_code=401, detail="No authenticated user on request.")

    # ---- validate body -----------------------------------------------------

    if not body or "values" not in body:
        raise HTTPException(status_code=400, detail="Request body must contain 'values' field.")

    values_dict = body["values"]
    if not isinstance(values_dict, dict) or not values_dict:
        raise HTTPException(status_code=400, detail="'values' must be a non-empty object.")

    settable = {lkp.primary_code, lkp.primary_decode, lkp.primary_desc, "code_set_nm"}
    unknown = values_dict.keys() - settable
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Not settable on create: {', '.join(sorted(unknown))}. "
                f"Settable fields are: {', '.join(sorted(settable))}. "
                "lookup_hk and the audit columns are derived server-side."
            ),
        )

    def _clean(key: str):
        raw = values_dict.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    code = _clean(lkp.primary_code)
    decode = _clean(lkp.primary_decode)
    desc = _clean(lkp.primary_desc)
    code_set = _clean("code_set_nm") or lkp.code_set

    # Blank is rejected rather than coerced: canonicalize() turns an empty
    # string into the __NULL__ sentinel, so a blank code would produce a
    # hash key for a record that has no business key.
    if not code:
        raise HTTPException(
            status_code=400, detail=f"'{lkp.primary_code}' is required and cannot be blank."
        )
    if not decode:
        raise HTTPException(
            status_code=400, detail=f"'{lkp.primary_decode}' is required and cannot be blank."
        )

    for value, limit, field in (
        (code, MAX_CODE_LEN, lkp.primary_code),
        (decode, MAX_DECODE_LEN, lkp.primary_decode),
        (code_set, MAX_CODE_SET_LEN, "code_set_nm"),
    ):
        if len(value) > limit:
            raise HTTPException(
                status_code=400,
                detail=f"'{field}' exceeds the maximum length of {limit} characters.",
            )

    # ---- derive keys -------------------------------------------------------

    effective_dttm = datetime.now(timezone.utc)
    row_key = lookup_hk(code_set, code)
    values_hash = record_values_hash(decode, desc)

    try:
        pool = get_connection_pool()
    except ConnectionError as e:
        logger.error(f"Failed to get connection pool: {e}")
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again later.",
        )

    try:
        # One connection, one transaction. psycopg3 commits on clean exit and
        # rolls back on exception, so both writes land together or not at all.
        with pool.connection() as conn:
            with conn.cursor() as cursor:

                # ---- 1. insert the current row ------------------------------
                insert_current = sql.SQL("""
                    INSERT INTO {schema}.{table} (
                        lookup_hk,
                        modified_by_user_id,
                        published_by_user_id,
                        record_effective_dttm,
                        code_set_nm,
                        {code_col},
                        {decode_col},
                        {desc_col}
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {cols}
                """).format(
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(lkp.name),
                    code_col=sql.Identifier(lkp.primary_code),
                    decode_col=sql.Identifier(lkp.primary_decode),
                    desc_col=sql.Identifier(lkp.primary_desc),
                    cols=sql.SQL(", ").join(sql.Identifier(c) for c in lkp.columns),
                )

                try:
                    cursor.execute(
                        insert_current,
                        (
                            row_key,
                            actor,
                            actor,
                            effective_dttm,
                            code_set,
                            code,
                            decode,
                            desc,
                        ),
                    )
                except pg_errors.UniqueViolation:
                    # Covers all three guards: the lookup_hk primary key, the
                    # (code_set_nm, code) constraint, and the case-insensitive
                    # expression index.
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"'{code}' already exists in code set '{code_set}'. "
                            "Edit the existing record instead."
                        ),
                    )

                created_row = cursor.fetchone()
                if created_row is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Insert succeeded but no row was returned.",
                    )
                created = dict(zip(lkp.columns, created_row))

                # ---- 2. close any stale open history ------------------------
                # Normally a no-op. It matters when a code was soft-deleted
                # and is now being recreated: without this the lookup would
                # end up with two open history versions.
                close_open = sql.SQL("""
                    UPDATE {schema}.{hist}
                    SET record_end_dttm = %s,
                        active_flg = false
                    WHERE lookup_hk = %s
                      AND record_end_dttm IS NULL
                """).format(
                    schema=sql.Identifier(schema_name),
                    hist=sql.Identifier(lkp.hist_table),
                )
                cursor.execute(close_open, (effective_dttm, row_key))
                if cursor.rowcount:
                    logger.info(
                        "Closed %s stale open history version(s) for lookup_hk=%s "
                        "in %s.%s before recreating.",
                        cursor.rowcount, row_key, schema_name, lkp.hist_table,
                    )

                # ---- 3. insert the opening history version ------------------
                hist_columns = [
                    "historic_record_hk",
                    "lookup_hk",
                    "record_values_hash",
                    "modified_by_user_id",
                    "published_by_user_id",
                    "record_effective_dttm",
                    "record_end_dttm",
                    "deleted_flg",
                    "active_flg",
                    "code_set_nm",
                    lkp.primary_code,
                    lkp.primary_decode,
                    lkp.primary_desc,
                ]
                hist_values = [
                    historic_record_hk(row_key, effective_dttm),
                    row_key,
                    values_hash,
                    actor,
                    actor,
                    effective_dttm,
                    None,       # open-ended
                    False,      # deleted_flg
                    True,       # active_flg
                    code_set,
                    code,
                    decode,
                    desc,
                ]

                insert_hist = sql.SQL("""
                    INSERT INTO {schema}.{hist} ({cols})
                    VALUES ({vals})
                """).format(
                    schema=sql.Identifier(schema_name),
                    hist=sql.Identifier(lkp.hist_table),
                    cols=sql.SQL(", ").join(sql.Identifier(c) for c in hist_columns),
                    vals=sql.SQL(", ").join(sql.Placeholder() for _ in hist_values),
                )
                cursor.execute(insert_hist, hist_values)

        return {
            "status": "success",
            "message": "Record created successfully.",
            "data": created,
            "record_values_hash": values_hash,
            "record_effective_dttm": effective_dttm.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Create failed for %s.%s code=%s", schema_name, table_name, code
        )
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
