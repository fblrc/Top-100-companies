#!/usr/bin/env python3
"""
dashboard.py — Dashboard UNICA e standalone per le maggiori societa' quotate
per capitalizzazione. Fonte dati GRATUITA: Yahoo Finance (yfinance).

Unisce i due strati precedenti in un solo file HTML con navigazione:
  VISTA TABELLA  -> confronto fondamentale + rischio, ordinabile e filtrabile
  (clic sul nome) -> VISTA SCHEDA -> analisi tecnica del titolo
                     (prezzo+SMA+S/R, RSI, MACD) + recap fondamentali/rischio

Una sola esecuzione: 1 set di prezzi (1 anno) riusato sia per il rischio sia
per gli indicatori tecnici, + .info per i fondamentali.

LIMITI (onesti):
  - UNIVERSE e' un seed statico: i ranghi reali cambiano ogni giorno.
  - .info di Yahoo e' non ufficiale: campi mancanti/incoerenti possibili.
  - beta/correlazione su giorni di trading comuni, instabili nel tempo.
  - lo strato tecnico e' DESCRITTIVO, non predittivo. Nessun buy/sell, no fair value.

Uso:
    python3 dashboard.py              # tutto l'universo
    python3 dashboard.py --limit 20   # test rapido
    python3 dashboard.py --benchmark SPY
"""
import argparse, sys, json, math, time, datetime as dt
import yfinance as yf
import pandas as pd
import numpy as np

BENCHMARK = "ACWI"
RANK_URL = "https://stockanalysis.com/list/biggest-companies/"

def fetch_universe(n):
    """Classifica per capitalizzazione ricostruita a ogni esecuzione da
    stockanalysis.com. Ticker gia' compatibili Yahoo (US + ADR esteri).
    Limite onesto: e' la classifica delle societa' QUOTATE NEGLI USA (incl.
    ADR): titoli solo esteri senza ADR (es. Saudi Aramco) non compaiono, in
    cambio ogni ticker e' garantito utilizzabile da yfinance senza mappature."""
    import urllib.request, re
    req = urllib.request.Request(RANK_URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    rows = re.findall(r'\{no:\d+,s:"([^"]+)",n:"([^"]*)",marketCap:(\d+)', html)
    if not rows:
        raise RuntimeError("parsing classifica fallito (struttura cambiata)")
    tickers = [s.replace(".", "-") for s, _n, _mc in rows[:n]]  # BRK.B -> BRK-B
    return tickers

# Lista di riserva (seed statico) usata solo se la fonte dinamica non risponde.
FALLBACK_UNIVERSE = [
    "NVDA","AAPL","MSFT","GOOGL","AMZN","META","2222.SR","AVGO","TSLA","BRK-B",
    "TSM","JPM","WMT","LLY","ORCL","V","005930.KS","MA","NFLX","XOM",
    "COST","JNJ","HD","PG","PLTR","BAC","ABBV","NVO","KO","SAP",
    "ASML","CVX","TMUS","GE","CRM","WFC","CSCO","PM","IBM","ABT",
    "MCD","NESN.SW","AXP","MS","LIN","T","DIS","GS","INTU","NOW",
    "ROG.SW","ACN","ISRG","MRK","RTX","BX","PEP","QCOM","AMD","TXN",
    "BKNG","ADBE","UBER","SHEL","CAT","VZ","BABA","SCHW","BA","SPGI",
    "0700.HK","C","BLK","HSBC","TMO","AMGN","PGR","BSX","SYK","NEE",
    "UNH","DHR","HON","TJX","PFE","GILD","DE","ETN","SONY","COP",
    "MUFG","UL","TTE.PA","SAN.PA","MC.PA","RMS.PA","OR.PA","SIE.DE","ALV.DE","AZN.L",
]

# ---------- helpers ----------
def safe(d, k):
    v = d.get(k)
    try:
        f = float(v); return f if math.isfinite(f) else np.nan
    except (TypeError, ValueError):
        return np.nan

def r(x, nd=2):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)

def series(idx, vals, nd=4):
    return [{"time": t.strftime("%Y-%m-%d"), "value": round(float(v), nd)}
            for t, v in zip(idx, vals) if pd.notna(v)]

def rsi_wilder(close, n=14):
    d = close.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1/n, min_periods=n).mean() / dn.ewm(alpha=1/n, min_periods=n).mean()
    return 100 - 100 / (1 + rs)

def macd(close, fast=12, slow=26, sig=9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal

# ---------- data ----------
def fx_to_usd(currencies):
    rates = {"USD": 1.0}
    for cur in {c for c in currencies if c and c != "USD"}:
        try:
            h = yf.Ticker(f"{cur}USD=X").history(period="5d")
            if len(h): rates[cur] = float(h["Close"].dropna().iloc[-1])
        except Exception: pass
    return rates

def fetch_fundamentals(tickers):
    rows, curr, names = [], [], {}
    for i, s in enumerate(tickers, 1):
        try: info = yf.Ticker(s).info
        except Exception: info = {}
        cur = info.get("currency") or "USD"; curr.append(cur)
        names[s] = info.get("shortName") or info.get("longName") or s
        rows.append({
            "ticker": s, "nome": names[s], "settore": info.get("sector"),
            "paese": info.get("country"), "valuta": cur,
            "mcap_local": safe(info, "marketCap"),
            "PE": safe(info, "trailingPE"), "PB": safe(info, "priceToBook"),
            "EV_EBITDA": safe(info, "enterpriseToEbitda"), "PEG": safe(info, "trailingPegRatio"),
            "div_yield_%": safe(info, "dividendYield"),
            "ROE_%": safe(info, "returnOnEquity") * 100,
            "debt_equity": safe(info, "debtToEquity"),
            "margine_netto_%": safe(info, "profitMargins") * 100,
            "margine_oper_%": safe(info, "operatingMargins") * 100,
        })
        print(f"  [{i}/{len(tickers)}] {s}", file=sys.stderr); time.sleep(0.12)
    df = pd.DataFrame(rows)
    rates = fx_to_usd(curr); df["fx_usd"] = df["valuta"].map(rates)
    df["mcap_usd_mld"] = df["mcap_local"] * df["fx_usd"] / 1e9
    return df, names

def download_prices(tickers, benchmark):
    syms = list(dict.fromkeys(tickers + [benchmark]))
    raw = yf.download(syms, period="1y", interval="1d",
                      auto_adjust=True, group_by="ticker", progress=False)
    return raw

def risk_metrics(raw, tickers, benchmark):
    def close(s):
        try: return raw[s]["Close"]
        except Exception: return pd.Series(dtype=float)
    cl = pd.DataFrame({s: close(s) for s in tickers + [benchmark]})
    ret = cl.pct_change(); bench = ret[benchmark]
    corr = ret[tickers].corr(); out = {}
    for s in tickers:
        rr = ret[s].dropna()
        vol = rr.std() * math.sqrt(252) * 100 if len(rr) > 20 else np.nan
        pair = pd.concat([ret[s], bench], axis=1).dropna()
        beta = (pair.cov().iloc[0, 1] / pair.iloc[:, 1].var()
                if len(pair) > 20 and pair.iloc[:, 1].var() > 0 else np.nan)
        p = cl[s].dropna()
        mdd = ((p / p.cummax()) - 1).min() * 100 if len(p) else np.nan
        c = corr[s].drop(s).dropna()
        out[s] = {"beta": r(beta), "volatilita_%": r(vol),
                  "max_drawdown_%": r(mdd), "corr_media": r(c.mean() if len(c) else np.nan)}
    return out

def technical(raw, tickers):
    out = {}
    for s in tickers:
        try: ohlc = raw[s]
        except Exception: continue
        df = ohlc.dropna(subset=["Close"]).copy()
        if len(df) < 60: continue
        c = df["Close"]
        df["sma50"] = c.rolling(50).mean(); df["sma200"] = c.rolling(200).mean()
        df["rsi"] = rsi_wilder(c)
        df["macd"], df["sig"], df["hist"] = macd(c)
        df["vol_ma20"] = df["Volume"].rolling(20).mean()
        win = df.tail(90); last = df.iloc[-1]; px = float(last["Close"])
        s50, s200 = last["sma50"], last["sma200"]
        if pd.notna(s200) and pd.notna(s50):
            trend = ("Rialzista" if px > s200 and s50 > s200 else
                     "Ribassista" if px < s200 and s50 < s200 else "Laterale/misto")
        else: trend = "Storia insufficiente"
        rsi_v = last["rsi"]
        zone = ("ipercomprato" if rsi_v > 70 else "ipervenduto" if rsi_v < 30 else "neutro") if pd.notna(rsi_v) else "n/d"
        h = df["hist"].dropna().tail(6).values; cross = "nessuno (recente)"
        for i in range(1, len(h)):
            if h[i-1] <= 0 < h[i]: cross = "rialzista"
            elif h[i-1] >= 0 > h[i]: cross = "ribassista"
        vr = last["Volume"] / last["vol_ma20"] if pd.notna(last["vol_ma20"]) and last["vol_ma20"] else np.nan
        golden = bool(pd.notna(s50) and pd.notna(s200) and s50 > s200)
        hh = df["hist"].dropna()
        macd_pos = bool(len(hh) and hh.iloc[-1] > 0)
        out[s] = {
            "candles": [{"time": t.strftime("%Y-%m-%d"), "open": round(float(o),4), "high": round(float(hi),4),
                         "low": round(float(lo),4), "close": round(float(cl_),4)}
                        for t,o,hi,lo,cl_ in zip(df.index, df["Open"], df["High"], df["Low"], df["Close"])
                        if pd.notna(o) and pd.notna(hi) and pd.notna(lo) and pd.notna(cl_)],
            "sma50": series(df.index, df["sma50"]), "sma200": series(df.index, df["sma200"]),
            "rsi": series(df.index, df["rsi"], 2),
            "macd": series(df.index, df["macd"]), "sig": series(df.index, df["sig"]),
            "hist": [{"time": t.strftime("%Y-%m-%d"), "value": round(float(v),4),
                      "color": "#26a69a" if v >= 0 else "#ef5350"}
                     for t,v in zip(df.index, df["hist"]) if pd.notna(v)],
            "levels": {"res90": r(win["High"].max()), "sup90": r(win["Low"].min()),
                       "hi52": r(df["High"].max()), "lo52": r(df["Low"].min())},
            "state": {"close": r(px), "date": df.index[-1].strftime("%Y-%m-%d"), "trend": trend,
                      "rsi": r(rsi_v,1), "rsi_zone": zone, "macd_cross": cross,
                      "vs_sma50": r((px/s50-1)*100,1) if pd.notna(s50) else None,
                      "vs_sma200": r((px/s200-1)*100,1) if pd.notna(s200) else None,
                      "vs_hi52": r((px/df['High'].max()-1)*100,1),
                      "vol_ma20": r(vr), "golden": golden, "macd_pos": macd_pos},
        }
    return out

# ---------- main ----------
def composite_score(state, frow, sector, med_sec, med_all):
    """Punteggio composito TRASPARENTE da regole esplicite. NON e' una
    raccomandazione: e' una sintesi meccanica degli indicatori gia' calcolati.
    La valutazione e' relativa alla mediana del SETTORE (fallback: universo).
    Restituisce (tech100, val100, comp100, tech_label, val_label, breakdown, val_basis)."""
    t, tmax, br = 0, 5, []
    v = state.get("vs_sma200")
    if v is not None:
        if v > 0: t += 1; br.append(["Prezzo > SMA200", "+"])
        else: t -= 1; br.append(["Prezzo < SMA200", "−"])
    if state.get("golden"): t += 1; br.append(["SMA50 > SMA200 (golden)", "+"])
    else: t -= 1; br.append(["SMA50 ≤ SMA200 (death)", "−"])
    if state.get("macd_pos"): t += 1; br.append(["MACD > 0", "+"])
    else: t -= 1; br.append(["MACD < 0", "−"])
    rsi = state.get("rsi")
    if rsi is not None:
        if 50 <= rsi <= 70: t += 1; br.append([f"RSI {rsi} (50-70)", "+"])
        elif rsi < 40: t -= 1; br.append([f"RSI {rsi} (<40)", "−"])
        elif rsi > 75: t -= 1; br.append([f"RSI {rsi} (ipercomprato)", "−"])
        else: br.append([f"RSI {rsi}", "0"])
    hi = state.get("vs_hi52")
    if hi is not None:
        if hi > -10: t += 1; br.append([f"{hi}% dai max 52s", "+"])
        elif hi < -25: t -= 1; br.append([f"{hi}% dai max 52s", "−"])
    tech100 = round((t + tmax) / (2 * tmax) * 100)
    secmed = med_sec.get(sector, {})
    parts, used_sec, used_uni = [], False, False
    for k in ("PE", "EV_EBITDA", "PEG"):
        val = frow.get(k)
        if val is None or val <= 0:
            continue
        if k in secmed:
            m = secmed[k]; used_sec = True
        elif k in med_all:
            m = med_all[k]; used_uni = True
        else:
            continue
        parts.append(max(-1.0, min(1.0, (m - val) / m)))  # >0 = piu' economico della mediana
    val100 = round((sum(parts) / len(parts) + 1) / 2 * 100) if parts else 50
    comp100 = round((tech100 + val100) / 2)
    tlab = "Rialzista" if tech100 >= 60 else "Ribassista" if tech100 <= 40 else "Neutro"
    vlab = "Sconto vs pari" if val100 >= 60 else "Premio vs pari" if val100 <= 40 else "In linea"
    basis = "settore" if used_sec and not used_uni else "misto" if used_sec else "universo" if used_uni else "n/d"
    return tech100, val100, comp100, tlab, vlab, br, basis

COLS = [
    ("nome","Nome",0),("ticker","Ticker",0),("settore","Settore",0),("paese","Paese",0),
    ("composito","Score",1),("tech_label","Tecnico",0),("val_label","Valut.vs pari",0),
    ("mcap_usd_mld","Mcap $mld",1),("PE","P/E",1),("PB","P/B",1),("EV_EBITDA","EV/EBITDA",1),
    ("PEG","PEG",1),("div_yield_%","Div %",1),("ROE_%","ROE %",1),("debt_equity","Debt/Eq",1),
    ("margine_netto_%","Marg.netto %",1),("margine_oper_%","Marg.oper %",1),
    ("beta","Beta",1),("volatilita_%","Volat %",1),("max_drawdown_%","MaxDD %",1),("corr_media","Corr media",1),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100, help="quante societa' (default 100)")
    ap.add_argument("--static", action="store_true", help="usa la lista di riserva, niente fetch")
    ap.add_argument("--benchmark", default=BENCHMARK)
    ap.add_argument("--out", default="dashboard")
    a = ap.parse_args()
    if a.static:
        tk = FALLBACK_UNIVERSE[:a.top]
        src = "lista statica di riserva"
    else:
        try:
            tk = fetch_universe(a.top)
            src = "classifica live (stockanalysis.com)"
            print(f"Classifica ricostruita: {len(tk)} societa' (fonte live).", file=sys.stderr)
        except Exception as e:
            tk = FALLBACK_UNIVERSE[:a.top]
            src = "lista statica di riserva (fonte live non raggiungibile)"
            print(f"Fonte live KO ({e}). Uso la lista di riserva.", file=sys.stderr)
    print(f"Fondamentali ({len(tk)})...", file=sys.stderr)
    fund, names = fetch_fundamentals(tk)
    print("Prezzi 1y (riuso per rischio + tecnico)...", file=sys.stderr)
    raw = download_prices(tk, a.benchmark)
    risk = risk_metrics(raw, tk, a.benchmark)
    tech = technical(raw, tk)
    fund = fund.set_index("ticker")
    for s in tk:
        for k, v in risk.get(s, {}).items(): fund.loc[s, k] = v
    fund = fund.reset_index().sort_values("mcap_usd_mld", ascending=False, na_position="last")
    VAL_METRICS = ("PE", "EV_EBITDA", "PEG")
    MIN_N = 4  # minimo titoli per fidarsi della mediana di settore
    med_all = {k: float(fund[fund[k] > 0][k].median())
               for k in VAL_METRICS if (fund[k] > 0).any()}
    med_sec = {}
    for sec, g in fund.groupby("settore"):
        d = {}
        for k in VAL_METRICS:
            vals = g[g[k] > 0][k]
            if len(vals) >= MIN_N:
                d[k] = float(vals.median())
        if d:
            med_sec[sec] = d
    rows = []
    for _, x in fund.iterrows():
        row = {"ticker": x["ticker"], "has_tech": x["ticker"] in tech}
        for k, _lbl, num in COLS:
            v = x.get(k)
            row[k] = (r(v, 2) if (num and pd.notna(v)) else (None if pd.isna(v) else v))
        st = tech.get(x["ticker"], {}).get("state")
        if st:
            frow = {k: (None if pd.isna(x.get(k)) else float(x.get(k))) for k in VAL_METRICS}
            t100, v100, c100, tl, vl, br, vb = composite_score(
                st, frow, x.get("settore"), med_sec, med_all)
            row["composito"], row["tech_label"], row["val_label"] = c100, tl, vl
            tech[x["ticker"]]["score"] = {"tech": t100, "val": v100, "comp": c100,
                                          "tlab": tl, "vlab": vl, "br": br, "vbasis": vb}
        else:
            row["composito"], row["tech_label"], row["val_label"] = None, None, None
        rows.append(row)
    payload = {"meta": {"gen": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "benchmark": a.benchmark, "n": len(rows), "src": src},
               "cols": [{"k": k, "l": l, "num": bool(n)} for k, l, n in COLS],
               "rows": rows, "names": names, "tech": tech}
    LIB_URL = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
    try:
        import urllib.request
        lib = urllib.request.urlopen(LIB_URL, timeout=30).read().decode("utf-8")
        libtag = "<script>\n" + lib + "\n</script>"
        print("Libreria grafici incorporata (offline-ready).", file=sys.stderr)
    except Exception as e:
        libtag = f'<script src="{LIB_URL}"></script>'
        print(f"Libreria non scaricata ({e}): uso CDN (richiede internet).", file=sys.stderr)
    html = HTML.replace("__LIBTAG__", libtag).replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    with open(f"{a.out}.html", "w") as f: f.write(html)
    fund.to_csv(f"{a.out}.csv", index=False)
    print(f"\nScritti: {a.out}.html  {a.out}.csv  (tabella {len(rows)}, schede tecniche {len(tech)})", file=sys.stderr)

HTML = r"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top societa' — fondamentali, rischio, tecnica</title>
__LIBTAG__
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--txt:#e6e9ef;--mut:#8b93a3;--acc:#4f8cff;--up:#26a69a;--dn:#ef5350}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:13px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;padding:20px}
h1{font-size:17px;margin:0 0 2px}p.sub{color:var(--mut);margin:0 0 14px;font-size:12px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
input,select,button{background:var(--card);color:var(--txt);border:1px solid var(--line);
border-radius:8px;padding:8px 10px;font-size:13px}
input{min-width:220px}select{min-width:300px}button{cursor:pointer}button:hover{border-color:var(--acc);color:var(--acc)}
.wrap{overflow:auto;border:1px solid var(--line);border-radius:10px;background:var(--card);max-height:78vh}
table{border-collapse:collapse;width:100%;white-space:nowrap}
th,td{padding:8px 10px;text-align:right;border-bottom:1px solid var(--line)}
th:nth-child(-n+4),td:nth-child(-n+4){text-align:left}
th{position:sticky;top:0;background:#1d212b;cursor:pointer;user-select:none;font-weight:600}
th:hover{color:var(--acc)}tr:hover td{background:#1b1f28}
td.name{font-weight:600;color:var(--acc);cursor:pointer}td.name:hover{text-decoration:underline}
td.dim{color:var(--mut)}
.grid{display:grid;grid-template-columns:1fr 300px;gap:14px;align-items:start}
@media(max-width:860px){.grid{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:14px}
.lbl{color:var(--mut);font-size:11px;margin:0 0 6px;text-transform:uppercase;letter-spacing:.04em}
#price{height:300px}#rsi{height:120px}#macd{height:120px}
.kv div{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--line)}
.tag{padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.t-up{background:rgba(38,166,154,.18);color:#5fd0c4}.t-dn{background:rgba(239,83,80,.18);color:#ff8a87}
.t-mid{background:rgba(139,147,163,.18);color:#b3bac7}
.note{color:var(--mut);font-size:11px;margin-top:12px;max-width:920px}
.hidden{display:none}
</style></head><body>
<div id="err" style="display:none;background:#3a1416;color:#ff8a87;border:1px solid #ef5350;border-radius:8px;padding:10px;margin-bottom:12px;font-size:12px;white-space:pre-wrap"></div>
<script>window.addEventListener('error',function(e){var b=document.getElementById('err');if(!b)return;b.style.display='block';b.textContent='Errore JS: '+(e.message||e)+(e.filename?(' @ '+(e.filename.split('/').pop())+':'+e.lineno):'');});</script>
<h1 id="title"></h1><p class="sub" id="sub"></p>
<p class="sub" id="disc" style="color:#b3bac7;background:#1b1f28;border:1px solid var(--line);border-radius:8px;padding:8px 10px;max-width:920px"></p>

<section id="view-table">
  <div class="bar">
    <input id="flt" placeholder="Filtra per nome / settore / paese…">
    <span class="sub" id="cnt"></span>
  </div>
  <div class="wrap"><table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></div>
  <p class="note">Multipli e ratio sono oggettivi; non c'e' "fair value" ne' segnali buy/sell. Beta/correlazione su giorni comuni vs benchmark, instabili nel tempo. Mcap convertita in USD ai cambi correnti. Clic sull'intestazione per ordinare, sul nome per la scheda tecnica.</p>
</section>

<section id="view-card" class="hidden">
  <div class="bar">
    <button id="back">← Torna alla tabella</button>
    <select id="sel"></select>
  </div>
  <div class="grid">
    <div>
      <div class="panel"><div class="lbl">Prezzo · SMA50 (blu) · SMA200 (arancio) · S/R 90g (tratteggio)</div><div id="price"></div></div>
      <div class="panel"><div class="lbl">RSI 14 (linee 30 / 70)</div><div id="rsi"></div></div>
      <div class="panel"><div class="lbl">MACD 12/26/9</div><div id="macd"></div></div>
    </div>
    <div>
      <div class="panel kv" id="fund"></div>
      <div class="panel" id="synth"></div>
      <div class="panel kv" id="state"></div>
    </div>
  </div>
  <p class="note">Strato tecnico DESCRITTIVO, non predittivo: su mega-cap liquide il valore predittivo dei segnali e' debole e contestato. S/R euristici (estremi 90g). Non e' consulenza finanziaria.</p>
</section>

<script>
const P=__PAYLOAD__;
if(typeof LightweightCharts==='undefined'){var eb=document.getElementById('err');eb.style.display='block';eb.textContent='Libreria grafici non caricata: la tabella funziona, le schede tecniche no.';}
const LWC=window.LightweightCharts;
const fmt=v=>v===null||v===undefined?'—':v;
document.getElementById('title').textContent='Maggiori societa\u2019 per capitalizzazione — fondamentali, rischio, tecnica';
document.getElementById('sub').textContent='Ranking: '+P.meta.src+' · '+P.meta.n+' societa\u2019 · benchmark beta: '+P.meta.benchmark+' · 1 anno giornaliero · generato '+P.meta.gen;
document.getElementById('disc').textContent='\u26a0 Lo "Score" composito e i campi Tecnico/Valutazione sono una sintesi MECCANICA e trasparente degli indicatori (vedi scomposizione nella scheda di ogni titolo). NON sono una raccomandazione di acquisto o vendita: descrivono lo stato attuale di trend e multipli, non prevedono i rendimenti futuri. La valutazione e\u2019 relativa alla mediana del SETTORE (fallback alla mediana dell\u2019universo per settori con meno di 4 titoli). Non e\u2019 consulenza finanziaria.';
const byTicker={};P.rows.forEach(r=>byTicker[r.ticker]=r);

/* ---- tabella ---- */
const head=document.getElementById('head');
P.cols.forEach((c,i)=>{const th=document.createElement('th');th.textContent=c.l;th.onclick=()=>sortBy(i);head.appendChild(th);});
let dir={};
function renderRows(list){
  const tb=document.getElementById('body');tb.innerHTML='';
  list.forEach(row=>{
    const tr=document.createElement('tr');
    P.cols.forEach((c,i)=>{
      const td=document.createElement('td');const v=row[c.k];
      td.dataset.v=(v===null||v===undefined)?'':v;
      td.textContent=fmt(v);
      if(i===0){td.className='name';td.onclick=()=>{if(row.has_tech)showCard(row.ticker);};if(!row.has_tech){td.style.color='var(--mut)';td.style.cursor='default';td.title='Scheda tecnica non disponibile';}}
      else if(i>=1&&i<=3)td.className='dim';
      if(c.k==='tech_label'||c.k==='val_label'){const up=/Rial|Sconto/.test(v||''),dn=/Riba|Premio/.test(v||'');td.style.color=up?'#5fd0c4':dn?'#ff8a87':'var(--mut)';td.style.textAlign='center';}
      if(c.k==='composito'&&v!=null){td.style.fontWeight='600';td.style.color=v>=60?'#5fd0c4':v<=40?'#ff8a87':'var(--txt)';}
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  document.getElementById('cnt').textContent=list.length+' righe';
}
let current=[...P.rows];
function sortBy(i){const k=P.cols[i].k,num=P.cols[i].num;dir[i]=!dir[i];const d=dir[i]?1:-1;
  current.sort((a,b)=>{let x=a[k],y=b[k];
    if(x===null||x===undefined)return 1;if(y===null||y===undefined)return -1;
    return num?(x-y)*d:String(x).localeCompare(String(y))*d;});
  renderRows(current);}
document.getElementById('flt').addEventListener('input',e=>{
  const q=e.target.value.toLowerCase();
  current=P.rows.filter(r=>[r.nome,r.settore,r.paese,r.ticker].some(x=>x&&String(x).toLowerCase().includes(q)));
  renderRows(current);});
renderRows(current);

/* ---- selettore scheda ---- */
const sel=document.getElementById('sel');
Object.keys(P.tech).sort((a,b)=>(P.names[a]||a).localeCompare(P.names[b]||b))
 .forEach(t=>{const o=document.createElement('option');o.value=t;o.textContent=(P.names[t]||t)+'  ('+t+')';sel.appendChild(o);});
sel.addEventListener('change',e=>showCard(e.target.value,true));
document.getElementById('back').onclick=()=>{document.getElementById('view-card').classList.add('hidden');document.getElementById('view-table').classList.remove('hidden');};

/* ---- grafici (lazy) ---- */
let charts=null,S={};
function ensureCharts(){
  if(charts)return;
  const opt={layout:{background:{color:'#171a21'},textColor:'#8b93a3'},
   grid:{vertLines:{color:'#1f2430'},horzLines:{color:'#1f2430'}},
   rightPriceScale:{borderColor:'#262b36'},timeScale:{borderColor:'#262b36'},autoSize:true};
  const cP=LWC.createChart(document.getElementById('price'),{...opt,height:300});
  const cR=LWC.createChart(document.getElementById('rsi'),{...opt,height:120});
  const cM=LWC.createChart(document.getElementById('macd'),{...opt,height:120});
  S.candle=cP.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
  S.sma50=cP.addLineSeries({color:'#4f8cff',lineWidth:1});
  S.sma200=cP.addLineSeries({color:'#f0a23b',lineWidth:1});
  S.rsi=cR.addLineSeries({color:'#c98bff',lineWidth:1});
  S.macd=cM.addLineSeries({color:'#4f8cff',lineWidth:1});
  S.sig=cM.addLineSeries({color:'#f0a23b',lineWidth:1});
  S.hist=cM.addHistogramSeries({});
  charts=[cP,cR,cM];
}
let plines=[];
function tagcls(tr){return tr.startsWith('Rial')?'t-up':tr.startsWith('Riba')?'t-dn':'t-mid';}
function pct(v){return v==null?'—':(v>0?'+':'')+v+'%';}
function kv(k,v){return '<div><span>'+k+'</span><span>'+v+'</span></div>';}
function showCard(t,keepSel){
  document.getElementById('view-table').classList.add('hidden');
  document.getElementById('view-card').classList.remove('hidden');
  if(!keepSel)sel.value=t;
  ensureCharts();
  const d=P.tech[t],s=d.state,f=byTicker[t]||{};
  S.candle.setData(d.candles);S.sma50.setData(d.sma50);S.sma200.setData(d.sma200);
  S.rsi.setData(d.rsi);S.macd.setData(d.macd);S.sig.setData(d.sig);S.hist.setData(d.hist);
  plines.forEach(([sr,pl])=>sr.removePriceLine(pl));plines=[];
  const L=d.levels;
  [['Resistenza 90g',L.res90,'#ef5350'],['Supporto 90g',L.sup90,'#26a69a']].forEach(([n,p,col])=>{
    if(p!=null){const pl=S.candle.createPriceLine({price:p,color:col,lineWidth:1,lineStyle:2,title:n});plines.push([S.candle,pl]);}});
  [30,70].forEach(y=>{const pl=S.rsi.createPriceLine({price:y,color:'#3a4150',lineWidth:1,lineStyle:2,title:''+y});plines.push([S.rsi,pl]);});
  charts.forEach(c=>c.timeScale().fitContent());
  document.getElementById('fund').innerHTML='<div class="lbl">'+(P.names[t]||t)+' — fondamentali &amp; rischio</div>'+
    kv('Capitalizzazione','$'+fmt(f.mcap_usd_mld)+' mld')+kv('Settore',fmt(f.settore))+
    kv('P/E',fmt(f.PE))+kv('P/B',fmt(f.PB))+kv('EV/EBITDA',fmt(f.EV_EBITDA))+kv('PEG',fmt(f.PEG))+
    kv('Div yield',fmt(f['div_yield_%'])+'%')+kv('ROE',fmt(f['ROE_%'])+'%')+kv('Debt/Equity',fmt(f.debt_equity))+
    kv('Beta',fmt(f.beta))+kv('Volatilita\u2019',fmt(f['volatilita_%'])+'%')+kv('Max drawdown',fmt(f['max_drawdown_%'])+'%')+kv('Corr media',fmt(f.corr_media));
  document.getElementById('state').innerHTML='<div class="lbl">Stato tecnico</div>'+
    kv('Ultimo prezzo','<b>'+s.close+'</b> ('+s.date+')')+
    kv('Trend','<span class="tag '+tagcls(s.trend)+'">'+s.trend+'</span>')+
    kv('RSI 14',s.rsi+' · '+s.rsi_zone)+kv('Incrocio MACD',s.macd_cross)+
    kv('vs SMA50',pct(s.vs_sma50))+kv('vs SMA200',pct(s.vs_sma200))+kv('vs max 52sett',pct(s.vs_hi52))+
    kv('Volume vs media20',s.vol_ma20==null?'—':s.vol_ma20+'x');
  const sc=d.score;const syn=document.getElementById('synth');
  if(sc){
    const col=v=>v>=60?'#26a69a':v<=40?'#ef5350':'#8b93a3';
    const bar=(lab,v)=>'<div style="margin:4px 0"><div style="display:flex;justify-content:space-between;font-size:12px"><span>'+lab+'</span><span style="color:'+col(v)+';font-weight:600">'+v+'/100</span></div><div style="height:6px;background:#0f1115;border-radius:4px;overflow:hidden"><div style="height:100%;width:'+v+'%;background:'+col(v)+'"></div></div></div>';
    const items=sc.br.map(b=>'<span style="display:inline-block;margin:2px 4px 2px 0;padding:1px 7px;border-radius:12px;font-size:11px;background:'+(b[1]==='+'?'rgba(38,166,154,.18)':b[1]==='−'?'rgba(239,83,80,.18)':'rgba(139,147,163,.15)')+';color:'+(b[1]==='+'?'#5fd0c4':b[1]==='−'?'#ff8a87':'#b3bac7')+'">'+b[1]+' '+b[0]+'</span>').join('');
    syn.innerHTML='<div class="lbl">Segnale composito (sintesi meccanica, non una raccomandazione)</div>'+
      bar('Score composito',sc.comp)+bar('Tecnico ('+sc.tlab+')',sc.tech)+bar('Valutazione vs '+(sc.vbasis==='settore'?'pari di settore':sc.vbasis==='misto'?'pari (settore+universo)':'universo')+' ('+sc.vlab+')',sc.val)+
      '<div style="margin-top:8px;color:#8b93a3;font-size:11px">Scomposizione tecnica:</div><div style="margin-top:4px">'+items+'</div>';
  } else { syn.innerHTML=''; }
}
</script></body></html>"""

if __name__ == "__main__":
    main()
