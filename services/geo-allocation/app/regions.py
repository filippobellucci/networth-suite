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
    # The rest of countries.py's _COUNTRY_TO_ISO2 European entries -- these
    # were previously recognized as valid countries (normalize_country
    # resolves them fine) but had no region mapping, so any fund with real
    # exposure to them (not rare -- Luxembourg-domiciled money-market
    # holdings, Malta, Ukraine bonds...) silently fell into "Other /
    # Unclassified" instead of Europe when grouping by region.
    "LU": "EUROPE", "MC": "EUROPE", "LI": "EUROPE", "MT": "EUROPE", "UA": "EUROPE",
    "SK": "EUROPE", "SI": "EUROPE", "HR": "EUROPE", "RS": "EUROPE", "BG": "EUROPE",
    "EE": "EUROPE", "LV": "EUROPE", "LT": "EUROPE", "CY": "EUROPE",

    # --- Asia (incl. Middle East, which has no dedicated bucket here) ---
    "JP": "ASIA", "HK": "ASIA", "SG": "ASIA", "KR": "ASIA", "TW": "ASIA", "CN": "ASIA",
    "IN": "ASIA", "ID": "ASIA", "TH": "ASIA", "MY": "ASIA", "PH": "ASIA", "VN": "ASIA",
    "PK": "ASIA", "IL": "ASIA", "SA": "ASIA", "AE": "ASIA", "QA": "ASIA", "KW": "ASIA",
    # Same completeness fix as Europe above.
    "BD": "ASIA", "KZ": "ASIA", "BH": "ASIA", "OM": "ASIA", "JO": "ASIA",

    # --- Africa ---
    "ZA": "AFRICA", "EG": "AFRICA", "KE": "AFRICA", "MA": "AFRICA", "NG": "AFRICA",
    # countries.py goes out of its way to keep "NA"/"Namibia" a real country
    # rather than reading it as a missing value -- but with no entry here it
    # still landed in "Other / Unclassified" when grouping by region, which
    # is the same place that earlier fix was meant to get it out of.
    "NA": "AFRICA",

    # --- Oceania ---
    "AU": "OCEANIA", "NZ": "OCEANIA",

    # --- Unclassified ---
    "XX": "OTHER",
}


def region_for(iso2: str) -> str:
    return COUNTRY_TO_REGION.get(iso2, "OTHER")
