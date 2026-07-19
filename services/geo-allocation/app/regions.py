"""
Maps ISO 3166-1 alpha-2 country codes to one of five macro-regions, for the
"group by region" view of geographic allocation. Only covers codes that
realistically show up in ETF/fund factsheets (mirrors country_names.py);
anything missing falls back to OTHER rather than raising.

Transcontinental cases (Russia, Turkey) follow the common index-provider
convention (e.g. MSCI) of grouping them with Europe.
"""

REGION_LABELS = {
    "AMERICAS": "Americas",
    "EUROPE": "Europe",
    "ASIA": "Asia",
    "AFRICA": "Africa",
    "OCEANIA": "Oceania",
    "OTHER": "Other / Unclassified",
}

COUNTRY_TO_REGION = {
    # --- Americas ---
    "US": "AMERICAS", "CA": "AMERICAS", "MX": "AMERICAS", "BR": "AMERICAS",
    "AR": "AMERICAS", "CL": "AMERICAS", "CO": "AMERICAS", "PE": "AMERICAS",

    # --- Europe (incl. Russia/Turkey, per common index-provider convention) ---
    "GB": "EUROPE", "FR": "EUROPE", "DE": "EUROPE", "CH": "EUROPE", "NL": "EUROPE",
    "IT": "EUROPE", "ES": "EUROPE", "SE": "EUROPE", "DK": "EUROPE", "FI": "EUROPE",
    "NO": "EUROPE", "BE": "EUROPE", "IE": "EUROPE", "AT": "EUROPE", "PT": "EUROPE",
    "PL": "EUROPE", "GR": "EUROPE", "HU": "EUROPE", "RO": "EUROPE", "CZ": "EUROPE",
    "IS": "EUROPE", "RU": "EUROPE", "TR": "EUROPE", "EU": "EUROPE",

    # --- Asia (incl. Middle East, which has no dedicated bucket here) ---
    "JP": "ASIA", "HK": "ASIA", "SG": "ASIA", "KR": "ASIA", "TW": "ASIA", "CN": "ASIA",
    "IN": "ASIA", "ID": "ASIA", "TH": "ASIA", "MY": "ASIA", "PH": "ASIA", "VN": "ASIA",
    "PK": "ASIA", "IL": "ASIA", "SA": "ASIA", "AE": "ASIA", "QA": "ASIA", "KW": "ASIA",

    # --- Africa ---
    "ZA": "AFRICA", "EG": "AFRICA", "KE": "AFRICA", "MA": "AFRICA", "NG": "AFRICA",

    # --- Oceania ---
    "AU": "OCEANIA", "NZ": "OCEANIA",

    # --- Unclassified ---
    "XX": "OTHER",
}


def region_for(iso2: str) -> str:
    return COUNTRY_TO_REGION.get(iso2, "OTHER")
