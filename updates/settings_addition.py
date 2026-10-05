# ---------------------------------------------------------------------------
# ADD THESE FIELDS to the existing Settings class in
# api/v1/middleware/settings.py
#
# This is a fragment, not a file to drop in. Paste the block below inside the
# Settings class alongside SCHEMA, DATABASE, etc. Keep the existing imports
# and add `frozenset` usage only if your pydantic version needs it (v2 is
# fine as written).
# ---------------------------------------------------------------------------

    # --- Reference-data model conventions ---------------------------------
    # Structural facts about the lkp_ / hist_lkp_ pattern, moved here per
    # review. These define what the API considers a valid lookup table and
    # which columns are business values vs. bookkeeping.
    #
    # CAUTION: KEY_COLUMN and the suffixes also determine which columns feed
    # record_values_hash. Overriding them per environment would make Python
    # hashes diverge from the SQL load templates, so treat them as fixed
    # unless the DDL changes with them.
    LKP_PREFIX: str = "lkp_"
    HIST_PREFIX: str = "hist_"

    KEY_COLUMN: str = "lookup_hk"

    CODE_SUFFIX: str = "_cd"
    DECODE_SUFFIX: str = "_nm"
    DESC_SUFFIX: str = "_desc"

    AUDIT_COLUMNS: frozenset[str] = frozenset({
        "lookup_hk",
        "modified_by_user_id",
        "published_by_user_id",
        "record_effective_dttm",
        "code_set_nm",
    })


# ---------------------------------------------------------------------------
# ALTERNATIVE, if "predefined setting object" meant a nested object rather
# than flat fields on Settings. Slightly more ceremony, but it groups the
# model conventions and keeps them out of the env-var surface.
#
#   from pydantic import BaseModel
#
#   class ReferenceModelSettings(BaseModel):
#       lkp_prefix: str = "lkp_"
#       hist_prefix: str = "hist_"
#       key_column: str = "lookup_hk"
#       code_suffix: str = "_cd"
#       decode_suffix: str = "_nm"
#       desc_suffix: str = "_desc"
#       audit_columns: frozenset[str] = frozenset({...})
#
#   class Settings(BaseSettings):
#       ...
#       REFERENCE_MODEL: ReferenceModelSettings = ReferenceModelSettings()
#
# lkp_tables.py would then read get_settings().REFERENCE_MODEL.lkp_prefix
# instead of get_settings().LKP_PREFIX.
# ---------------------------------------------------------------------------
