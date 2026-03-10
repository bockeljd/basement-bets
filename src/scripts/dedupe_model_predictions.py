"""One-time cleanup: dedupe model_predictions and backfill prediction_key.

Why:
- repeated reruns inserted the same prediction many times
- model performance series uses model_predictions; duplicates inflate metrics

Safe behavior:
- keeps the most recent analyzed_at per (user/event/model/market/pick/line/price/book)
- deletes older duplicates
- sets prediction_key deterministically for remaining rows

Run:
  python -m src.scripts.dedupe_model_predictions
"""

from __future__ import annotations

import hashlib

from src.database import get_db_connection, _exec


def compute_key(row: dict) -> str:
    parts = [
        str(row.get('user_id') or ''),
        str(row.get('event_id') or ''),
        str(row.get('model_version') or 'v1'),
        str(row.get('market_type') or ''),
        str(row.get('pick') or ''),
        str(row.get('bet_line') if row.get('bet_line') is not None else ''),
        str(row.get('bet_price') if row.get('bet_price') is not None else ''),
        str(row.get('book') or ''),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


def main(limit_groups: int | None = None) -> dict:
    # 1) Delete duplicates (keep newest)
    # Use COALESCE to make NULLs comparable.
    delete_sql = """
    WITH ranked AS (
      SELECT
        id,
        ROW_NUMBER() OVER (
          PARTITION BY
            COALESCE(user_id,''),
            event_id,
            COALESCE(model_version,''),
            COALESCE(market_type,''),
            COALESCE(pick,''),
            COALESCE(bet_line, -999999),
            COALESCE(bet_price, -999999),
            COALESCE(book,'')
          ORDER BY analyzed_at DESC NULLS LAST, id DESC
        ) AS rn
      FROM model_predictions
    )
    DELETE FROM model_predictions
    WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
      AND id NOT IN (
          SELECT prediction_id FROM recommended_slate_items WHERE prediction_id IS NOT NULL
      )
    """

    # 2) Backfill prediction_key for any remaining NULL/blank
    fetch_sql = """
    SELECT id, user_id, event_id, model_version, market_type, pick, bet_line, bet_price, book, prediction_key
    FROM model_predictions
    WHERE prediction_key IS NULL OR TRIM(prediction_key) = ''
    ORDER BY analyzed_at DESC NULLS LAST
    """

    upd_sql = """
    UPDATE model_predictions
    SET prediction_key = %s
    WHERE id = %s
    """

    deleted = 0
    backfilled = 0
    with get_db_connection() as conn:
        cur = _exec(conn, delete_sql)
        try:
            deleted = cur.rowcount or 0
        except Exception:
            deleted = 0
        conn.commit()

    with get_db_connection() as conn:
        rows = _exec(conn, fetch_sql).fetchall()
        for r in rows:
            d = dict(r)
            pk = compute_key(d)
            _exec(conn, upd_sql, (pk, d['id']))
            backfilled += 1
        conn.commit()

    return {"deleted": deleted, "backfilled": backfilled}


if __name__ == "__main__":
    res = main()
    print(res)
