"""
Country name normalization to ISO 3166-1 alpha-2.

Different fund/ETF issuers use different languages and conventions for the
same country in their Excel files (e.g. "Stati Uniti", "Stati Uniti
d'America", "USA", "United States", "US"). To be able to sum weights coming
from different sources, a single canonical key is needed: here we use the
ISO 3166-1 alpha-2 code.

Two special buckets are also handled, NOT part of the ISO standard but
common in real-world files:
  - "EU" : aggregated "European Union" entry without the detail of the
           individual member country.
  - "XX" : any non-country entry (cash, "Other", derivatives, placeholders
           such as "--" or blank spaces).

``normalize_country`` returns None when the label is not recognized: it is
up to the caller (the individual parsers) to decide whether to discard it,
sum it into "XX", or flag it as unmapped for quality control (see
AllocationResult.unmapped_labels).
"""

from __future__ import annotations
import unicodedata
from typing import Optional

SPECIAL_EU = "EU"
SPECIAL_OTHER = "XX"

# Labels that explicitly represent "not a country" and must always be
# bucketed as SPECIAL_OTHER, regardless of their weight.
# NOTE: these are literal strings as they appear in the source files
# (Italian and English) and must NOT be translated, since they are used
# for exact matching against real file content.
_NON_COUNTRY_LABELS = {
    "altro", "other", "others", "cash", "cash and other", "cash & other",
    "liquidita", "liquidita'", "not classified", "non classificato",
    "unclassified", "n/a", "na", "--", "-", "",
}

_EU_LABELS = {
    "unione europea", "european union", "eurozona", "eurozone", "ue", "eu",
}

# Map: normalized form (lowercase, no accents/apostrophes) -> ISO alpha-2.
# Covers the most common Italian and English country names used by Amundi,
# Vanguard, iShares/BlackRock, Lyxor/Amundi, SPDR, Xtrackers, etc.
# NOTE: the dict keys below are literal country-name strings that must
# match the actual labels found in source Excel files (Italian and
# English); they are intentionally left untranslated.
_COUNTRY_TO_ISO2 = {
    # --- North America ---
    "stati uniti": "US", "stati uniti d america": "US", "usa": "US",
    "united states": "US", "united states of america": "US", "us": "US",
    "canada": "CA",
    "messico": "MX", "mexico": "MX",

    # --- Western Europe ---
    "regno unito": "GB", "regno unito ": "GB", "united kingdom": "GB",
    "uk": "GB", "great britain": "GB",
    "germania": "DE", "germany": "DE",
    "francia": "FR", "france": "FR",
    "italia": "IT", "italy": "IT",
    "spagna": "ES", "spain": "ES",
    "portogallo": "PT", "portugal": "PT",
    "paesi bassi": "NL", "olanda": "NL", "netherlands": "NL", "holland": "NL",
    "belgio": "BE", "belgium": "BE",
    "svizzera": "CH", "switzerland": "CH",
    "austria": "AT",
    "irlanda": "IE", "ireland": "IE",
    "lussemburgo": "LU", "luxembourg": "LU",
    "monaco": "MC",
    "liechtenstein": "LI",
    "malta": "MT",

    # --- Northern Europe ---
    "svezia": "SE", "sweden": "SE",
    "norvegia": "NO", "norway": "NO",
    "danimarca": "DK", "dinamarca": "DK", "denmark": "DK",
    "finlandia": "FI", "finland": "FI",
    "islanda": "IS", "iceland": "IS",

    # --- Eastern / Central Europe ---
    "polonia": "PL", "poland": "PL",
    "repubblica ceca": "CZ", "czech republic": "CZ", "cechia": "CZ", "czechia": "CZ",
    "ungheria": "HU", "hungary": "HU",
    "romania": "RO",
    "grecia": "GR", "greece": "GR",
    "russia": "RU", "federazione russa": "RU", "russian federation": "RU",
    "turchia": "TR", "turkey": "TR", "turkiye": "TR",
    "ucraina": "UA", "ukraine": "UA",
    "slovacchia": "SK", "slovakia": "SK",
    "slovenia": "SI",
    "croazia": "HR", "croatia": "HR",
    "serbia": "RS",
    "bulgaria": "BG",
    "estonia": "EE",
    "lettonia": "LV", "latvia": "LV",
    "lituania": "LT", "lithuania": "LT",
    "cipro": "CY", "cyprus": "CY",

    # --- Developed Asia-Pacific ---
    "giappone": "JP", "japan": "JP",
    "australia": "AU",
    "nuova zelanda": "NZ", "new zealand": "NZ", "new_zealand": "NZ",
    "hong kong": "HK", "hongkong": "HK",
    "singapore": "SG",
    "corea del sud": "KR", "south korea": "KR", "korea": "KR",
    "korea, republic of": "KR", "republic of korea": "KR",

    # --- Emerging Asia ---
    "cina": "CN", "china": "CN",
    "taiwan": "TW",
    "india": "IN",
    "indonesia": "ID",
    "malesia": "MY", "malaysia": "MY",
    "thailandia": "TH", "thailand": "TH",
    "filippine": "PH", "philippines": "PH",
    "vietnam": "VN",
    "pakistan": "PK",
    "bangladesh": "BD",
    "kazakistan": "KZ", "kazakhstan": "KZ",

    # --- Middle East ---
    "israele": "IL", "israel": "IL",
    "arabia saudita": "SA", "saudi arabia": "SA",
    "emirati arabi uniti": "AE", "united arab emirates": "AE", "uae": "AE",
    "qatar": "QA",
    "kuwait": "KW",
    "bahrein": "BH", "bahrain": "BH",
    "oman": "OM",
    "giordania": "JO", "jordan": "JO",

    # --- Africa ---
    "sudafrica": "ZA", "south africa": "ZA",
    "egitto": "EG", "egypt": "EG",
    "marocco": "MA", "morocco": "MA",
    "nigeria": "NG",
    "kenya": "KE",

    # --- South America ---
    "brasile": "BR", "brazil": "BR",
    "cile": "CL", "chile": "CL",
    "colombia": "CO",
    "perù": "PE", "peru": "PE",
    "argentina": "AR",

    # --- Other ---
    "cina a": "CN",  # "China A-shares", sometimes reported separately
}


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _canonicalize(label: str) -> str:
    s = _strip_accents(label).lower().strip()
    s = s.replace("’", "'").replace("`", "'")
    s = s.replace("'", " ")
    s = " ".join(s.split())  # collapse repeated whitespace
    return s


def normalize_country(label: Optional[str]) -> Optional[str]:
    """
    Converts a raw country label (as it appears in the Excel file) to the
    corresponding ISO 3166-1 alpha-2 code, or to one of the two special
    buckets SPECIAL_EU / SPECIAL_OTHER.

    Returns None if the label is non-empty and not a known non-country
    label, but is still not recognized: in this case the caller should
    record it in ``AllocationResult.unmapped_labels`` for quality control,
    rather than silently discarding it.
    """
    if label is None:
        return SPECIAL_OTHER
    raw = str(label).strip()
    if raw == "":
        return SPECIAL_OTHER

    key = _canonicalize(raw)

    if key in _NON_COUNTRY_LABELS:
        return SPECIAL_OTHER
    if key in _EU_LABELS:
        return SPECIAL_EU
    if key in _COUNTRY_TO_ISO2:
        return _COUNTRY_TO_ISO2[key]

    # Already a valid ISO alpha-2 code? (case-insensitive, 2 letters)
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()

    return None


def register_country_alias(label: str, iso2: str) -> None:
    """Lets a consumer project add/extend aliases (e.g. names in other
    languages) without modifying the library's code."""
    _COUNTRY_TO_ISO2[_canonicalize(label)] = iso2.upper()
