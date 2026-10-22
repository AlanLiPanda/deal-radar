#!/usr/bin/env python3
"""Milk Radar: check Lactantia UltraPur stock at every BC Superstore / No Frills.

Writes data.json next to this file. Run: python3 update.py [--region "British Columbia"]
"""
import json, sys, time, datetime, concurrent.futures, urllib.request, urllib.error, os

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.pcexpress.ca/pcx-bff/api/v1"
KEY_FILE = os.path.expanduser("~/.config/milk-radar/pcx-apikey")

def api_key():
    """Loblaw's public web API key, kept out of the repo: $PCX_APIKEY or ~/.config/milk-radar/pcx-apikey."""
    k = os.environ.get("PCX_APIKEY", "").strip()
    if not k and os.path.exists(KEY_FILE):
        k = open(KEY_FILE).read().strip()
    if not k:
        sys.exit("No API key: set PCX_APIKEY or write it to " + KEY_FILE)
    return k

HEADERS = {
    "x-apikey": "",
    "x-application-type": "Web",
    "x-loblaw-tenant-id": "ONLINE_GROCERIES",
    "accept": "application/json",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
}
BANNERS = {"superstore": ("Superstore", "https://www.realcanadiansuperstore.ca"),
           "nofrills": ("No Frills", "https://www.nofrills.ca"),
           "independent": ("Independent", "https://www.yourindependentgrocer.ca")}
PRODUCTS = [
    {"code": "21694606_EA", "fat": "3.25%", "name": "Lactantia UltraPur 3.25% (whole)", "slug": "ultrapur-protein-ultra-filtered-milk-3-25"},
    {"code": "21694605_EA", "fat": "2%",    "name": "Lactantia UltraPur 2%",            "slug": "ultrapur-protein-ultra-filtered-milk-2"},
    {"code": "21694529_EA", "fat": "0%",    "name": "Lactantia UltraPur 0% (skim)",     "slug": "ultrapur-protein-ultra-filtered-milk-0"},
]
REGION = "British Columbia"
if "--region" in sys.argv:
    REGION = sys.argv[sys.argv.index("--region") + 1]

def get(url, tries=3):
    if not HEADERS["x-apikey"]:
        HEADERS["x-apikey"] = api_key()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            err = e
            time.sleep(1.5 * (i + 1))
    print("FAILED", url, err, file=sys.stderr)
    return None

def stores():
    out = []
    for banner in BANNERS:
        d = get(f"{API}/pickup-locations?bannerIds={banner}")
        if not d:
            continue
        items = d if isinstance(d, list) else next((v for v in d.values() if isinstance(v, list)), [])
        for s in items:
            a = s.get("address") or {}
            if a.get("region") != REGION or not s.get("visible", True):
                continue
            g = s.get("geoPoint") or {}
            out.append({
                "id": s["storeId"], "banner": banner,
                "name": s["name"].replace("Real Canadian Superstore ", "").replace("NOFRILLS", "No Frills").replace("Your Independent Grocer", "Independent"),
                "town": a.get("town"), "addr": a.get("line1"), "postal": a.get("postalCode"),
                "lat": g.get("latitude"), "lng": g.get("longitude"),
                "phone": s.get("orderContactNumber"),
                "hours": (s.get("openNowResponseData") or {}).get("hours"),
                "openNow": (s.get("openNowResponseData") or {}).get("openNow"),
            })
    return out

def check(store, prod):
    date = datetime.date.today().strftime("%d%m%Y")
    url = (f"{API}/products/{prod['code']}?lang=en&storeId={store['id']}"
           f"&banner={store['banner']}&pickupType=STORE&date={date}")
    d = get(url)
    if not d or "offers" not in d or not d["offers"]:
        return {"stock": "UNKNOWN"}
    o = d["offers"][0]
    deal = (o.get("badges") or {}).get("dealBadge") or {}
    return {
        "stock": o.get("stockStatus") or "UNKNOWN",
        "price": (o.get("price") or {}).get("value"),
        "was": (o.get("wasPrice") or {}).get("value") if o.get("wasPrice") else None,
        "deal": deal.get("text"),
        "dealExp": (deal.get("expiryDate") or "")[:10] or None,
        "shoppable": o.get("shoppable"),
    }

def main():
    st = stores()
    print(f"{len(st)} stores in {REGION}", file=sys.stderr)
    jobs = [(s, p) for s in st for p in PRODUCTS]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(check, s, p): (s["id"], p["code"]) for s, p in jobs}
        for f in concurrent.futures.as_completed(futs):
            results[futs[f]] = f.result()
    for s in st:
        s["items"] = {p["code"]: results[(s["id"], p["code"])] for p in PRODUCTS}
    # --- history: one compact entry per run, kept 14 days, summarised per store/product ---
    now = datetime.datetime.now(datetime.timezone.utc)
    hpath = os.path.join(HERE, "history.json")
    try:
        history = json.load(open(hpath))
    except Exception:
        history = []
    history.append({"t": now.isoformat(timespec="seconds"),
                    "s": {s["id"]: {c: it["stock"] for c, it in s["items"].items()} for s in st}})
    cutoff = (now - datetime.timedelta(days=14)).isoformat(timespec="seconds")
    history = [h for h in history if h["t"] >= cutoff]
    with open(hpath, "w") as f:
        json.dump(history, f, separators=(",", ":"))
    week = (now - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    for s in st:
        for c, it in s["items"].items():
            seq = [(h["t"], h["s"].get(s["id"], {}).get(c)) for h in history if h["t"] >= week]
            seq = [(t, v) for t, v in seq if v]
            last_out = next((t for t, v in reversed(seq) if v == "OUT"), None)
            last_low = next((t for t, v in reversed(seq) if v == "LOW"), None)
            last_change = None
            for i in range(len(seq) - 1, 0, -1):
                if seq[i][1] != seq[i - 1][1]:
                    last_change = seq[i][0]; break
            it["hist"] = {"n": len(seq), "out": sum(1 for _, v in seq if v == "OUT"),
                          "low": sum(1 for _, v in seq if v == "LOW"),
                          "lastOut": last_out, "lastLow": last_low, "lastChange": last_change}
    data = {
        "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "region": REGION,
        "banners": {k: {"label": v[0], "site": v[1]} for k, v in BANNERS.items()},
        "products": PRODUCTS,
        "stores": st,
    }
    with open(os.path.join(HERE, "data.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    tally = {}
    for s in st:
        for c, it in s["items"].items():
            tally[(c, it["stock"])] = tally.get((c, it["stock"]), 0) + 1
    for k in sorted(tally):
        print(k, tally[k], file=sys.stderr)

if __name__ == "__main__":
    main()
