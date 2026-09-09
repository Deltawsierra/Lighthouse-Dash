-- ============================================================
-- Lighthouse RDM — dev seed data (no SDL dependency)
--
-- Purpose: get realistic test rows into the reference schema so the
-- API and frontend can be built, without waiting on the SDL
-- reference_data column layout.
--
-- Hashing matches ddl/load/*.sql exactly:
--   canonicalize: UPPER(COALESCE(NULLIF(TRIM(col::text), ''), '__NULL__'))
--   hash:         encode(digest(concat_ws('|', ...), 'sha256'), 'hex')
--
-- Effective timestamp is a FIXED literal, not now(). This matters:
-- historic_record_hk = hash(lookup_hk, record_effective_dttm), so a
-- fixed timestamp makes the whole seed reproducible. Re-running this
-- file produces identical hashes and ON CONFLICT skips cleanly.
--
-- Run order:
--   1. This file (statements 1-4 below), one statement at a time
--   2. ddl/load/load_hist_lkp_geography.sql   (runs as-is, no placeholders)
--   3. ddl/load/load_hist_lkp_office.sql      (runs as-is, no placeholders)
--   4. ddl/load/load_hist_lkp_situs_type.sql  (runs as-is, no placeholders)
--
-- The Lakebase SQL Editor has no transactions, so each statement
-- auto-commits. Run them individually and check the row count between.
--
-- ALL VALUES BELOW ARE INVENTED FOR DEV. Replace with real business
-- values once someone confirms them. modified_by_user_id is set to
-- 'dev_seed' so these rows are obvious in any audit query.
-- ============================================================

-- ------------------------------------------------------------
-- 1. lkp_geography
-- ------------------------------------------------------------
INSERT INTO reference.lkp_geography (
    lookup_hk,
    modified_by_user_id,
    published_by_user_id,
    record_effective_dttm,
    code_set_nm,
    geography_cd,
    geography_nm,
    geography_desc
)
SELECT
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.code_set_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.geography_cd), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    'dev_seed',
    'dev_seed',
    timestamptz '2026-09-09 00:00:00+00',
    v.code_set_nm,
    v.geography_cd,
    v.geography_nm,
    v.geography_desc
FROM (VALUES
    ('geography', 'US-CA', 'California',   'US state'),
    ('geography', 'US-FL', 'Florida',      'US state'),
    ('geography', 'US-NY', 'New York',     'US state'),
    ('geography', 'US-RI', 'Rhode Island', 'US state'),
    ('geography', 'US-TX', 'Texas',        'US state'),
    ('geography', 'US-VA', 'Virginia',     'US state'),
    ('geography', 'US-WA', 'Washington',   'US state'),
    ('geography', 'CA-ON', 'Ontario',      'Canadian province')
) AS v(code_set_nm, geography_cd, geography_nm, geography_desc)
ON CONFLICT (code_set_nm, geography_cd) DO NOTHING;

-- ------------------------------------------------------------
-- 2. lkp_office
-- ------------------------------------------------------------
INSERT INTO reference.lkp_office (
    lookup_hk,
    modified_by_user_id,
    published_by_user_id,
    record_effective_dttm,
    code_set_nm,
    office_cd,
    office_nm,
    office_desc
)
SELECT
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.code_set_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.office_cd), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    'dev_seed',
    'dev_seed',
    timestamptz '2026-09-09 00:00:00+00',
    v.code_set_nm,
    v.office_cd,
    v.office_nm,
    v.office_desc
FROM (VALUES
    ('office', 'OFF-RIC', 'Richmond',   'Home office'),
    ('office', 'OFF-LYN', 'Lynchburg',  'Operations office'),
    ('office', 'OFF-STA', 'Stamford',   'Regional office'),
    ('office', 'OFF-RTP', 'Raleigh',    'Regional office'),
    ('office', 'OFF-REM', 'Remote',     'Distributed staff, no physical site')
) AS v(code_set_nm, office_cd, office_nm, office_desc)
ON CONFLICT (code_set_nm, office_cd) DO NOTHING;

-- ------------------------------------------------------------
-- 3. lkp_situs_type
-- ------------------------------------------------------------
INSERT INTO reference.lkp_situs_type (
    lookup_hk,
    modified_by_user_id,
    published_by_user_id,
    record_effective_dttm,
    code_set_nm,
    situs_type_cd,
    situs_type_nm,
    situs_type_desc
)
SELECT
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.code_set_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.situs_type_cd), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    'dev_seed',
    'dev_seed',
    timestamptz '2026-09-09 00:00:00+00',
    v.code_set_nm,
    v.situs_type_cd,
    v.situs_type_nm,
    v.situs_type_desc
FROM (VALUES
    ('situs_type', 'ISSUE',     'Issue State',       'Jurisdiction where the policy was issued'),
    ('situs_type', 'RESIDENCE', 'Residence State',   'Jurisdiction where the insured resides'),
    ('situs_type', 'PROPERTY',  'Property Location', 'Jurisdiction where the covered property is located'),
    ('situs_type', 'GROUP',     'Group Situs',       'Jurisdiction governing the group contract')
) AS v(code_set_nm, situs_type_cd, situs_type_nm, situs_type_desc)
ON CONFLICT (code_set_nm, situs_type_cd) DO NOTHING;

-- ------------------------------------------------------------
-- 4. source_reference_map
--
-- standard_lookup_hk is recomputed here with the SAME recipe used for
-- lookup_hk above, so the join to the lkp_ tables resolves. If the
-- column gets renamed to standard_lookup_key per the Data Model
-- Pattern diagram, change it in the column list below.
-- ------------------------------------------------------------
INSERT INTO reference.source_reference_map (
    mapping_record_hk,
    record_values_hash,
    modified_by_user_id,
    published_by_user_id,
    record_effective_dttm,
    record_end_dttm,
    deleted_flg,
    active_flg,
    code_set_nm,
    record_source_nm,
    source_reference_cd,
    source_reference_nm,
    standard_lookup_hk,
    mapping_notes
)
SELECT
    -- pk hash: source system + source code + code set
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.record_source_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.source_reference_cd), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.code_set_nm), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    -- diff hash: tracked value columns
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.source_reference_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.standard_cd), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    'dev_seed',
    'dev_seed',
    timestamptz '2026-09-09 00:00:00+00',
    NULL,
    false,
    true,
    v.code_set_nm,
    v.record_source_nm,
    v.source_reference_cd,
    v.source_reference_nm,
    -- must equal the matching lkp_ table's lookup_hk
    encode(digest(concat_ws('|',
        upper(coalesce(nullif(trim(v.code_set_nm), ''), '__NULL__')),
        upper(coalesce(nullif(trim(v.standard_cd), ''), '__NULL__'))
    ), 'sha256'), 'hex'),
    v.mapping_notes
FROM (VALUES
    ('geography',  'LEGACY_ADMIN', 'CA', 'CALIF',         'US-CA',     'Legacy admin uses bare two-letter state code'),
    ('geography',  'LEGACY_ADMIN', 'NY', 'NEW YORK',      'US-NY',     'Legacy admin uses bare two-letter state code'),
    ('geography',  'LEGACY_ADMIN', 'TX', 'TEXAS',         'US-TX',     'Legacy admin uses bare two-letter state code'),
    ('geography',  'POLICY_SYS',   '06', 'California',    'US-CA',     'Policy system uses FIPS-style numeric codes'),
    ('geography',  'POLICY_SYS',   '36', 'New York',      'US-NY',     'Policy system uses FIPS-style numeric codes'),
    ('geography',  'POLICY_SYS',   '48', 'Texas',         'US-TX',     'Policy system uses FIPS-style numeric codes'),
    ('office',     'LEGACY_ADMIN', '01', 'RICHMOND HO',   'OFF-RIC',   'Legacy admin uses numeric office ids'),
    ('office',     'LEGACY_ADMIN', '02', 'LYNCHBURG OPS', 'OFF-LYN',   'Legacy admin uses numeric office ids'),
    ('situs_type', 'POLICY_SYS',   'I',  'Issue',         'ISSUE',     'Single-character situs indicator'),
    ('situs_type', 'POLICY_SYS',   'R',  'Residence',     'RESIDENCE', 'Single-character situs indicator')
) AS v(code_set_nm, record_source_nm, source_reference_cd, source_reference_nm, standard_cd, mapping_notes)
ON CONFLICT (mapping_record_hk) DO NOTHING;

-- ============================================================
-- VERIFICATION — run after steps 1-4 and after the history loads
-- ============================================================

-- Row counts. Expect 8 / 5 / 4 / 10, and history matching current.
-- SELECT 'lkp_geography' t, count(*) FROM reference.lkp_geography
-- UNION ALL SELECT 'lkp_office',           count(*) FROM reference.lkp_office
-- UNION ALL SELECT 'lkp_situs_type',       count(*) FROM reference.lkp_situs_type
-- UNION ALL SELECT 'source_reference_map', count(*) FROM reference.source_reference_map
-- UNION ALL SELECT 'hist_geography',       count(*) FROM reference.hist_lkp_geography
-- UNION ALL SELECT 'hist_office',          count(*) FROM reference.hist_lkp_office
-- UNION ALL SELECT 'hist_situs_type',      count(*) FROM reference.hist_lkp_situs_type;

-- The real test: does the crosswalk actually resolve? Every row should
-- come back with a non-null standardized name. Any NULL means a hash
-- mismatch between the map and the lookup table.
-- SELECT m.record_source_nm, m.source_reference_cd, m.source_reference_nm,
--        g.geography_cd, g.geography_nm
-- FROM reference.source_reference_map m
-- LEFT JOIN reference.lkp_geography g ON g.lookup_hk = m.standard_lookup_hk
-- WHERE m.code_set_nm = 'geography'
-- ORDER BY m.record_source_nm, m.source_reference_cd;

-- Orphan check across all code sets. Should return zero rows.
-- SELECT m.* FROM reference.source_reference_map m
-- WHERE NOT EXISTS (SELECT 1 FROM reference.lkp_geography   x WHERE x.lookup_hk = m.standard_lookup_hk)
--   AND NOT EXISTS (SELECT 1 FROM reference.lkp_office      x WHERE x.lookup_hk = m.standard_lookup_hk)
--   AND NOT EXISTS (SELECT 1 FROM reference.lkp_situs_type  x WHERE x.lookup_hk = m.standard_lookup_hk);
