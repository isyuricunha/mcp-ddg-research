"""Typed request and response models for MCP tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_ddg_research.domains import normalize_domains

SafeSearch = Literal["off", "moderate", "strict"]
TimeFilter = Literal["day", "week", "month", "year"]
SearchProvider = Literal["ddgs", "duckduckgo_html"]

ARGUMENT_DESCRIPTIONS = {
    "query": "DuckDuckGo search query text.",
    "max_results": (
        "Final number of search results returned after URL dedupe and optional domain controls. "
        "This is not the provider request window."
    ),
    "search_window": (
        "Internal provider result count requested from DuckDuckGo before URL dedupe, domain "
        "filtering, and final max_results capping. This is a result-count window, not a time "
        "range or number of days."
    ),
    "safe_search": "DuckDuckGo safe search level: off, moderate, or strict.",
    "time_filter": "DuckDuckGo time filter for search recency: day, week, month, or year.",
    "blocked_domains": (
        "Exclusion list of domains to remove from search results. Exact domains and subdomains "
        "match; lookalike substring matches do not."
    ),
    "allowed_domains": (
        "Exclusive domain allowlist. When provided, only matching domains and their subdomains "
        "are kept."
    ),
    "preferred_domains": (
        "Stable ordering preference. Matching domains are moved earlier while preserving relative "
        "order; this is not exclusive filtering and does not add numeric scores."
    ),
    "url": "HTTP or HTTPS URL to fetch with SSRF protections and redirect validation.",
    "max_chars": "Maximum number of extracted characters returned from one fetched page.",
    "max_pages": "Number of top search result pages to fetch in ddg_deep_search.",
    "max_chars_per_page": "Maximum number of extracted characters returned per fetched page.",
    "max_concurrency": (
        "Per-call concurrent page fetch limit for ddg_deep_search. If omitted, MAX_CONCURRENCY "
        "from the environment is used."
    ),
}


class StrictBaseModel(BaseModel):
    """Base model that rejects unexpected tool arguments."""

    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictBaseModel):
    query: str = Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["query"])
    max_results: int = Field(
        default=10,
        ge=1,
        le=30,
        description=ARGUMENT_DESCRIPTIONS["max_results"],
    )
    search_window: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=ARGUMENT_DESCRIPTIONS["search_window"],
    )
    safe_search: SafeSearch = Field(default="off", description=ARGUMENT_DESCRIPTIONS["safe_search"])
    time_filter: TimeFilter | None = Field(
        default=None,
        description=ARGUMENT_DESCRIPTIONS["time_filter"],
    )
    blocked_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["blocked_domains"],
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["allowed_domains"],
    )
    preferred_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["preferred_domains"],
    )

    @field_validator("blocked_domains", "allowed_domains", "preferred_domains")
    @classmethod
    def normalize_domain_options(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)


class FetchRequest(StrictBaseModel):
    url: str = Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["url"])
    max_chars: int = Field(
        default=12000,
        ge=1000,
        le=50000,
        description=ARGUMENT_DESCRIPTIONS["max_chars"],
    )


class DeepSearchRequest(StrictBaseModel):
    query: str = Field(min_length=1, description=ARGUMENT_DESCRIPTIONS["query"])
    max_results: int = Field(
        default=10,
        ge=1,
        le=30,
        description=ARGUMENT_DESCRIPTIONS["max_results"],
    )
    search_window: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=ARGUMENT_DESCRIPTIONS["search_window"],
    )
    max_pages: int = Field(default=5, ge=1, le=10, description=ARGUMENT_DESCRIPTIONS["max_pages"])
    max_chars_per_page: int = Field(
        default=12000,
        ge=1000,
        le=50000,
        description=ARGUMENT_DESCRIPTIONS["max_chars_per_page"],
    )
    safe_search: SafeSearch = Field(default="off", description=ARGUMENT_DESCRIPTIONS["safe_search"])
    time_filter: TimeFilter | None = Field(
        default=None,
        description=ARGUMENT_DESCRIPTIONS["time_filter"],
    )
    blocked_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["blocked_domains"],
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["allowed_domains"],
    )
    preferred_domains: list[str] = Field(
        default_factory=list,
        description=ARGUMENT_DESCRIPTIONS["preferred_domains"],
    )
    max_concurrency: int | None = Field(
        default=None,
        ge=1,
        le=12,
        description=ARGUMENT_DESCRIPTIONS["max_concurrency"],
    )

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
