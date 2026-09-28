"""Pydantic settings for OSM planet ingest."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgis_dsn: str = Field(
        default="postgresql://osm:osm@localhost:5433/osm_businesses",
        alias="POSTGIS_DSN",
    )
    osm_data_dir: Path = Field(default=Path("./data/osm"), alias="OSM_DATA_DIR")
    osm_planet_url: str = Field(
        default="https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf",
        alias="OSM_PLANET_URL",
    )
    osm_planet_md5_url: str = Field(
        default="https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf.md5",
        alias="OSM_PLANET_MD5_URL",
    )
    osm_replication_base_url: str = Field(
        default="https://planet.openstreetmap.org/replication/hour",
        alias="OSM_REPLICATION_BASE_URL",
    )
    osm_batch_size: int = Field(default=10_000, alias="OSM_BATCH_SIZE", ge=100)
    osm_osmium_bin: str = Field(default="osmium", alias="OSM_OSMIUM_BIN")
    osm_tags_config: Path = Field(
        default=_REPO_ROOT / "osm_ingest" / "config" / "business_tags.yaml",
        alias="OSM_TAGS_CONFIG",
    )
    osm_job_name: str = Field(default="osm_business_ingest", alias="OSM_JOB_NAME")
    osm_download_chunk_bytes: int = Field(
        default=8 * 1024 * 1024,
        alias="OSM_DOWNLOAD_CHUNK_BYTES",
        ge=64 * 1024,
    )
    osm_replication_max_bytes: int = Field(
        default=512 * 1024 * 1024,
        alias="OSM_REPLICATION_MAX_BYTES",
        ge=1024 * 1024,
    )
    osm_location_store: str = Field(
        default="flex_mem",
        alias="OSM_LOCATION_STORE",
        description="pyosmium location storage: flex_mem | dense_file_array | sparse_file_array",
    )

    @property
    def planet_path(self) -> Path:
        return self.osm_data_dir / "planet" / "planet-latest.osm.pbf"

    @property
    def filtered_path(self) -> Path:
        return self.osm_data_dir / "filtered" / "businesses.osm.pbf"

    @property
    def changes_dir(self) -> Path:
        return self.osm_data_dir / "changes"

    @property
    def location_cache_path(self) -> Path:
        return self.osm_data_dir / "cache" / "node_locations.dat"


@lru_cache
def get_settings() -> Settings:
    return Settings()
