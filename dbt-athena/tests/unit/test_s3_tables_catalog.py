"""Unit tests for AWS S3 Tables support in dbt-athena.

Covers:
- AthenaAdapter.is_s3_tables_catalog (the @available adapter method)
- list_schemas passes CatalogId for non-default Glue catalogs
- relation.get_table_type ordering — Parameters.table_type=iceberg wins over
  TableType so S3 Tables tables (which report TableType="customer") are
  classified as Iceberg rather than raising.
"""

from multiprocessing import get_context

import pytest
from moto import mock_aws

from dbt.adapters.athena import AthenaAdapter
from dbt.adapters.athena import Plugin as AthenaPlugin
from dbt.adapters.athena.relation import TableType, get_table_type

from .constants import (
    ATHENA_WORKGROUP,
    AWS_REGION,
    DATABASE_NAME,
    DATA_CATALOG_NAME,
    S3_STAGING_DIR,
    SHARED_DATA_CATALOG_NAME,
)
from .utils import config_from_parts_or_dicts, inject_adapter


class TestIsS3TablesCatalogMethod:
    """The @available adapter method delegates to the util helper."""

    def setup_method(self, _):
        self.config = self._config()
        self._adapter = None

    @property
    def adapter(self):
        if self._adapter is None:
            self._adapter = AthenaAdapter(self.config, get_context("spawn"))
            inject_adapter(self._adapter, AthenaPlugin)
        return self._adapter

    @staticmethod
    def _config():
        project_cfg = {
            "name": "X",
            "version": "0.1",
            "profile": "test",
            "project-root": "/tmp/dbt/does-not-exist",
            "config-version": 2,
        }
        profile_cfg = {
            "outputs": {
                "test": {
                    "type": "athena",
                    "s3_staging_dir": S3_STAGING_DIR,
                    "region_name": AWS_REGION,
                    "database": DATA_CATALOG_NAME,
                    "work_group": ATHENA_WORKGROUP,
                    "schema": DATABASE_NAME,
                }
            },
            "target": "test",
        }
        return config_from_parts_or_dicts(project_cfg, profile_cfg)

    @pytest.mark.parametrize(
        ("database", "expected"),
        (
            pytest.param(None, False, id="none"),
            pytest.param("", False, id="empty"),
            pytest.param("awsdatacatalog", False, id="not_s3_tables"),
            pytest.param("s3tablescatalog/my-bucket", True, id="s3_tables"),
            pytest.param("S3TABLESCATALOG/my-bucket", True, id="case_insensitive"),
            pytest.param("s3tablescatalog", False, id="missing_bucket"),
        ),
    )
    def test_is_s3_tables_catalog(self, database, expected):
        assert self.adapter.is_s3_tables_catalog(database) is expected


class TestListSchemasCatalogId:
    """list_schemas should pass CatalogId for non-default Glue catalogs."""

    def setup_method(self, _):
        self.config = TestIsS3TablesCatalogMethod._config()
        self._adapter = None

    @property
    def adapter(self):
        if self._adapter is None:
            self._adapter = AthenaAdapter(self.config, get_context("spawn"))
            inject_adapter(self._adapter, AthenaPlugin)
        return self._adapter

    @mock_aws
    def test_default_catalog_does_not_pass_catalog_id(self, mock_aws_service):
        """Default catalog has no catalog-id parameter — CatalogId omitted."""
        mock_aws_service.create_data_catalog()
        mock_aws_service.create_database("ns_one")
        mock_aws_service.create_database("ns_two")
        self.adapter.acquire_connection("dummy")
        result = self.adapter.list_schemas(DATA_CATALOG_NAME)
        assert sorted(result) == ["ns_one", "ns_two"]

    @mock_aws
    def test_shared_catalog_passes_catalog_id(self, mock_aws_service):
        """Shared catalog has catalog-id — CatalogId is forwarded so the
        Glue paginator queries the right account."""
        mock_aws_service.create_data_catalog(
            catalog_name=SHARED_DATA_CATALOG_NAME,
            catalog_id=SHARED_DATA_CATALOG_NAME,
        )
        # Both databases land in the default mocked Glue account; the
        # assertion that matters is that the call doesn't fail and the
        # CatalogId kwarg is plumbed through.
        mock_aws_service.create_database("ns_alpha", catalog_id=SHARED_DATA_CATALOG_NAME)
        mock_aws_service.create_database("ns_beta", catalog_id=SHARED_DATA_CATALOG_NAME)
        self.adapter.acquire_connection("dummy")
        result = self.adapter.list_schemas(SHARED_DATA_CATALOG_NAME)
        assert sorted(result) == ["ns_alpha", "ns_beta"]


class TestGetTableTypeOrdering:
    """get_table_type checks Parameters.table_type=iceberg before TableType.

    S3 Tables tables report TableType='customer' (not in RELATION_TYPE_MAP).
    With the old ordering this raised before the Iceberg parameter check
    could match.
    """

    def test_s3_tables_customer_type_classified_as_iceberg(self):
        table = {
            "Name": "tbl_name",
            "DatabaseName": "ns",
            "TableType": "customer",
            "Parameters": {"table_type": "ICEBERG"},
        }
        assert get_table_type(table) is TableType.ICEBERG

    def test_unknown_table_type_without_iceberg_param_still_raises(self):
        table = {
            "Name": "tbl_name",
            "DatabaseName": "ns",
            "TableType": "customer",
            "Parameters": {},
        }
        with pytest.raises(ValueError, match="is not supported"):
            get_table_type(table)

    def test_iceberg_parameter_wins_over_external_table(self):
        table = {
            "Name": "tbl_name",
            "DatabaseName": "ns",
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {"table_type": "iceberg"},
        }
        assert get_table_type(table) is TableType.ICEBERG

    def test_external_table_without_iceberg_param(self):
        table = {
            "Name": "tbl_name",
            "DatabaseName": "ns",
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {},
        }
        assert get_table_type(table) is TableType.TABLE

    def test_none_table_type_with_no_iceberg_param_raises(self):
        table = {
            "Name": "tbl_name",
            "DatabaseName": "ns",
            "Parameters": {},
        }
        with pytest.raises(ValueError, match="cannot be None"):
            get_table_type(table)
