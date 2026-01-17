
from pydantic import BaseModel, model_validator, Field
from typing import Optional, List, Dict

class MarketSnapshot(BaseModel):
    """
    Consolidated market snapshot for an event.
    Standardized to Home Team perspective for Spread.
    """
    spread_home: float # Home - Away (e.g., -5.5)
    total_line: float
    moneyline_home: Optional[float] = None
    moneyline_away: Optional[float] = None
    implied_prob_home: Optional[float] = None
    
    @model_validator(mode='after')
    def check_spread_consistency(self):
        # We can implement minimal logic here if needed, but primary canonicalization
        # often happens before or during instantiation.
        return self
    
class TorvikMetrics(BaseModel):
    """
    Efficiency metrics from BartTorvik.
    """
    adj_oe_home: float
    adj_de_home: float
    adj_oe_away: float
    adj_de_away: float
    tempo_home: float
    tempo_away: float
    is_neutral: bool = False
    
class Signal(BaseModel):
    """
    Structured signal for adjustment.
    """
    category: str # INJURY, TRAVEL, MOTIVATION, LINEUP
    target: str # HOME, AWAY, TOTAL
    impact_points: float # +ve favors Home (for Spread), +ve favors Over (for Total)
    confidence: float # 0.0 to 1.0
    description: str

class ModelInput(BaseModel):
    """
    Full input payload for the NCAAM Market-First Model.
    """
    event_id: str
    home_team: str
    away_team: str
    market: MarketSnapshot
    metrics: TorvikMetrics
    signals: List[Signal] = Field(default_factory=list)

class PredictionComponent(BaseModel):
    mu_market: float
    mu_torvik: float
    delta: float
    signal_adj: float
    conf_signals: float = 0.0
    
    # Detailed Breakdowns (Reference)
    mu_market_margin: float = 0.0
    mu_market_total: float = 0.0
    mu_torvik_margin: float = 0.0
    mu_torvik_total: float = 0.0
    delta_margin: float = 0.0
    delta_total: float = 0.0
    mu_final_margin: float = 0.0
    mu_final_total: float = 0.0


class PredictionResult(BaseModel):
    score_home: float
    score_away: float
    mu_final_margin: float
    mu_final_total: float
    prob_cover: float
    prob_over: float
    edge_cover: float
    edge_over: float

class OpportunityRanking(BaseModel):
    ev_units: float
    edge_margin: float # Difference in points
    confidence_score: float # 0-100
    is_allowed: bool
    
class ModelSnapshot(BaseModel):
    """
    Final Output of the model.
    """
    prediction: PredictionResult
    market_snapshot: MarketSnapshot
    torvik_metrics: TorvikMetrics
    components: PredictionComponent
    ranking: Optional[OpportunityRanking] = None
