"""
api/v1/controllers/__init__.py

Re-exports the public surface of each controller module, matching the
convention used by api/v1/middleware and api/v1/routes.

Routes should import from this package rather than reaching into submodules:

    from api.v1.controllers import require_lkp_table

The one exception is provision.py, which is imported by its module path
(`from api.v1.controllers.provision import ...`) so that the DDL entry point
is visible at every call site rather than blending in with the read helpers.
"""

from .lkp_tables import (
    LkpTable,
    canonicalize,
    format_dttm_for_hash,
    get_lkp_tables,
    historic_record_hk,
    lookup_hk,
    record_values_hash,
    require_lkp_table,
    sha256_hex,
    warm_cache,
)

__all__ = [
    "LkpTable",
    "canonicalize",
    "format_dttm_for_hash",
    "get_lkp_tables",
    "historic_record_hk",
    "lookup_hk",
    "record_values_hash",
    "require_lkp_table",
    "sha256_hex",
    "warm_cache",
]
