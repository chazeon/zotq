"""Pydantic models for config, domain objects, and runtime contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Mode(str, Enum):
    LOCAL_API = "local-api"
    REMOTE = "remote"


class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"
    JSONL = "jsonl"


class SearchMode(str, Enum):
    KEYWORD = "keyword"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class Creator(BaseModel):
    model_config = ConfigDict(extra="ignore")

    first_name: str | None = None
    last_name: str | None = None


class Item(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    item_type: str | None = None
    title: str | None = None
    date: str | None = None
    creators: list[Creator] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    abstract: str | None = None


class Collection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    name: str
    parent_collection: str | None = None


class Tag(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tag: str
    type: int | None = None


class BackendCapabilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keyword: bool = True
    fuzzy: bool = True
    semantic: bool = False
    hybrid: bool = False
    index_status: bool = True
    index_sync: bool = True
    index_rebuild: bool = True


class IndexStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ready: bool = False
    enabled: bool = True
    provider: str = "local"
    model: str = ""
    document_count: int = 0
    chunk_count: int = 0
    last_sync_at: datetime | None = None


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item: Item
    score: float | None = None
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requested_mode: SearchMode
    executed_mode: SearchMode
    limit: int
    offset: int
    total: int
    hits: list[SearchHit] = Field(default_factory=list)


class ChunkRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    item_key: str
    ordinal: int
    text: str


class VectorRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    item_key: str
    ordinal: int
    embedding: list[float] = Field(default_factory=list)


class SearchDefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    default_mode: SearchMode = SearchMode.KEYWORD
    allow_fallback: bool = False
    alpha: float = Field(default=0.35, ge=0.0, le=1.0)
    lexical_k: int = Field(default=100, ge=1)
    vector_k: int = Field(default=100, ge=1)


class IndexConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    index_dir: str = "~/.local/share/zotq/index"
    embedding_provider: str = "local"
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_timeout_seconds: int = 30
    embedding_max_retries: int = Field(default=2, ge=0, le=10)

    def expanded_index_dir(self) -> Path:
        return Path(self.index_dir).expanduser()


class LocalApiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = "http://127.0.0.1:23119"
    api_key: str = ""
    timeout_seconds: int = 10
    library_id: str = "0"


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = ""
    bearer_token: str = ""
    api_key: str = ""
    timeout_seconds: int = 15
    verify_tls: bool = True
    library_id: str = "0"


class ProfileConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Mode = Mode.LOCAL_API
    output: OutputFormat = OutputFormat.TABLE
    search: SearchDefaultsConfig = Field(default_factory=SearchDefaultsConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    local_api: LocalApiConfig = Field(default_factory=LocalApiConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_profile: str = "default"
    profiles: dict[str, ProfileConfig] = Field(default_factory=lambda: {"default": ProfileConfig()})

    def require_profile(self, name: str | None = None) -> ProfileConfig:
        profile_name = name or self.active_profile
        if profile_name not in self.profiles:
            raise ValueError(f"Profile not found: {profile_name}")
        return self.profiles[profile_name]


class QuerySpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    search_mode: SearchMode = SearchMode.KEYWORD
    allow_fallback: bool = False
    title: str | None = None
    creators: list[str] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    tags: list[str] = Field(default_factory=list)
    collection: str | None = None
    item_type: str | None = None
    alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    lexical_k: int | None = Field(default=None, ge=1)
    vector_k: int | None = Field(default=None, ge=1)
    debug: bool = False
    limit: int = Field(default=20, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


SearchModeName = Literal["keyword", "fuzzy", "semantic", "hybrid"]
