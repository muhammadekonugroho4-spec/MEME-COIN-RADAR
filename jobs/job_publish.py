"""Job publish (Fase web): render dashboard STATIS dari data/ -> folder publish/.

Output (dibagikan GitHub Pages):
  publish/index.html   - dashboard satu halaman: KPI, radar, posisi, jurnal, statistik, laporan
  publish/data.json    - semua data (untuk render JS)

Dipanggil workflow pages.yml setelah scan/trade/report; dashboard selalu sinkron dgn bot.
Murni baca file lokal - tidak ada network.
"""
from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import pandas as pd

from backend import config
from backend.core import portfolio as pf

MAX_ROWS = 60


def _clean_nans(obj):
    """NaN/inf -> None supaya JSON valid untuk browser (json.dumps menulis NaN mentah)."""
    if isinstance(obj, float):
        return None if (obj != obj or obj in (float("inf"), float("-inf"))) else obj
    if isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nans(v) for v in obj]
    return obj


def _latest_day() -> Path | None:
    dirs = sorted((d for d in config.DAILY_DIR.iterdir() if d.is_dir() and d.name[:2] == "20"), reverse=True)
    return dirs[0] if dirs else None


def _read_scan(day: Path) -> tuple[list[dict], dict]:
    p = day / "scan_results.csv"
    mf = day / "scan_manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {}
    if not p.exists():
        return [], manifest
    df = pd.read_csv(p)
    df = pd.read_csv(p).astype(object).where(pd.notna(df), None)
    return [_clean_nans(r) for r in df.to_dict(orient="records")], manifest


def _read_portfolio() -> dict:
    state = pf.load_state(config.PORTFOLIO_DIR, config.PAPER_START_EQUITY)

    def _latest(mint: str):
        p = config.COINS_DIR / f"{mint}.parquet"
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        return float(df.iloc[-1]["price_usd"]) if len(df) else None

    positions = []
    for mint, pos in state.get("positions", {}).items():
        positions.append({
            "mint": mint, "symbol": pos.get("symbol", mint[:8]), "qty": pos.get("qty"),
            "entry_price": pos.get("entry_price"), "price_now": _latest(mint),
            "tp_done": pos.get("tp_done", False),
        })
    prices = {p["mint"]: p["price_now"] for p in positions if p["price_now"] is not None}
    unreal = pf.unrealized_pnl(state, prices)
    equity_rows = []
    eq_path = config.PORTFOLIO_DIR / pf.EQUITY_FILE
    if eq_path.exists():
        equity_rows = pd.read_csv(eq_path).tail(80).to_dict(orient="records")
    trades = []
    tr_path = config.PORTFOLIO_DIR / pf.TRADES_FILE
    if tr_path.exists():
        trades = pd.read_csv(tr_path).tail(MAX_ROWS).to_dict(orient="records")
    return {
        "start_equity": state.get("start_equity", config.PAPER_START_EQUITY),
        "equity_cash": state["equity"], "unrealized": round(unreal, 4),
        "total": round(state["equity"] + unreal, 4),
        "positions": positions, "pending": state.get("pending", []),
        "trades": list(reversed(trades)), "equity": equity_rows,
    }


def _read_report(day: Path | None) -> str:
    if day is None:
        return ""
    p = day / "report.md"
    return p.read_text() if p.exists() else ""


def _read_stats(daily_root: Path) -> dict:
    buckets = {"likuiditas": 0, "umur": 0, "FDV": 0, "wash": 0, "rug": 0, "umur tidak diketahui": 0, "lain": 0}
    total = 0
    for d in sorted(daily_root.glob("20*")):
        p = d / "scan_results.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        for reasons in df.get("reasons", pd.Series(dtype=str)).fillna(""):
            if not reasons:
                continue
            total += 1
            rl = reasons.lower()
            if "likuiditas" in rl:
                buckets["likuiditas"] += 1
            elif "tidak diketahui" in rl:
                buckets["umur tidak diketahui"] += 1
            elif "umur" in rl:
                buckets["umur"] += 1
            elif "FDV" in reasons:
                buckets["FDV"] += 1
            elif "wash" in rl:
                buckets["wash"] += 1
            elif "rug" in rl:
                buckets["rug"] += 1
            else:
                buckets["lain"] += 1
    return {"total_rejected": total, "by_reason": buckets}


def build(publish_dir: Path | None = None) -> Path:
    publish_dir = publish_dir or config.BASE_DIR / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)
    day = _latest_day()
    scan_rows, scan_manifest = _read_scan(day) if day else ([], {})
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M UTC"),
        "day": day.name if day else None,
        "scan": {"manifest": scan_manifest, "results": scan_rows[-MAX_ROWS:]},
        "portfolio": _read_portfolio(),
        "stats": _read_stats(config.DAILY_DIR),
        "report_md": _read_report(day)[-4000:],  # ekor laporan (bagian paling relevan)
    }
    data = _clean_nans(data)
    dpnl = config.PORTFOLIO_DIR / "daily_pnl.json"
    data["daily_pnl"] = json.loads(dpnl.read_text()) if dpnl.exists() else {}
    data = _clean_nans(data)
    (publish_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, default=str, allow_nan=False))
    (publish_dir / "index.html").write_text(INDEX_HTML)
    return publish_dir


INDEX_HTML = """<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MEME-COIN-RADAR</title>
<style>
:root{--bg:#0b0f1a;--card:#121a2e;--line:#1f2b47;--txt:#dbe4f5;--dim:#7d8db0;--buy:#31c48d;--watch:#f5b942;--rej:#f05252;--acc:#5a8dee}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 2px}h1 span{color:var(--acc)}
.sub{color:var(--dim);font-size:12px;margin-bottom:14px}
.kpis{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.k{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px}
.k b{display:block;font-size:20px}.k span{color:var(--dim);font-size:12px}
.up{color:var(--buy)}.down{color:var(--rej)}.watch{color:var(--watch)}
h2{font-size:15px;margin:18px 0 8px;color:var(--acc)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;margin-bottom:14px;font-size:13px}
th,td{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
th{background:#0e1730;color:var(--dim);text-align:right}
th:first-child,td:first-child{text-align:left}
td.why{text-align:left;max-width:280px;color:var(--dim);font-size:12px}
.zb{font-size:11px;padding:2px 8px;border-radius:6px;font-weight:700}
.zb.BUY{background:#0e2e22;color:var(--buy)}.zb.WATCH{background:#33290f;color:var(--watch)}
.zb.PASSIVE{background:#1a2236;color:var(--dim)}.zb.REJECT{background:#331a1a;color:var(--rej)}.zb.SKIP{background:#1a2236;color:var(--dim)}
.bar{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;font-size:13px}
.track{flex:1;height:8px;background:#0e1730;border-radius:4px;margin:0 14px;overflow:hidden}
.fill{height:100%;background:var(--rej);border-radius:4px}
pre.report{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;font-size:12px;white-space:pre-wrap;color:var(--txt);max-height:420px;overflow:auto}
.empty{padding:14px;text-align:center;color:var(--dim)}
.cal-head{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px}
.cal-head div{text-align:center;color:var(--dim);font-size:11px;padding:2px 0}
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:14px}
.cal .day{aspect-ratio:1.5;border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid var(--line);background:var(--card);font-size:11px}
.cal .day .pnl{font-weight:700;font-size:11px}
.cal .day.win{background:#0e2e22;border-color:#1d5c40}
.cal .day.loss{background:#331a1a;border-color:#6b2424}
.cal .day.flat{opacity:.55}
.cal .day .num{color:var(--dim)}
.legend{display:flex;gap:12px;margin:8px 0 10px;font-size:12px;color:var(--dim)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.dot{width:12px;height:12px;border-radius:4px;display:inline-block}
.dis{color:var(--dim);font-size:11px;text-align:center;margin-top:14px}
</style>
</head>
<body>
<div class="wrap">
<h1>MEME-COIN-<span>RADAR</span></h1>
<div class="sub" id="gen"></div>
<div class="kpis" id="kpis"></div>

<h2>Radar (scan terbaru)</h2>
<table><thead><tr><th>Coin</th><th>Zona</th><th>Skor</th><th>Harga</th><th>Likuid</th><th>Umur</th><th>AI</th><th>Alasan</th></tr></thead>
<tbody id="radar"></tbody></table>

<h2>Posisi paper terbuka</h2>
<table><thead><tr><th>Coin</th><th>Qty</th><th>Entry</th><th>Harga kini</th><th>PnL</th></tr></thead>
<tbody id="pos"></tbody></table>

<h2>Trades terakhir</h2>
<table><thead><tr><th>Waktu</th><th>Coin</th><th>Side</th><th>Qty</th><th>Harga</th><th>USD</th><th>Alasan</th></tr></thead>
<tbody id="trades"></tbody></table>

<h2>Statistik filter (kumulatif)</h2>
<div id="stats"></div>

<h2>Kalender PnL harian</h2>
<div class="legend">
  <span><i class="dot" style="background:#0e2e22;border:1px solid #1d5c40"></i> untung</span>
  <span><i class="dot" style="background:#331a1a;border:1px solid #6b2424"></i> rugi</span>
  <span><i class="dot" style="background:var(--card);border:1px solid var(--line)"></i> netral</span>
</div>
<div class="cal-head"><div>Sen</div><div>Sel</div><div>Rab</div><div>Kam</div><div>Jum</div><div>Sab</div><div>Min</div></div>
<div class="cal" id="cal"></div>

<h2>Laporan terakhir</h2>
<pre class="report" id="report"></pre>
<div class="dis">Simulasi virtual (paper-only) — bukan saran finansial. Meme coin berisiko total loss.<br>
Data diperbarui otomatis oleh bot tiap 5-10 menit via GitHub Actions.</div>
</div>
<script>
const fmt$=v=>v==null?'-':Number(v)>=1?'$'+Number(v).toLocaleString('en',{maximumFractionDigits:0}):'$'+Number(v).toPrecision(3);
const cls=v=>v>=0?'up':'down';
fetch('data.json').then(r=>r.json()).then(d=>{
  document.getElementById('gen').textContent=`Data: ${d.day||'-'} · render ${d.generated_at} · sumber: repo ini (auto-commit bot)`;
  const P=d.portfolio||{};
  const k=document.getElementById('kpis');
  k.innerHTML=`
   <div class="k"><b class="${cls(P.total-P.start_equity)}">$${Number(P.total||0).toFixed(2)}</b><span>Total equity</span></div>
   <div class="k"><b>$${Number(P.equity_cash||0).toFixed(2)}</b><span>Cash</span></div>
   <div class="k"><b class="${cls(P.unrealized)}">$${Number(P.unrealized||0).toFixed(2)}</b><span>Unrealized</span></div>
   <div class="k"><b>${(P.positions||[]).length}</b><span>Posisi terbuka</span></div>
   <div class="k"><b>${(d.stats||{}).total_rejected??'-'}</b><span>Reject filter total</span></div>`;
  const r=(d.scan&&d.scan.results)||[];
  document.getElementById('radar').innerHTML=r.length?r.map(x=>`<tr>
    <td><b>${(x.symbol||'?').slice(0,10)}</b><div style="color:var(--dim);font-size:10px">${(x.mint||'').slice(0,8)}…</div></td>
    <td><span class="zb ${x.zone}">${x.zone}</span></td><td>${x.score??'-'}</td><td>${fmt$(x.price_usd)}</td>
    <td>${fmt$(x.liquidity_usd)}</td><td>${x.age_min!=null?x.age_min+'m':'?'}</td>
    <td class="why" style="color:${x.ai_flag==='danger'?'var(--rej)':x.ai_flag==='caution'?'var(--watch)':'var(--buy)'}">${x.ai_flag||''} ${x.ai_note||''}</td>
    <td class="why">${x.reasons||''}</td></tr>`).join('')
    :'<tr><td colspan="8" class="empty">Belum ada scan.</td></tr>';
  const pos=P.positions||[];
  document.getElementById('pos').innerHTML=pos.length?pos.map(p=>{
    const pnl=p.price_now!=null?(p.price_now-p.entry_price)*p.qty:null;
    return `<tr><td>${p.symbol}</td><td>${Number(p.qty).toPrecision(4)}</td><td>${fmt$(p.entry_price)}</td>
    <td>${fmt$(p.price_now)}</td><td class="${cls(pnl)}">${pnl!=null?'$'+pnl.toFixed(2):'-'}</td></tr>`;}).join('')
    :'<tr><td colspan="5" class="empty">Tidak ada posisi terbuka.</td></tr>';
  const tr=P.trades||[];
  document.getElementById('trades').innerHTML=tr.length?tr.map(t=>`<tr>
    <td>${(t.ts||'').slice(5,16)}</td><td>${t.symbol||'?'}</td><td class="${t.side==='buy'?'up':'down'}">${t.side}</td>
    <td>${Number(t.qty).toPrecision(4)}</td><td>${t.price}</td><td>${Number(t.usd).toFixed(2)}</td><td class="why">${t.reason||''}</td></tr>`).join('')
    :'<tr><td colspan="7" class="empty">Belum ada trade.</td></tr>';
  const st=(d.stats&&d.stats.by_reason)||{}; const tot=(d.stats||{}).total_rejected||0;
  document.getElementById('stats').innerHTML=tot?Object.entries(st).filter(([k,v])=>v>0).map(([k,v])=>
    `<div class="bar"><span>${k}</span><div class="track"><div class="fill" style="width:${(v/tot*100).toFixed(1)}%"></div></div><b>${v} (${(v/tot*100).toFixed(0)}%)</b></div>`).join('')
    +`<div class="bar" style="border-color:var(--acc)"><span><b>Total ditolak</b></span><b style="color:var(--acc)">${tot}</b></div>`
    :'<div class="empty">Belum ada coin ditolak.</div>';
  document.getElementById('report').textContent=d.report_md||'Belum ada laporan.';
  // kalender PnL harian
  const days=d.daily_pnl||{};
  const cal=document.getElementById('cal'); cal.innerHTML='';
  const now=new Date(), y=now.getFullYear(), m=now.getMonth();
  const offset=(new Date(y,m,1).getDay()+6)%7;
  const dim=new Date(y,m+1,0).getDate();
  for(let i=0;i<offset;i++)cal.insertAdjacentHTML('beforeend','<div></div>');
  for(let dd=1;dd<=dim;dd++){
    const key=`${y}-${String(m+1).padStart(2,'0')}-${String(dd).padStart(2,'0')}`;
    const rec=days[key]; let cls='day flat', txt='·';
    if(rec){const pnl=Number(rec.pnl);
      if(pnl>0.0001){cls='day win';txt=`+$${pnl.toFixed(2)}`;}
      else if(pnl<-0.0001){cls='day loss';txt=`-$${Math.abs(pnl).toFixed(2)}`;}
      else{txt='±$0';}}
    cal.insertAdjacentHTML('beforeend',`<div class="${cls}"><span class="num">${dd}</span><span class="pnl">${txt}</span></div>`);
  }
}).catch(e=>{document.getElementById('gen').textContent='gagal memuat data: '+e});
</script>
</body>
</html>
"""


def main() -> int:
    out = build()
    print(f"publish: {out}/ (index.html + data.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
