
import json
import hashlib
import uuid
from typing import Dict, Any, List, Optional, Tuple

try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec


def _canonical_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(parts: List[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


class SettlementEngine:
    GRADING_VERSION = "v1.0.0"

    def run_settlement_cycle(self, league: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        """
        Grades unsettled legs for which game_results.final = true.
        Returns reconciliation stats.
        Wrapper for 'run' to match established interface if any.
        """
        return self.run(league, limit)

    def run(self, league: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        """
        Grades unsettled legs for which game_results.final = true.
        Returns reconciliation stats.
        """
        stats = {
            "processed_legs": 0,
            "inserted_events": 0,
            "skipped_idempotent": 0,
            "missing_fields": 0,
            "missing_results": 0,
            "unlinked_legs": 0,
            "touched_bets": set(),
        }

        print("Starting Settlement Cycle...")

        with get_db_connection() as conn:
            try:
                legs = self._fetch_candidate_legs(conn, league=league, limit=limit)
                conn.commit() # Ensure transaction is clean
            except Exception as e:
                print(f"Candidates Fetch Failed: {e}")
                raise
            
            print(f"Found {len(legs)} candidate legs.")

            for leg in legs:
                leg_id = leg["leg_id"]
                bet_id = leg["bet_id"]
                event_id = leg.get("event_id")

                if not event_id:
                    stats["unlinked_legs"] += 1
                    continue

                try:
                    result = self._fetch_final_result(conn, event_id)
                except Exception as e:
                    print(f"Fetch Result Failed for {event_id}: {e}")
                    conn.rollback() 
                    continue

                if not result:
                    stats["missing_results"] += 1
                    # This happens frequently if events are scheduled but not played. Silence unless verbose.
                    continue

                outcome, grade_inputs, err = self._grade_leg(leg, result)
                if err:
                    print(f"Error grading leg {leg_id}: {err}")
                    stats["missing_fields"] += 1
                    continue

                # Fetch CLV (Closing Line Value)
                # Looking for the snapshot closest to start time for this book/market
                from src.database import get_last_prestart_snapshot
                clv_snapshots = get_last_prestart_snapshot(event_id, leg.get("market_type"))
                
                # Filter for this book
                book_key = leg.get("book")
                # Normalize book key if needed (e.g. 'draftkings' vs 'DK') - Adapter usually normalizes
                # For now assume exact match or try loose match
                
                clv_data = next((s for s in clv_snapshots if s['book'] == book_key), None)
                if not clv_data and clv_snapshots:
                    # Fallback to Consensus (Average of all books) if specific book missing
                    avg_line = sum(s['line'] for s in clv_snapshots) / len(clv_snapshots)
                    # For price, avg probability implies... let's just take avg price
                    avg_price = sum(s['price'] for s in clv_snapshots) / len(clv_snapshots)
                    clv_data = {
                        "line": avg_line, 
                        "price": avg_price, 
                        "book": "consensus_fallback"
                    }

                # Build settlement event inputs (Full context for storage)
                inputs_json = {
                    "event_id": event_id,
                    "league": leg.get("league"),
                    "market_type": leg.get("market_type"),
                    "selection_team_id": leg.get("selection_team_id"),
                    "side": leg.get("side"),
                    "line": leg.get("line"),
                    "price": leg.get("odds_american"), # Capture bet price too if avail
                    "book": leg.get("book"),
                    "clv": clv_data, # NEW: Store CLV
                    "result": result,
                    "computed": grade_inputs,
                }
                
                # Fingerprint: Canonical Stable Input (Exclude updated_at/metadata)
                # event_id, final scores, market keys, grading version
                fp_parts = [
                    str(event_id),
                    str(result.get("home_score")),
                    str(result.get("away_score")),
                    str(leg.get("market_type") or "").upper(),
                    str(leg.get("side") or "").upper(),
                    str(leg.get("line") or ""),
                    self.GRADING_VERSION
                ]
                fp = _fingerprint(fp_parts)

                inserted = self._insert_settlement_event(
                    conn=conn,
                    bet_id=bet_id,
                    leg_id=leg_id,
                    event_id=event_id,
                    outcome=outcome,
                    fingerprint=fp,
                    inputs_json=inputs_json,
                )

                stats["processed_legs"] += 1
                if inserted:
                    stats["inserted_events"] += 1
                    try:
                        self._update_leg_status(conn, leg_id, outcome)
                        conn.commit() # Commit per leg
                        print(f"Settled Leg {leg_id}: {outcome}")
                    except Exception as e:
                        print(f"Update Leg Failed {leg_id}: {e}")
                        conn.rollback()
                else:
                    stats["skipped_idempotent"] += 1
                    # Ensure transaction clean even if skipped (if insert aborted it)
                    if hasattr(conn, 'info') and getattr(conn.info, 'transaction_status', 0) == 3: # INERROR
                         conn.rollback()

                stats["touched_bets"].add(bet_id)

            # After legs graded, settle slips for touched bets
            for bet_id in list(stats["touched_bets"]):
                self._settle_bet_from_legs(conn, bet_id)

            conn.commit()

        stats["touched_bets"] = len(stats["touched_bets"])
        print(f"Settlement Complete: {stats}")
        return stats

    def _fetch_candidate_legs(self, conn, league: Optional[str], limit: int) -> List[Dict[str, Any]]:
        # Adapted for schema:
        # bets.provider -> book
        # bet_legs.leg_type -> market_type
        # bet_legs.line_value -> line
        q = """
        SELECT
          bl.id as leg_id,
          bl.bet_id as bet_id,
          bl.event_id as event_id,
          b.provider as book,
          e.league as league,
          bl.leg_type as market_type,
          bl.selection_team_id as selection_team_id,
          bl.side as side,
          bl.line_value as line,
          bl.status as leg_status,
          bl.selection as selection_text
        FROM bet_legs bl
        JOIN bets b ON b.id = bl.bet_id
        LEFT JOIN events e ON e.id = bl.event_id
        WHERE (bl.status = 'PENDING' OR bl.status = 'UNSETTLED')
          AND bl.event_id IS NOT NULL
          AND (:league IS NULL OR e.league = :league)
        LIMIT :lim
        """
        # Note: Added selection_text for fallback if needed, though user code didn't use it.
        # Adjusted WHERE clause to include 'PENDING' which is my default.
        
        cur = _exec(conn, q, {"league": league, "lim": limit})
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _fetch_final_result(self, conn, event_id: str) -> Optional[Dict[str, Any]]:
        q = """
        SELECT home_score, away_score, final, period, updated_at
        FROM game_results
        WHERE event_id = :eid
        """
        cur = _exec(conn, q, {"eid": event_id})
        row = cur.fetchone()
        if not row:
            return None
        # Access by index or name. Row factory might be DictRow or Row.
        if hasattr(row, 'keys'):
            # It's a dict-like object
            home_score = row['home_score']
            away_score = row['away_score']
            final = row['final']
            period = row['period']
            updated_at = row['updated_at']
        else:
            # Tuple
            home_score, away_score, final, period, updated_at = row

        if not final:
            return None
        return {
            "home_score": home_score,
            "away_score": away_score,
            "final": bool(final),
            "period": period,
            "updated_at": updated_at,
        }

    def _grade_leg(self, leg: Dict[str, Any], result: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """
        Returns: (outcome, computed_fields, error_reason_if_any)
        """
        from src.utils.normalize import normalize_market
        market = normalize_market(leg.get("market_type"))
        home = float(result["home_score"])
        away = float(result["away_score"])
        total = home + away

        selection_side = (leg.get("side") or "").upper()  # HOME/AWAY/OVER/UNDER
        line = leg.get("line")

        # Fallback: If Side is missing, try to infer from selection text (legacy support)
        if not selection_side and leg.get('selection_text'):
            sel = leg['selection_text'].upper()
            if 'OVER' in sel: selection_side = 'OVER'
            elif 'UNDER' in sel: selection_side = 'UNDER'
            # Can't easily infer HOME/AWAY without team names here.
            
        computed = {"home": home, "away": away, "total": total}

        if market == 'TOTAL':
             # Basic Game Total
            if line is None or selection_side not in ("OVER", "UNDER"):
                return "UNSETTLED", computed, f"missing_total_fields: line={line}, side={selection_side}"
            
            line_val = float(line)
            computed["line"] = line_val
            
            # Simple Total Rule
            score_to_compare = total
            
            if "TEAM_TOTAL" in market:
                return "UNSETTLED", computed, "unsupported_market: TEAM_TOTAL"
            
            if selection_side == "OVER":
                if score_to_compare > line_val: return "WON", computed, None
                if score_to_compare == line_val: return "PUSH", computed, None
                return "LOST", computed, None
            else:  # UNDER
                if score_to_compare < line_val: return "WON", computed, None
                if score_to_compare == line_val: return "PUSH", computed, None
                return "LOST", computed, None

        if market == 'MONEYLINE':
            if selection_side not in ("HOME", "AWAY", "DRAW"):
                # Strict: Do not infer from text.
                return "UNSETTLED", computed, f"missing_moneyline_side: {selection_side}"
                
            margin_home = home - away
            computed["margin_home"] = margin_home
            
            if selection_side == "HOME":
                return ("WON" if margin_home > 0 else "LOST" if margin_home < 0 else "PUSH"), computed, None
            if selection_side == "AWAY":
                return ("WON" if margin_home < 0 else "LOST" if margin_home > 0 else "PUSH"), computed, None
            # DRAW
            return ("WON" if margin_home == 0 else "LOST"), computed, None

        if market == 'SPREAD':
            if line is None or selection_side not in ("HOME", "AWAY"):
                return "UNSETTLED", computed, f"missing_spread_fields: line={line}, side={selection_side}"
            
            spread = float(line)
            computed["spread"] = spread
            
            # Formula: Selection Score + Spread > Opponent Score
            if selection_side == "HOME":
                adj = (home - away) + spread
            else:
                adj = (away - home) + spread
                
            computed["adj_margin"] = adj
            if adj > 0: return "WON", computed, None
            if adj == 0: return "PUSH", computed, None
            return "LOST", computed, None

        return "UNSETTLED", computed, f"unknown_market_type: {market}"

    def _insert_settlement_event(
        self, conn, bet_id: str, leg_id: str, event_id: str, outcome: str, fingerprint: str, inputs_json: Dict[str, Any]
    ) -> bool:
        # Insert if fingerprint not present
        q = """
        INSERT INTO settlement_events (
          id, bet_id, leg_id, event_id, outcome, graded_at, graded_by, grading_version, fingerprint, inputs_json, result_revision
        ) VALUES (
          :id, :bet_id, :leg_id, :event_id, :outcome, CURRENT_TIMESTAMP, 'system', :gv, :fp, :inputs, 0
        ) ON CONFLICT(fingerprint) DO NOTHING
        """
        try:
            cur = _exec(conn, q, {
                "id": str(uuid.uuid4()),
                "bet_id": bet_id,
                "leg_id": leg_id,
                "event_id": event_id,
                "outcome": outcome,
                "gv": self.GRADING_VERSION,
                "fp": fingerprint,
                "inputs": _canonical_json(inputs_json),
            })
            # Return True only if row was actually inserted
            return cur.rowcount > 0
        except Exception as e:
            # Expect unique violation on fingerprint
            print(f"Insert Failed (Idempotent?): {e}", flush=True)
            return False

    def _update_leg_status(self, conn, leg_id: str, outcome: str) -> None:
        q = """
        UPDATE bet_legs
        SET status = :s --, settled_at = CURRENT_TIMESTAMP (if column exists)
        WHERE id = :id
        """
        _exec(conn, q, {"s": outcome, "id": leg_id})

    def _settle_bet_from_legs(self, conn, bet_id: str) -> None:
        # Conservative default: any LOSS -> LOST; else if all in {WON,PUSH,VOID} and at least one WON -> WON; else VOID
        q = "SELECT status FROM bet_legs WHERE bet_id = :bid"
        cur = _exec(conn, q, {"bid": bet_id})
        statuses = [r[0] for r in cur.fetchall()]
        
        if not statuses:
            return
            
        # Map statuses to standard set just in case
        # My code uses WON/LOST/PUSH. User used WIN/LOSS.
        # I should normalize in _grade_leg relative to my DB constraints?
        # My DB uses 'WON', 'LOST' (Phase 4 Verified).
        # User Code uses 'WIN', 'LOSS'.
        # I updated `_grade_leg` above to return WON/LOST.
        
        if any(s == "LOST" for s in statuses):
            slip_status = "LOST"
        elif any(s == "PENDING" for s in statuses) or any(s == "UNSETTLED" for s in statuses):
             # If any are pending, the slip is pending (unless one is LOST? Some books settle early loss).
             # For now, if any pending, leave whole slip pending UNLESS strictly loss.
             if any(s == "LOST" for s in statuses):
                 slip_status = "LOST"
             else:
                 return # Still pending
        else:
            wins = sum(1 for s in statuses if s == "WON")
            if wins > 0:
                slip_status = "WON"
            else:
                # all PUSH/VOID
                # Check for single leg push -> Void
                slip_status = "VOID"
        
        _exec(conn, "UPDATE bets SET status = :s WHERE id = :bid",
              {"s": slip_status, "bid": bet_id})
