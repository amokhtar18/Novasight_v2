-- Staging model for the Phase 1 regional-sales dataset.
--
-- 1:1 with the source (one staging model per source, per the dbt-dagster-workflow
-- skill): light cleaning and typing only, no business logic. Grain is one row per
-- region. Materialized as a view (see dbt_project.yml) in the tenant's schema, so it
-- is recomputed from the source on read and stays tenant-isolated.

with source as (
    select *
    from {{ source('phase1', 'regional_sales') }}
),

cleaned as (
    select
        -- Normalize the region label so it is a stable key (trimmed, lower-cased).
        lower(trim(region)) as region,
        -- Type the measure explicitly rather than rely on inferred CSV/Iceberg types.
        toFloat64(amount)   as amount
    from source
)

select
    region,
    amount
from cleaned
