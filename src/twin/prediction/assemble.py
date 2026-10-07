"""Pure assembly of the glucose forecast response from the loaded inputs.

    forecast(inputs, tz, gru_loader) -> dict   (the body of GET /patients/{id}/predictions/glucose)

`gru_loader` returns the exported GRU bundle (or raises BundleError); it is a parameter so
tests run with a stub. When the data can't support a forecast, the response still carries
the measured history and `unavailable.reason`, with no forecast and no warnings.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from twin.prediction import rules
from twin.prediction.model import GRU_SOURCES, Unavailable, arima_forecast, gru_forecast, input_frame
from twin.prediction.store import MACROS, ForecastInputs
from twin.streaming.state import glucose_trend

HISTORY = timedelta(hours=3)  # measured glucose shown before the origin
MAX_STALENESS = timedelta(minutes=15)  # the live twin marks CGM stale after this
CAVEATS = {
    "gru": "Model estimate, not a measurement or a clinical prediction. Trained on CGMacros participants; "
           "it can miss what it hasn't seen, such as meals not yet logged or insulin.",
    "arima": "Model estimate, not a measurement or a clinical prediction. Fitted to this twin's own CGM only, "
             "so it extends recent momentum and can't anticipate meals, activity or insulin.",
}
CAVEAT = "Model estimate, not a measurement or a clinical prediction."


def _points(s: pd.Series, tz: ZoneInfo) -> list[dict]:
    return [{"t": t.astimezone(tz), "v": round(float(v), 1)} for t, v in s.items()]


def _inputs_used(inputs: ForecastInputs, frame: pd.DataFrame, idx: int, tz: ZoneInfo, model: str) -> dict:
    if model != "gru":
        return {"glucose_only": True, "meals": [], "heart_rate": False, "activity": False,
                "missing": ["meals", "heart_rate", "activity"]}
    from twin.ml.bench.neural import LOOKBACK

    recent = frame.iloc[max(0, idx + 1 - LOOKBACK): idx + 1]
    hr, activity = bool(recent["hr"].notna().any()), bool(recent["active_kcal"].notna().any())
    meals = [{"time": t.astimezone(tz), "meal_type": m["meal_type"],
              **{k: (None if pd.isna(m[k]) else round(float(m[k]), 1)) for k in MACROS}}
             for t, m in inputs.meals.iterrows()]
    missing = [name for name, ok in (("heart_rate", hr), ("activity", activity)) if not ok]
    return {"glucose_only": False, "meals": meals, "heart_rate": hr, "activity": activity, "missing": missing}


def forecast(inputs: ForecastInputs, tz: ZoneInfo, gru_loader: Callable) -> dict:
    out: dict = {"patient_id": str(inputs.patient_id), "at": inputs.at.astimezone(tz), "model": None, "origin": None,
                 "history": [], "forecast": [], "actual": _points(inputs.after, tz), "warnings": [],
                 "inputs": None, "unavailable": None, "caveat": CAVEAT}
    glucose = inputs.glucose
    if glucose.empty:
        out["unavailable"] = {"reason": "no CGM readings for this twin"}
        return out
    last_t = glucose.index[-1]
    out["history"] = _points(glucose[glucose.index > last_t - HISTORY], tz)
    now = float(glucose.iloc[-1])
    recent = tuple((t.to_pydatetime(), float(v)) for t, v in glucose[glucose.index > last_t - HISTORY].items())
    trend, slope = glucose_trend(recent)
    out["origin"] = {"time": last_t.astimezone(tz), "glucose": now, "band": rules.glucose_band(now),
                     "trend": trend, "trend_mg_dl_min": slope}

    stale = inputs.at - last_t.to_pydatetime()
    try:
        if stale > MAX_STALENESS:
            raise Unavailable(f"the last CGM reading is {stale.total_seconds() / 60:.0f} minutes before the forecast time")
        frame, idx = input_frame(inputs, tz)
        use_gru = inputs.source in GRU_SOURCES
        result = gru_forecast(gru_loader(), frame, idx, inputs.static) if use_gru else arima_forecast(frame, idx)
    except Unavailable as e:
        out["unavailable"] = {"reason": str(e)}
        return out

    out["model"] = result.model
    out["caveat"] = CAVEATS[result.model["name"]]
    out["inputs"] = _inputs_used(inputs, frame, idx, tz, result.model["name"])
    points = [rules.Point(h, round(float(v), 1), round(float(lo), 1), round(float(hi), 1))
              for h, v, lo, hi in zip(result.horizons, result.glucose, result.low, result.high)]
    per_horizon = rules.horizon_warnings(now, points)
    origin_time: datetime = last_t.to_pydatetime()
    out["forecast"] = [
        {"horizon_min": p.horizon_min, "time": (origin_time + timedelta(minutes=p.horizon_min)).astimezone(tz),
         "glucose": p.glucose, "low": p.low, "high": p.high, "change": round(p.glucose - now, 1),
         "band": rules.glucose_band(p.glucose), "warnings": [w.kind for w in found]}
        for p, found in zip(points, per_horizon)
    ]
    out["warnings"] = [w.as_dict() for w in rules.summary(per_horizon)]
    return out

