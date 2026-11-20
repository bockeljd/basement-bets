import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


def test_moneyline_symmetry_across_probability_grid(monkeypatch):
    model = object.__new__(NCAAMMarketFirstModelV2)
    monkeypatch.setattr(model, "_calibrate_win_prob", lambda p, **kw: .06 + .8*p)
    last = 0
    for i in range(101):
        raw = i / 100
        home, away = model._moneyline_probabilities(raw, True)
        assert home + away == pytest.approx(1)
        assert away == pytest.approx(model._moneyline_probabilities(1-raw, True)[0])
        assert last <= home <= 1
        last = home
    assert model._moneyline_probabilities(.5, True) == (.5, .5)


@pytest.mark.parametrize("market,side,line", [
    ("SPREAD","home",-7), ("SPREAD","away",7), ("SPREAD","home",-7.5),
    ("TOTAL","over",150), ("TOTAL","under",150.5),
])
def test_fair_line_point_inside_confidence_interval(monkeypatch, market, side, line):
    model = object.__new__(NCAAMMarketFirstModelV2)
    monkeypatch.setattr(model, "_tau_for_market", lambda *args, **kwargs: 1e-6)
    monkeypatch.setattr(model, "_calibrate_win_prob", lambda p, **kw: p)
    bounds = model._confidence_bounds_from_mu_uncertainty(market,line,10,line,side)
    assert bounds["lb10"] <= .5 <= bounds["ub90"]
    assert bounds["ub90"] - bounds["lb10"] < 1e-6


def test_calibration_holdout_uses_later_dates_and_separate_markets(monkeypatch):
    from contextlib import nullcontext
    from datetime import date, datetime, timedelta, timezone
    from unittest.mock import Mock
    from scripts import build_winprob_calibration_ncaam as builder

    rows = []
    for i in range(300):
        rows.append({"date_et": (date(2025,11,1) + timedelta(days=i//10)).isoformat(),
                     "market_type": "SPREAD", "snapshot": {"win_prob": .54, "raw_win_prob": .55,
                     "opposite_price": -110}, "bet_price": -110, "outcome": "WON" if i%2 else "LOST"})
    rows.append({**rows[0], "market_type": "TOTAL"})
    monkeypatch.setattr(builder, "get_db_connection", lambda: nullcontext(None))
    monkeypatch.setattr(builder, "_exec", lambda *args: Mock(fetchall=lambda: rows))
    report = builder.evaluate_ncaam_candidates(90, datetime.now(timezone.utc), None, 75)
    assert report["SPREAD"]["train"] == 240
    assert report["SPREAD"]["holdout"] == 60
    assert report["SPREAD"]["scores"]["market"]["brier"] == .25
    assert "scores" not in report["TOTAL"]
