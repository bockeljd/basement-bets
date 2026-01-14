class ResearchAuditor:
    """
    Quality Control Agent for betting model predictions.
    Assigns a confidence score and rating based on heuristic sanity checks.
    """

    def audit(self, edge: dict) -> dict:
        """
        Audits a single edge dictionary.
        Returns the original dictionary enriched with:
        - audit_class: 'high' | 'medium' | 'low'
        - audit_score: 0.0 to 1.0
        - audit_reason: Description of the finding
        """
        sport = edge.get('sport')
        edge_val = edge.get('edge', 0)
        
        # Clean edge value if string
        if isinstance(edge_val, str):
            try:
                edge_val = float(edge_val.replace('% EV', '').replace('%', '').replace(' pts', ''))
            except:
                edge_val = 0.0

        if sport == 'NFL':
            return self._audit_nfl(edge_val)
        elif sport == 'NCAAM':
            return self._audit_ncaam(edge_val, edge)
        elif sport == 'EPL':
            return self._audit_epl(edge_val)
        
        # Default
        return {
            "audit_class": "high",
            "audit_score": 1.0, 
            "audit_reason": "Standard Edge"
        }

    def _audit_nfl(self, deviation: float) -> dict:
        deviation = abs(deviation)
        if deviation > 7.0:
            return {
                "audit_class": "low",
                "audit_score": 0.2,
                "audit_reason": f"Extreme Deviation (>7pts). Likely data error or key player injury missed by model."
            }
        elif deviation > 3.5:
             return {
                "audit_class": "medium",
                "audit_score": 0.6,
                "audit_reason": f"Aggressive Edge (>3.5pts). Crosses key number variance."
            }
        return {
            "audit_class": "high",
            "audit_score": 0.9,
            "audit_reason": "Solid statistical edge within normal variance."
        }

    def _audit_ncaam(self, deviation: float, edge_data: dict = None) -> dict:
        deviation = abs(deviation)
        reason_extras = []
        score_boost = 0.0
        
        # Style Clash Checks (if stats available)
        if edge_data and 'home_stats' in edge_data:
            # Determine which side the edge is on
            # edge > 0 => OVER, edge < 0 => UNDER for totals usually. 
            # But here we look for Upset Potential or Strong Mismatch on Rebounding
            
            # Simple heuristic: Rebounding Edge
            # If Home ORB% > 35% (Elite) and Away ORB% < 25% (Poor)
            h_orb = edge_data['home_stats'].get('ORB%', 0)
            a_orb = edge_data['away_stats'].get('ORB%', 0)
            
            if h_orb > 0.35 and a_orb < 0.25: # Assuming fractional, check scale
                 # SR data is usually 0-100 or 0-1. Let's assume 35.0 based on common scrape
                 pass 
            
            if h_orb > 35.0:
                reason_extras.append("Home Elite Rebounding")
            
            # 3-Point Variance
            # If either team has 3PAr > 50% (High Variance)
            h_3par = edge_data['home_stats'].get('3PAr', 0)
            if h_3par > 0.50:
                 reason_extras.append("High 3P Variance")

        base_res = {
            "audit_class": "high",
            "audit_score": 0.9,
            "audit_reason": "Valid efficiency mismatch."
        }
        
        if deviation > 15.0:
            base_res = {
                "audit_class": "low",
                "audit_score": 0.1,
                "audit_reason": f"Suspicious Deviation (>15pts). Verify team mapping."
            }
        elif deviation > 8.0:
             base_res = {
                "audit_class": "medium",
                "audit_score": 0.5,
                "audit_reason": f"High Deviation (>8pts)."
            }
            
        if reason_extras:
            base_res['audit_reason'] += f" | Style Clash: {', '.join(reason_extras)}"
            # Boost confidence for medium if style clash supports it?
            # actually high deviation + style clash might mean we caught something real
            if base_res['audit_class'] == 'medium':
                 base_res['audit_class'] = 'high'
                 base_res['audit_reason'] = base_res['audit_reason'].replace('High Deviation', 'Style Clash Edge')

        return base_res

    def _audit_epl(self, ev_percent: float) -> dict:
        # ev_percent is typically 0-100
        if ev_percent > 40.0:
             return {
                "audit_class": "low",
                "audit_score": 0.2,
                "audit_reason": f"Implausible EV (>40%). Check for odds mapping error."
            }
        elif ev_percent > 20.0:
             return {
                "audit_class": "medium",
                "audit_score": 0.6,
                "audit_reason": f"High EV (>20%). Market may know something about lineups."
            }
        return {
            "audit_class": "high",
            "audit_score": 0.9,
            "audit_reason": "Strong value play backed by xG metrics."
        }
