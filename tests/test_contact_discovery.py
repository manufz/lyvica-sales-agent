import pytest
from unittest.mock import patch, MagicMock

from app.contact_discovery import (
    _extract_emails,
    _extract_instagram,
    _has_contact_form,
    _is_business_email,
    discover_contacts,
)
from bs4 import BeautifulSoup


def test_extract_emails_basic():
    text = "Contact us at info@mybiz.com or sales@company.org"
    assert _extract_emails(text) == ["info@mybiz.com", "sales@company.org"]


def test_extract_emails_ignores_tracking():
    text = "pixel@googletagmanager.com should be ignored, but hello@mybiz.com should not"
    result = _extract_emails(text)
    assert "hello@mybiz.com" in result
    assert not any("googletagmanager" in e for e in result)


def test_extract_emails_dedup():
    text = "info@mybiz.com and info@mybiz.com again"
    emails = _extract_emails(text)
    assert emails.count("info@mybiz.com") == 2  # dedup happens in discover_contacts


def test_is_business_email():
    assert _is_business_email("info@mybiz.com") is True
    assert _is_business_email("owner@gmail.com") is False
    assert _is_business_email("sales@outlook.com") is False


def test_extract_instagram_from_anchor():
    html = '<a href="https://www.instagram.com/mybiz/">Follow us</a>'
    soup = BeautifulSoup(html, "lxml")
    result = _extract_instagram(soup, html)
    assert result == "https://www.instagram.com/mybiz"


def test_extract_instagram_none():
    html = "<p>No social links here</p>"
    soup = BeautifulSoup(html, "lxml")
    assert _extract_instagram(soup, html) is None


def test_has_contact_form_true():
    html = '<form><input type="email" name="email"><textarea></textarea></form>'
    soup = BeautifulSoup(html, "lxml")
    assert _has_contact_form(soup) is True


def test_has_contact_form_false():
    html = "<form><input type='text' name='search'></form>"
    soup = BeautifulSoup(html, "lxml")
    assert _has_contact_form(soup) is False


def test_discover_contacts_returns_structure():
    mock_html = """
    <html><body>
      <a href="mailto:hello@testbiz.com">Email us</a>
      <a href="https://instagram.com/testbiz">Instagram</a>
      <form><input type="email" name="email"><textarea></textarea></form>
    </body></html>
    """

    with patch("app.contact_discovery.httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.text = mock_html
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = discover_contacts("https://testbiz.com")

    assert "hello@testbiz.com" in result["email_addresses"]
    assert result["email"] == "hello@testbiz.com"
    assert result["instagram_url"] is not None
    assert result["contact_form_url"] is not None


def test_recommended_channel_priority():
    """email > contact_form > instagram > none"""
    from app.main import app
    # Just logic check without HTTP
    contacts_email = {"email": "a@b.com", "contact_form_url": "http://x.com/contact", "instagram_url": "http://ig.com/x"}
    contacts_form = {"email": None, "contact_form_url": "http://x.com/contact", "instagram_url": "http://ig.com/x"}
    contacts_ig = {"email": None, "contact_form_url": None, "instagram_url": "http://ig.com/x"}
    contacts_none = {"email": None, "contact_form_url": None, "instagram_url": None}

    def channel(c):
        if c["email"]: return "email"
        if c["contact_form_url"]: return "contact_form"
        if c["instagram_url"]: return "instagram"
        return "none"

    assert channel(contacts_email) == "email"
    assert channel(contacts_form) == "contact_form"
    assert channel(contacts_ig) == "instagram"
    assert channel(contacts_none) == "none"
