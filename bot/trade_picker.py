from __future__ import annotations

from typing import Any, Dict, List


def pick_trade_candidate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    actionable = [
        row for row in rows
        if row.get("signal", {}).get("signal") in {"BUY", "SELL"}
    ]
    if not actionable:
        return rows[0]

    return max(
        actionable,
        key=lambda row: float(row.get("signal", {}).get("suggested_probability", 0) or 0),
    )
