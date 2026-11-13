"""Shared monotonic piecewise-linear (PAVA) calibration helpers."""

from __future__ import annotations

import json
import os
from typing import Any, Dict


def resolve_model_param_path(filename: str) -> str:
    """Resolve a model parameter JSON path from bundled service params or data/model_params."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    bundled_path = os.path.join(repo_root, "src", "services", "model_params", filename)
    if os.path.exists(bundled_path):
        return bundled_path
    return os.path.join(repo_root, "data", "model_params", filename)


def load_winprob_calibration(param_key: str, filename: str) -> Dict[str, Any]:
    """Load calibration curve from DB model_params_store first, falling back to local JSON."""
    try:
        from src.database import get_model_param

        db_cal = get_model_param(param_key)
        if isinstance(db_cal, dict) and (db_cal.get("points") or []):
            return db_cal
    except Exception:
        pass

    path = resolve_model_param_path(filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"points": []}
    except Exception:
        return {"points": []}


def interpolate_pava_prob(
    p: Any,
    calibration: Dict[str, Any] | None,
    *,
    min_obs: int = 0,
    blend_weight: float = 1.0,
) -> float:
    """Apply monotonic piecewise-linear calibration to probability p with optional raw shrinkage."""
    try:
        p_val = float(p)
    except Exception:
        return p

    if not isinstance(calibration, dict):
        return p_val

    try:
        n_obs = int(calibration.get("n_obs") or 0)
    except Exception:
        n_obs = 0
    if min_obs > 0 and n_obs < min_obs:
        return p_val

    pts = calibration.get("points") or []
    xs = [float(x.get("p")) for x in pts if x and x.get("p") is not None and x.get("p_cal") is not None]
    ys = [float(x.get("p_cal")) for x in pts if x and x.get("p") is not None and x.get("p_cal") is not None]
    if len(xs) != len(ys) or len(xs) < 2:
        return p_val

    if p_val <= xs[0]:
        p_cal = max(0.0, min(1.0, ys[0]))
    elif p_val >= xs[-1]:
        p_cal = max(0.0, min(1.0, ys[-1]))
    else:
        p_cal = p_val
        for i in range(1, len(xs)):
            if p_val <= xs[i]:
                x0, x1 = xs[i - 1], xs[i]
                y0, y1 = ys[i - 1], ys[i]
                if x1 == x0:
                    p_cal = max(0.0, min(1.0, y1))
                else:
                    t = (p_val - x0) / (x1 - x0)
                    p_cal = max(0.0, min(1.0, y0 + t * (y1 - y0)))
                break

    w = max(0.0, min(1.0, float(blend_weight)))
    blended = ((1.0 - w) * p_val) + (w * p_cal)
    return max(0.0, min(1.0, blended))
