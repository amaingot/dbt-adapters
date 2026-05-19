"""Functional tests for AWS S3 Tables support.

Requires a real S3 Table Bucket. Set DBT_TEST_ATHENA_S3_TABLES_DATABASE to
the S3 Tables catalog reference, e.g. `s3tablescatalog/my-bucket`. Skipped
when the env var is not set so CI without S3 Tables credentials still passes.

Expected env vars when running:
- DBT_TEST_ATHENA_S3_TABLES_DATABASE  (e.g. "s3tablescatalog/my-bucket")
- DBT_TEST_ATHENA_S3_STAGING_DIR
- DBT_TEST_ATHENA_REGION_NAME
- DBT_TEST_ATHENA_SCHEMA            (defaults to "dbt_s3_tables_test")
- DBT_TEST_ATHENA_WORK_GROUP        (optional)
- DBT_TEST_ATHENA_AWS_PROFILE_NAME  (optional)
"""

import os

import pytest

from dbt.tests.util import run_dbt

S3_TABLES_DATABASE = os.getenv("DBT_TEST_ATHENA_S3_TABLES_DATABASE")

pytestmark = pytest.mark.skipif(
    not S3_TABLES_DATABASE,
    reason="DBT_TEST_ATHENA_S3_TABLES_DATABASE not set — skipping S3 Tables integration tests",
)


TABLE_MODEL = """
{# table_type intentionally omitted to verify S3 Tables auto-detection forces Iceberg #}
{{ config(materialized='table', format='parquet') }}
select 1 as id, 'hello' as name
"""

INCREMENTAL_MERGE_MODEL = """
{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='id',
    format='parquet'
) }}
select 1 as id, 'hello' as name
{% if is_incremental() %}
  union all
  select 2 as id, 'world' as name
{% endif %}
"""

INCREMENTAL_APPEND_MODEL = """
{{ config(
    materialized='incremental',
    incremental_strategy='append',
    format='parquet'
) }}
select 1 as id, 'row' as name
"""

VIEW_MODEL = """
{{ config(materialized='view') }}
select 1 as id
"""

SEED_CSV = """id,name
1,alice
2,bob
"""

SNAPSHOT_SQL = """
{% snapshot s3_tables_snapshot %}
{{ config(
    target_schema=var('schema'),
    strategy='check',
    unique_key='id',
    check_cols=['name'],
) }}
select 1 as id, 'snap' as name
{% endsnapshot %}
"""


@pytest.fixture(scope="class")
def dbt_profile_target():
    return {
        "type": "athena",
        "s3_staging_dir": os.getenv("DBT_TEST_ATHENA_S3_STAGING_DIR"),
        "region_name": os.getenv("DBT_TEST_ATHENA_REGION_NAME"),
        "database": S3_TABLES_DATABASE,
        "schema": os.getenv("DBT_TEST_ATHENA_SCHEMA", "dbt_s3_tables_test"),
        "work_group": os.getenv("DBT_TEST_ATHENA_WORK_GROUP"),
        "threads": int(os.getenv("DBT_TEST_ATHENA_THREADS", "1")),
        "poll_interval": float(os.getenv("DBT_TEST_ATHENA_POLL_INTERVAL", "1.0")),
        "num_retries": int(os.getenv("DBT_TEST_ATHENA_NUM_RETRIES", "2")),
        "aws_profile_name": os.getenv("DBT_TEST_ATHENA_AWS_PROFILE_NAME") or None,
    }


class TestS3TablesTable:
    @pytest.fixture(scope="class")
    def models(self):
        return {"s3_tables_table.sql": TABLE_MODEL}

    def test_table_build_and_rebuild(self, project):
        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"

        # Re-run does drop-and-recreate; rename swap is not supported on S3 Tables.
        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"


class TestS3TablesIncrementalMerge:
    @pytest.fixture(scope="class")
    def models(self):
        return {"s3_tables_merge.sql": INCREMENTAL_MERGE_MODEL}

    def test_merge_then_incremental(self, project):
        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"

        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"

    def test_full_refresh_drops_and_recreates(self, project):
        run_dbt(["run"])
        results = run_dbt(["run", "--full-refresh"])
        assert len(results) == 1 and results[0].status == "success"


class TestS3TablesIncrementalAppend:
    @pytest.fixture(scope="class")
    def models(self):
        return {"s3_tables_append.sql": INCREMENTAL_APPEND_MODEL}

    def test_append(self, project):
        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"

        results = run_dbt(["run"])
        assert len(results) == 1 and results[0].status == "success"


class TestS3TablesViewBlocked:
    @pytest.fixture(scope="class")
    def models(self):
        return {"s3_tables_view.sql": VIEW_MODEL}

    def test_view_raises_compiler_error(self, project):
        results = run_dbt(["run"], expect_pass=False)
        assert len(results) == 1
        assert "CREATE VIEW is not supported" in results[0].message


class TestS3TablesSeedBlocked:
    @pytest.fixture(scope="class")
    def seeds(self):
        return {"s3_tables_seed.csv": SEED_CSV}

    def test_seed_raises_compiler_error(self, project):
        results = run_dbt(["seed"], expect_pass=False)
        assert any("Seeds are not supported" in str(r.message) for r in results)


class TestS3TablesSnapshot:
    @pytest.fixture(scope="class")
    def snapshots(self):
        return {"s3_tables_snapshot.sql": SNAPSHOT_SQL}

    @pytest.fixture(scope="class")
    def models(self):
        return {}

    def test_snapshot_initial_and_subsequent(self, project):
        results = run_dbt(["snapshot", "--vars", f"schema: {project.test_schema}"])
        assert len(results) == 1 and results[0].status == "success"

        results = run_dbt(["snapshot", "--vars", f"schema: {project.test_schema}"])
        assert len(results) == 1 and results[0].status == "success"
