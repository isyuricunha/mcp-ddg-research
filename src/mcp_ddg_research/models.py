"""Typed request and response models for MCP tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_ddg_research.domains import normalize_domains

SafeSearch = Literal["off", "moderate", "strict"]
TimeFilter = Literal["day", "week", "month", "year"]
SearchProvider = Literal["ddgs", "duckduckgo_html"]


class StrictBaseModel(BaseModel):
    """Base model that rejects unexpected tool arguments."""

    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictBaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=30)
    search_window: int | None = Field(default=None, ge=1, le=100)
    safe_search: SafeSearch = "off"
    time_filter: TimeFilter | None = None
    blocked_domains: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)

    @field_validator("blocked_domains", "allowed_domains", "preferred_domains")
    @classmethod
    def normalize_domain_options(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)


class FetchRequest(StrictBaseModel):
    url: str = Field(min_length=1)
    max_chars: int = Field(default=12000, ge=1000, le=50000)


class DeepSearchRequest(StrictBaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=30)
    search_window: int | None = Field(default=None, ge=1, le=100)
    max_pages: int = Field(default=5, ge=1, le=10)
    max_chars_per_page: int = Field(default=12000, ge=1000, le=50000)
    safe_search: SafeSearch = "off"
    time_filter: TimeFilter | None = None
    blocked_domains: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)
    max_concurrency: int | None = Field(default=None, ge=1, le=12)

    @field_validator("blocked_domains", "allowed_domains", "preferred_domains")
    @classmethod
    def normalize_domain_options(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)


class SearchResult(StrictBaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(StrictBaseModel):
    query: str
    provider: SearchProvider
    results: list[SearchResult]
    cached: bool
    error: str | None


class FetchResponse(StrictBaseModel):
    url: str
    final_url: str
    title: str
    content: str
    content_type: str
    cached: bool
    success: bool
    error: str | None


class DeepSearchPage(StrictBaseModel):
    title: str
    url: str
    final_url: str
    content: str


class FailedPage(StrictBaseModel):
    url: str
    error: str


class DeepSearchResponse(StrictBaseModel):
    query: str
    search_provider: SearchProvider
    sources: list[SearchResult]
    pages: list[DeepSearchPage]
    failed_pages: list[FailedPage]
    cached: bool
