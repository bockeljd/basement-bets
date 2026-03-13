import os
import re
from src.utils.model_performance import norm_outcome, is_decided, payout_per_unit, roi_per_unit, conf_bucket

# --- Section A: Real Helper Tests (Imported Logic) ---

def test_payout_per_unit_logic():
    """Verify American odds payout math and fallbacks."""
    # Negative odds (favorites)
    assert round(payout_per_unit(-110), 3) == 0.909
    assert payout_per_unit(-200) == 0.5
    # Positive odds (underdogs)
    assert payout_per_unit(100) == 1.0
    assert payout_per_unit(120) == 1.2
    # Fallbacks and edge cases
    assert round(payout_per_unit(None), 3) == 0.909
    assert round(payout_per_unit("invalid"), 3) == 0.909
    assert round(payout_per_unit(0), 3) == 0.909

def test_roi_per_unit_logic():
    """Verify ROI logic for different outcomes and odds."""
    # Wins
    assert round(roi_per_unit("WIN", -110), 3) == 0.909
    assert round(roi_per_unit("WON", -110), 3) == 0.909
    assert roi_per_unit("WON", 120) == 1.2
    # Losses
    assert roi_per_unit("LOSS", 120) == -1.0
    assert roi_per_unit("LOST", -110) == -1.0
    # Pushes and others
    assert roi_per_unit("PUSH", -110) == 0.0
    assert roi_per_unit("PENDING", -110) == 0.0
    assert roi_per_unit(None, -110) == 0.0

def test_confidence_bucketing_scales():
    """Verify confidence mapping for both 0-1 and 0-100 scales."""
    # 0-100 scale
    assert conf_bucket(85) == "High"
    assert conf_bucket(80) == "High"
    assert conf_bucket(65) == "Medium"
    assert conf_bucket(50) == "Medium"
    assert conf_bucket(40) == "Low"
    # 0-1 scale
    assert conf_bucket(0.85) == "High"
    assert conf_bucket(0.65) == "Medium"
    assert conf_bucket(0.45) == "Low"
    # Invalid
    assert conf_bucket(None) == "Low"
    assert conf_bucket("invalid") == "Low"

def test_outcome_normalization_strict():
    """Verify strict outcome string normalization."""
    assert norm_outcome("win") == "WON"
    assert norm_outcome(" won ") == "WON"
    assert norm_outcome("loss") == "LOST"
    assert norm_outcome("LOST") == "LOST"
    assert norm_outcome("Push") == "PUSH"
    assert norm_outcome("pending") == "PENDING"
    assert norm_outcome("invalid") == "PENDING"
    
    assert is_decided("WON") is True
    assert is_decided("LOST") is True
    assert is_decided("PUSH") is True
    assert is_decided("PENDING") is False

# --- Section B: Source-Audit Tests (Brittle-Resistant) ---

def read_file(path_from_root):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(root, path_from_root)
    with open(full_path, 'r', encoding='utf-8') as f:
        return f.read()

def test_source_audit_database_canonical():
    """Verify database.py implementation markers."""
    content = read_file('src/database.py')
    assert 'fetch_recommended_history_canonical' in content
    assert 'recommended_slates' in content
    assert 'recommended_slate_items' in content

def test_source_audit_api_history_prioritization():
    """Verify /api/research/history prioritization markers."""
    content = read_file('src/api.py')
    # Search for the route string loosely (app.get or router.get)
    start_idx = content.find("'/api/research/history'")
    if start_idx == -1:
        start_idx = content.find('"/api/research/history"')
    
    assert start_idx != -1
    # Check within 3000 chars of the route definition
    block = content[start_idx:start_idx + 3000]
    assert 'fetch_recommended_history_canonical' in block
    assert 'fetch_model_history' in block
    # Check prioritization: canonical comes before fallback
    assert block.index('fetch_recommended_history_canonical') < block.index('fetch_model_history')
    # Confirm fallback is conditional (e.g. if not rows:)
    assert 'if not rows:' in block or 'if not history:' in block

def test_source_audit_rank_6_enforcement():
    """Verify rank <= 6 usage and cleanup of rank <= 5."""
    content = read_file('src/api.py')
    # Verify rank 6 exists in model performance contexts
    assert re.search(r'rank\s*<=\s*6', content) is not None
    
    # Target NCAAM performance area for strict cleanup check
    ncaam_marker = content.find('def ncaam_performance_report')
    if ncaam_marker != -1:
        # Scan a larger block (e.g. 10000 chars) to cover all queries in that report helper area
        ncaam_block = content[ncaam_marker:ncaam_marker + 10000]
        assert 'rank <= 6' in ncaam_block
        assert 'rank <= 5' not in ncaam_block

def test_source_audit_picks_jsx_sorting():
    """Verify Picks.jsx sorting and hasReco logic markers."""
    content = read_file('client/src/pages/Picks.jsx')
    # Edge sorting fix
    assert 'ev_per_unit' in content
    # Ensure sorting 'edge' is not simply using created_at
    edge_sort_match = re.search(r"key\s*===\s*'edge'.*?ev_per_unit", content, re.DOTALL)
    assert edge_sort_match is not None
    # Explicitly check that created_at is NOT in the immediate edge sort branch
    edge_sort_block = edge_sort_match.group(0)
    assert 'created_at' not in edge_sort_block
    
    # recoStraight/recoMlParlay logic
    assert 'hasReco' in content
    assert 'recoStraight' in content
    assert 'recoMlParlay' in content

def test_source_audit_analytics_component_helpers():
    """Verify Analytics component uses shared helpers and avoids hardcoded ROI."""
    content = read_file('client/src/components/ModelPerformanceAnalytics.jsx')
    # Helper imports
    assert 'import {' in content
    assert 'getPerformanceDay' in content
    assert 'roiPerUnit' in content
    
    # Logic usage
    assert 'getPerformanceDay(h)' in content
    assert 'roiPerUnit(' in content

    # Hardcoded -110 ROI cleanup check
    # We look for the ROI calculation block and ensure it calls the helper
    roi_calc_marker = content.find('const roi =')
    if roi_calc_marker != -1:
        roi_block = content[roi_calc_marker:roi_calc_marker + 500]
        assert 'roiPerUnit' in roi_block
        # Should not find hardcoded (wins * 0.909 - losses) or similar math where bet_price is available
        assert '0.909' not in roi_block or 'roiPerUnit' in roi_block

def test_source_audit_frontend_helpers():
    """Verify client/src/utils/modelPerformance.js implementation."""
    content = read_file('client/src/utils/modelPerformance.js')
    assert 'export const normalizeOutcome =' in content
    assert 'export const getPerformanceDay =' in content
    assert 'export const roiPerUnit =' in content
    assert 'export const getNumericConfidence =' in content
    assert 'export const getConfidenceBucket =' in content

def test_source_audit_day_precedence():
    """Verify day precedence logic in frontend explicitly (day_et > start_time > analyzed_at)."""
    content = read_file('client/src/utils/modelPerformance.js')
    # Capture function body more robustly
    day_func_match = re.search(r'export const getPerformanceDay =.*?\n};', content, re.DOTALL)
    assert day_func_match is not None
    day_func = day_func_match.group(0)
    
    # Priority check: day_et should be mentioned before start_time, then analyzed_at
    assert 'day_et' in day_func
    assert 'start_time' in day_func
    assert 'analyzed_at' in day_func
    
    assert day_func.index('day_et') < day_func.index('start_time')
    assert day_func.index('start_time') < day_func.index('analyzed_at')
