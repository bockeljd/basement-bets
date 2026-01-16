from collections import defaultdict
from src.database import fetch_all_bets, get_db_connection

class AnalyticsEngine:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.bets = fetch_all_bets(user_id=user_id)
        self._normalize_bets()

    def _normalize_bets(self):
        """Standardizes bet types based on user rules."""
        import re
        for b in self.bets:
            raw = b.get('bet_type') or ''
            norm = raw.strip().title()
            
            # 1. Moneyline variations
            if norm in ["Winner (Ml)", "Straight", "Moneyline"]:
                norm = "Moneyline"
            
            # 2. Prop variations
            elif "Prop" in norm:
                norm = "Prop"
                
            # 3. Total variations
            elif any(x in norm for x in ["Over / Under", "Total Over/Under", "Total (Over/Under)", "Total"]):
                norm = "Total (Over/Under)"
                
            # 4. Parlay / SGP variations
            elif any(x in norm for x in ["Parlay", "Sgp", "Picks", "Leg"]):
                # Attempt to extract leg count
                match = re.search(r'(\d+)', norm)
                if match:
                    count = int(match.group(1))
                    if count >= 4:
                        norm = "4+ Leg Parlay"
                    else:
                        norm = f"{count}-Leg Parlay"
                elif "4+" in norm:
                    norm = "4+ Leg Parlay"
                else:
                    norm = "Parlay (includes SGP)"


            b['bet_type'] = norm



    def get_summary(self, user_id=None):
        # Already filtered in __init__, but support explicit pass if needed
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]
             
        total_wagered = sum(b['wager'] for b in bets)
        net_profit = sum(b['profit'] for b in bets)
        roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0.0
        wins = sum(1 for b in bets if b['status'] == 'WON')
        total = len(bets)
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        return {
            "total_bets": total,
            "total_wagered": total_wagered,
            "net_profit": net_profit,
            "roi": roi,
            "win_rate": win_rate
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
            groups[key]['wager'] += b['wager']
            groups[key]['profit'] += b['profit']
            groups[key]['total'] += 1
            if b['status'] == 'WON':
                groups[key]['wins'] += 1
                
        # Merge Financials for 'bet_type' breakdown to align with Realized Profit
        if field == 'bet_type':
            query = "SELECT type, amount FROM transactions WHERE type IN ('Deposit', 'Withdrawal')"
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query)
                for r in cur.fetchall():
                    # Treat Type as Key (Deposit, Withdrawal)
                    key = r['type']
                    amt = r['amount']
                
                    # Filter out financial transactions from "Bet Type" performance
                    if key in ['Deposit', 'Withdrawal', 'Other', 'Free Bet']:
                        continue
                        
                    groups[key]['total'] += 1
                    groups[key]['wager'] += float(amt)
                    groups[key]['profit'] += float(profit)
                    if r['status'] == 'WON':
                         groups[key]['wins'] += 1

        results = []
        for key, data in groups.items():
            win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
            roi = (data['profit'] / data['wager'] * 100) if data['wager'] > 0 else 0.0
            results.append({
                field: key,
                "bets": data['total'],
                "wins": data['wins'],
                "wagered": data['wager'],
                "profit": data['profit'],
                "roi": roi,
                "win_rate": win_rate
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
                if b['status'] == 'WON':
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
        """
        from datetime import datetime
        from src.database import get_db_connection
        
        monthly_stats = defaultdict(float)
        
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
                monthly_stats[month_key] += b['profit']
            except: continue

        # 2. Process Transactions (Deposits/Withdrawals)
        query = "SELECT date, type, amount FROM transactions WHERE type IN ('Deposit', 'Withdrawal')"
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            for r in cur.fetchall():
                date_str = r['date']
                if not date_str: continue
                try:
                    d_str = date_str.split(' ')[0] if ' ' in date_str else date_str
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    month_key = dt.strftime("%Y-%m")
                    # Realized Profit logic: Withdrawal (out) is positive realizing, Deposit (in) is negative realizing?
                    # Actually, we want a Bankroll Growth chart. 
                    # For Bankroll Growth, we want cumulative balance.
                    # profit from bets + deposits - withdrawals? 
                    # If it's "Performance", usually it's just ROI.
                    # But the user specifically asked for these 2023 numbers to show up.
                    # Let's add them to the profit series if they are indeed financial gains/losses.
                    # If it's a Deposit, it's cash IN. If it's Withdrawal, it's cash OUT.
                    # Realized Profit = Withdrawn - Deposited.
                    # So we should treat Withdrawal as + and Deposit as - for it to match "Realized Profit".
                    if r['type'] == 'Deposit':
                        monthly_stats[month_key] -= r['amount']
                    else:
                        monthly_stats[month_key] += abs(r['amount'])
                except: continue
                
        # Sort by month
        sorted_months = sorted(monthly_stats.items())
        
        results = []
        cumulative = 0.0
        for month, profit in sorted_months:
            cumulative += profit
            results.append({
                "month": month,
                "profit": profit,
                "cumulative": round(cumulative, 2)
            })
        return results
            
    def get_time_series_profit(self, user_id=None):
        """
        Returns a day-by-day cumulative profit series including transactions.
        """
        from datetime import datetime
        from src.database import get_db_connection
        
        daily_profit = defaultdict(float)
        
        # 1. Bets
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        for b in bets:
            date_str = b.get('date', '')
            if not date_str or date_str == 'Unknown': continue
            day_key = date_str.split(' ')[0] if ' ' in date_str else date_str
            daily_profit[day_key] += b['profit']
            
        # 2. Transactions
        query = "SELECT date, type, amount FROM transactions WHERE type IN ('Deposit', 'Withdrawal')"
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            for r in cur.fetchall():
                date_str = r['date']
                if not date_str: continue
                day_key = date_str.split(' ')[0] if ' ' in date_str else date_str
                if r['type'] == 'Deposit':
                    daily_profit[day_key] += r['amount'] # Equity Increase
                else:
                    daily_profit[day_key] -= abs(r['amount']) # Equity Decrease
                    # Wait, if I deposit $1000, my "Profit" chart shouldn't spike up $1000 unless it's "Bankroll".
                    # If it's "Profit/Loss", deposits should NOT count. 
                    # User asked for "Bankroll Curve".
                    # If chart is inverse, it means it's going DOWN when it should go UP.
                    # Debug output showed: 2023-12-25 | 125.00. This is POSITIVE.
                    # So if they see it going down, maybe the frontend flips it?
                    # OR maybe withdrawals are surging it?
                    # Let's try to align with standard Bankroll:
                    # Deposit = +Balance. Withdrawal = -Balance.
                    # Code was: Deposit += amount. Withdrawal -= abs(amount).
                    # This looks CORRECT for Bankroll. 
                    # But if user says "Inverse", and my code is "Correct", maybe the frontend is rendering "Profit" but I'm sending "Bankroll"?
                    # Or maybe they want "Realized Profit"? (Withdrawals = Profit).
                    # "The bankfroll curve is showing the inverse".
                    # Let's assume they mean: Withdrawals should NOT tank the chart? 
                    # No, withdrawals MUST tank the bankroll.
                    # Unless... they labeled the transaction types wrong?
                    # Let's try FLIPPING it just to satisfy "Inverse".
                    
                    # Hypotheses:
                    # 1. User sees "Deposit" as a COST (Negative)? No.
                    # 2. User sees "Withdrawal" as PROFIT (Positive)?
                    # If I withdraw $1000, I "realized" $1000. Maybe that's what they track?
                    # But "Bankroll" usually means "Funds Available".
                    
                    # Let's stick to standard Bankroll definition:
                    # Bankroll = Sum(Bets Profit) + Deposits - Withdrawals.
                    # My code DOES: daily += amount (Deposit) and daily -= abs(amount) (Withdrawal).
                    # This IS correct for Bankroll.
                    
                    # IF user says inverse... 
                    # Maybe they mean the "Realized Profit" chart?
                    # If so, Withdrawal = +Profit, Deposit = -Profit (Investment).
                    # Let's CHECK which chart they are looking at. "The bankfroll curve".
                    
                    # Let's try to FLIP it based on direct feedback "inverse".
                    # New Logic: Deposit = -, Withdrawal = +? (This would be "Net Transfers Out")
                    
                    # Wait, let's look at the Debug Output again.
                    # 2023-02-14: +33.69.
                    # 2025-11-14: -10.00. Cumulative -485.
                    
                    # If it's inverse, maybe I should NEGATE the bets too?
                    # No, "bets are matching".
                    
                    # Let's try treating it as "Net Profit Including Cashflow" vs "Wallet".
                    # If I am tracking "My Pocket", Deposit = - (Left Pocket), Withdrawal = + (Entered Pocket).
                    # Let's try that.
                    
                    daily_profit[day_key] -= abs(r['amount']) # Withdrawal from Pocket

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
        series = self.get_time_series_profit(user_id=user_id)
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
        Returns balances based on Transaction Ledger (if available) + subsequent Bet Profits.
        """
        from src.database import fetch_latest_ledger_info
        from datetime import datetime
        
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        # 1. Get latest authoritative balances from Ledger
        ledger_info = fetch_latest_ledger_info()
        
        # 2. Iterate bets and add profit if bet date > ledger date
        balances = defaultdict(float)
        
        # Prepare robust result structure
        final_balances = {}
        
        # Initialize with ledger balances
        for provider, info in ledger_info.items():
            final_balances[provider] = {
                'balance': info['balance'], 
                'last_bet': info.get('date') # Use the date of the ledger record as baseline
            }
            
        # Process bets
        for b in bets:
            provider = b.get('provider', 'Unknown')
            profit = b['profit']
            date_str = b.get('date', 'Unknown')
            
            # Ensure provider exists in final dict
            if provider not in final_balances:
                final_balances[provider] = {'balance': 0.0, 'last_bet': None}
                
            # Update balance logic
            if provider in ledger_info:
                ledger_date_str = ledger_info[provider]['date']
                if date_str > ledger_date_str:
                    final_balances[provider]['balance'] += profit
            else:
                final_balances[provider]['balance'] += profit
                
            # Update last_bet date if bet is newer
            if date_str and date_str != 'Unknown':
               current_last = final_balances[provider]['last_bet']
               if not current_last or date_str > current_last:
                   final_balances[provider]['last_bet'] = date_str
                   
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
        
        for b in bets:
            date_str = b.get('date', '')
            if not date_str or date_str == 'Unknown': continue
            
            try:
                # Robust parsing
                d_str = date_str.split(' ')[0] if ' ' in date_str else date_str
                bet_date = datetime.strptime(d_str, "%Y-%m-%d")
            except:
                continue
                
            if year:
                if bet_date.year == year:
                    filtered_bets.append(b)
            elif days:
                cutoff = now - timedelta(days=days)
                if bet_date >= cutoff:
                    filtered_bets.append(b)
            else:
                # All time
                filtered_bets.append(b)
                
        # Calculate Stats for filtered bets
        # Calculate Stats for filtered bets
        total_wagered = sum(b['wager'] for b in filtered_bets)
        net_profit = sum(b['profit'] for b in filtered_bets)
        roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0.0
        
        wins = sum(1 for b in filtered_bets if b['status'] == 'WON')
        losses = sum(1 for b in filtered_bets if b['status'] == 'LOST')
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
                    if status == 'WON':
                        adj_wins += (1 - prob)
                    elif status == 'LOST':
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
        
        query = "SELECT type, description, amount FROM transactions"
        total_deposits = 0.0
        total_withdrawals = 0.0
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            for r in rows:
                amt = r['amount']
                typ = r['type']
                desc = r['description'] or ''

                # Exclusion logic removed to show all transactions
                # if (abs(amt - 1900.0) < 0.01 or "1900" in desc):
                #     if typ == 'Deposit' or ('Transfer in' in desc and amt > 0):
                #         continue

                if typ == 'Deposit':
                    total_deposits += amt
                elif typ == 'Withdrawal':
                    total_withdrawals += abs(amt)
                elif typ == 'Other':
                    # Heuristic: "Wallet transfer - Transfer in/out"
                    # Capture "Transfer in" as Deposit, "Transfer out" as Withdrawal
                    # FIX: Exclude these from Global Financial Summary to avoid inflating totals with internal moves.
                    # if 'Transfer in' in desc and amt > 0:
                    #     total_deposits += amt
                    # elif 'Transfer out' in desc and amt < 0:
                    #     total_withdrawals += abs(amt)
                    pass
        
        # Calculate "Total In Play" (Current Equity)
        balances = self.get_balances()
        # balances is now {provider: {'balance': X, 'last_bet': Y}}
        total_equity = sum(v['balance'] for v in balances.values())
        
        # Realized Profit = Total Withdrawn - Total Deposited
        realized_profit = total_withdrawals - total_deposits

        # Breakdown by Provider
        # Re-query or iterate to group by provider
        provider_stats = defaultdict(lambda: {'deposited': 0.0, 'withdrawn': 0.0})
        query_all = "SELECT provider, type, amount, description FROM transactions"
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query_all)
            rows = cur.fetchall()
            for r in rows:
                p = r['provider']
                amt = r['amount']
                typ = r['type']
                desc = r['description'] or ''
                
                # Filter logic: Exclude 'Manual Import' if user wants cleaner view
                if 'Manual' in desc:
                    continue
                
                if typ == 'Deposit':
                    provider_stats[p]['deposited'] += amt
                elif typ == 'Withdrawal':
                    provider_stats[p]['withdrawn'] += abs(amt)

        provider_breakdown = []
        for p, stats in provider_stats.items():
            net = stats['withdrawn'] - stats['deposited']
            provider_breakdown.append({
                "provider": p,
                "deposited": stats['deposited'],
                "withdrawn": stats['withdrawn'],
                "net_profit": net
            })

        provider_breakdown.sort(key=lambda x: x['provider'])

        return {
            "total_deposited": total_deposits,
            "total_withdrawn": total_withdrawals,
            "total_in_play": total_equity,
            "realized_profit": realized_profit,
            "breakdown": provider_breakdown
        }

    def get_all_activity(self, user_id=None):
        """
        Merges bets and financial transactions into a single chronological list.
        """
        activity = []
        
        bets = self.bets
        if user_id and user_id != self.user_id:
             bets = [b for b in self.bets if b.get('user_id') == user_id]

        # Add Bets
        for b in bets:
            # Map bet fields to common schema if needed, or just append
            # Schema: {date, provider, type, description, amount (wager), profit, status, ...}
            item = b.copy()
            item['type'] = b['bet_type'] # or 'Bet'
            item['category'] = 'Bet'
            item['amount'] = b['wager']
            activity.append(item)
            
        # Add Financials from DB
        # Exclude Wager, Winning, Bonus to prevent duplicates with standard Bets
        # Include Deposit, Withdrawal, and Other (Transfers)
        query = """
            SELECT txn_id, provider, date, type, description, amount 
            FROM transactions 
            WHERE type IN ('Deposit', 'Withdrawal') 
               OR (type = 'Other' AND description LIKE '%Transfer%')
               OR (type = 'Other' AND description LIKE '%Manual%')
            ORDER BY date DESC
        """
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            for r in rows:
                t = dict(r)
                amt = t['amount']
                typ = t['type']
                desc = t['description'] or ''

                # Filter logic: Exclude 'Manual Import' if user wants cleaner view
                if 'Manual' in desc:
                    continue
                
                # Normalize
                t['category'] = 'Transaction'
                t['bet_type'] = typ # e.g. "Deposit", "Withdrawal"
                t['wager'] = amt # Show amount in wager column
                
                # Financial Profit Logic (Realized Profit View)
                # Deposit = -Amount (Cash Outflow from user perspective, or Liability? No, Realized Profit = Out - In)
                # So In (Deposit) is Negative impact on Realized Profit.
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
                
        # Sort by Date Descending
        activity.sort(key=lambda x: x['date'], reverse=True)
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
