"""
api/v1/routes/update.py

Update one record in a current-state lookup table.

Rewritten for the lkp_ / hist_lkp_ data model. The previous version did SCD2
inside a single table (close the row, insert a successor beside it) and
assumed a database-generated surrogate key. This model splits those concerns:
lkp_<area> holds current state and is updated in place (SCD1), hist_lkp_<area>
is append-only history (SCD2).

One edit therefore performs three writes in a single transaction:
  1. close the open history version   (set record_end_dttm, clear active_flg)
  2. insert the new history version   (open-ended)
  3. update the current row in place

lookup_hk never changes. It is derived from (code_set_nm, <area>_cd), so
changing either of those makes it a different concept -- that is a
retire-and-create, not an update, and this endpoint rejects it.
"""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Body, HTTPException, Request, Response
from psycopg import sql

from api.v1.middleware import (
    get_connection_pool,
    get_schema,
    get_settings,
    require_permission_or_403,
)
from api.v1.controllers import (
    historic_record_hk,
    record_values_hash,
    require_lkp_table,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_DECODE_LEN = 255


@router.put("/tables/{table_name}/{row_key}")
def update_record(
    request: Request,
    response: Response,
    table_name: str,
    row_key: str,
    body: dict = Body(
        ...,
        description="{'values': {...}, 'expected_values_hash': '<optional>'}",
    ),
):
    """
    Update one row in a current-state lookup table.

    Path params:
        table_name: a lkp_* table in the configured schema.
        row_key:    the row's lookup_hk.

    Body:
        {
          "values": { "<area>_nm": "...", "<area>_desc": "..." },
          "expected_values_hash": "<optional, for optimistic concurrency>"
        }

    Only the decode and description are editable. The code and code set are
    part of the record's identity.

    If `expected_values_hash` is supplied and no longer matches, the request is
    rejected with 409 rather than silently overwriting someone else's edit.
    Submitting unchanged values is a no-op and creates no new version.

    Permissions:
        Requires `table:update` on `{SCHEMA}.{table_name}`.

    Returns:
        { "status": "success" | "unchanged", "data": <current row>,
          "record_values_hash": ..., "record_effective_dttm": ... }

    Raises HTTPException:
        400 - missing/invalid `values`, or an attempt to change identity columns.
        403 - caller lacks `table:update` on this table.
        404 - unknown table, or no row with that lookup_hk.
        409 - the row changed since the caller read it.
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
        "table:update",
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

    identity_columns = {"lookup_hk", "code_set_nm", lkp.primary_code}
    attempted_identity = identity_columns & values_dict.keys()
    if attempted_identity:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change identity columns: {', '.join(sorted(attempted_identity))}. "
                "The lookup key is derived from the code set and code, so changing "
                "either is a retire-and-create, not an update."
            ),
        )

    unknown = values_dict.keys() - set(lkp.editable_columns)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Not editable: {', '.join(sorted(unknown))}. "
                f"Editable columns are: {', '.join(lkp.editable_columns)}."
            ),
        )

    # Empty string is a user clearing a field, which is NULL in the database.
    cleaned = {}
    for key, raw in values_dict.items():
        if raw is None:
            cleaned[key] = None
            continue
        text = str(raw).strip()
        cleaned[key] = text or None
    values_dict = cleaned

    # The decode is NOT NULL in the DDL, so clearing it would fail at the
    # database with an unhelpful 500.
    if lkp.primary_decode in values_dict and values_dict[lkp.primary_decode] is None:
        raise HTTPException(
            status_code=400, detail=f"'{lkp.primary_decode}' cannot be blank."
        )

    decode_value = values_dict.get(lkp.primary_decode)
    if decode_value is not None and len(decode_value) > MAX_DECODE_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"'{lkp.primary_decode}' exceeds the maximum length of {MAX_DECODE_LEN} characters.",
        )

    expected_hash = body.get("expected_values_hash")

    try:
        pool = get_connection_pool()
    except ConnectionError as e:
        logger.error(f"Failed to get connection pool: {e}")
        raise HTTPException(
            status_code=503,
            detail="Database connection unavailable. Please try again later.",
        )

    effective_dttm = datetime.now(timezone.utc)

    try:
        # One connection, one transaction. psycopg3 commits on clean exit and
        # rolls back on exception, so all three writes land together or not at all.
        with pool.connection() as conn:
            with conn.cursor() as cursor:

                # ---- 1. read and lock the current row -----------------------
                select_query = sql.SQL("""
                    SELECT {cols}
                    FROM {schema}.{table}
                    WHERE lookup_hk = %s
                    FOR UPDATE
                """).format(
                    cols=sql.SQL(", ").join(sql.Identifier(c) for c in lkp.columns),
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(lkp.name),
                )
                cursor.execute(select_query, (row_key,))
                current_row = cursor.fetchone()

                if current_row is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No row found with lookup_hk = '{row_key}'.",
                    )

                current = dict(zip(lkp.columns, current_row))

                current_hash = record_values_hash(
                    *(current.get(c) for c in lkp.tracked_columns)
                )

                if expected_hash and expected_hash != current_hash:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "This record changed since you loaded it. "
                            "Reload and reapply your edit."
                        ),
                    )

                # ---- 2. decide whether anything actually changed ------------
                merged = dict(current)
                merged.update(values_dict)

                new_hash = record_values_hash(
                    *(merged.get(c) for c in lkp.tracked_columns)
                )

                if new_hash == current_hash:
                    # Submitting unchanged values must not create a version.
                    return {
                        "status": "unchanged",
                        "message": "No tracked values changed; no new version created.",
                        "data": current,
                        "record_values_hash": current_hash,
                        "record_effective_dttm": current.get("record_effective_dttm"),
                    }

                # ---- 3. close the open history version ----------------------
                close_query = sql.SQL("""
                    UPDATE {schema}.{hist}
                    SET record_end_dttm = %s,
                        active_flg = false
                    WHERE lookup_hk = %s
                      AND record_end_dttm IS NULL
                """).format(
                    schema=sql.Identifier(schema_name),
                    hist=sql.Identifier(lkp.hist_table),
                )
                cursor.execute(close_query, (effective_dttm, row_key))

                if cursor.rowcount == 0:
                    # Pre-existing data without a seeded opening version. Not
                    # fatal -- the new version still records the change -- but
                    # the gap is worth knowing about.
                    logger.warning(
                        "No open history version for lookup_hk=%s in %s.%s; "
                        "inserting a new version anyway.",
                        row_key, schema_name, lkp.hist_table,
                    )
                elif cursor.rowcount > 1:
                    # A partial unique index on (lookup_hk) WHERE
                    # record_end_dttm IS NULL would make this impossible.
                    raise HTTPException(
                        status_code=500,
                        detail="Data integrity error: multiple open history versions.",
                    )

                # ---- 4. insert the new history version ----------------------
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
                    new_hash,
                    actor,
                    actor,
                    effective_dttm,
                    None,       # open-ended
                    False,      # deleted_flg
                    True,       # active_flg
                    current["code_set_nm"],
                    current[lkp.primary_code],
                    merged[lkp.primary_decode],
                    merged[lkp.primary_desc],
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

                # ---- 5. update the current row in place ---------------------
                set_columns = list(values_dict.keys()) + [
                    "modified_by_user_id",
                    "published_by_user_id",
                    "record_effective_dttm",
                ]
                set_values = list(values_dict.values()) + [
                    actor,
                    actor,
                    effective_dttm,
                ]

                update_query = sql.SQL("""
                    UPDATE {schema}.{table}
                    SET {assignments}
                    WHERE lookup_hk = %s
                    RETURNING {cols}
                """).format(
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(lkp.name),
                    assignments=sql.SQL(", ").join(
                        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
                        for c in set_columns
                    ),
                    cols=sql.SQL(", ").join(sql.Identifier(c) for c in lkp.columns),
                )
                cursor.execute(update_query, set_values + [row_key])
                updated_row = cursor.fetchone()

                if updated_row is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Update succeeded but no row was returned.",
                    )

                updated = dict(zip(lkp.columns, updated_row))

        return {
            "status": "success",
            "message": "Record updated successfully.",
            "data": updated,
            "record_values_hash": new_hash,
            "record_effective_dttm": effective_dttm.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Update failed for %s.%s lookup_hk=%s", schema_name, table_name, row_key
        )
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
