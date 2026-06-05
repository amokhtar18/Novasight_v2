-- Mart: consumption-ready regional-sales table — the model ClickHouse serves and the
-- semantic layer reads (see the dbt-dagster-workflow skill: marts = consumption-ready
-- tables loaded into ClickHouse). Materialized as a table (dbt_project.yml) in the
-- tenant's schema.
--
-- Grain: one row per region. Adds a sales rank on top of the share-of-total measure
-- from the intermediate building block, then exposes the final consumption shape.

with enriched as (
    select
        region,
        amount,
        amount_share_pct
    from {{ ref('int_regional_sales_enriched') }}
)

select
    region,
    amount,
    amount_share_pct,
    -- Dense rank by sales descending: 1 = highest-selling region. Deterministic on the
    -- (unique) region key so re-runs are stable.
    dense_rank() over (order by amount desc, region asc) as sales_rank
from enriched
