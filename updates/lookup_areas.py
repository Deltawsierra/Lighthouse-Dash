"""
api/v1/routes/lookup_areas.py

Provision a new reference area from the dashboard.

Kept separate from create.py on purpose: that endpoint inserts rows, this one
issues DDL. They need different permissions, different error handling, and a
reviewer should be able to see at a glance which one creates tables.

POST /v1/lookup-areas  with  {"area": "claim_status"}
  -> creates reference.lkp_claim_status and reference.hist_lkp_claim_status

The area name is the only user input in the whole service that becomes a SQL
identifier. Validation lives in controllers/provision.py and runs before any
SQL is built.
"""

import logging

from fastapi import APIRouter, Body, HTTPException, Request, Response

from api.v1.middleware import (
    get_schema,
    get_settings,
    require_permission_or_403,
)
from api.v1.controllers import get_lkp_tables
from api.v1.controllers.provision import provision_lookup_area, validate_area_name

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/lookup-areas", status_code=201)
def create_lookup_area(
    request: Request,
    response: Response,
    body: dict = Body(..., description="{'area': 'claim_status'}"),
):
    """
    Create a new reference area: the current table, its history table, and
    their indexes.

    Body:
        { "area": "claim_status" }

    Creates, using the configured naming conventions:
        {SCHEMA}.lkp_claim_status       with claim_status_cd / _nm / _desc
        {SCHEMA}.hist_lkp_claim_status

    Permissions:
        Requires `table:create` on the schema. This is DDL, so it should be
        restricted to admins -- `table:insert` is row-level and deliberately
        does NOT grant this.

    Returns:
        201 with the new area's registry entry, in the same shape the table
        endpoints return, so the dashboard can render it without a reload.

    Raises HTTPException:
        400 - invalid area name.
        403 - caller lacks `table:create` on the schema.
        409 - a table for that area already exists.
        500 - the service account cannot create tables, or another DB error.
        503 - connection pool unavailable.
    """

    settings = get_settings()
    scope = f"{settings.SCHEMA}"
    user = getattr(request.state, "user", None) or {}
    permissions = user.get("permissions", {}) or {}

    require_permission_or_403(
        permissions,
        "schema",
        scope,
        "table:create",
    )

    actor = user.get("username") or user.get("id")
    if not actor:
        raise HTTPException(status_code=401, detail="No authenticated user on request.")

    if not body or "area" not in body:
        raise HTTPException(status_code=400, detail="Request body must contain 'area'.")

    area = validate_area_name(body["area"])

    schema_name = get_schema()

    # Cheap pre-check for a clean error message. provision_lookup_area also
    # catches the database's own duplicate error, which is what makes this
    # race-safe -- this check alone would not be.
    existing = get_lkp_tables(schema_name)
    lkp_name = f"{settings.LKP_PREFIX}{area}"
    if lkp_name in existing:
        raise HTTPException(
            status_code=409, detail=f"Area '{area}' already exists."
        )

    logger.info("User %s provisioning lookup area '%s' in schema %s",
                actor, area, schema_name)

    created = provision_lookup_area(schema_name, area)

    return {
        "status": "success",
        "message": f"Created lookup area '{area}'.",
        "data": {
            "table": created.name,
            "hist_table": created.hist_table,
            "code_set": created.code_set,
            "key_column": created.key_column,
            "columns": created.describe_columns(),
        },
    }
