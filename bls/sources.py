"""The US CPI index, run on GitHub Actions: BLS allows few keyless requests a day per IP (Workers share
theirs) and FRED, the fallback, refuses Cloudflare.

``us_cpi() -> {"all.2026-09": 336.94, "core.2026-09": 339.287, ...}``: the index of the last 2-3 years,
listed in ``SOURCES`` for common.runner.
"""
from __future__ import annotations

import datetime

from common import http
from common.runner import SourceError, first_ok

# CPI-U, US city average, not seasonally adjusted: all items and core (less food and energy).
_BLS = {"CUUR0000SA0": "all", "CUUR0000SA0L1E": "core"}
_FRED = {"CPIAUCNS": "all", "CPILFENS": "core"}


def _bls_cpi(year: int) -> dict:
    d = http.post_json("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                       {"seriesid": list(_BLS), "startyear": str(year - 2), "endyear": str(year)})
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise SourceError(f"{d.get('status')}: {' '.join(d.get('message') or [])[:200]}")
    out = {}
    for s in d["Results"]["series"]:
        for x in s["data"]:
            p = x["period"]
            if p.startswith("M") and p != "M13" and x["value"] not in ("", "-"):
                out[f"{_BLS[s['seriesID']]}.{x['year']}-{p[1:]}"] = float(x["value"])
    return out


def _fred_cpi(year: int) -> dict:
    text = http.request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={','.join(_FRED)}&cosd={year - 2}-01-01").decode()
    rows = [line.split(",") for line in text.strip().splitlines()]
    cols = {i: _FRED[c] for i, c in enumerate(rows[0]) if c in _FRED}
    if len(cols) != 2:
        raise SourceError("unexpected CSV")
    return {f"{k}.{r[0][:7]}": float(r[i]) for r in rows[1:] for i, k in cols.items() if r[i] not in ("", ".")}


def us_cpi() -> dict:
    year = datetime.date.today().year
    return first_ok([("BLS", lambda: _bls_cpi(year)), ("FRED", lambda: _fred_cpi(year))])


SOURCES = {"us_cpi": us_cpi}
