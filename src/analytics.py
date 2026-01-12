from collections import defaultdict
from database import fetch_all_bets

class AnalyticsEngine:
    def __init__(self):
        self.bets = fetch_all_bets()

    def get_summary(self):
        total_wagered = sum(b['wager'] for b in self.bets)
        net_profit = sum(b['profit'] for b in self.bets)
        roi = (net_profit / total_wagered * 100) if total_wagered > 0 else 0.0
        wins = sum(1 for b in self.bets if b['status'] == 'WON')
        total = len(self.bets)
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        return {
            "total_bets": total,
            "total_wagered": total_wagered,
            "net_profit": net_profit,
            "roi": roi,
            "win_rate": win_rate
        }

    def get_breakdown(self, field: str):
        """
        Groups bets by a field (sport, bet_type) and calculates metrics.
        """
        groups = defaultdict(lambda: {'wager': 0.0, 'profit': 0.0, 'wins': 0, 'total': 0})
        
        for b in self.bets:
            key = b[field]
            groups[key]['wager'] += b['wager']
            groups[key]['profit'] += b['profit']
            groups[key]['total'] += 1
            if b['status'] == 'WON':
                groups[key]['wins'] += 1
                
        results = []
        for key, data in groups.items():
            win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
            results.append({
                field: key,
                "bets": data['total'],
                "wagered": data['wager'],
                "profit": data['profit'],
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
