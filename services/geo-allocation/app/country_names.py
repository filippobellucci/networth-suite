"""Small ISO 3166-1 alpha-2 -> display name map, used only to make chart
labels human-readable. Not exhaustive of every country in the world -- only
the ones that realistically show up in ETF/fund factsheets -- but falls
back gracefully to the raw code for anything missing."""

COUNTRY_NAMES = {
    "US": "United States", "JP": "Japan", "GB": "United Kingdom", "CA": "Canada",
    "FR": "France", "CH": "Switzerland", "DE": "Germany", "AU": "Australia",
    "NL": "Netherlands", "IT": "Italy", "ES": "Spain", "SE": "Sweden",
    "DK": "Denmark", "HK": "Hong Kong", "SG": "Singapore", "KR": "South Korea",
    "TW": "Taiwan", "CN": "China", "IN": "India", "BR": "Brazil", "ZA": "South Africa",
    "MX": "Mexico", "ID": "Indonesia", "TH": "Thailand", "MY": "Malaysia",
    "PH": "Philippines", "SA": "Saudi Arabia", "AE": "United Arab Emirates",
    "IL": "Israel", "FI": "Finland", "NO": "Norway", "BE": "Belgium",
    "IE": "Ireland", "AT": "Austria", "PT": "Portugal", "PL": "Poland",
    "GR": "Greece", "NZ": "New Zealand", "TR": "Turkey", "CL": "Chile",
    "CO": "Colombia", "PE": "Peru", "EU": "Europe (aggregate)",
    "QA": "Qatar", "KW": "Kuwait", "HU": "Hungary", "RO": "Romania",
    "CZ": "Czech Republic", "IS": "Iceland", "EG": "Egypt", "KE": "Kenya",
    "PK": "Pakistan", "VN": "Vietnam", "AR": "Argentina", "RU": "Russia",
    "XX": "Other / Unclassified",
}


def display_name(iso2: str) -> str:
    return COUNTRY_NAMES.get(iso2, iso2)
