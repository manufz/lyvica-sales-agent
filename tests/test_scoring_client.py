from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.scoring_client import score_domain


def test_score_domain_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "score": 72,
        "tier": "high",
        "confidence": 0.85,
        "subscores": {"mobile": 60},
        "pitch_angles": [{"issue": "slow mobile load"}],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.scoring_client.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_cls.return_value = mock_client

        result = score_domain("example.com", "Example Co", "Vienna", "dentist")

    assert result["score"] == 72
    assert result["tier"] == "high"
    assert len(result["pitch_angles"]) == 1


def test_score_domain_unavailable():
    with patch("app.scoring_client.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("Connection refused")
        mock_cls.return_value = mock_client

        result = score_domain("example.com")

    assert result["score"] is None
    assert result["tier"] == "unknown"
    assert "error" in result


def test_score_domain_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("app.scoring_client.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )
        mock_cls.return_value = mock_client

        result = score_domain("example.com")

    assert result["tier"] == "unknown"
    assert "error" in result


def test_stripe_buying_intent_guard():
    """Stripe endpoint must reject buying_intent=false."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings

    client = TestClient(app)
    resp = client.post(
        "/stripe/checkout-link",
        json={"lead_id": "00000000-0000-0000-0000-000000000000", "package": "starter", "buying_intent": False},
        headers={"x-hermes-secret": settings.HERMES_SHARED_SECRET},
    )
    assert resp.status_code == 400
    assert "buying_intent" in resp.text
