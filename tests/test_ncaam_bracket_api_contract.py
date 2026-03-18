import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)

@pytest.fixture
def mock_bracket_service():
    with patch("src.api_extensions.ncaam_bracket_api.NCAAMBracketStateService") as mock:
        yield mock


def _mock_payload():
    return {
        "season": "2025-26",
        "regions": {
            "East": {
                "round_of_64": [
                    {
                        "team_a": "Duke Blue Devils",
                        "team_b": "Siena Saints",
                        "display_winner": "Duke Blue Devils",
                        "status": "final",
                        "winner_source": "final",
                        "predicted_winner": "Siena Saints",
                        "predicted_win_prob_a": 85.0,
                        "predicted_win_prob_b": 15.0,
                        "projection_source": "model:tournament_ensemble_v1",
                        "actual_score_a": 78,
                        "actual_score_b": 71
                    }
                ]
            }
        },
        "first_four": [],
        "final_four": [],
        "championship": None,
        "title_odds": {"Duke Blue Devils": 28.7},
        "round_advancement_probs": [],
        "seed_metadata": {
            "source": "manual_bracket_data",
            "note": "Manual entry"
        },
        "v": "6-actual-first"
    }


def test_bracket_api_actual_first_payload(mock_bracket_service):
    payload = _mock_payload()
    _instance = mock_bracket_service.return_value
    _instance.build_bracket_payload.return_value = payload

    with patch("src.api.settings.BASEMENT_PASSWORD", "test"):
        res = client.get("/api/ncaam/bracket/2026?refresh=true", headers={"X-BASEMENT-KEY": "test"})

    assert res.status_code == 200
    data = res.json()
    assert data["v"] == "6-actual-first"
    assert data["regions"]["East"]["round_of_64"][0]["winner_source"] == "final"
    assert data["regions"]["East"]["round_of_64"][0]["display_winner"] == "Duke Blue Devils"
    assert data["seed_metadata"]["source"] == "manual_bracket_data"
    assert data["title_odds"]["Duke Blue Devils"] == 28.7

def test_bracket_api_uses_db_cache_when_fresh(mock_bracket_service):
    payload = _mock_payload()
    cache_timestamp = datetime.now(timezone.utc)

    with patch("src.api_extensions.ncaam_bracket_api._get_db_cache") as mock_cache:
        mock_cache.return_value = {"data": payload, "updated_at": cache_timestamp}
        with patch("src.api.settings.BASEMENT_PASSWORD", "test"):
            res = client.get("/api/ncaam/bracket/2026", headers={"X-BASEMENT-KEY": "test"})

    assert res.status_code == 200
    assert res.json() == payload
    mock_bracket_service.assert_not_called()
