"""
Reading a fund factsheet.

These go through `parse_bytes`, i.e. the real spreadsheet reader on real
.xlsx bytes, not a dict of rows handed straight to a parser. The difference
matters: the reader is where a NaN cell, a merged header or a stray sheet
actually comes from, and a parser tested on tidy dicts never meets any of it.

Every issuer layout here mirrors a real file's shape (the Italian column
names are what those factsheets actually use).
"""
from __future__ import annotations

import io

import pytest

from service_loader import service_module

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def parse_bytes():
    return service_module("geo_app", "lib.registry").parse_bytes


@pytest.fixture(scope="module")
def aggregate():
    return service_module("geo_app", "lib.aggregator").aggregate


def xlsx(sheets: dict[str, list[list]]) -> bytes:
    """Builds a real workbook: {sheet name: rows}."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def amundi_country_table(rows):
    return xlsx({"Ripartizione Geografica": [["Paesi", "Peso"]] + rows})


# -------------------------------------------------------------- issuer shapes
def test_amundi_country_table(parse_bytes):
    data = amundi_country_table([["Stati Uniti", 0.60], ["Giappone", 0.15],
                                 ["Germania", 0.15], ["Francia", 0.10]])
    result = parse_bytes(data, source_file="amundi.xlsx")
    assert result.weights == {"US": 0.60, "JP": 0.15, "DE": 0.15, "FR": 0.10}
    assert result.metadata.parser_name == "amundi_index_composition"
    assert result.total_weight() == pytest.approx(1.0)


def test_amundi_per_holding_sheet_sums_by_country(parse_bytes):
    data = xlsx({"Titoli detenuti dal fondo": [
        ["Titolo", "Paese", "Peso"],
        ["Apple", "Stati Uniti", 0.30],
        ["Microsoft", "Stati Uniti", 0.25],
        ["Toyota", "Giappone", 0.20],
        ["SAP", "Germania", 0.25],
    ]})
    result = parse_bytes(data, source_file="holdings.xlsx")
    assert result.weights["US"] == pytest.approx(0.55), "two US rows must sum"
    assert result.weights["JP"] == pytest.approx(0.20)


def test_ishares_holdings_sheet(parse_bytes):
    data = xlsx({"Partecipazioni": [
        ["Nome", "Area Geografica", "Ponderazione (%)"],
        ["Apple", "Stati Uniti", 40.0],
        ["Nestle", "Svizzera", 35.0],
        ["Toyota", "Giappone", 25.0],
    ]})
    result = parse_bytes(data, source_file="ishares.xlsx")
    assert result.weights == {"US": pytest.approx(0.40), "CH": pytest.approx(0.35),
                              "JP": pytest.approx(0.25)}


def test_vanguard_market_allocation_uses_the_fund_not_the_benchmark(parse_bytes):
    data = xlsx({"Ripartizione di mercato": [
        ["Nazione", "Regione", "Fondo", "Benchmark"],
        ["Stati Uniti", "Nord America", "60,00%", "99,00%"],
        ["Giappone", "Asia", "40,00%", "1,00%"],
    ]})
    result = parse_bytes(data, source_file="vanguard.xlsx")
    assert result.weights["US"] == pytest.approx(0.60)
    assert result.weights["JP"] == pytest.approx(0.40)


def test_an_unrecognisable_file_says_why_each_parser_declined(parse_bytes):
    exceptions = service_module("geo_app", "lib.exceptions")
    data = xlsx({"Sheet1": [["Something", "Else"], ["a", 1]]})
    with pytest.raises(exceptions.NoParserFoundError) as exc:
        parse_bytes(data, source_file="mystery.xlsx")
    assert "Sheet1" in str(exc.value)


# ------------------------------------------------------------- hostile content
def test_one_unreadable_weight_does_not_wipe_its_country(parse_bytes):
    """A single NaN in a per-holding sheet used to take the whole country's
    total with it, silently."""
    data = xlsx({"Titoli detenuti dal fondo": [
        ["Titolo", "Paese", "Peso"],
        ["Apple", "Stati Uniti", 0.30],
        ["Broken", "Stati Uniti", None],
        ["Toyota", "Giappone", 0.70],
    ]})
    result = parse_bytes(data, source_file="holdings.xlsx")
    assert result.weights["US"] == pytest.approx(0.30)
    assert result.weights["JP"] == pytest.approx(0.70)


def test_a_blank_country_cell_is_not_a_country(parse_bytes):
    data = amundi_country_table([["Stati Uniti", 0.60], ["", 0.20], [None, 0.10],
                                 ["Giappone", 0.10]])
    result = parse_bytes(data, source_file="blanks.xlsx")
    assert set(result.weights) <= {"US", "JP", "XX"}
    assert result.weights["US"] == pytest.approx(0.60)


def test_an_unmapped_label_is_reported_rather_than_dropped(parse_bytes):
    data = amundi_country_table([["Stati Uniti", 0.70], ["Freedonia", 0.30]])
    result = parse_bytes(data, source_file="unmapped.xlsx")
    assert result.weights["US"] == pytest.approx(0.70)
    assert result.unmapped_labels, "an unrecognised label must be surfaced, not silently lost"


def test_percentages_and_fractions_both_come_out_as_fractions(parse_bytes):
    as_fraction = parse_bytes(amundi_country_table([["Stati Uniti", 0.60], ["Giappone", 0.40]]))
    as_percent = parse_bytes(amundi_country_table([["Stati Uniti", 60.0], ["Giappone", 40.0]]))
    assert as_fraction.weights["US"] == pytest.approx(0.60)
    assert as_percent.weights["US"] == pytest.approx(0.60)


def test_a_small_country_in_a_percentage_table_is_not_misread(parse_bytes):
    """The heuristic that decides percent-vs-fraction is per column, not per
    row: judging row by row read a 0.4% holding as 40%."""
    result = parse_bytes(amundi_country_table([
        ["Stati Uniti", 95.0], ["Giappone", 4.6], ["Lussemburgo", 0.4],
    ]))
    assert result.weights["LU"] == pytest.approx(0.004, abs=1e-6)
    assert result.total_weight() == pytest.approx(1.0, abs=1e-6)


def test_the_same_country_listed_twice_is_summed(parse_bytes):
    result = parse_bytes(amundi_country_table([
        ["Stati Uniti", 0.30], ["Stati Uniti", 0.20], ["Giappone", 0.50],
    ]))
    assert result.weights["US"] == pytest.approx(0.50)


def test_a_subtotal_beside_its_members_inflates_the_total(parse_bytes):
    """"Unione Europea" listed alongside France and Germany double-counts
    them. Aggregation normalises the total back to 100%, so the only sign
    is the raw total -- which is why the upload endpoint refuses anything
    over 150%."""
    result = parse_bytes(amundi_country_table([
        ["Francia", 0.30], ["Germania", 0.30], ["Unione Europea", 0.60],
        ["Stati Uniti", 0.40],
    ]))
    assert result.total_weight() > 1.5


# -------------------------------------------------------------- aggregation
def test_portfolio_aggregation_weights_by_value(aggregate):
    """Two funds at 75/25: US ends at 0.75*0.8 + 0.25*0.2 = 0.65."""
    models = service_module("geo_app", "lib.models")
    one = models.AllocationResult(weights={"US": 0.8, "JP": 0.2},
                                  unmapped_labels={}, metadata=models.FundMetadata())
    two = models.AllocationResult(weights={"US": 0.2, "DE": 0.8},
                                  unmapped_labels={}, metadata=models.FundMetadata())
    combined = aggregate([one, two], fund_weights=[75.0, 25.0])
    assert combined["US"] == pytest.approx(0.65)
    assert combined["JP"] == pytest.approx(0.15)
    assert combined["DE"] == pytest.approx(0.20)
    assert sum(combined.values()) == pytest.approx(1.0)


def test_aggregating_nothing_is_empty_rather_than_an_error(aggregate):
    assert aggregate([]) == {}
