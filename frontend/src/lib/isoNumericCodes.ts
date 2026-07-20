/**
 * world-atlas's TopoJSON identifies each country feature by its ISO 3166-1
 * NUMERIC code (e.g. "840" for the US), not the ISO2 codes ("US") used
 * everywhere else in this app. This is the crosswalk between the two,
 * covering the same country set as the backend's country_names.py so the
 * world map can shade every country we already know how to label.
 *
 * Generated once from the `i18n-iso-countries` package's verified data
 * (not bundled at runtime -- this static table avoids that extra
 * dependency in the browser bundle for what is, in practice, a fixed
 * reference table that never changes).
 */
export const ISO2_TO_NUMERIC: Record<string, string> = {
  US: "840", JP: "392", GB: "826", CA: "124", FR: "250", CH: "756", DE: "276",
  AU: "036", NL: "528", IT: "380", ES: "724", SE: "752", DK: "208", HK: "344",
  SG: "702", KR: "410", TW: "158", CN: "156", IN: "356", BR: "076", ZA: "710",
  MX: "484", ID: "360", TH: "764", MY: "458", PH: "608", SA: "682", AE: "784",
  IL: "376", FI: "246", NO: "578", BE: "056", IE: "372", AT: "040", PT: "620",
  PL: "616", GR: "300", NZ: "554", TR: "792", CL: "152", CO: "170", PE: "604",
  QA: "634", KW: "414", HU: "348", RO: "642", CZ: "203", IS: "352", EG: "818",
  KE: "404", PK: "586", VN: "704", AR: "032", RU: "643", MA: "504", NG: "566",
};
