"""Typed request and response models for MCP tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SafeSearch = Literal["off", "moderate", "strict"]
TimeFilter = Literal["day", "week", "month", "year"]
SearchProvider = Literal["ddgs", "duckduckgo_html"]


class StrictBaseModel(BaseModel):
    """Base model that rejects unexpected tool arguments."""

    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictBaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=30)
    safe_search: SafeSearch = "off"
    time_filter: TimeFilter | None = None


class FetchRequest(StrictBaseModel):
    url: str = Field(min_length=1)
    max_chars: int = Field(default=12000, ge=1000, le=50000)


class DeepSearchRequest(StrictBaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=30)
    max_pages: int = Field(default=5, ge=1, le=10)
    max_chars_per_page: int = Field(default=12000, ge=1000, le=50000)
    safe_search: SafeSearch = "off"
    time_filter: TimeFilter | None = None


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
