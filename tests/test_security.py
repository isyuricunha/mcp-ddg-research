import pytest

from mcp_ddg_research.security import UnsafeUrlError, validate_url_shape
from mcp_ddg_research.text import extract_html_text


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://192.168.1.1",
        "http://metadata.google.internal",
    ],
)
def test_private_url_blocker_rejects_internal_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url_shape(url)


def test_private_url_blocker_rejects_non_http_schemes() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url_shape("file:///etc/passwd")


def test_html_extraction_removes_script_style_nav_and_footer() -> None:
    html = """
    <html>
      <head>
        <title>Example Page</title>
        <style>.hidden { display: none; }</style>
        <script>window.secret = "do-not-include";</script>
      </head>
      <body>
        <nav>Navigation should be removed</nav>
        <main>
          <article class="article-content">
            This is the readable article body.
          </article>
        </main>
        <footer>Footer should be removed</footer>
      </body>
    </html>
    """

    extracted = extract_html_text(html, max_chars=5000)

    assert extracted.title == "Example Page"
    assert "This is the readable article body." in extracted.content
    assert "do-not-include" not in extracted.content
    assert "Navigation should be removed" not in extracted.content
    assert "Footer should be removed" not in extracted.content
