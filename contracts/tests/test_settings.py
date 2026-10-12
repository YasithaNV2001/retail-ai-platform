import pytest
from pydantic import ValidationError

from retail_contracts.settings import Settings, table


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAP_ENV", "dev")
    monkeypatch.setenv("RAP_CATALOG", "rap_dev")
    monkeypatch.delenv("RAP_SCHEMA_PREFIX", raising=False)


def test_table_full_name(dev_env: None) -> None:
    assert table("gold", "fact_sales_daily") == "rap_dev.gold.fact_sales_daily"


def test_schema_prefix_fallback(dev_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-006 fallback: default catalog, schemas prefixed dev_ / prod_
    monkeypatch.setenv("RAP_CATALOG", "workspace")
    monkeypatch.setenv("RAP_SCHEMA_PREFIX", "dev_")
    assert table("ops", "dq_results") == "workspace.dev_ops.dq_results"


def test_unknown_layer_is_rejected(dev_env: None) -> None:
    with pytest.raises(ValueError, match="unknown layer"):
        table("platinum", "x")  # type: ignore[arg-type]


def test_env_must_be_dev_or_prod(dev_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()


def test_catalog_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAP_ENV", "dev")
    monkeypatch.delenv("RAP_CATALOG", raising=False)
    with pytest.raises(ValidationError):
        Settings()
