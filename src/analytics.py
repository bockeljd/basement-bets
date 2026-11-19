from collections import defaultdict
from src.database import fetch_all_bets, get_db_connection

class AnalyticsEngine:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.bets = fetch_all_bets(user_id=user_id)
        self._normalize_bets()
        self._add_sortable_dates()
    
    def _add_sortable_dates(self):
        """Adds ISO-formatted sort_date field for proper date sorting.

        Avoid hard dependency on python-dateutil (some runtimes/venvs omit it).
        """
        try:
            from dateutil.parser import parse as parse_date  # type: ignore
        except Exception:
            parse_date = None

        for b in self.bets:
            raw_date = b.get('date', '')
            try:
                dt = None
                if parse_date is not None:
                    dt = parse_date(raw_date, fuzzy=True)
                else:
                    # Best-effort ISO date/datetime parsing
                    s = str(raw_date or '').strip()
                    s0 = s.split('T')[0].split(' ')[0] if s else ''
                    if len(s0) == 10:
                        dt = datetime.strptime(s0, '%Y-%m-%d')
                if dt is not None:
                    b['sort_date'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    b['display_date'] = dt.strftime('%d/%m/%Y')
                else:
                    b['sort_date'] = raw_date
                    b['display_date'] = raw_date
            except Exception:
                b['sort_date'] = raw_date
                b['display_date'] = raw_date

    def _normalize_bets(self):
        """Standardizes bet types and adds display helpers for the UI."""
        import re

        def compact_selection(text: str) -> str:
            if not text:
                return ""
            t = str(text).replace("\n", " ").strip()
            # Split FanDuel/DK multi-leg strings
            parts = [p.strip() for p in re.split(r"\s*\|\s*", t) if p.strip()]
            if len(parts) <= 2:
                out = " | ".join(parts) if parts else t
            else:
                out = " | ".join(parts[:2]) + f" | … (+{len(parts)-2} more)"
            # Hard cap
            return out[:140] + "..." if len(out) > 140 else out

        for b in self.bets:
            # Normalize odds: treat 0 as missing
            if b.get('odds') == 0:
                b['odds'] = None

            raw = b.get('bet_type') or ''
            norm = raw.strip()

            # Case-insensitive check
            check = norm.lower()

            # 1. Moneyline
            if check in ["winner (ml)", "straight", "moneyline", "ml"]:
                norm = "Winner (ML)"
            
            # 2. Spread
            elif "spread" in check or "point spread" in check:
                norm = "Spread"

            # 3. Totals
            elif any(x in check for x in ["over", "under", "total"]):
                norm = "Over / Under"

            # 4. Props
            elif "prop" in check:
                norm = "Prop"

            # 5. SGP (Same Game Parlay)
            elif "sgp" in check or "same game" in check:
                norm = "SGP"

            # 6. FanDuel accumulator codes (ACC5, ACC7, etc)
            elif re.match(r"^acc\d+$", check):
                n = int(re.findall(r"\d+", check)[0])
                norm = f"{n} leg parlay"

            # 7. FanDuel DBL (2-leg)
            elif check == "dbl":
                norm = "2 leg parlay"

            # 8. FanDuel TBL (treat as parlay/teaser bucket for now)
            elif check == "tbl":
                norm = "Parlay"

            # 9. Parlays (check last so SGP matches first if labeled SGP)
            elif "parlay" in check or "leg" in check or "picks" in check:
                # Extract leg count
                match = re.search(r'(\d+)', check)
                if match:
                    count = int(match.group(1))
                    if count == 2:
                        norm = "2 Leg Parlay"
                    elif count == 3:
                        norm = "3 Leg Parlay"
                    elif count >= 4:
                        norm = "4+ Parlay"
                    else:
                        norm = "2 Leg Parlay" # Default to 2 if 1 logic fails or parse error
                elif "4+" in check:
                    norm = "4+ Parlay"
                else: 
                     # If generic "Parlay", assume 2 or 3? Or default bucket.
                     # User spec: 2 Leg, 3 Leg, 4+.
                     # Let's map generic "Parlay" to "2 Leg Parlay" as baseline or check selection count (not avail here easily)
                     norm = "2 Leg Parlay"

            b['bet_type'] = norm

            # Selection/description display helpers
            base_text = b.get('selection') or b.get('description') or ''
            b['display_selection'] = compact_selection(base_text)



    def get_summary(self, user_id=None):
        # Already filtered in __init__, but support explicit pass if needed
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]
             
        def is_perf_bet(b: dict) -> bool:
            st = (b.get('status') or '').strip().upper()
            # Performance metrics should exclude placeholders/voids.
            return st not in ('PENDING', 'OPEN', 'VOID')

        perf = [b for b in bets if is_perf_bet(b)]
        voids = [b for b in bets if (b.get('status') or '').strip().upper() == 'VOID']

        total_wagered = sum(float(b.get('wager') or 0.0) for b in perf)
        net_profit = sum(float(b.get('profit') or 0.0) for b in perf)
        roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0.0

        wins = sum(
            1 for b in perf
            if (str(b.get('status') or '').strip().upper() in ('WON', 'WIN'))
            or ((str(b.get('status') or '').strip().upper() == 'CASHED OUT') and float(b.get('profit') or 0.0) > 0)
        )
        total = len(perf)
        win_rate = (wins / total * 100) if total > 0 else 0.0

        return {
            # Core performance metrics (VOID excluded)
            "total_bets": total,
            "total_wagered": total_wagered,
            "net_profit": net_profit,
            "roi": roi,
            "win_rate": win_rate,
            # Additional transparency
            "void_bets": len(voids),
            "void_wagered": sum(float(b.get('wager') or 0.0) for b in voids),
        }

    def get_breakdown(self, field: str, user_id=None):
        """
        Groups bets by a field (sport, bet_type) and calculates metrics.
        Includes Financial Transactions if field is 'bet_type'.
        """
        from src.database import get_db_connection
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        groups = defaultdict(lambda: {'wager': 0.0, 'profit': 0.0, 'wins': 0, 'total': 0})
        
        for b in bets:
            key = b.get(field, 'Unknown')
            st = (b.get('status') or '').strip().upper()
            if st in ('PENDING', 'OPEN', 'VOID'):
                continue

            groups[key]['wager'] += float(b.get('wager') or 0.0)
            groups[key]['profit'] += float(b.get('profit') or 0.0)
            groups[key]['total'] += 1
            if st in ('WON', 'WIN') or (st == 'CASHED OUT' and float(b.get('profit') or 0.0) > 0):
                groups[key]['wins'] += 1
        results = []
        for key, vals in groups.items():
            wins = vals['wins']
            total = vals['total']
            results.append({
                field: key,
                "bets": total,
                "wins": wins,
                "profit": vals['profit'],
                "wager": vals['wager'],
                "win_rate": (wins / total * 100) if total > 0 else 0.0,
                "roi": (vals['profit'] / vals['wager'] * 100) if vals['wager'] > 0 else 0.0
            })

        return sorted(results, key=lambda x: x['profit'], reverse=True)

    def get_predictions(self):
        """
        Generates Green/Red light recommendations based on historical performance.
        """
        sports = self.get_breakdown('sport')
        types = self.get_breakdown('bet_type')
        
        green_lights = []
        red_lights = []
        
        # Heuristics for Prediction
        # Green: > 40% win rate AND Positive Profit (min 3 bets)
        # Red: < 20% win rate OR Negative Profit > $20 (min 3 bets)
        
        for s in sports:
            if s['bets'] < 3: continue
            if s['profit'] > 0 and s['win_rate'] >= 40:
                green_lights.append(f"Sport: {s['sport']} (WR: {s['win_rate']:.0f}%, Profit: ${s['profit']:.2f})")
            elif s['profit'] < -20 or s['win_rate'] < 20:
                red_lights.append(f"Sport: {s['sport']} (WR: {s['win_rate']:.0f}%, Profit: ${s['profit']:.2f})")
                
        for t in types:
            if t['bets'] < 3: continue
            if t['profit'] > 0 and t['win_rate'] >= 40:
                green_lights.append(f"Type: {t['bet_type']} (WR: {t['win_rate']:.0f}%, Profit: ${t['profit']:.2f})")
            elif t['profit'] < -20 or t['win_rate'] < 20:
                red_lights.append(f"Type: {t['bet_type']} (WR: {t['win_rate']:.0f}%, Profit: ${t['profit']:.2f})")
                
        return green_lights, red_lights

    def get_edge_analysis(self, user_id=None):
        """
        Groups bets by (sport, bet_type) and calculates profitability vs market expectations.
        """
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        groups = defaultdict(lambda: {
            'wager': 0.0, 
            'profit': 0.0, 
            'wins': 0, 
            'total': 0, 
            'implied_probs': []
        })

        for b in bets:
            # Skip financial transactions
            if b.get('bet_type') in ['Deposit', 'Withdrawal', 'Other']:
                continue
                
            sport = b.get('sport', 'Unknown')
            btype = b.get('bet_type', 'Straight')
            key = (sport, btype)
            
            groups[key]['wager'] += b['wager']
            groups[key]['profit'] += b['profit']
            groups[key]['total'] += 1
            
            status = b.get('status', 'PENDING').strip().upper()
            if status in ('WON', 'WIN') or (status == 'CASHED OUT' and b['profit'] > 0):
                groups[key]['wins'] += 1
            
            if b.get('odds'):
                prob = self._calculate_implied_probability(b['odds'])
                if prob:
                    groups[key]['implied_probs'].append(prob)

        results = []
        for (sport, btype), vals in groups.items():
            total = vals['total']
            if total == 0: continue
            
            actual_wr = (vals['wins'] / total * 100)
            avg_implied = (sum(vals['implied_probs']) / len(vals['implied_probs']) * 100) if vals['implied_probs'] else 0.0
            
            results.append({
                "sport": sport,
                "bet_type": btype,
                "bets": total,
                "wins": vals['wins'],
                "actual_win_rate": round(actual_wr, 1),
                "implied_win_rate": round(avg_implied, 1),
                "edge": round(actual_wr - avg_implied, 1),
                "profit": round(vals['profit'], 2),
                "roi": round((vals['profit'] / vals['wager'] * 100), 1) if vals['wager'] > 0 else 0.0
            })

        # Sort by edge descending
        return sorted(results, key=lambda x: x['edge'], reverse=True)

    def get_player_performance(self, user_id=None):
        """
        Aggregates performance by player name extracted from bet selections.
        """
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        player_stats = defaultdict(lambda: {'wager': 0.0, 'profit': 0.0, 'wins': 0, 'total': 0})
        
        for b in bets:
            # Skip if no selection text
            if not b['selection']: continue
            
            # Extract potential player names
            players = self._extract_player_names(b['selection'])
            
            # If SGP, profit applies to all players involved? 
            # Or split? Usually we track correlation. 
            # For simplicity, attribute the full Result to the player involved.
            # (Note: This double-counts profit if multiple players are in one SGP, but correctly reflects "When I bet on X, I win")
            
            for player in players:
                player_stats[player]['wager'] += b['wager'] # Full wager
                player_stats[player]['profit'] += b['profit']
                player_stats[player]['total'] += 1
                if b['status'].upper() in ('WON', 'WIN'):
                    player_stats[player]['wins'] += 1

        results = []
        for player, data in player_stats.items():
            # Filter out noise (min 1 bets)
            if data['total'] < 1: continue
            
            win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
            results.append({
                "player": player,
                "bets": data['total'],
                "profit": data['profit'],
                "win_rate": win_rate
            })
            
        return sorted(results, key=lambda x: x['profit'], reverse=True)

    def get_monthly_performance(self, user_id=None):
        """
        Aggregates profit by Month (YYYY-MM).
        Includes both Bets and Financial Transactions (Deposits/Withdrawals).
        Returns both realized profit and total balance (money in play) time series.
        """
        from datetime import datetime
        from src.database import get_db_connection
        
        monthly_profit = defaultdict(float)  # Bet profit only
        monthly_deposits = defaultdict(float)
        monthly_withdrawals = defaultdict(float)
        
        # 1. Process Bets
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]
        
        for b in bets:
            date_str = b.get('date', '')
            if not date_str or date_str == 'Unknown': continue
            try:
                d_str = date_str.split(' ')[0] if ' ' in date_str else date_str
                dt = datetime.strptime(d_str, "%Y-%m-%d")
                month_key = dt.strftime("%Y-%m")
                monthly_profit[month_key] += b['profit']
            except: continue

        # 2. Process Transactions (Deposits/Withdrawals) - graceful degradation if table missing
        query = "SELECT date, type, amount FROM transactions WHERE type IN ('Deposit', 'Withdrawal') AND (%(user_id)s IS NULL OR user_id = %(user_id)s)"
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, {"user_id": user_id})
                for r in cur.fetchall():
                    date_str = r['date']
                    if not date_str: continue
                    try:
                        d_str = date_str.split(' ')[0] if ' ' in date_str else date_str
                        dt = datetime.strptime(d_str, "%Y-%m-%d")
                        month_key = dt.strftime("%Y-%m")
                        if r['type'] == 'Deposit':
                            monthly_deposits[month_key] += abs(float(r['amount'] or 0))
                        else:
                            monthly_withdrawals[month_key] += abs(float(r['amount'] or 0))
                    except: continue
        except Exception as e:
            # Transactions table may not exist yet - degrade gracefully
            print(f"[Analytics] Skipping transactions (table may not exist): {e}")
            
        # Get all month keys
        all_months = set(monthly_profit.keys()) | set(monthly_deposits.keys()) | set(monthly_withdrawals.keys())
        sorted_months = sorted(all_months)
        
        results = []
        cumulative_profit = 0.0  # Realized profit (Withdrawals - Deposits)
        cumulative_balance = 0.0  # Total money in play (Deposits + Profits - Withdrawals)
        
        for month in sorted_months:
            profit = monthly_profit.get(month, 0)
            deposits = monthly_deposits.get(month, 0)
            withdrawals = monthly_withdrawals.get(month, 0)
            
            # Realized profit = what you've taken out minus what you put in
            realized_change = withdrawals - deposits + profit
            cumulative_profit += realized_change
            
            # Balance = what's still in play = deposits + profits - withdrawals
            balance_change = deposits + profit - withdrawals
            cumulative_balance += balance_change
            
            results.append({
                "month": month,
                "profit": round(profit, 2),
                "deposits": round(deposits, 2),
                "withdrawals": round(withdrawals, 2),
                "cumulative": round(cumulative_profit, 2),  # Backward compat
                "balance": round(cumulative_balance, 2)  # Total money in play
            })
        return results

            
    def _to_day_key(self, s: str):
        import re
        from dateutil.parser import parse as parse_date

        if not s:
            return None
        # Fast-path: already ISO date
        if re.match(r"^\d{4}-\d{2}-\d{2}$", str(s)):
            return str(s)
        # If it looks like ISO datetime, keep date part
        if re.match(r"^\d{4}-\d{2}-\d{2}T", str(s)):
            return str(s).split('T')[0]
        # Otherwise try to parse; if it fails, skip
        try:
            dt = parse_date(str(s), fuzzy=True)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            return None


    def get_time_series_profit(self, user_id=None):
        """Legacy time series including cashflows.

        NOTE: This mixes betting performance with deposits/withdrawals.
        Prefer get_time_series_settled_equity() for drawdown/strategy curves.
        """
        from src.database import get_db_connection

        daily_profit = defaultdict(float)  # bankroll impact from bets (pending stake + settled profit)
        daily_deposits = defaultdict(float)
        daily_withdrawals = defaultdict(float)

        bets = self.bets
        if user_id and user_id != self.user_id:
            bets = [b for b in self.bets if b.get('user_id') == user_id]

        for b in bets:
            day_key = self._to_day_key(b.get('date', ''))
            if not day_key:
                continue

            status = (b.get('status') or 'PENDING').upper()
            wager = float(b.get('wager') or 0.0)
            profit = float(b.get('profit') or 0.0)

            if status in ('PENDING', 'OPEN'):
                daily_profit[day_key] -= wager
            elif status == 'VOID':
                # do not impact equity curve
                continue
            else:
                daily_profit[day_key] += profit

        # Transactions
        query = "SELECT date, type, amount FROM transactions WHERE type IN ('Deposit', 'Withdrawal') AND (%(user_id)s IS NULL OR user_id = %(user_id)s)"
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, {"user_id": user_id})
                for r in cur.fetchall():
                    day_key = self._to_day_key(r['date'])
                    if not day_key:
                        continue
                    if r['type'] == 'Deposit':
                        daily_deposits[day_key] += abs(float(r['amount'] or 0))
                    elif r['type'] == 'Withdrawal':
                        daily_withdrawals[day_key] += abs(float(r['amount'] or 0))
        except Exception as e:
            print(f"[Analytics] Skipping transactions (table may not exist): {e}")

        all_dates = set(daily_profit.keys()) | set(daily_deposits.keys()) | set(daily_withdrawals.keys())
        sorted_dates = sorted(all_dates)

        results = []
        cumulative_profit = 0.0
        cumulative_balance = 0.0

        for date in sorted_dates:
            profit = daily_profit.get(date, 0)
            dep = daily_deposits.get(date, 0)
            wd = daily_withdrawals.get(date, 0)

            cumulative_profit += (wd - dep + profit)
            cumulative_balance += (dep + profit - wd)

            results.append({
                "date": date,
                "profit": round(profit, 2),
                "cumulative": round(cumulative_profit, 2),
                "balance": round(cumulative_balance, 2)
            })
        return results


    def get_time_series_settled_equity(self, user_id=None):
        """Settled-only betting equity curve (ignores deposits/withdrawals).

        This is the curve we should use for drawdown (withdrawals are not drawdowns).
        """
        daily_profit = defaultdict(float)

        bets = self.bets
        if user_id and user_id != self.user_id:
            bets = [b for b in self.bets if b.get('user_id') == user_id]

        for b in bets:
            status = (b.get('status') or 'PENDING').upper()
            if status in ('PENDING', 'OPEN', 'VOID'):
                continue

            day_key = self._to_day_key(b.get('date', ''))
            if not day_key:
                continue

            daily_profit[day_key] += float(b.get('profit') or 0.0)

        sorted_dates = sorted(daily_profit.keys())
        results = []
        cum = 0.0
        for d in sorted_dates:
            p = daily_profit.get(d, 0.0)
            cum += p
            results.append({
                "date": d,
                "profit": round(p, 2),
                "cumulative": round(cum, 2),
                "balance": round(cum, 2),
            })
        return results

        sorted_dates = sorted(daily_profit.items())
        
        results = []
        cumulative = 0.0
        for date, profit in sorted_dates:
            cumulative += profit
            results.append({
                "date": date,
                "profit": profit,
                "cumulative": round(cumulative, 2)
            })
        return results

    def get_drawdown_metrics(self, user_id=None):
        """
        Calculates maximum drawdown from peak.
        """
        # Drawdown should be strategy drawdown (settled bets only), not cashflow-driven.
        series = self.get_time_series_settled_equity(user_id=user_id)
        if not series:
            return {"max_drawdown": 0.0, "current_drawdown": 0.0, "peak_profit": 0.0}
            
        peak = -float('inf')
        max_dd = 0.0
        current_profit = 0.0
        
        for point in series:
            current_profit = point['cumulative']
            if current_profit > peak:
                peak = current_profit
            
            dd = peak - current_profit
            if dd > max_dd:
                max_dd = dd
                
        return {
            "max_drawdown": round(max_dd, 2),
            "current_drawdown": round(peak - current_profit, 2),
            "peak_profit": round(peak, 2),
            "recovery_pct": round((current_profit / peak * 100), 1) if peak > 0 else 0
        }

    def get_balances(self, user_id=None):
        """
        Calculates current sportsbook balances by starting from the latest manual snapshots
        and adding subsequent transactions (deposits/withdrawals) and bet results.
        Returns a dict: { provider: { balance: float, last_bet: str|None } }
        """
        try:
            from dateutil.parser import parse as parse_date  # type: ignore
        except Exception:
            parse_date = None
        from src.database import get_db_connection
        from collections import defaultdict

        def _to_naive(d):
            if not d:
                return None
            if isinstance(d, str):
                if parse_date is not None:
                    try:
                        d = parse_date(d)
                    except Exception:
                        return None
                else:
                    # best-effort YYYY-MM-DD
                    try:
                        s = str(d).split('T')[0].split(' ')[0]
                        if len(s) == 10:
                            d = datetime.strptime(s, '%Y-%m-%d')
                        else:
                            return None
                    except Exception:
                        return None
            if hasattr(d, 'replace') and hasattr(d, 'tzinfo') and d.tzinfo:
                from datetime import timezone as _tz
                return d.astimezone(_tz.utc).replace(tzinfo=None)
            return d

        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]
             
        explicit_balances = {}  # provider -> (balance, dt_object, original_date_str, source_type)

        # Prefer dedicated balance_snapshots table
        try:
            from src.database import fetch_latest_balance_snapshots
            latest_snaps = fetch_latest_balance_snapshots(user_id=user_id)
            for provider, snap in (latest_snaps or {}).items():
                # snap['captured_at'] may be str or datetime
                dt = _to_naive(snap.get('captured_at'))
                explicit_balances[provider] = (float(snap.get('balance') or 0), dt, str(snap.get('captured_at') or ''), 'BalanceSnapshot')
        except Exception as e:
            print(f"[Analytics] balance_snapshots lookup failed: {e}")

        deposits = defaultdict(list)     # provider -> list of (amount, dt)
        withdrawals = defaultdict(list)  # provider -> list of (amount, dt)
        
        query = """
        SELECT provider, type, amount, balance, date
        FROM transactions
        WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
        """
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, {"user_id": user_id})
                for r in cur.fetchall():
                    provider = r['provider']
                    tx_type = r['type']
                    
                    # Parse date and normalize to naive
                    dt = _to_naive(r['date'])

                    # Treat BalanceSnapshot as highest-priority (explicit source-of-truth for UI).
                    if tx_type in ('BalanceSnapshot', 'Balance'):
                        current_bal = float(r['balance'] or 0)
                        # Keep the LATEST snapshot; prefer BalanceSnapshot over Balance when timestamps tie/are ambiguous.
                        if provider not in explicit_balances:
                            explicit_balances[provider] = (current_bal, dt, r['date'], tx_type)
                        else:
                            existing_bal, existing_dt, existing_raw, existing_type = explicit_balances[provider]
                            # If new is newer, replace
                            if dt and existing_dt and dt > existing_dt:
                                explicit_balances[provider] = (current_bal, dt, r['date'], tx_type)
                            elif dt and not existing_dt:
                                explicit_balances[provider] = (current_bal, dt, r['date'], tx_type)
                            elif (dt and existing_dt and dt == existing_dt) and (existing_type != 'BalanceSnapshot') and (tx_type == 'BalanceSnapshot'):
                                explicit_balances[provider] = (current_bal, dt, r['date'], tx_type)
                                
                    elif tx_type == 'Deposit':
                        deposits[provider].append((float(r['amount'] or 0), dt))
                    elif tx_type == 'Withdrawal':
                        withdrawals[provider].append((abs(float(r['amount'] or 0)), dt))
        except Exception as e:
            print(f"[Analytics] Error fetching transactions: {e}")
        
        # 2. Iterate Providers and Calculate Final Balance
        # We need to consider all providers found in bets OR transactions
        all_providers = set()
        for b in bets: all_providers.add(b.get('provider', 'Unknown'))
        for p in explicit_balances: all_providers.add(p)
        for p in deposits: all_providers.add(p)
        
        final_balances = {}
        last_bet_dates = {}
        
        for provider in all_providers:
            base_balance = 0.0
            snapshot_dt = None
            
            # A. Start with Snapshot if available
            if provider in explicit_balances:
                base_balance, snapshot_dt, _, _snap_type = explicit_balances[provider]
            else:
                # If no snapshot, base is 0.0 and we sum ALL history
                # (effectively snapshot_dt is 'beginning of time')
                snapshot_dt = None
            
            # B. Add Transactions AFTER snapshot
            # Deposits
            for amt, dt in deposits.get(provider, []):
                # If no snapshot, include all. If snapshot, include only if newer.
                if not snapshot_dt:
                    base_balance += amt
                elif dt and snapshot_dt and dt > snapshot_dt:
                    base_balance += amt
                    
            # Withdrawals
            for amt, dt in withdrawals.get(provider, []):
                if not snapshot_dt:
                    base_balance -= amt
                elif dt and snapshot_dt and dt > snapshot_dt:
                    base_balance -= amt
                    
            # C. Add Bet Profits AFTER snapshot
            # Filter bets for this provider
            provider_bets = [b for b in bets if b.get('provider', 'Unknown') == provider]
            last_date_str = None

            # Normalize last-bet date so old strings like "Sep 6, 2024, 3:37pm ET" don't win.
            def to_day_key(s: str):
                try:
                    return self._to_day_key(s)
                except Exception:
                    return None

            for b in provider_bets:
                profit = b['profit']
                date_str = b.get('date', '')

                day_key = to_day_key(date_str)
                if day_key:
                    if not last_date_str or day_key > last_date_str:
                        last_date_str = day_key
                
                # Decide whether to include in balance
                # Note: b['date'] is usually string "YYYY-MM-DD". Snapshot is full datetime.
                # We need to parse bet date safely.
                status = b.get('status', 'PENDING').upper()
                wager = b.get('wager', 0.0)
                
                try:
                    # Use fuzzy=True just in case, or assume YYYY-MM-DD
                    bet_dt = parse_date(date_str)
                    
                    if not snapshot_dt:
                        if status == 'PENDING':
                            base_balance -= wager
                        else:
                            base_balance += profit
                    else:
                        # Compare logic
                        b_mz = bet_dt.replace(tzinfo=None)
                        s_mz = snapshot_dt.replace(tzinfo=None)
                        
                        if b_mz > s_mz:
                            if status == 'PENDING':
                                base_balance -= wager
                            else:
                                base_balance += profit
                            
                except:
                    # If date parse fails, we can't determine order. 
                    if not snapshot_dt:
                        if status == 'PENDING':
                            base_balance -= wager
                        else:
                            base_balance += profit
            
            final_balances[provider] = {
                'balance': round(base_balance, 2),
                'last_bet': last_date_str
            }
        
        return final_balances

    def get_period_stats(self, days=None, year=None, user_id=None):
        """
        Calculates stats for a specific time period.
        """
        from datetime import datetime, timedelta
        
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        filtered_bets = []
        now = datetime.now()

        def _bet_day(b):
            # Prefer canonical date_et (DATE) when present
            try:
                de = b.get('date_et')
                if de:
                    # psycopg2 returns date objects; leave as datetime for comparisons
                    return datetime(de.year, de.month, de.day)
            except Exception:
                pass

            date_str = b.get('date', '')
            if not date_str or date_str == 'Unknown':
                return None
            try:
                d_str = date_str.split(' ')[0] if ' ' in date_str else date_str
                if '/' in d_str:
                    return datetime.strptime(d_str, "%m/%d/%Y")
                return datetime.strptime(d_str, "%Y-%m-%d")
            except Exception:
                return None

        # Filter to performance-relevant bets only
        perf_bets = []
        for b in bets:
            st = str(b.get('status') or '').strip().upper()
            if st in ('PENDING', 'OPEN', 'VOID'):
                continue
            perf_bets.append(b)

        anchor_day = now.date()
        cutoff_day = (anchor_day - timedelta(days=int(days))) if days else None

        for b in perf_bets:
            bet_date = _bet_day(b)
            if not bet_date:
                continue
            bet_day = bet_date.date()

            if year:
                if bet_day.year == int(year):
                    filtered_bets.append(b)
            elif days:
                # Date-based window (inclusive) so "Last 30d" aligns with ET-day reporting.
                if bet_day >= cutoff_day:
                    filtered_bets.append(b)
            else:
                filtered_bets.append(b)
                
        # Calculate Stats for filtered bets
        # Calculate Stats for filtered bets
        total_wagered = sum(float(b.get('wager') or 0.0) for b in filtered_bets)
        net_profit = sum(float(b.get('profit') or 0.0) for b in filtered_bets)
        roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0.0

        wins = sum(
            1 for b in filtered_bets
            if (str(b.get('status') or '').strip().upper() in ('WON', 'WIN'))
            or ((str(b.get('status') or '').strip().upper() == 'CASHED OUT') and float(b.get('profit') or 0.0) > 0)
        )
        losses = sum(1 for b in filtered_bets if str(b.get('status') or '').strip().upper() in ('LOST', 'LOSE'))
        total = len(filtered_bets)
        actual_win_rate = (wins / total * 100) if total > 0 else 0.0
        
        # Implied Win Rate Calculation & CLV & Fair Record
        implied_probs = []
        clv_values = []
        
        adj_wins = 0.0
        adj_losses = 0.0
        
        for b in filtered_bets:
            odds = b.get('odds')
            closing = b.get('closing_odds')
            status = b.get('status')
            
            prob = None
            if odds:
                prob = self._calculate_implied_probability(odds)
                if prob:
                    implied_probs.append(prob)
                    
                    # Fair Record Calculation
                    if status in ('WON', 'WIN'):
                        adj_wins += (1 - prob)
                    elif status in ('LOST', 'LOSE'):
                        adj_losses += prob
            
            if odds and closing:
                clv = self.calculate_clv(odds, closing)
                if clv is not None:
                    clv_values.append(clv)
        
        avg_implied_prob = (sum(implied_probs) / len(implied_probs) * 100) if implied_probs else 0.0
        avg_clv = (sum(clv_values) / len(clv_values)) if clv_values else None
        
        return {
            "net_profit": net_profit,
            "total_wagered": total_wagered,
            "roi": roi,
            "wins": wins,
            "losses": losses,
            "total_bets": total,
            "actual_win_rate": actual_win_rate,
            "implied_win_rate": avg_implied_prob,
            "avg_clv": avg_clv,
            "adj_wins": round(adj_wins, 1),
            "adj_losses": round(adj_losses, 1)
        }
        


    def get_financial_summary(self, user_id=None):
        """
        Aggregates financial flows from transactions table.
        """
        from src.database import get_db_connection, fetch_latest_ledger_info
        
        query = """
        SELECT type, description, amount 
        FROM transactions 
        WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
        """
        total_deposits = 0.0
        total_withdrawals = 0.0
        
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, {"user_id": user_id})
                rows = cur.fetchall()
                for r in rows:
                    amt = float(r['amount'] or 0)
                    typ = r['type']
                    desc = r['description'] or ''

                    if typ == 'Deposit':
                        total_deposits += amt
                    elif typ == 'Withdrawal':
                        total_withdrawals += abs(amt)
        except Exception as e:
            # Transactions table may not exist yet - degrade gracefully
            print(f"[Analytics] Skipping transactions for financial summary (table may not exist): {e}")
        
        # Snapshot-anchored balances (source of truth for "baseline")
        from src.database import fetch_latest_balance_snapshots
        latest_snaps = fetch_latest_balance_snapshots(user_id=user_id)
        # provider -> total
        snap_balances = {p: float((s.get('balance') or 0)) for p, s in (latest_snaps or {}).items()}
        snap_captured = {p: s.get('captured_at') for p, s in (latest_snaps or {}).items()}
        # provider -> per-account dict
        snap_accounts = {p: (s.get('accounts') or {}) for p, s in (latest_snaps or {}).items()}

        # Calculate "Total In Play" baseline from latest snapshots
        total_equity = sum(snap_balances.values())

        # Keep the previous computed balances available (for debugging/analysis)
        balances = self.get_balances(user_id=user_id)
        
        # Realized Profit = Simple Cash Out - Cash In
        # This answers: "How much more/less money do I have from withdrawals vs deposits?"
        realized_profit = total_withdrawals - total_deposits
        
        # Net Betting Profit = What the betting activity produced (excludes flows)
        # (Current Equity + Withdrawals) - Deposits = realized gains from betting
        net_bet_profit = (total_equity + total_withdrawals) - total_deposits

        import re
        from datetime import date, datetime, timezone as _tz

        def _to_naive_dt(x):
            try:
                from dateutil.parser import parse as parse_date
                if isinstance(x, str):
                    try:
                        x = parse_date(x)
                    except Exception:
                        return None
                if hasattr(x, 'tzinfo') and x.tzinfo:
                    x = x.astimezone(_tz.utc).replace(tzinfo=None)
                return x
            except Exception:
                # Fallback if dateutil is unavailable
                try:
                    if isinstance(x, str):
                        s = x.strip()
                        if s.endswith('Z'):
                            s = s[:-1] + '+00:00'
                        parsed = datetime.fromisoformat(s)
                        if parsed.tzinfo:
                            parsed = parsed.astimezone(_tz.utc).replace(tzinfo=None)
                        return parsed
                    if hasattr(x, 'tzinfo') and x.tzinfo:
                        return x.astimezone(_tz.utc).replace(tzinfo=None)
                    return x if isinstance(x, datetime) else None
                except Exception:
                    return None

        def _norm_prov(p_raw):
            s = str(p_raw or '').strip()
            low = s.lower()
            if 'draftkings' in low or low == 'dk':
                return 'DraftKings'
            if 'fanduel' in low or low == 'fd':
                return 'FanDuel'
            return s

        def _norm_acc(a_raw):
            s = str(a_raw or '').strip()
            if not s or s.lower() in ('primary', 'main', '1'):
                return 'Main'
            if s.lower() in ('secondary', 'user2', '2'):
                return 'User2'
            return s

        account_last_sync = {}

        def _update_last_sync(prov_raw, acc_raw, dt_val):
            if not prov_raw or dt_val is None or dt_val == '':
                return
            prov = _norm_prov(prov_raw)
            acc = _norm_acc(acc_raw)
            is_date_only = False
            if isinstance(dt_val, str):
                s = dt_val.strip()
                if not s:
                    return
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                    is_date_only = True
                dt_naive = _to_naive_dt(s)
            elif isinstance(dt_val, datetime):
                dt_naive = _to_naive_dt(dt_val)
            elif isinstance(dt_val, date):
                dt_naive = datetime(dt_val.year, dt_val.month, dt_val.day)
                is_date_only = True
            else:
                dt_naive = _to_naive_dt(dt_val)
            if not isinstance(dt_naive, datetime):
                return
            key = (prov, acc)
            cand = (dt_naive, not is_date_only)
            prev = account_last_sync.get(key)
            if prev is None or cand > prev:
                account_last_sync[key] = cand

        def _format_sync_iso(entry):
            if not entry:
                return None
            dt_val, has_time = entry
            if not isinstance(dt_val, datetime):
                return None
            return dt_val.strftime('%Y-%m-%dT%H:%M:%SZ') if has_time else dt_val.strftime('%Y-%m-%d')

        for p_snap, accs_map in (snap_accounts or {}).items():
            if isinstance(accs_map, dict) and accs_map:
                for acc_id, snap in accs_map.items():
                    _update_last_sync(p_snap, acc_id, (snap or {}).get('captured_at'))
            elif snap_captured.get(p_snap):
                _update_last_sync(p_snap, 'Main', snap_captured.get(p_snap))

        # Breakdown by Provider + Account
        provider_stats = defaultdict(lambda: {'deposited': 0.0, 'withdrawn': 0.0})
        provider_account_stats = defaultdict(lambda: {'deposited': 0.0, 'withdrawn': 0.0})
        query_all = """
        SELECT provider, COALESCE(account_id,'Main') as account_id, type, amount, date, created_at
        FROM transactions
        WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
        """
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                # Defensive migration
                try:
                    _exec(conn, "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account_id TEXT;")
                except Exception:
                    pass
                cur = _exec(conn, query_all, {"user_id": user_id})
                rows = cur.fetchall()
                for r in rows:
                    p = _norm_prov(r.get('provider'))
                    if not p:
                        continue
                    acc = _norm_acc(r.get('account_id') or 'Main')
                    _update_last_sync(p, acc, r.get('created_at') or r.get('date'))
                    amt = float(r.get('amount') or 0)
                    typ = r.get('type')

                    if typ == 'Deposit':
                        provider_stats[p]['deposited'] += amt
                        provider_account_stats[(p, acc)]['deposited'] += amt
                    elif typ == 'Withdrawal':
                        provider_stats[p]['withdrawn'] += abs(amt)
                        provider_account_stats[(p, acc)]['withdrawn'] += abs(amt)
        except Exception as e:
            # Transactions table may not exist yet - degrade gracefully
            print(f"[Analytics] Skipping provider breakdown (table may not exist): {e}")

        # Latest recorded sync/ingest runs per book + account
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                ingest_rows = _exec(
                    conn,
                    """
                    SELECT book,
                           COALESCE(NULLIF(account_id, ''), 'Main') AS account_id,
                           MAX(COALESCE(run_finished_at, run_started_at)) AS last_ingest_at
                    FROM book_ingest_runs
                    WHERE UPPER(COALESCE(status, '')) NOT IN ('ERROR', 'FAILED')
                    GROUP BY book, COALESCE(NULLIF(account_id, ''), 'Main')
                    """,
                ).fetchall()
                for r in ingest_rows or []:
                    if r.get('book') and r.get('last_ingest_at'):
                        _update_last_sync(r.get('book'), r.get('account_id') or 'Main', r.get('last_ingest_at'))
        except Exception:
            pass

        # Compute "computed" balances from ledger + settled bet P/L - open stakes (per provider & per account)
        bet_profit = defaultdict(float)
        bet_profit_acc = defaultdict(float)
        open_stake_prov = defaultdict(float)
        open_stake_acc = defaultdict(float)
        bets = []
        try:
            bets = self.bets or []
            if user_id and user_id != self.user_id:
                bets = [b for b in self.bets if b.get('user_id') == user_id]
            for b in bets:
                prov = _norm_prov(b.get('provider', 'Unknown'))
                acc_b = _norm_acc(b.get('account_id') or 'Main')
                if (b.get('category') or '').lower() == 'transaction':
                    continue
                if b.get('bet_type') in ('Deposit', 'Withdrawal', 'Other'):
                    continue
                _update_last_sync(prov, acc_b, b.get('created_at') or b.get('date_et') or b.get('date'))
                st = str(b.get('status') or '').upper().strip()
                if st in ('PENDING', 'OPEN'):
                    w_open = float(b.get('wager') or b.get('stake') or 0.0)
                    if w_open > 0:
                        open_stake_prov[prov] += w_open
                        open_stake_acc[(prov, acc_b)] += w_open
                    continue
                if st == 'VOID':
                    continue
                prof_v = float(b.get('profit') or 0)
                bet_profit[prov] += prof_v
                bet_profit_acc[(prov, acc_b)] += prof_v
        except Exception:
            bet_profit = defaultdict(float)
            bet_profit_acc = defaultdict(float)
            open_stake_prov = defaultdict(float)
            open_stake_acc = defaultdict(float)

        for req_p in ('DraftKings', 'FanDuel'):
            _ = provider_stats[req_p]
        for snap_p in (snap_accounts or {}).keys():
            if snap_p:
                _ = provider_stats[_norm_prov(snap_p)]

        provider_breakdown = []

        # Build per-provider + per-account breakdown using snapshots as baseline.
        for p, stats in provider_stats.items():
            net = stats['withdrawn'] - stats['deposited']

            accounts = dict(snap_accounts.get(p) or {})
            if not accounts and (p in snap_balances or p in snap_captured):
                # Backward compatible: single baseline per provider (no account snapshots yet)
                accounts = {'Main': {"balance": float(snap_balances.get(p, 0.0) or 0.0), "captured_at": snap_captured.get(p), "source": None}}

            base_accs = ['Main', 'User2'] if p in ('DraftKings', 'FanDuel') else ['Main']
            acc_ids = list(dict.fromkeys(base_accs + list(accounts.keys())))

            # account rows
            prov_total_in_play = 0.0
            prov_total_ledger_in_play = 0.0
            prov_total_ledger_delta = 0.0
            prov_last_sync_entry = None

            for acc_id in acc_ids:
                has_snapshot = acc_id in accounts
                snap = accounts.get(acc_id) if has_snapshot else {}
                base_bal = float((snap or {}).get('balance') or 0.0) if has_snapshot else 0.0
                cap0 = _to_naive_dt((snap or {}).get('captured_at')) if has_snapshot else None

                ledger_delta = 0.0
                if has_snapshot:
                    # 1) Settled bet P/L after snapshot
                    for b in (bets or []):
                        if _norm_prov(b.get('provider') or '') != p:
                            continue
                        if _norm_acc(b.get('account_id') or 'Main') != str(acc_id):
                            continue
                        st = str(b.get('status') or '').upper().strip()
                        if st in ('PENDING', 'OPEN', 'VOID'):
                            continue
                        if (b.get('category') or '').lower() == 'transaction':
                            continue
                        bc = _to_naive_dt(b.get('created_at'))
                        if cap0:
                            # Snapshot anchored: only include bets after baseline
                            if not bc:
                                continue
                            if bc <= cap0:
                                continue
                        ledger_delta += float(b.get('profit') or 0)

                    # 1b) Open/pending wagers after snapshot (reduce displayed balance immediately)
                    for b in (bets or []):
                        if _norm_prov(b.get('provider') or '') != p:
                            continue
                        if _norm_acc(b.get('account_id') or 'Main') != str(acc_id):
                            continue
                        st = str(b.get('status') or '').upper().strip()
                        if st not in ('PENDING', 'OPEN'):
                            continue
                        bc = _to_naive_dt(b.get('created_at'))
                        if cap0:
                            if not bc:
                                continue
                            if bc <= cap0:
                                continue
                        try:
                            w = float(b.get('wager') or 0.0)
                        except Exception:
                            w = 0.0
                        if w > 0:
                            ledger_delta -= w

                    # 2) Cashflows (deposits/withdrawals) after snapshot
                    # These should move the computed bankroll immediately, even before the next sportsbook snapshot.
                    try:
                        with get_db_connection() as conn:
                            from src.database import _exec
                            # Defensive migration
                            try:
                                _exec(conn, "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account_id TEXT;")
                            except Exception:
                                pass

                            tx_rows = _exec(conn, """
                                SELECT date, type, amount
                                FROM transactions
                                WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
                                  AND provider = %(prov)s
                                  AND COALESCE(account_id,'Main') = %(acc)s
                                  AND type IN ('Deposit','Withdrawal')
                            """, {"user_id": user_id, "prov": p, "acc": str(acc_id)}).fetchall()

                        for tr in tx_rows:
                            dt = _to_naive_dt(tr.get('date'))
                            if cap0 and dt and dt <= cap0:
                                continue
                            # Deposits are positive, withdrawals often negative. Add raw amount.
                            ledger_delta += float(tr.get('amount') or 0.0)
                    except Exception:
                        pass

                ledger_in_play = (base_bal + float(ledger_delta or 0)) if has_snapshot else 0.0

                prov_total_in_play += base_bal
                prov_total_ledger_in_play += ledger_in_play
                prov_total_ledger_delta += float(ledger_delta or 0)

                sync_entry = account_last_sync.get((p, str(acc_id)))
                if sync_entry is None and has_snapshot and (snap or {}).get('captured_at'):
                    _update_last_sync(p, str(acc_id), (snap or {}).get('captured_at'))
                    sync_entry = account_last_sync.get((p, str(acc_id)))
                if sync_entry and (prov_last_sync_entry is None or sync_entry > prov_last_sync_entry):
                    prov_last_sync_entry = sync_entry

                acc_stats = provider_account_stats.get((p, str(acc_id)), {'deposited': 0.0, 'withdrawn': 0.0})
                acc_dep = float(acc_stats.get('deposited') or 0.0)
                acc_wdr = float(acc_stats.get('withdrawn') or 0.0)
                acc_bet_pl = float(bet_profit_acc.get((p, str(acc_id)), 0.0))
                acc_open_st = float(open_stake_acc.get((p, str(acc_id)), 0.0))
                acc_computed = acc_dep - acc_wdr + acc_bet_pl - acc_open_st
                provider_breakdown.append({
                    "provider": p,
                    "account_id": acc_id,
                    "deposited": acc_dep,
                    "withdrawn": acc_wdr,
                    "net_profit": acc_wdr - acc_dep,
                    "bet_profit": round(acc_bet_pl, 2),
                    "open_stake": round(acc_open_st, 2),
                    "in_play": base_bal,
                    "captured_at": (snap or {}).get('captured_at') if has_snapshot else None,
                    "last_sync_at": _format_sync_iso(sync_entry),
                    "snapshot_source": (snap or {}).get('source') if has_snapshot else None,
                    "ledger_delta": float(ledger_delta),
                    "ledger_in_play": float(ledger_in_play),
                    "computed_in_play": round(acc_computed, 2),
                    "computed_delta": round(float(ledger_in_play) - float(acc_computed), 2),
                })

            # provider total row (still includes deposit/withdrawal/realized profit since those are provider-wide today)
            provider_balance = float(prov_total_in_play)
            ledger_in_play = float(prov_total_ledger_in_play)
            ledger_delta = float(prov_total_ledger_delta)
            prov_bet_pl = float(bet_profit.get(p) or 0.0)
            prov_open_st = float(open_stake_prov.get(p) or 0.0)
            computed_balance = float(stats['deposited'] or 0) - float(stats['withdrawn'] or 0) + prov_bet_pl - prov_open_st

            provider_breakdown.append({
                "provider": p,
                "account_id": None,
                "deposited": stats['deposited'],
                "withdrawn": stats['withdrawn'],
                "net_profit": net,
                "bet_profit": round(prov_bet_pl, 2),
                "open_stake": round(prov_open_st, 2),
                "in_play": provider_balance,
                "captured_at": snap_captured.get(p),
                "last_sync_at": _format_sync_iso(prov_last_sync_entry),
                "ledger_delta": ledger_delta,
                "ledger_in_play": ledger_in_play,
                "computed_in_play": round(computed_balance, 2),
                "computed_delta": round(float(ledger_in_play) - float(computed_balance), 2)
            })

        provider_breakdown.sort(key=lambda x: (x.get('provider') or '', '' if x.get('account_id') is None else str(x.get('account_id'))))

        computed_total_in_play = 0.0
        ledger_total_in_play = 0.0
        provider_totals_only = [x for x in provider_breakdown if x.get('account_id') is None]
        try:
            computed_total_in_play = round(sum(float(x.get('computed_in_play') or 0) for x in provider_totals_only), 2)
        except Exception:
            computed_total_in_play = 0.0
        try:
            ledger_total_in_play = round(sum(float(x.get('ledger_in_play') or 0) for x in provider_totals_only), 2)
        except Exception:
            ledger_total_in_play = 0.0

        return {
            "total_deposited": round(total_deposits, 2),
            "total_withdrawn": round(total_withdrawals, 2),
            "total_in_play": round(total_equity, 2),
            "realized_profit": round(realized_profit, 2),
            "net_bet_profit": round(net_bet_profit, 2),
            "ledger_total_in_play": float(ledger_total_in_play),
            "ledger_total_delta": round(float(ledger_total_in_play) - float(total_equity), 2),
            "computed_total_in_play": computed_total_in_play,
            "computed_total_delta": round(float(ledger_total_in_play) - float(computed_total_in_play), 2),
            "breakdown": provider_breakdown
        }

    def get_reconciliation_view(self, user_id=None):
        """
        Returns per-book reconciliation data for validating transaction ingestion.
        Helps identify:
        - Missing transactions
        - Misclassified bonus/adjustment types
        - Discrepancies between computed and reported balances
        """
        from src.database import get_db_connection
        from collections import defaultdict
        
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        # 1. Calculate bet profits per provider
        bet_profits = defaultdict(float)
        bet_counts = defaultdict(int)
        for b in bets:
            provider = b.get('provider', 'Unknown')
            bet_profits[provider] += b['profit']
            bet_counts[provider] += 1
        
        # 2. Aggregate transactions by provider and type
        provider_txns = defaultdict(lambda: {
            'deposits': 0.0,
            'withdrawals': 0.0,
            'bonuses': 0.0,
            'wagers': 0.0,
            'winnings': 0.0,
            'other': 0.0,
            'balance_snapshots': [],
            'txn_count': 0
        })
        
        try:
            query = """
            SELECT provider, type, amount, balance, date 
            FROM transactions
            WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
            """
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, {"user_id": user_id})
                for r in cur.fetchall():
                    provider = r['provider']
                    tx_type = (r['type'] or '').strip()
                    amount = float(r['amount'] or 0)
                    balance = r['balance']
                    
                    provider_txns[provider]['txn_count'] += 1
                    
                    if tx_type == 'Deposit':
                        provider_txns[provider]['deposits'] += abs(amount)
                    elif tx_type == 'Withdrawal':
                        provider_txns[provider]['withdrawals'] += abs(amount)
                    elif tx_type in ('Bonus', 'Promo', 'Free Bet', 'Casino Bonus'):
                        provider_txns[provider]['bonuses'] += amount
                    elif tx_type == 'Wager':
                        provider_txns[provider]['wagers'] += amount
                    elif tx_type in ('Winning', 'Payout'):
                        provider_txns[provider]['winnings'] += amount
                    elif tx_type == 'Balance':
                        # Track balance snapshots for latest reported balance
                        provider_txns[provider]['balance_snapshots'].append({
                            'balance': float(balance or 0),
                            'date': r['date']
                        })
                    else:
                        provider_txns[provider]['other'] += amount
        except Exception as e:
            print(f"[Analytics] Error fetching transactions for reconciliation: {e}")

        # 3. Build reconciliation view per provider
        all_providers = set(bet_profits.keys()) | set(provider_txns.keys())
        
        reconciliation = []
        for provider in sorted(all_providers):
            txns = provider_txns[provider]
            bet_profit = bet_profits.get(provider, 0.0)
            
            # Computed balance = Deposits + Bonuses + Bet Profit - Withdrawals
            # Alternative: Deposits + Wagers + Winnings + Bonuses - Withdrawals
            computed_balance = (
                txns['deposits'] 
                + txns['bonuses'] 
                + bet_profit 
                - txns['withdrawals']
            )
            
            # Alternative calculation using transaction wagers/winnings
            txn_based_balance = (
                txns['deposits']
                + txns['winnings']
                + txns['bonuses']
                + txns['wagers']  # typically negative
                + txns['other']
                - txns['withdrawals']
            )
            
            # Get latest reported balance
            latest_balance = None
            latest_balance_date = None
            if txns['balance_snapshots']:
                sorted_snaps = sorted(txns['balance_snapshots'], key=lambda x: x['date'] or '', reverse=True)
                latest_balance = sorted_snaps[0]['balance']
                latest_balance_date = sorted_snaps[0]['date']
            
            discrepancy = None
            if latest_balance is not None:
                discrepancy = round(latest_balance - computed_balance, 2)
            
            reconciliation.append({
                "provider": provider,
                "deposits_total": round(txns['deposits'], 2),
                "withdrawals_total": round(txns['withdrawals'], 2),
                "bonuses_total": round(txns['bonuses'], 2),
                "wagers_total": round(txns['wagers'], 2),
                "winnings_total": round(txns['winnings'], 2),
                "other_total": round(txns['other'], 2),
                "bet_profit_total": round(bet_profit, 2),
                "bet_count": bet_counts.get(provider, 0),
                "txn_count": txns['txn_count'],
                "computed_balance": round(computed_balance, 2),
                "txn_based_balance": round(txn_based_balance, 2),
                "latest_reported_balance": latest_balance,
                "latest_balance_date": latest_balance_date,
                "discrepancy": discrepancy,
                "status": "OK" if (discrepancy is None or abs(discrepancy) < 1.0) else "MISMATCH"
            })
        
        return {
            "providers": reconciliation,
            "total_providers": len(reconciliation),
            "has_discrepancies": any(r['status'] == 'MISMATCH' for r in reconciliation)
        }

    def get_all_bets(self, user_id=None):
        """Return bets only (no financial ledger rows)."""
        bets = self.bets
        if user_id and user_id != self.user_id:
            bets = [b for b in self.bets if b.get('user_id') == user_id]
        return bets

    def get_all_activity(self, user_id=None):
        """Deprecated: merges bets + some transactions.

Kept for backward compatibility, but UI should prefer bets-only endpoints.
"""
        activity = []

        bets = self.get_all_bets(user_id=user_id)

        # Add Bets
        for b in bets:
            item = b.copy()
            item['type'] = b.get('bet_type')
            item['category'] = 'Bet'
            item['amount'] = b.get('wager')
            activity.append(item)

        # (Transactions merge retained)
        query = """
            SELECT txn_id, provider, date, type, description, amount
            FROM transactions
            WHERE (user_id=%s) AND (
               type IN ('Deposit', 'Withdrawal')
               OR (type = 'Other' AND description LIKE '%%Transfer%%')
               OR (type = 'Other' AND description LIKE '%%Manual%%')
            )
            ORDER BY date DESC
        """
        try:
            with get_db_connection() as conn:
                from src.database import _exec
                cur = _exec(conn, query, (user_id,))
                for r in cur.fetchall():
                    t = dict(r)
                    amt = t['amount']
                    typ = t['type']
                    desc = t['description'] or ''
                    if 'Manual' in desc:
                        continue
                    t['category'] = 'Transaction'
                    t['bet_type'] = typ
                    t['wager'] = amt
                    if typ == 'Deposit':
                        t['profit'] = -abs(amt)
                    elif typ == 'Withdrawal':
                        t['profit'] = abs(amt)
                    else:
                        t['profit'] = 0.0
                    t['status'] = 'COMPLETED'
                    t['selection'] = desc
                    t['odds'] = None
                    activity.append(t)
        except Exception as e:
            print(f"[Analytics] Skipping transactions for activity (table may not exist): {e}")

        activity.sort(key=lambda x: x.get('date',''), reverse=True)
        return activity

    def _calculate_implied_probability(self, odds: int):
        """
        Converts American Odds to Implied Probability (0.0 - 1.0).
        """
        try:
            if odds is None: return None
            # Handle float odds (DraftKings sometimes?)
            odds = float(odds)
            if odds > 0:
                return 100 / (odds + 100)
            else:
                return abs(odds) / (abs(odds) + 100)
        except:
            return None

    def calculate_clv(self, placed_odds, closing_odds):
        """
        Calculates CLV %.
        (Implied(Placed) - Implied(Closing)) / Implied(Closing)
        """
        prob_placed = self._calculate_implied_probability(placed_odds)
        prob_closing = self._calculate_implied_probability(closing_odds)
        
        if not prob_placed or not prob_closing:
            return None
            
        return ((prob_placed - prob_closing) / prob_closing) * 100

    def _extract_player_names(self, text):
        """
        Heuristic to find player names in text.
        Strategies:
        1. "Name - Prop" pattern (Common in FanDuel: "Jalen Hurts - Alt Passing Yds")
        2. "Name Any Time Touchdown" pattern
        3. General 2-word capitalized fallback
        """
        import re
        ignored_words = {
            "Over", "Under", "Total", "Points", "Yards", "Assists", "Rebounds", "Touchdown", 
            "Scorer", "Moneyline", "Spread", "First", "Half", "Quarter", "Any", "Time", 
            "Alternate", "Passing", "Rushing", "Receiving", "Rec", "Yds", "Pts", "Threes", 
            "Made", "To", "Score", "Record", "Double", "Triple", "Parlay", "Same", "Game", 
            "Leg", "Team", "Win", "Loss", "Draw", "Alt", "Prop", "Live", "Bonus", "Boost",
            "Buffalo", "Bills", "Miami", "Dolphins", "Detroit", "Lions", "Chicago", "Bears",
            "Green", "Bay", "Packers", "San", "Francisco", "49ers", "Kansas", "City", "Chiefs",
            "Philadelphia", "Eagles", "Dallas", "Cowboys", "New", "York", "Giants", "Jets",
            "Denver", "Broncos", "Indiana", "Pacers", "Oregon", "Ducks", "Ohio", "State",
            "Notre", "Dame", "USC", "Trojans", "Michigan", "Wolverines", "Georgia", "Bulldogs"
        }
        
        candidates = set()
        
        # Strategy 1: FanDuel "Name - Prop" lookahead
        # Matches "Jalen Hurts - Alt"
        hyphen_matches = re.finditer(r'\b([A-Z][a-z]+ [A-Z][a-z]+)(?=\s+-)', text)
        for m in hyphen_matches:
            name = m.group(1)
            parts = name.split()
            if parts[0] in ignored_words or parts[1] in ignored_words: continue
            if "Alt " not in name:
                candidates.add(name)

        # Strategy 2: "Name Any Time Touchdown" or "Name To Score"
        # "Kyren Williams Any Time Touchdown"
        # "Pascal Siakam To Score"
        prop_matches = re.finditer(r'\b([A-Z][a-z]+ [A-Z][a-z]+)\s+(?:Any Time|To Score|Over|Under)\b', text)
        for m in prop_matches:
            name = m.group(1)
            parts = name.split()
            if parts[0] in ignored_words or parts[1] in ignored_words: continue
            candidates.add(name)

        # Strategy 3: General Fallback (if specific patterns fail)
        if not candidates:
            matches = re.finditer(r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b', text)
            for m in matches:
                first, last = m.groups()
                if first in ignored_words or last in ignored_words:
                    continue
                # Length check to avoid abbreviations like "Alt Yds" if regex missed
                if len(first) < 3 and first != "Ty" and first != "AJ" and first != "DJ": continue 
                
                candidates.add(f"{first} {last}")
            
        return list(candidates)
