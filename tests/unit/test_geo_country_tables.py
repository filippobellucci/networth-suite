"""
The four country tables must agree with each other.

A country's exposure passes through four separate lookups on its way to the
screen: the parser turns a label into an ISO2 code, `country_to_region` files
it under a macro-region, `country_names` gives it a display name, and the
frontend's ISO2 -> numeric crosswalk lets the world map shade it. They are
four hand-maintained tables in two languages, so they drift -- and when they
do the symptom is quiet: an allocation grouped correctly under Europe but
labelled "LU" instead of "Luxembourg", and left blank on the map as though it
were zero. Twenty-two countries were in that state at once.

Nothing here checks that any particular country is present. It checks that
whatever set exists is the SAME set everywhere, which is the property that was
actually broken and the one a future addition can break again.
"""
from __future__ import annotations

import re

import pytest

from service_loader import REPO_ROOT, service_module

pytestmark = pytest.mark.unit

CROSSWALK_TS = REPO_ROOT / "frontend" / "src" / "lib" / "isoNumericCodes.ts"


@pytest.fixture(scope="module")
def tables():
    names = service_module("geo_app", "country_names").COUNTRY_NAMES
    regions_mod = service_module("geo_app", "regions")
    countries = service_module("geo_app", "lib.countries")

    source = CROSSWALK_TS.read_text(encoding="utf-8")
    body = source[source.index("ISO2_TO_NUMERIC"):]
    body = body[body.index("{"): body.index("};") + 1]
    body = re.sub(r"//[^\n]*", "", body)          # strip comments first
    crosswalk = dict(re.findall(r'([A-Z]{2})\s*:\s*"(\d+)"', body))

    return {
        "names": names,
        "regions": regions_mod.COUNTRY_TO_REGION,
        "region_labels": regions_mod.REGION_LABELS,
        "parser_codes": set(countries._COUNTRY_TO_ISO2.values()),
        "crosswalk": crosswalk,
        "specials": {countries.SPECIAL_EU, countries.SPECIAL_OTHER},
    }


def test_the_crosswalk_parsed_at_all(tables):
    """Guards the test itself: a refactor of the .ts file that this regex
    stopped understanding would otherwise make every check below vacuous."""
    assert len(tables["crosswalk"]) > 50
    assert tables["crosswalk"]["US"] == "840"


def test_the_pseudo_codes_are_named_and_filed(tables):
    """"EU" (a factsheet giving a Europe subtotal instead of countries) and
    "XX" (everything unrecognised) are not countries, so they are excluded
    from the country comparisons below -- but they must still be labelled,
    or they render as a bare code in the table."""
    for code in tables["specials"]:
        assert code in tables["names"], code
        assert code in tables["regions"], code


def test_every_named_country_has_a_region(tables):
    missing = sorted(set(tables["names"]) - set(tables["regions"]))
    assert not missing, f"named but unfiled, so they fall into 'Other': {missing}"


def test_every_filed_country_has_a_name(tables):
    missing = sorted(set(tables["regions"]) - set(tables["names"]))
    assert not missing, f"filed under a region but shown as a bare code: {missing}"


def test_every_named_country_can_be_drawn_on_the_map(tables):
    # The two pseudo-codes have no country to shade, by definition.
    missing = sorted(set(tables["names"]) - set(tables["crosswalk"]) - tables["specials"])
    assert not missing, f"named in the table but left blank on the world map: {missing}"


def test_the_map_knows_nothing_the_backend_does_not(tables):
    extra = sorted(set(tables["crosswalk"]) - set(tables["names"]))
    assert not extra, f"in the frontend crosswalk with no backend name: {extra}"


def test_every_code_a_parser_can_produce_is_known(tables):
    """The parsers are the entry point: a label they resolve to a code nothing
    else knows about lands in 'Other / Unclassified' with no explanation."""
    unknown = sorted(tables["parser_codes"] - set(tables["names"]) - tables["specials"])
    assert not unknown, f"a parser can produce these, but nothing can name them: {unknown}"


def test_every_region_used_has_a_label(tables):
    unlabelled = sorted(set(tables["regions"].values()) - set(tables["region_labels"]))
    assert not unlabelled


def test_numeric_codes_are_well_formed(tables):
    for iso2, numeric in tables["crosswalk"].items():
        assert len(iso2) == 2 and iso2.isalpha() and iso2.isupper(), iso2
        assert numeric.isdigit() and 1 <= len(numeric) <= 3, (iso2, numeric)
    assert len(set(tables["crosswalk"].values())) == len(tables["crosswalk"]), \
        "two countries share one numeric code"


def test_namibia_is_a_country(tables):
    """"NA" reads as "not available" to almost every CSV tool that touches a
    factsheet, and Namibia has been lost to that more than once -- it had no
    region, no name and no map entry while still being parsed."""
    countries = service_module("geo_app", "lib.countries")
    assert countries.normalize_country("Namibia") == "NA"
    assert tables["names"]["NA"] == "Namibia"
    assert "NA" in tables["regions"]
    assert "NA" in tables["crosswalk"]


@pytest.mark.parametrize("label", ["n/a", "N/A", "--", "", "   ", "unknown", "Other"])
def test_non_country_labels_are_still_not_countries(tables, label):
    countries = service_module("geo_app", "lib.countries")
    got = countries.normalize_country(label)
    assert got in (None, countries.SPECIAL_OTHER), f"{label!r} resolved to {got!r}"
