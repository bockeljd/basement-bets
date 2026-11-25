import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


def test_moneyline_symmetry_across_probability_grid(monkeypatch):
    model = object.__new__(NCAAMMarketFirstModelV2)
    monkeypatch.setattr(model, "_calibrate_win_prob", lambda p, **kw: .06 + .8*p)
    last = 0
    for i in range(101):
        raw = i / 100
        home, away = model._binary_probabilities(raw, True)
        assert home + away == pytest.approx(1)
        assert away == pytest.approx(model._binary_probabilities(1-raw, True)[0])
        assert last <= home <= 1
        last = home
    assert model._binary_probabilities(.5, True) == (.5, .5)


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


def test_executable_moneyline_requires_recent_named_price():
    from datetime import datetime, timedelta, timezone
    from src.utils.ncaam_quotes import executable_moneyline_quote

    now = datetime.now(timezone.utc)
    quote = {"book": "FanDuel", "price": 110, "captured_at": now}
    assert executable_moneyline_quote(quote, now)
    for change in ({"book": "consensus"}, {"price": -99}, {"captured_at": now-timedelta(minutes=91)}):
        assert not executable_moneyline_quote({**quote, **change}, now)


def test_opposite_total_bounds_are_complementary_at_same_line(monkeypatch):
    model = object.__new__(NCAAMMarketFirstModelV2)
    monkeypatch.setattr(model, "_tau_for_market", lambda *args, **kw: 1.2)
    monkeypatch.setattr(model, "_calibrate_win_prob", lambda p, **kw: .04+.8*p)
    bounds = [model._confidence_bounds_from_mu_uncertainty("TOTAL", 147, 13, 145, side)
              for side in ("over", "under")]
    assert bounds[0]["lb10"] + bounds[1]["ub90"] == pytest.approx(1)


@pytest.mark.parametrize("book", ["LowVig", "Pinnacle", "BetOnlineAG", "Circa Sports"])
def test_benchmark_prices_cannot_become_retail_recommendations(book):
    from datetime import datetime, timezone
    from src.utils.ncaam_quotes import executable_moneyline_quote, recent_retail_quote

    now = datetime.now(timezone.utc)
    quote = {"book": book, "price": -110, "captured_at": now}
    assert not recent_retail_quote(quote, now)
    assert not executable_moneyline_quote(quote, now)
