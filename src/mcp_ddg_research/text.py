"""Readable text extraction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

BOILERPLATE_TAGS = ("script", "style", "noscript", "template", "nav", "header", "footer", "aside")
CONTENT_CLASS_RE = re.compile(r"(content|main|body|article|post|entry|text)", re.IGNORECASE)
TEXT_FILE_EXTENSIONS = (".md", ".markdown", ".txt", ".json", ".jsonl")


@dataclass(frozen=True)
class ExtractedText:
    title: str
    content: str


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()


def is_plain_text_content(content_type: str, url: str) -> bool:
    lowered = content_type.lower()
    path = urlparse(url).path.lower()
    return (
        lowered.startswith("text/")
        or "json" in lowered
        or path.endswith(TEXT_FILE_EXTENSIONS)
    )


def _clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(BOILERPLATE_TAGS):
        tag.decompose()


def _tag_text(tag: Tag) -> str:
    return normalize_whitespace(tag.get_text(" ", strip=True))


def _candidate_tags(soup: BeautifulSoup) -> list[Tag]:
    candidates: list[Tag] = []
    candidates.extend(tag for tag in soup.find_all(["main", "article"]) if isinstance(tag, Tag))
    candidates.extend(
        tag
        for tag in soup.find_all(["section", "div"], class_=CONTENT_CLASS_RE)
        if isinstance(tag, Tag)
    )
    return candidates


def extract_html_text(html: str, max_chars: int) -> ExtractedText:
    soup = BeautifulSoup(html, "html.parser")
    title = normalize_whitespace(soup.title.get_text(" ", strip=True)) if soup.title else ""
    _clean_soup(soup)

    best_text = ""
    for tag in _candidate_tags(soup):
        candidate_text = _tag_text(tag)
        if len(candidate_text) > len(best_text):
            best_text = candidate_text

    if len(best_text) < 600:
        body = soup.body if soup.body else soup
        best_text = _tag_text(body)

    return ExtractedText(title=title, content=truncate_text(best_text, max_chars))
