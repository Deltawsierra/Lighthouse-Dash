def _build_dev_sample_permissions() -> PermissionBlob:
    return {
        "platform": [],
        "schema": {
            "reference": ["table:list", "table:read"],
        },
        "table": {
            "reference.lkp_geography": [
                "table:insert",
                "table:update",
                "table:delete",
            ],
            "reference.lkp_office": [
                "table:insert",
                "table:update",
                "table:delete",
            ],
            "reference.lkp_situs_type": [
                "table:insert",
                "table:update",
                "table:delete",
            ],
        },
    }
