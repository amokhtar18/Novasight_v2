-- Intermediate model: reusable business-logic building block over the regional-sales
-- staging view (see the dbt-dagster-workflow skill: intermediate = reusable joins /
-- business logic, materialized ephemeral so it is inlined into downstream marts and
-- never written to the tenant's schema on its own).
--
-- Grain: one row per region (unchanged from staging). Adds the share-of-total measure
-- that marts and the semantic layer build on, so the percentage logic lives in exactly
-- one place.

with staged as (
    select
        region,
        amount
    from {{ ref('stg_phase1__regional_sales') }}
),

enriched as (
    select
        region,
        amount,
        -- Each region's share of total sales, as a percentage rounded to 4 dp.
        -- Window over the full set => denominator is total sales across all regions.
        round(amount / sum(amount) over () * 100, 4) as amount_share_pct
    from staged
)

select
    region,
    amount,
    amount_share_pct
from enriched
