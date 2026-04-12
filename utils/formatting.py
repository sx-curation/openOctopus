"""Shared formatting helpers for numbers and dates."""


def parse_item_string(item_str: str) -> tuple[str | None, str]:
    """Convert 'Item 5.02' → ('5.02', 'item_502'). Returns (None, '') if unrecognised."""
    try:
        num = item_str.strip()
        if num.lower().startswith("item "):
            num = num[5:].strip()
        section_key = "item_" + num.replace(".", "")
        return num, section_key
    except Exception:
        return None, ""


def fmt_large(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1e12:
        return f"${value/1e12:.2f}T{suffix}"
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B{suffix}"
    if abs(value) >= 1e6:
        return f"${value/1e6:.2f}M{suffix}"
    return f"${value:,.0f}{suffix}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"
