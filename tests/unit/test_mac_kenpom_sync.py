"""Unit tests for Mac local KenPom full-bundle sync script."""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("REQUIRE_DATABASE", "0")

from scripts import mac_kenpom_daily_sync as kp_sync


def test_html_table_to_tsv_extracts_ratings_table_and_limits_rows():
    html = """
    <html><body>
      <table><tr><td>Nav</td></tr></table>
      <table id="ratings-table">
        <thead><tr><th>Rk</th><th>Team</th><th>AdjEM</th></tr></thead>
        <tbody>
          <tr><td>1</td><td>Duke</td><td>+31.2</td></tr>
          <tr><td>2</td><td>Houston</td><td>+29.8</td></tr>
          <tr><td>3</td><td>Auburn</td><td>+28.4</td></tr>
        </tbody>
      </table>
    </body></html>
    """
    tsv = kp_sync._html_table_to_tsv(html, max_rows=2)
    lines = tsv.splitlines()
    assert lines[0] == "Rk\tTeam\tAdjEM"
    assert len(lines) == 3
    assert "Duke\t+31.2" in lines[1]
    assert "Auburn" not in tsv


def test_build_kenpom_bundle_from_session_collects_all_endpoints():
    table_html = (
        "<table id='ratings-table'>"
        "<thead><tr><th>Rk</th><th>Team</th><th>AdjEM</th></tr></thead><tbody>"
        + "".join(f"<tr><td>{i}</td><td>Team {i}</td><td>+10.0</td></tr>" for i in range(1, 13))
        + "</tbody></table>"
    )
    sess = MagicMock()
    with patch.object(kp_sync, "fetch_html", return_value=table_html) as mock_fetch:
        bundle = kp_sync.build_kenpom_bundle_from_session(sess, sleep_s=0.0)

    assert bundle["_kp_bundle"] == 1
    expected_keys = {"ratings", "stats", "height", "hca", "playerstats", "refs", "fanmatch"}
    assert expected_keys.issubset(bundle.keys())
    assert all(len(str(bundle[k]).splitlines()) >= 11 for k in expected_keys)
    assert mock_fetch.call_count == 7


def test_upload_bundle_to_api_posts_payload_and_handles_403():
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"status": "ok", "teams": 364}
    with patch.object(kp_sync.requests, "post", return_value=ok_resp) as mock_post:
        res = kp_sync.upload_bundle_to_api('{"_kp_bundle":1}', app_url="https://example.app/", basement_password="secret")
    assert res == {"status": "ok", "teams": 364}
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-BASEMENT-KEY"] == "secret"
    assert json.loads(kwargs["json"]["csv_text"]) == {"_kp_bundle": 1}

    forbidden = MagicMock()
    forbidden.status_code = 403
    with patch.object(kp_sync.requests, "post", return_value=forbidden):
        with pytest.raises(RuntimeError, match="403 Forbidden"):
            kp_sync.upload_bundle_to_api('{"_kp_bundle":1}', app_url="https://example.app")


def test_run_mac_sync_dry_run_and_short_table_error():
    small_bundle = {"_kp_bundle": 1, "ratings": "Rk\tTeam\n1\tDuke"}
    with patch.object(kp_sync, "_session", return_value=MagicMock()), patch.object(
        kp_sync, "build_kenpom_bundle_from_session", return_value=small_bundle
    ):
        with pytest.raises(RuntimeError, match="Could not fetch KenPom ratings table"):
            kp_sync.run_mac_sync(dry_run=True)

    full_ratings = "Rk\tTeam\n" + "\n".join(f"{i}\tTeam {i}" for i in range(1, 20))
    ok_bundle = {
        "_kp_bundle": 1,
        "ratings": full_ratings,
        "stats": "",
        "height": "",
        "hca": "",
        "playerstats": "",
        "refs": "",
        "fanmatch": "",
    }
    with patch.object(kp_sync, "_session", return_value=MagicMock()), patch.object(
        kp_sync, "build_kenpom_bundle_from_session", return_value=ok_bundle
    ):
        res = kp_sync.run_mac_sync(dry_run=True)
    assert res["status"] == "dry_run"
    assert res["summary"]["ratings"] == 20


def test_mac_sync_cli_check_without_database_url():
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL", "REQUIRE_DATABASE")}
    proc = subprocess.run(
        [sys.executable, "scripts/mac_kenpom_daily_sync.py", "--check"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["has_cloudscraper"] is True
    assert "app_url" in payload


def test_kenpom_login_posts_to_handlers_login_handler_with_submit():
    from src.scripts import ingest_kenpom

    homepage_html = """
    <html><body>
      <form id="login" action="handlers/login_handler.php" method="post">
        <input type="email" name="email" />
        <input type="password" name="password" />
        <input type="submit" name="submit" value="Login!" />
        <input type="checkbox" name="remember" />
      </form>
    </body></html>
    """
    logged_in_html = '<html><body><a href="/handlers/logout_handler.php">Logout</a></body></html>'

    get_resp = MagicMock(status_code=200, url="https://kenpom.com/", text=homepage_html)
    post_resp = MagicMock(status_code=200, url="https://kenpom.com/", text=logged_in_html)

    sess = MagicMock()
    sess.cookies = {"PHPSESSID": "abc123"}
    sess.get.return_value = get_resp
    sess.post.return_value = post_resp

    with patch.object(ingest_kenpom.time, "sleep"):
        ok = ingest_kenpom._login_with_credentials(sess, "user@example.com", "secret-pw")

    assert ok is True
    post_url, kwargs = sess.post.call_args[0][0], sess.post.call_args[1]
    assert post_url == "https://kenpom.com/handlers/login_handler.php"
    assert kwargs["data"]["email"] == "user@example.com"
    assert kwargs["data"]["password"] == "secret-pw"
    assert kwargs["data"]["submit"] == "Login!"
    assert kwargs["data"]["remember"] == "1"

    # Success when handlers/login_handler.php renders HTTP 200 meta/JS redirect with PHPSESSID set
    meta_resp = MagicMock(
        status_code=200,
        url="https://kenpom.com/handlers/login_handler.php",
        text='<html><head><meta http-equiv="refresh" content="0;url=/"></head></html>',
    )
    sess.post.return_value = meta_resp
    with patch.object(ingest_kenpom.time, "sleep"):
        assert ingest_kenpom._login_with_credentials(sess, "user@example.com", "secret-pw") is True

    # Failed login (still has login form, no logout link) returns False even with status 200
    fail_resp = MagicMock(status_code=200, url="https://kenpom.com/user.php", text=homepage_html)
    sess.post.return_value = fail_resp
    with patch.object(ingest_kenpom.time, "sleep"):
        ok_fail = ingest_kenpom._login_with_credentials(sess, "user@example.com", "bad-pw")
    assert ok_fail is False


def test_build_kenpom_bundle_stops_fallback_on_429_or_login_gate():
    sess = MagicMock()
    calls = []

    def fake_fetch(s, path):
        calls.append(path)
        if path == "/":
            return "<table id='ratings-table'><thead><tr><th>Rk</th><th>Team</th></tr></thead><tbody>" + "".join(
                f"<tr><td>{i}</td><td>T{i}</td></tr>" for i in range(1, 13)
            ) + "</tbody></table>"
        if path == "/hca.php":
            raise RuntimeError("429 Client Error: Too Many Requests")
        return '<html><form id="login"></form><a href="register-kenpom.php">Register</a></html>'

    with patch.object(kp_sync, "fetch_html", side_effect=fake_fetch):
        bundle = kp_sync.build_kenpom_bundle_from_session(sess, sleep_s=0.0)

    assert len(bundle["ratings"].splitlines()) == 13
    assert "/home.php" not in calls
    assert "/refs.php" not in calls
    assert bundle["hca"] == ""
    assert bundle["refs"] == ""


def test_parse_kenpom_refs_handles_live_officials_tsv_format():
    from src.scripts.ingest_kenpom import parse_kenpom_refs_text

    tsv = (
        "\tName FAA\tRating\tGms\tLast Game\tLast Game Rank\tLast Game Rank\n"
        "\tName FAA\tRating\tGms\tLast Game\n"
        "1\tPaul Szelc\t9.66\t9\tFri 11/13\t10 Virginia 87, 62 Maryland 83\tbox · win prob\n"
        "2\tTony Padilla\t8.65\t11\tFri 11/13\t12 Arizona 80, 21 Auburn 69\tbox · win prob\n"
    )
    parsed = parse_kenpom_refs_text(tsv)
    assert [r["ref_name"] for r in parsed] == ["Paul Szelc", "Tony Padilla"]

    # Also verify copy-pasted variant where leading tab was trimmed
    trimmed = "\n".join(line.lstrip("\t") for line in tsv.splitlines())
    parsed_trimmed = parse_kenpom_refs_text(trimmed)
    assert [r["ref_name"] for r in parsed_trimmed] == ["Paul Szelc", "Tony Padilla"]
