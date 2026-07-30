# ADR mapping for Taiwan stocks listed on US exchanges.
# ratio: number of ordinary TW shares represented by 1 ADR.
# ratio=None means the ratio is unconfirmed; these entries will return available=False
# from the API until the ratio is officially verified from the ADR prospectus.

TW_ADR_MAP: dict[str, dict] = {
    "2330": {"adr": "TSM",  "ratio": 5,    "exchange": "NYSE", "name": "台積電"},
    "2303": {"adr": "UMC",  "ratio": 5,    "exchange": "NYSE", "name": "聯電"},
    "3711": {"adr": "ASX",  "ratio": 2,    "exchange": "NYSE", "name": "日月光投控"},
    "2412": {"adr": "CHT",  "ratio": None, "exchange": "NYSE", "name": "中華電"},
    # CHT ratio unconfirmed — public sources suggest 1 ADR = 10 shares,
    # but this must be verified against the official prospectus before enabling.
}
