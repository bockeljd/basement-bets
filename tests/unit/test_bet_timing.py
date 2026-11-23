import json
from datetime import datetime, timedelta, timezone

from src.utils.bet_timing import (
    compute_bet_timing,
    extract_bet_timing_action,
    load_timing_thresholds,
    summarize_timing_clv,
)
from src.utils.model_performance import normalize_history_row


NOW = datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)


def _tip_in(minutes: float) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


def test_compute_bet_timing_returns_none_for_invalid_or_tipped():
    assert compute_bet_timing(None, now_utc=NOW) is None
    assert compute_bet_timing({"bet_type": "TOTAL"}, start_time=_tip_in(0), now_utc=NOW) is None
    assert compute_bet_timing({"bet_type": "TOTAL"}, start_time=_tip_in(-15), now_utc=NOW) is None


def test_rule1_tipoff_imminent_overrides_injury_and_public():
    rec = {
        "bet_type": "TOTAL",
        "selection": "UNDER 154.5",
        "side": "under",
        "book": "DraftKings",
        "sharp_edge_pts": 1.5,
        "signals": {
            "injuries": [{"player": "Jayden Pierre", "status": "Questionable"}],
            "public_splits": {"TOTAL": {"OVER": {"bet_pct": 74}, "UNDER": {"bet_pct": 26}}},
        },
    }
    res = compute_bet_timing(rec, start_time=_tip_in(40), now_utc=NOW)
    assert res is not None
    assert res["action"] == "BET_NOW"
    assert res["tone"] == "emerald"
    assert "tipoff_imminent" in res["drivers"]
    assert "1.5 pts" in res["reason"]


def test_rule2_uncertain_injury_triggers_wait_while_confirmed_out_does_not():
    rec_q = {
        "bet_type": "SPREAD",
        "selection": "Duke -4.5",
        "side": "home",
        "sharp_edge_pts": 1.0,
        "signals": {
            "injuries": [{"player": "Caleb Foster", "status": "Questionable"}],
        },
    }
    wait_res = compute_bet_timing(rec_q, start_time=_tip_in(180), now_utc=NOW)
    assert wait_res["action"] == "WAIT_LINEUPS"
    assert wait_res["tone"] == "amber"
    assert "Caleb Foster" in wait_res["reason"]

    rec_out = {
        "bet_type": "SPREAD",
        "selection": "Duke -4.5",
        "side": "home",
        "sharp_edge_pts": 1.0,
        "signals": {
            "injuries": [{"player": "Bench Guard", "status": "Out"}],
        },
    }
    now_res = compute_bet_timing(rec_out, start_time=_tip_in(180), now_utc=NOW)
    assert now_res["action"] == "BET_NOW"
    assert "sharp_price_edge" in now_res["drivers"]


def test_rule3_sharp_edge_and_steam_trigger_bet_now():
    vcu_like = {
        "bet_type": "TOTAL",
        "selection": "UNDER 154.5",
        "side": "under",
        "book": "DraftKings",
        "sharp_edge_pts": 1.5,
        "movement_tags": ["sharp_price_edge"],
    }
    res = compute_bet_timing(vcu_like, start_time=_tip_in(180), now_utc=NOW)
    assert res["action"] == "BET_NOW"
    assert "DraftKings" in res["reason"]
    assert "1.5 pts" in res["reason"]

    rlm_rec = {
        "bet_type": "SPREAD",
        "selection": "Providence +3.5",
        "side": "home",
        "movement_tags": ["rlm_confirmed"],
    }
    rlm_res = compute_bet_timing(rlm_rec, start_time=_tip_in(220), now_utc=NOW)
    assert rlm_res["action"] == "BET_NOW"
    assert "rlm_confirmed" in rlm_res["drivers"]


def test_rule4_opposite_public_tickets_triggers_monitor():
    rec = {
        "bet_type": "SPREAD",
        "selection": "Seton Hall +6.5",
        "home_team": "Villanova",
        "away_team": "Seton Hall",
        "signals": {
            "public_splits": {
                "SPREAD": {
                    "HOME": {"bet_pct": 72},
                    "AWAY": {"bet_pct": 28},
                }
            }
        },
    }
    res = compute_bet_timing(rec, start_time=_tip_in(150), home_team="Villanova", away_team="Seton Hall", now_utc=NOW)
    assert res["action"] == "MONITOR"
    assert res["tone"] == "blue"
    assert "72%" in res["reason"]


def test_rule5_early_1h_and_smart_risk_trigger_monitor():
    h1_rec = {"bet_type": "TOTAL_1H", "selection": "1H OVER 66.5", "side": "over"}
    res_1h = compute_bet_timing(h1_rec, start_time=_tip_in(240), now_utc=NOW)
    assert res_1h["action"] == "MONITOR"
    assert "early_1h_market" in res_1h["drivers"]

    sr_rec = {"bet_type": "MONEYLINE", "selection": "Penn +145", "is_smart_risk": True, "risk_tier": "SMART_RISK"}
    res_sr = compute_bet_timing(sr_rec, start_time=_tip_in(240), now_utc=NOW)
    assert res_sr["action"] == "MONITOR"
    assert "early_smart_risk" in res_sr["drivers"]


def test_rule6_our_public_conviction_and_strong_ev_trigger_bet_now():
    conv_rec = {"bet_type": "TOTAL", "selection": "UNDER 144.5", "side": "under", "conviction_sources_total": 3, "ev": 0.045}
    res_conv = compute_bet_timing(conv_rec, start_time=_tip_in(300), now_utc=NOW)
    assert res_conv["action"] == "BET_NOW"
    assert "high_conviction" in res_conv["drivers"]

    ev_rec = {"bet_type": "SPREAD", "selection": "Temple +3.5", "side": "away", "ev": 0.068}
    res_ev = compute_bet_timing(ev_rec, start_time=_tip_in(300), now_utc=NOW)
    assert res_ev["action"] == "BET_NOW"
    assert "strong_ev" in res_ev["drivers"]


def test_rule7_default_early_vs_midday_and_calibration_file(tmp_path):
    plain_rec = {"bet_type": "SPREAD", "selection": "Yale -2.5", "side": "home", "ev": 0.042}
    early = compute_bet_timing(plain_rec, start_time=_tip_in(300), now_utc=NOW)
    mid = compute_bet_timing(plain_rec, start_time=_tip_in(150), now_utc=NOW)
    assert early["action"] == "MONITOR"
    assert "early_no_rush" in early["drivers"]
    assert mid["action"] == "BET_NOW"
    assert "clean_number" in mid["drivers"]

    cal_file = tmp_path / "bet_timing_calibration.json"
    cal_file.write_text(json.dumps({"thresholds": {"early_default_mins_to_tip": 120}}), encoding="utf-8")
    loaded = load_timing_thresholds(str(cal_file))
    assert loaded["early_default_mins_to_tip"] == 120.0
    tuned = compute_bet_timing(plain_rec, start_time=_tip_in(150), now_utc=NOW, thresholds=loaded)
    assert tuned["action"] == "MONITOR"


def test_extract_normalize_and_summarize_timing_clv():
    row_bet_now = normalize_history_row({
        "event_id": "ncaam:1",
        "market_type": "TOTAL",
        "selection": "UNDER 154.5",
        "outcome": "WON",
        "clv_points": 1.5,
        "bet_timing": {"action": "BET_NOW", "label": "Bet Now"},
    })
    assert row_bet_now["bet_timing_action"] == "BET_NOW"

    row_monitor = {
        "outcome": "LOST",
        "clv_points": -0.5,
        "rec_json": {"bet_timing": {"action": "MONITOR"}},
    }
    assert extract_bet_timing_action(row_monitor) == "MONITOR"

    summary = summarize_timing_clv([row_bet_now, row_monitor, {"outcome": "PENDING", "bet_timing_action": "BET_NOW"}])
    by_act = {b["action"]: b for b in summary}
    assert by_act["BET_NOW"]["count"] == 1
    assert by_act["BET_NOW"]["wins"] == 1
    assert by_act["BET_NOW"]["avg_clv"] == 1.5
    assert by_act["BET_NOW"]["positive_clv_rate"] == 100.0
    assert by_act["MONITOR"]["count"] == 1
    assert by_act["MONITOR"]["losses"] == 1
    assert by_act["MONITOR"]["avg_clv"] == -0.5
    assert by_act["WAIT_LINEUPS"]["count"] == 0
