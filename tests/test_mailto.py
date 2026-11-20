"""R4: RFC 6068 mailto parsing for participant emails."""

import pytest

from macos_calendar_events._mapping import parse_mailto


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("mailto:a@example.com", "a@example.com"),
        ("MAILTO:a@example.com", "a@example.com"),
        ("mailto:a%40example.com", "a@example.com"),
        ("mailto:a@example.com?subject=x", "a@example.com"),
        ("mailto:", None),
        ("mailto:a@example.com,b@example.com", "a@example.com"),
        ("mailto:?to=a@example.com", "a@example.com"),
        ("mailto:a%2Cb@example.com", "a,b@example.com"),  # split before decoding
        ("mailto:%20a@example.com%20", "a@example.com"),
        ("mailto:?TO=a@example.com", "a@example.com"),
        ("mailto:a+b@example.com", "a+b@example.com"),
        ("mailto:?subject=x", None),
        ("mailto:?subject=x&to=b@example.com,c@example.com", "b@example.com"),
        ("mailto:%20", None),
    ],
)
def test_parse_mailto(url: str, expected: str | None) -> None:
    assert parse_mailto(url) == expected


@pytest.mark.parametrize("url", ["https://example.com/u/1", "urn:uuid:1234", "a@example.com"])
def test_non_mailto_urls_have_no_email(url: str) -> None:
    assert parse_mailto(url) is None
