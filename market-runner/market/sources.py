"""Binance price sources, run on GitHub Actions because Binance blocks Cloudflare; also the US CPI index
(BLS allows few keyless requests a day per IP and Workers share theirs, FRED refuses Cloudflare).

The other sources run on the Worker (cloudflare/sources.js, where REMOTE lists these).
Each source is a function ``fetch(**params) -> dict[side, float]``.
"""
from __future__ import annotations

from . import http


class SourceError(Exception):
    pass


def _first_ok(attempts):
    """Run callables in order, return first success; raise with all errors."""
    errors = []
    for name, fn in attempts:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {e}")
    raise SourceError(" | ".join(errors))


# ---------------------------------------------------------------- Binance spot
_BINANCE_HOSTS = [
    "https://data-api.binance.vision",  # public market data, not geo-blocked
    "https://api.binance.com",
    "https://api1.binance.com",
]


def binance_spot(symbol: str) -> dict:
    def make(host):
        def f():
            d = http.get_json(f"{host}/api/v3/ticker/price?symbol={symbol}")
            return {"price": float(d["price"])}
        return f
    return _first_ok([(h, make(h)) for h in _BINANCE_HOSTS])


# ---------------------------------------------------------------- Binance P2P
_P2P_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"


def _p2p_ok(adv: dict, min_amount: float) -> bool:
    """True if one order of ``min_amount`` (in the asset) fits this ad's limits."""
    price = float(adv["price"])
    fiat = min_amount * price
    lo = float(adv.get("minSingleTransAmount") or 0)
    hi = float(adv.get("dynamicMaxSingleTransAmount") or adv.get("maxSingleTransAmount") or 0)
    qty = float(adv.get("tradableQuantity") or adv.get("surplusAmount") or 0)
    return lo <= fiat <= hi and (not qty or qty >= min_amount)


def _p2p_matches(ads: list, min_amount: float) -> list[dict]:
    """The ads that allow an order of ``min_amount``."""
    return [a for a in ads
            if a.get("adv", {}).get("price") and a["adv"].get("isTradable") is not False
            and _p2p_ok(a["adv"], min_amount)]


def _p2p_prices(ads: list, min_amount: float) -> list[float]:
    """Prices of the ads that allow an order of ``min_amount``."""
    return [float(a["adv"]["price"]) for a in _p2p_matches(ads, min_amount)]


# where lone ads go: runner.fetch_all collects them for the Worker, which keeps them in D1 table `notes`
NOTE = lambda note: print(f"NOTE {note['kind']}: {note.get('summary', '')}", flush=True)  # noqa: E731


def _p2p_brief(a: dict) -> dict:
    v, u = a.get("adv", {}), a.get("advertiser") or {}
    return {"price": float(v["price"]), "advNo": v.get("advNo"), "nick": u.get("nickName"),
            "userType": u.get("userType"), "orders": u.get("monthOrderCount"),
            "finish": u.get("monthFinishRate"), "min": v.get("minSingleTransAmount"),
            "max": v.get("dynamicMaxSingleTransAmount") or v.get("maxSingleTransAmount"),
            "qty": v.get("tradableQuantity")}


def _p2p_lone(matched: list[dict], asset: str, fiat: str, trade_type: str, min_amount: float,
              total: int, lone: float) -> None:
    """Note a best ad more than ``lone`` % beyond the next one (26 906 at 6h on 5/11 while the rest sat at
    ~26 020). The price stays as it is; the note keeps the whole ad as Binance returned it plus the
    next ads, so that after a few cases the cause can be worked out."""
    buying = trade_type == "BUY"
    s = sorted(matched, key=lambda a: float(a["adv"]["price"]), reverse=not buying)  # best first
    out = []
    for a, nxt in zip(s, s[1:]):
        if abs(float(a["adv"]["price"]) - float(nxt["adv"]["price"])) <= float(nxt["adv"]["price"]) * lone / 100:
            break
        out.append(a)
    if not out:
        return
    nxt = s[len(out)]
    NOTE({"kind": "p2p_lone", "asset": asset, "fiat": fiat, "trade_type": trade_type,
          "min_amount": min_amount, "ads_scanned": total,
          "price": float(out[0]["adv"]["price"]), "next": float(nxt["adv"]["price"]),
          "summary": f"{asset} {trade_type} {out[0]['adv']['price']} vs next {nxt['adv']['price']} "
                     f"by {(out[0].get('advertiser') or {}).get('nickName')}",
          "lone_ads": out,  # full raw ads (adv + advertiser): limits, conditions, labels, counts
          "next_ads": [_p2p_brief(a) for a in s[len(out):len(out) + 10]]})


def binance_p2p(asset: str = "USDT", fiat: str = "VND", trade_type: str = "SELL",
                min_amount: float = 1000, pages: int = 5, pay_types: list | None = None,
                spread: bool = False, lone: float = 1.0) -> dict:
    """Best P2P price among ads whose limits allow an order of ``min_amount`` (in ``asset``):
    the highest when selling, the lowest when buying. A best ad more than ``lone`` % beyond the next
    matching ad still counts, but is noted in full (``NOTE``) for later analysis.

    ``spread``: with trade_type SELL, also the best BUY price, for the spread line in the push
    (``buy`` = what you get selling, ``sell`` = what you pay buying, as with a dealer)."""
    best = _p2p_best(asset, fiat, trade_type, min_amount, pages, pay_types, lone)
    if not spread:
        return {"price": best}
    other = _p2p_best(asset, fiat, "BUY", min_amount, pages, pay_types, lone)
    return {"price": best, "buy": best, "sell": other}


def _p2p_best(asset, fiat, trade_type, min_amount, pages, pay_types, lone=1.0) -> float:
    total, matched = 0, []
    for page in range(1, pages + 1):
        payload = {
            "asset": asset,
            "fiat": fiat,
            "tradeType": trade_type,
            "page": page,
            "rows": 20,
            "payTypes": pay_types or [],
            "publisherType": None,
            "countries": [],
            "proMerchantAds": False,
            "shieldMerchantAds": False,
        }
        d = http.post_json(_P2P_URL, payload, headers={
            "Origin": "https://p2p.binance.com",
            "Referer": f"https://p2p.binance.com/trade/{trade_type.lower()}/{asset}?fiat={fiat}",
        })
        ads = d.get("data") or []
        if not ads:
            if page == 1:
                raise SourceError(f"P2P: no ads returned ({d.get('code')} {d.get('message')})")
            break
        total += len(ads)
        # ads come sorted best price first; two matches are enough to tell a lone ad
        matched += _p2p_matches(ads, min_amount)
        if len(matched) >= 2:
            break
    if not matched:
        raise SourceError(f"P2P: none of {total} ads allow {min_amount:g} {asset}")
    buying = trade_type == "BUY"
    _p2p_lone(matched, asset, fiat, trade_type, min_amount, total, lone)
    prices = [float(a["adv"]["price"]) for a in matched]
    return min(prices) if buying else max(prices)


def binance_p2p_vs(asset: str = "USDC", via: str = "USDT", fiat: str = "VND", trade_type: str = "SELL",
                   min_amount: float = 1000, symbol: str = "USDCUSDT") -> dict:
    """P2P price of ``asset`` plus "vs": that price minus converting to ``via`` on spot
    (``symbol``, e.g. USDCUSDT, free on Binance) and selling ``via`` on P2P. Negative = selling
    ``asset`` directly gets less than going through ``via``."""
    direct = binance_p2p(asset, fiat, trade_type, min_amount)["price"]
    rate = binance_spot(symbol)["price"]
    via_price = binance_p2p(via, fiat, trade_type, min_amount * rate)["price"]
    return {"price": direct, "vs": direct - rate * via_price}


def binance_spot_p2p(symbol: str = "USDCUSDT", asset: str = "USDC", via: str = "USDT", fiat: str = "VND",
                     trade_type: str = "SELL", min_amount: float = 1000) -> dict:
    """Spot price of ``symbol`` as "price", plus "p2p" and "vs" from ``binance_p2p_vs``,
    so one line shows the spot rate and the P2P price of the same coin."""
    rate = binance_spot(symbol)["price"]
    direct = binance_p2p(asset, fiat, trade_type, min_amount)["price"]
    via_price = binance_p2p(via, fiat, trade_type, min_amount * rate)["price"]
    return {"price": rate, "p2p": direct, "vs": direct - rate * via_price}


# ---------------------------------------------------------------- US CPI
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
    """{"all.2026-09": 336.94, "core.2026-09": 339.287, ...}: the index of the last 2-3 years (the Worker,
    cloudflare/cpi.js, takes the year-on-year changes)."""
    import datetime
    year = datetime.date.today().year
    return _first_ok([("BLS", lambda: _bls_cpi(year)), ("FRED", lambda: _fred_cpi(year))])


SOURCES = {
    "us_cpi": us_cpi,
    "binance_spot": binance_spot,
    "binance_p2p": binance_p2p,
    "binance_p2p_vs": binance_p2p_vs,
    "binance_spot_p2p": binance_spot_p2p,
}


def fetch(source: str, params: dict) -> dict:
    if source not in SOURCES:
        raise SourceError(f"unknown source {source!r}")
    return SOURCES[source](**params)
