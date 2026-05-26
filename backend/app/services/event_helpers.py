"""
Event helpers for generating scanner-specific summaries and severities.
"""

from typing import Dict, Any, Callable


# Summary generators for each scanner type
SUMMARY_GENERATORS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "pre_market_volume_spike": lambda ind: f"{ind.get('volume_spike_ratio', 0):.1f}x volume spike, {ind.get('gap_pct', 0):+.1f}% gap",
    "liquidity_hunt_pre": lambda ind: (
        f"Pre-mkt liquidity hunt: {ind.get('session_volume_ratio') or '∞'}x session vol, "
        f"{ind.get('session_spike_pct', 0)*100:+.1f}% spike"
    ),
    "liquidity_hunt_post": lambda ind: (
        f"Post-mkt liquidity hunt: {ind.get('session_volume_ratio') or '∞'}x session vol, "
        f"{ind.get('session_spike_pct', 0)*100:+.1f}% spike"
    ),
    "oversold_bounce": lambda ind: f"RSI cross ({ind.get('rsi_2', 0):.0f}/{ind.get('rsi_5', 0):.0f}), ATR ${ind.get('atr_target', 0):.2f}",
    "live_volume_spike": lambda ind: (
        f"{ind.get('volume_spike_ratio', 0):.1f}x projected volume "
        f"({ind.get('session', 'regular')} session, {ind.get('minutes_elapsed', 0):.0f} min elapsed)"
    ),
    "live_price_move": lambda ind: (
        f"{ind.get('price_move_pct', 0):+.2f}% from prior close "
        f"(${ind.get('prior_close', 0):.2f} → ${ind.get('current_price', 0):.2f})"
    ),
    "social_callout": lambda ind: (
        f"@{ind.get('source_account', '?')} {ind.get('direction', '')} callout"
        + (f" ${ind.get('price_entry', 0):.2f}" if ind.get('price_entry') else "")
        + (f" → ${ind.get('price_target', 0):.2f}" if ind.get('price_target') else "")
        + f" (conf {ind.get('confidence', 0):.0%})"
    ),
}

# Severity calculators for each scanner type
SEVERITY_CALCULATORS: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "pre_market_volume_spike": lambda ind: (
        "high" if ind.get('volume_spike_ratio', 0) > 5
        else "medium" if ind.get('volume_spike_ratio', 0) > 3
        else "low"
    ),
    "liquidity_hunt_pre": lambda ind: (
        "high" if (ind.get('session_volume_ratio') or 0) > 8
             or (ind.get('session_volume_ratio') is None and (ind.get('session_volume_pct_of_daily') or 0) > 0.50)
        else "medium" if (ind.get('session_volume_ratio') or 0) > 4
             or ind.get('session_volume_ratio') is None
        else "low"
    ),
    "liquidity_hunt_post": lambda ind: (
        "high" if (ind.get('session_volume_ratio') or 0) > 8
             or (ind.get('session_volume_ratio') is None and (ind.get('session_volume_pct_of_daily') or 0) > 0.50)
        else "medium" if (ind.get('session_volume_ratio') or 0) > 4
             or ind.get('session_volume_ratio') is None
        else "low"
    ),
    "oversold_bounce": lambda ind: (
        "high" if ind.get('rsi_2', 100) < 10
        else "medium"
    ),
    "live_volume_spike": lambda ind: (
        "high" if ind.get('volume_spike_ratio', 0) > 8
        else "medium" if ind.get('volume_spike_ratio', 0) > 4
        else "low"
    ),
    "live_price_move": lambda ind: (
        "high" if abs(ind.get('price_move_pct', 0)) > 5
        else "medium" if abs(ind.get('price_move_pct', 0)) > 2
        else "low"
    ),
    "social_callout": lambda ind: (
        "high" if ind.get('confidence', 0) > 0.9
        else "medium" if ind.get('confidence', 0) > 0.7
        else "low"
    ),
}


def generate_event_summary(scanner_type: str, indicators: Dict[str, Any]) -> str:
    """Generate a human-readable summary for a scanner event."""
    generator = SUMMARY_GENERATORS.get(scanner_type)
    if generator:
        try:
            return generator(indicators)
        except Exception:
            pass
    
    # Fallback summary
    return f"Detected {scanner_type.replace('_', ' ')} logic"


def compute_event_severity(scanner_type: str, indicators: Dict[str, Any]) -> str:
    """Compute the severity level for a scanner event."""
    calculator = SEVERITY_CALCULATORS.get(scanner_type)
    if calculator:
        try:
            return calculator(indicators)
        except Exception:
            pass
    
    return "medium"
