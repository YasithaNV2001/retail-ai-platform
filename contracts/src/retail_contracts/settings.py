"""Runtime settings shared by every project (System design, sections 6 and 10).

Values come from environment variables only: RAP_ENV, RAP_CATALOG, RAP_SCHEMA_PREFIX.
No code anywhere else may hard-code a catalog or schema name; it calls table() instead.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Layer = Literal["landing", "bronze", "silver", "gold", "ml", "ops"]
LAYERS: tuple[str, ...] = ("landing", "bronze", "silver", "gold", "ml", "ops")


class Settings(BaseSettings):
    """RAP_* environment variables, validated once when the object is created."""

    model_config = SettingsConfigDict(env_prefix="RAP_", extra="ignore", frozen=True)

    env: Literal["dev", "prod"]
    catalog: str
    schema_prefix: str = ""  # "" normally; "dev_" or "prod_" under the ADR-006 fallback

    def schema(self, layer: Layer) -> str:
        """Full schema name, for example rap_dev.gold."""
        if layer not in LAYERS:
            raise ValueError(f"unknown layer {layer!r}; expected one of {LAYERS}")
        return f"{self.catalog}.{self.schema_prefix}{layer}"

    def table(self, layer: Layer, name: str) -> str:
        """Full three-part table name, for example rap_dev.gold.fact_sales_daily."""
        return f"{self.schema(layer)}.{name}"


def get_settings() -> Settings:
    """Read the environment now (not cached, so tests and jobs always see current values)."""
    return Settings()


def table(layer: Layer, name: str) -> str:
    """table("gold", "fact_sales_daily") -> "rap_dev.gold.fact_sales_daily" in dev."""
    return get_settings().table(layer, name)
