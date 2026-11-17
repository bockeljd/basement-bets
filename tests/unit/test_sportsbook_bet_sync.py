from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("REQUIRE_DATABASE", "0")

from src.api import app
from src.config import settings
from src.api_clients.fanduel_client import FanDuelAPIClient
from src.parsers.statement_csv import parse_sportsbook_statement_csv
from src.services.bet_sync_service import (
    compute_actuals_model_reconciliation,
    ingest_browser_payload,
    ingest_normalized_bets,
)
from scripts.install_mac_sync_agent import build_launchd_plist


def test_fanduel_client_open_settled_and_cashout():
    open_resp = {
        "bets": [
            {
                "betId": "O/111/222",
                "placedDate": "2026-11-16T18:10:00.000Z",
                "currentSize": 25.0,
                "isSettled": False,
                "isInPlay": False,
                "betType": "SGL",
                "odds": {"american": -110},
                "legs": [
                    {
                        "parts": [
                            {
                                "selectionName": "Duke -3.5",
                                "eventMarketDescription": "Point Spread",
                                "eventDescription": "Duke @ North Carolina",
                                "competitionName": "NCAAB College Basketball",
                            }
                        ]
                    }
                ],
            }
        ]
    }
    settled_resp = {
        "bets": [
            {
                "betId": "O/111/222",  # Duplicate betId also in settled must dedupe cleanly
                "placedDate": "2026-11-16T18:10:00.000Z",
                "currentSize": 25.0,
                "payout": 47.73,
                "settledResult": "WIN",
                "isSettled": True,
                "betType": "SGL",
                "odds": {"american": -110},
                "legs": [
                    {
                        "parts": [
                            {
                                "selectionName": "Duke -3.5",
                                "eventMarketDescription": "Point Spread",
                                "eventDescription": "Duke @ North Carolina",
                                "competitionName": "NCAAB",
                            }
                        ]
                    }
                ],
            },
            {
                "betId": "O/333/444",
                "placedDate": "2026-11-15T20:00:00.000Z",
                "currentSize": 50.0,
                "payout": 32.0,
                "settledResult": "CASHOUT",
                "isSettled": True,
                "isInPlay": True,
                "betType": "SGL",
                "legs": [
                    {
                        "parts": [
                            {
                                "selectionName": "Over 148.5",
                                "eventMarketDescription": "Total Points",
                                "eventDescription": "Kansas @ Baylor",
                                "competitionName": "Men's College Basketball",
                                "decimalPrice": 1.91,
                            }
                        ]
                    }
                ],
            },
        ]
    }

    client = FanDuelAPIClient(auth_token="tok_abc")
    open_parsed = client._parse_api_response(open_resp, default_settled=False)
    assert len(open_parsed) == 1
    assert open_parsed[0]["status"] == "PENDING"
    assert open_parsed[0]["profit"] == 0.0
    assert open_parsed[0]["external_id"] == "O/111/222"
    assert open_parsed[0]["sport"] == "NCAAM"

    settled_parsed = client._parse_api_response(settled_resp, default_settled=True)
    assert len(settled_parsed) == 2
    assert settled_parsed[0]["status"] == "WON"
    assert settled_parsed[0]["profit"] == 22.73
    # Cashout below stake must record LOST with partial negative profit (-18.0)
    assert settled_parsed[1]["status"] == "LOST"
    assert settled_parsed[1]["profit"] == -18.0
    assert settled_parsed[1]["is_live"] is True
    assert settled_parsed[1]["odds"] == -110

    with patch.object(client, "fetch_bets", side_effect=[open_parsed, settled_parsed]):
        combined = client.fetch_all_recent_bets()
    assert len(combined) == 2
    assert {b["external_id"] for b in combined} == {"O/111/222", "O/333/444"}


def test_csv_statement_parser_bets_and_financials():
    dk_csv = "\n".join(
        [
            "Bet ID,Date Placed,Sport,Event,Bet Type,Selection,Odds,Stake,Payout,Status,Balance",
            "DK-9001,2026-11-15,NCAAM,Duke @ UNC,Spread,Duke -3.5,-105,$50.00,$97.62,WON,$450.25",
            "DK-9002,2026-11-16,NCAAM,Kansas @ Baylor,Total,Over 146.5,-110,$25.00,$0.00,OPEN,$425.25",
        ]
    )
    parsed_bets = parse_sportsbook_statement_csv(dk_csv, sportsbook="DraftKings", account_id="Main")
    assert parsed_bets["provider"] == "DraftKings"
    assert parsed_bets["closing_balance"] == 450.25 or parsed_bets["closing_balance"] == 425.25
    assert len(parsed_bets["bets"]) == 2
    assert parsed_bets["bets"][0]["external_id"] == "DK-9001"
    assert parsed_bets["bets"][0]["odds"] == -105
    assert parsed_bets["bets"][1]["status"] == "PENDING"

    fd_ledger_csv = "\n".join(
        [
            "Transaction ID,Date,Type,Description,Amount,Balance",
            "TX1,2026-11-14,Deposit,ACH Deposit,$500.00,$500.00",
            "TX2,2026-11-15,Wager Placed,O/99/1 Duke -3.5,-$50.00,$450.00",
            "TX3,2026-11-15,Wager Won,O/99/1 Duke -3.5,$95.45,$545.45",
            "TX4,2026-11-16,Withdrawal,PayPal Withdrawal,-$100.00,$445.45",
        ]
    )
    parsed_fd = parse_sportsbook_statement_csv(fd_ledger_csv, sportsbook="FanDuel", account_id="User2")
    assert parsed_fd["provider"] == "FanDuel"
    assert len(parsed_fd["transactions"]) == 2
    assert parsed_fd["transactions"][0]["type"] == "Deposit"
    assert parsed_fd["transactions"][0]["amount"] == 500.0
    assert parsed_fd["transactions"][1]["type"] == "Withdrawal"
    assert parsed_fd["transactions"][1]["amount"] == -100.0
    assert len(parsed_fd["bets"]) == 1
    assert parsed_fd["bets"][0]["status"] == "WON"
    assert parsed_fd["bets"][0]["profit"] == 45.45
    assert parsed_fd["closing_balance"] == 445.45


def test_ingest_normalized_bets_updates_existing_external_id():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = {"id": 777, "status": "PENDING", "profit": 0.0}
    mock_conn.execute.return_value = mock_cur

    with patch("src.database.get_db_connection") as mock_ctx, \
         patch("src.database._exec", return_value=mock_cur) as mock_exec, \
         patch("src.database._sync_transaction_for_bet") as mock_txn_sync, \
         patch("src.database.insert_bet_v2") as mock_ins_v2:
        mock_ctx.return_value.__enter__ = lambda s: mock_conn
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        res = ingest_normalized_bets(
            [
                {
                    "provider": "FanDuel",
                    "external_id": "O/111/222",
                    "date": "2026-11-16",
                    "sport": "NCAAM",
                    "bet_type": "Spread",
                    "wager": 50.0,
                    "profit": 45.45,
                    "status": "WON",
                    "description": "Duke @ North Carolina",
                    "selection": "Duke -3.5",
                    "odds": -110,
                }
            ],
            user_id="00000000-0000-0000-0000-000000000000",
        )

    assert res["updated"] == 1
    assert res["inserted"] == 0
    assert res["bet_ids"] == [777]
    mock_txn_sync.assert_called_once()
    mock_ins_v2.assert_not_called()
    assert mock_exec.call_count >= 2
    assert any("UPDATE bets SET" in str(c) for c in mock_exec.call_args_list)


def test_actuals_model_reconciliation_metrics():
    bets = [
        {
            "id": 1,
            "date": "2026-11-15",
            "provider": "FanDuel",
            "sport": "NCAAM",
            "bet_type": "Spread",
            "selection": "Duke -3.5",
            "description": "Duke @ UNC",
            "odds": -102,  # Better price than model -110!
            "wager": 100.0,
            "profit": 98.04,
            "status": "WON",
        },
        {
            "id": 2,
            "date": "2026-11-15",
            "provider": "DraftKings",
            "sport": "NCAAM",
            "bet_type": "Total",
            "selection": "Under 148.5",  # Opposite of model Over
            "description": "Kansas @ Baylor",
            "odds": -110,
            "wager": 50.0,
            "profit": -50.0,
            "status": "LOST",
        },
    ]
    predictions = [
        {
            "event_id": "evt1",
            "start_time": "2026-11-15T20:00:00Z",
            "sport": "NCAAM",
            "away_team": "Duke",
            "home_team": "UNC",
            "market_type": "SPREAD",
            "pick": "AWAY",
            "selection": "Duke -3.5",
            "bet_price": -110,
            "ev_per_unit": 0.055,
            "outcome": "WON",
        },
        {
            "event_id": "evt2",
            "start_time": "2026-11-15T21:00:00Z",
            "sport": "NCAAM",
            "away_team": "Kansas",
            "home_team": "Baylor",
            "market_type": "TOTAL",
            "pick": "OVER",
            "selection": "Over 148.5",
            "bet_price": -110,
            "ev_per_unit": 0.04,
            "outcome": "WON",
        },
    ]

    rec = compute_actuals_model_reconciliation(bets, predictions)
    s = rec["summary"]
    assert s["matched_to_model"] == 2
    assert s["aligned_count"] == 1
    assert s["faded_count"] == 1
    assert s["follow_rate_pct"] == 50.0
    assert s["actual_roi_pct"] == 98.0
    assert s["model_roi_on_same_picks_pct"] == 90.9
    assert s["avg_price_edge_vs_model_pct"] > 0  # -102 beats -110 implied probability


def test_api_sync_token_csv_browser_and_reconciliation_routes(monkeypatch):
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    headers = {"X-BASEMENT-KEY": "test-secret"}
    client = TestClient(app)

    # 1. Verify /api/sync/fanduel/token no longer hits NameError `user.get("sub")`
    with patch("src.database.update_user_preference"), \
         patch("src.api_clients.fanduel_client.FanDuelAPIClient.fetch_all_recent_bets", return_value=[
             {
                 "provider": "FanDuel",
                 "external_id": "O/888/999",
                 "date": "2026-11-16",
                 "sport": "NCAAM",
                 "bet_type": "Spread",
                 "wager": 20.0,
                 "profit": 0.0,
                 "status": "PENDING",
                 "description": "Duke @ UNC",
                 "selection": "Duke -3.5",
                 "odds": -110,
             }
         ]), \
         patch("src.services.bet_sync_service._upsert_bet_by_external_id_or_v2", return_value=(101, "inserted")):
        r1 = client.post(
            "/api/sync/fanduel/token",
            headers=headers,
            json={"curl_or_token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig", "account_id": "Primary"},
        )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["status"] == "success"
    assert b1["account_id"] == "Main"
    assert b1["bets_saved"] == 1

    # 2. Verify /api/sync/browser-payload
    with patch("src.services.bet_sync_service._upsert_bet_by_external_id_or_v2", return_value=(102, "inserted")), \
         patch("src.database.insert_balance_snapshot", return_value=True) as mock_snap:
        r2 = client.post(
            "/api/sync/browser-payload",
            headers=headers,
            json={
                "provider": "FanDuel",
                "account_id": "Main",
                "balance": 612.40,
                "api_bets": [
                    {
                        "external_id": "O/777/888",
                        "date": "2026-11-16",
                        "sport": "NCAAM",
                        "bet_type": "Total",
                        "wager": 30.0,
                        "status": "PENDING",
                        "description": "Kansas @ Baylor",
                        "selection": "Over 145.5",
                        "odds": -110,
                    }
                ],
            },
        )
    assert r2.status_code == 200
    assert r2.json()["bets_saved"] == 1
    assert r2.json()["balance_snapshot_saved"] is True
    mock_snap.assert_called_once()

    # 3. Verify /api/bets/import-csv (both multipart file upload and JSON csv_text without python-multipart)
    csv_bytes = (
        "Bet ID,Date Placed,Sport,Event,Bet Type,Selection,Odds,Stake,Payout,Status,Balance\n"
        "DK-500,2026-11-16,NCAAM,Duke @ UNC,Spread,Duke -3.5,-110,$40,$76.36,WON,$510.00\n"
    ).encode("utf-8")
    with patch("src.services.bet_sync_service._upsert_bet_by_external_id_or_v2", return_value=(103, "inserted")), \
         patch("src.database.insert_balance_snapshot", return_value=True):
        r3 = client.post(
            "/api/bets/import-csv",
            headers=headers,
            data={"sportsbook": "DraftKings", "account_id": "Main"},
            files={"file": ("dk_bets.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        r3_json = client.post(
            "/api/bets/import-csv",
            headers=headers,
            json={"csv_text": csv_bytes.decode("utf-8"), "sportsbook": "DraftKings", "account_id": "Main"},
        )
    assert r3.status_code == 200
    assert r3_json.status_code == 200
    b3 = r3.json()
    assert b3["provider"] == "DraftKings"
    assert b3["bets_saved"] == 1
    assert b3["closing_balance"] == 510.0
    assert r3_json.json()["bets_saved"] == 1

    # 4. Verify /api/actuals/model-reconciliation
    with patch("src.database.fetch_all_bets", return_value=[]), \
         patch("src.database.fetch_model_history", return_value=[]):
        r4 = client.get("/api/actuals/model-reconciliation", headers=headers)
    assert r4.status_code == 200
    assert r4.json()["summary"]["total_actual_bets"] == 0


def test_mac_sync_agent_plist_builder():
    plist = build_launchd_plist(
        repo_dir=Path("/tmp/repo"),
        python_bin=Path("/tmp/repo/venv/bin/python"),
        log_path=Path("/tmp/sync.log"),
        dk_profile_path=Path("/tmp/dk_prof"),
        sleep_seconds=30,
    )
    assert plist["Label"] == "com.basementbets.syncworker"
    assert "--loop" in plist["ProgramArguments"]
    assert plist["EnvironmentVariables"]["DK_PROFILE_PATH"] == "/tmp/dk_prof"


def test_dk_text_parser_rejects_false_won_tab_and_zero_payout():
    from src.parsers.draftkings_text import DraftKingsTextParser

    # Case 1: UI filter tabs ("All / Open / Settled / Won / Lost") captured above card + Paid: $0.00
    raw_with_tabs = """All
Open
Settled
Won
Lost
FLORIDA A&M +26.5
-125
Spread
FLORIDA A&M @ UTEP
LOST
Wager: $5.00
Paid: $0.00
Nov 16, 2026, 7:15:00 PM
DK638991234567890
"""
    parser = DraftKingsTextParser()
    bets = parser.parse(raw_with_tabs)
    assert len(bets) == 1
    b = bets[0]
    assert b["status"] == "LOST"
    assert b["profit"] == -5.0
    assert b["event_text"] == "FLORIDA A&M @ UTEP"

    # Case 2: Card with "Paid: $0.00" where "Won" appeared earlier -> Paid: $0.00 must win -> LOST (-$5.00)
    raw_paid_zero = """Won Boost Promo
FLORIDA A&M +26.5
-125
Spread
FLORIDA A&M @ UTEP
Wager: $5.00
Paid: $0.00
Nov 16, 2026, 7:15:00 PM
DK638991234567891
"""
    bets2 = parser.parse(raw_paid_zero)
    assert len(bets2) == 1
    assert bets2[0]["status"] == "LOST"
    assert bets2[0]["profit"] == -5.0


def test_extract_event_text_strips_market_odds_prefix():
    from src.database import _extract_event_text_from_fields

    ev = _extract_event_text_from_fields(
        "",
        "Spread -125: Florida A&M @ Utep",
        "FLORIDA A&M +26.5",
    )
    assert ev == "Florida A&M @ Utep"


def test_add_balance_snapshot_invalidates_analytics_cache(monkeypatch):
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    headers = {"X-BASEMENT-KEY": "test-secret"}
    client = TestClient(app)

    with patch("src.database.insert_balance_snapshot", return_value=True) as mock_snap, \
         patch("src.api.invalidate_analytics_cache") as mock_inv:
        resp = client.post(
            "/api/balances/snapshots",
            headers=headers,
            json={"provider": "DraftKings", "account_id": "Primary", "balance": 12.34},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    mock_snap.assert_called_once()
    mock_inv.assert_called_once()


def test_analytics_timezone_aware_snapshot_cutoff():
    from datetime import datetime, timezone
    from src.analytics import AnalyticsEngine

    # Snapshot captured at 20:00 UTC (15:00 -05:00 EST); bet created at 19:00 UTC (BEFORE snapshot!)
    # Without astimezone(utc), 15:00 EST naive would look <= 19:00 UTC and falsely double-count the bet.
    snaps = {
        "DraftKings": {
            "balance": 20.00,
            "captured_at": datetime.fromisoformat("2026-11-16T15:00:00-05:00"),
            "source": "manual",
            "accounts": {
                "Main": {
                    "balance": 20.00,
                    "captured_at": datetime.fromisoformat("2026-11-16T15:00:00-05:00"),
                    "source": "manual",
                }
            },
        }
    }
    bets = [
        {
            "id": 1,
            "user_id": "u1",
            "provider": "DraftKings",
            "account_id": "Main",
            "date": "2026-11-16",
            "status": "LOST",
            "wager": 5.0,
            "profit": -5.0,
            "created_at": datetime(2026, 11, 16, 19, 0, 0),  # 19:00 UTC == 14:00 EST -> BEFORE 15:00 EST snapshot!
        }
    ]
    with patch("src.analytics.fetch_all_bets", return_value=bets), \
         patch("src.database.fetch_latest_balance_snapshots", return_value=snaps), \
         patch("src.analytics.get_db_connection") as mock_conn, \
         patch("src.database.get_db_connection", new=mock_conn):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [{"provider": "DraftKings", "account_id": "Main", "date": "2026-11-14", "type": "Deposit", "description": "Deposit", "amount": 50.0, "balance": None}]
        mock_conn.return_value.__enter__.return_value.execute.return_value = mock_cur
        with patch("src.database._exec", return_value=mock_cur):
            eng = AnalyticsEngine(user_id="u1")
            fin = eng.get_financial_summary(user_id="u1")

    dk_main = [r for r in fin["breakdown"] if r["provider"] == "DraftKings" and r["account_id"] == "Main"][0]
    assert dk_main["ledger_delta"] == 0.0
    assert dk_main["ledger_in_play"] == 20.00

