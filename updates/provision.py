"""
api/v1/controllers/provision.py

Provision a new reference area: creates the lkp_<area> / hist_lkp_<area> pair
and their indexes, matching ddl/reference.sql exactly.

This is the only place in the API that issues DDL, and the area name is the
only user-supplied value that becomes a SQL identifier anywhere in the
service. It is validated against a strict pattern before any SQL is built --
sql.Identifier() quoting alone is not the control here, the pattern is.

Postgres DDL is transactional, so either both tables and all their indexes
exist afterwards, or none of them do. There is no half-provisioned state to
clean up.

Requires the application's Postgres role to hold CREATE on the schema:

    GRANT CREATE ON SCHEMA reference TO "<service-principal-client-id>";
"""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException
from psycopg import errors as pg_errors
from psycopg import sql

from api.v1.middleware import get_connection_pool, get_settings
from api.v1.controllers.lkp_tables import LkpTable, get_lkp_tables

logger = logging.getLogger(__name__)

# Lowercase letters, digits and underscores, starting with a letter.
#
# The 40-character ceiling is not arbitrary: the longest derived identifier is
# idx_hist_lkp_<area>_lookup_hk, which is 23 characters plus the area name,
# and Postgres truncates identifiers at 63. A longer area would silently
# collide with another area's index name after truncation.
AREA_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_AREA_LEN = 40


def validate_area_name(area: str) -> str:
    """Normalize and validate a proposed area name, or raise 400."""
    if not isinstance(area, str):
        raise HTTPException(status_code=400, detail="'area' must be a string.")

    area = area.strip().lower()

    if not area:
        raise HTTPException(status_code=400, detail="'area' is required.")

    if len(area) > MAX_AREA_LEN:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'area' must be {MAX_AREA_LEN} characters or fewer so the derived "
                "index names stay within the Postgres identifier limit."
            ),
        )

    if not AREA_NAME_RE.fullmatch(area):
        raise HTTPException(
            status_code=400,
            detail=(
                "'area' must start with a lowercase letter and contain only "
                "lowercase letters, digits and underscores (e.g. 'claim_status')."
            ),
        )

    if area.endswith("_"):
        raise HTTPException(status_code=400, detail="'area' cannot end with an underscore.")

    if "__" in area:
        raise HTTPException(
            status_code=400, detail="'area' cannot contain consecutive underscores."
        )

    settings = get_settings()
    for reserved in (settings.LKP_PREFIX, settings.HIST_PREFIX):
        if area.startswith(reserved):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'area' cannot start with '{reserved}' -- the prefix is added "
                    "automatically."
                ),
            )

    return area


def provision_lookup_area(schema: str, area: str) -> LkpTable:
    """Create lkp_<area>, hist_lkp_<area> and their indexes in one transaction.

    Returns the new registry entry. Raises HTTPException on a name collision,
    a missing privilege, or any other database failure.
    """
    settings = get_settings()

    lkp_name = f"{settings.LKP_PREFIX}{area}"
    hist_name = f"{settings.HIST_PREFIX}{lkp_name}"

    code_col = f"{area}{settings.CODE_SUFFIX}"
    decode_col = f"{area}{settings.DECODE_SUFFIX}"
    desc_col = f"{area}{settings.DESC_SUFFIX}"

    ident = sql.Identifier

    create_current = sql.SQL("""
        CREATE TABLE {schema}.{table} (
            lookup_hk             varchar(64)   NOT NULL,
            modified_by_user_id   varchar(50)   NOT NULL,
            published_by_user_id  varchar(50),
            record_effective_dttm timestamptz   NOT NULL,
            code_set_nm           varchar(100)  NOT NULL,
            {code_col}            varchar(50)   NOT NULL,
            {decode_col}          varchar(255)  NOT NULL,
            {desc_col}            text,
            CONSTRAINT {pk} PRIMARY KEY (lookup_hk),
            CONSTRAINT {uq} UNIQUE (code_set_nm, {code_col})
        )
    """).format(
        schema=ident(schema),
        table=ident(lkp_name),
        code_col=ident(code_col),
        decode_col=ident(decode_col),
        desc_col=ident(desc_col),
        pk=ident(f"pk_{lkp_name}"),
        uq=ident(f"uq_{lkp_name}_code_set_cd"),
    )

    # Case-insensitive business-key guard. Mirrors the UPPER() canonicalization
    # used to build lookup_hk, so the database enforces the same identity the
    # hash assumes.
    create_current_ci = sql.SQL("""
        CREATE UNIQUE INDEX {idx}
            ON {schema}.{table} (upper(code_set_nm), upper({code_col}))
    """).format(
        idx=ident(f"uq_{lkp_name}_code_set_cd_ci"),
        schema=ident(schema),
        table=ident(lkp_name),
        code_col=ident(code_col),
    )

    # No foreign key to the current table: history must survive deletion of
    # the current-state row, so the link is by value only.
    create_hist = sql.SQL("""
        CREATE TABLE {schema}.{hist} (
            historic_record_hk    varchar(64)   NOT NULL,
            lookup_hk             varchar(64)   NOT NULL,
            record_values_hash    varchar(64)   NOT NULL,
            modified_by_user_id   varchar(50)   NOT NULL,
            published_by_user_id  varchar(50),
            record_effective_dttm timestamptz   NOT NULL,
            record_end_dttm       timestamptz,
            deleted_flg           boolean       NOT NULL DEFAULT false,
            active_flg            boolean       NOT NULL DEFAULT true,
            code_set_nm           varchar(100)  NOT NULL,
            {code_col}            varchar(50)   NOT NULL,
            {decode_col}          varchar(255)  NOT NULL,
            {desc_col}            text,
            CONSTRAINT {pk} PRIMARY KEY (historic_record_hk)
        )
    """).format(
        schema=ident(schema),
        hist=ident(hist_name),
        code_col=ident(code_col),
        decode_col=ident(decode_col),
        desc_col=ident(desc_col),
        pk=ident(f"pk_{hist_name}"),
    )

    create_hist_idx = sql.SQL("""
        CREATE INDEX {idx} ON {schema}.{hist} (lookup_hk)
    """).format(
        idx=ident(f"idx_{hist_name}_lookup_hk"),
        schema=ident(schema),
        hist=ident(hist_name),
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
        # Postgres runs DDL inside the transaction, so a failure on the third
        # statement rolls back the first two.
        with pool.connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(create_current)
                    cursor.execute(create_current_ci)
                    cursor.execute(create_hist)
                    cursor.execute(create_hist_idx)
                except pg_errors.DuplicateTable:
                    raise HTTPException(
                        status_code=409,
                        detail=f"A table named '{lkp_name}' or '{hist_name}' already exists.",
                    )
                except pg_errors.DuplicateObject:
                    raise HTTPException(
                        status_code=409,
                        detail=f"An index or constraint for area '{area}' already exists.",
                    )
                except pg_errors.InsufficientPrivilege:
                    logger.error(
                        "Service principal lacks CREATE on schema %s; cannot provision %s",
                        schema, lkp_name,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "The service account is not permitted to create tables in "
                            "this schema. A database administrator needs to grant "
                            "CREATE on the schema."
                        ),
                    )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Provisioning failed for area '%s' in schema %s", area, schema)
        raise HTTPException(status_code=500, detail=f"Could not create tables: {e}")

    logger.info("Provisioned %s.%s and %s.%s", schema, lkp_name, schema, hist_name)

    # Rebuild this process's registry so the new area is immediately visible.
    #
    # NOTE: the registry is per-process. On a multi-replica deployment the
    # other pods keep their cached list until their own TTL expires, so a
    # newly provisioned area can take up to an hour to appear everywhere.
    registry = get_lkp_tables(schema, force_refresh=True)

    created = registry.get(lkp_name)
    if created is None:
        # The tables exist but did not pass the registry's own validation.
        # That means the DDL above and _discover() have drifted apart.
        logger.error(
            "Provisioned %s.%s but it did not appear in the registry.", schema, lkp_name
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Created '{lkp_name}' but it does not match the expected lookup "
                "pattern. Check the server logs."
            ),
        )

    return created
