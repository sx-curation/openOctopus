from config.ui_data_contracts import get_ui_section_contract


def build_portfolio_overview() -> dict:
    contract = get_ui_section_contract("portfolio.overview") or {"fields": []}
    fields = {field["name"]: field for field in contract["fields"]}

    return {
        "status": "input_required",
        "summary_cards": {
            "total_aum": _field_payload(fields, "total_aum"),
            "active_positions": _field_payload(fields, "active_positions"),
            "ytd_return": _field_payload(fields, "ytd_return"),
        },
        "top_holdings": {
            "status": fields.get("top_holdings", {}).get("status", "planned"),
            "items": [],
            "rationale": fields.get("top_holdings", {}).get("rationale"),
        },
        "signal_badges": {
            "status": fields.get("signal_badges", {}).get("status", "planned"),
            "items": [],
            "rationale": fields.get("signal_badges", {}).get("rationale"),
        },
        "required_inputs": [
            "portfolio positions",
            "cost basis",
            "benchmark configuration",
        ],
    }


def _field_payload(fields: dict, field_name: str) -> dict:
    field = fields.get(field_name, {})
    return {
        "status": field.get("status", "unavailable"),
        "value": None,
        "rationale": field.get("rationale"),
    }
