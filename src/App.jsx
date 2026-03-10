import { useState, useEffect, useCallback } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell, LineChart, Line, CartesianGrid,
} from "recharts";

// ═══════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════
const SERVER_URL = "http://localhost:7432";

// ═══════════════════════════════════════════════════════════════════
// THEME  (MenthorQ dark palette)
// ═══════════════════════════════════════════════════════════════════
const T = {
  bg:      "#0d1117",
  card:    "#161b22",
  card2:   "#1c2128",
  border:  "#30363d",
  text:    "#e6edf3",
  muted:   "#7d8590",
  green:   "#3fb950",
  gDark:   "#238636",
  red:     "#f85149",
  orange:  "#f78166",
  gold:    "#e3b341",
  blue:    "#79c0ff",
  purple:  "#bc8cff",
};

// ═══════════════════════════════════════════════════════════════════
// DEMO DATA  — mirrors MenthorQ 2026-03-06 Deribit screenshot
// ═══════════════════════════════════════════════════════════════════
const DEMO = {
  spot: 68129, ts: "2026-03-06 15:59 EST",
  total_net_gex: 3055.2, gex_regime: "POZİTİF",
  put_support: 60000, call_resistance: 75000, hvl: 67000,
  put_support_0dte: 68500, call_resistance_0dte: 71000,
  front_iv: 50.20, front_expiry: "0DTE",
  iv_rank: 58.43, term_shape: "CONTANGO",
  pc_ratio: 0.68, hv_30d: 67.97,
  option_score: 5, vol_score: 5, momentum_score: 3,
  gamma_regime: "LONG_GAMMA",
  regime: "BULLISH_HIGH_VOL", long_ok: true, short_ok: false,
  term_ivs: [
    { expiry: "0DTE", iv: 55.2 }, { expiry: "7MAR",  iv: 52.1 },
    { expiry: "14MAR",iv: 50.8 }, { expiry: "21MAR", iv: 50.2 },
    { expiry: "28MAR",iv: 49.8 }, { expiry: "25APR", iv: 49.1 },
    { expiry: "27JUN",iv: 48.5 }, { expiry: "26SEP", iv: 47.9 },
  ],
  call_walls: [75000, 71000, 80000, 85000],
  put_walls:  [60000, 68500, 65000, 58000],
  pos_gex_nodes: [
    { strike: 75000, net_gex: 28.3 }, { strike: 70000, net_gex: 18.5 },
    { strike: 80000, net_gex: 12.1 }, { strike: 72000, net_gex:  9.4 },
    { strike: 85000, net_gex:  6.8 },
  ],
  neg_gex_nodes: [
    { strike: 60000, net_gex: -25.8 }, { strike: 65000, net_gex: -18.4 },
    { strike: 62000, net_gex: -12.1 }, { strike: 66000, net_gex:  -8.9 },
    { strike: 58000, net_gex:  -6.2 },
  ],
  n_contracts: 8247, _source: "demo",
};

// ═══════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════
const fmt = (n) => n?.toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtK = (n) => `$${fmt(n)}`;
const pct  = (n) => `${(+n).toFixed(2)}%`;

const scoreColor = (s) => {
  if (s >= 4) return T.green;
  if (s >= 3) return T.gold;
  if (s >= 2) return "#e09b39";
  return T.red;
};
const scoreLabel = (s) =>
  ["Very Low","Low","Neutral","High","Very High","Very High"][Math.min(+s, 5)];

// Build per-strike GEX bars from server nodes + interpolation
function buildGEXStrikes(d) {
  const nodeMap = {};
  [...(d.pos_gex_nodes || []), ...(d.neg_gex_nodes || [])].forEach(
    (n) => { nodeMap[n.strike] = n.net_gex; }
  );
  const spot = d.spot;
  const lo = Math.ceil((spot * 0.68) / 1000) * 1000;
  const hi = Math.ceil((spot * 1.38) / 1000) * 1000;
  const rows = [];
  for (let s = hi; s >= lo; s -= 1000) {
    const known = nodeMap[s];
    let gex;
    if (known !== undefined) {
      gex = known;
    } else {
      const dist = (s - spot) / spot;
      if (s < spot) {
        gex = -6 * Math.exp(-Math.abs(dist) * 6);
      } else {
        gex = 5 * Math.exp(-Math.abs(dist) * 7);
      }
      gex = Math.round(gex * 10) / 10;
    }
    rows.push({ strike: s, label: `${(s / 1000).toFixed(0)}K`, gex });
  }
  return rows;
}

// Build IV×OI grouped bars
function buildIVOI(d) {
  const { spot, call_walls = [], put_walls = [] } = d;
  const lo = Math.ceil((spot * 0.72) / 1000) * 1000;
  const hi = Math.ceil((spot * 1.32) / 1000) * 1000;
  const rows = [];
  for (let s = hi; s >= lo; s -= 1000) {
    const dist = Math.abs(s - spot) / spot;
    const isCW = call_walls.includes(s);
    const isPW = put_walls.includes(s);
    const base = Math.max(5, 280 * Math.exp(-dist * 9));
    const calls = Math.round(base * (isCW ? 3.8 : s > spot ? 1.1 : 0.45));
    const puts  = Math.round(base * (isPW ? 3.8 : s < spot ? 1.1 : 0.45));
    rows.push({ label: `${(s / 1000).toFixed(0)}K`, strike: s, calls, puts });
  }
  return rows;
}

// ═══════════════════════════════════════════════════════════════════
// FETCH
// ═══════════════════════════════════════════════════════════════════
async function fetchLive() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 3000);
    const h = await fetch(`${SERVER_URL}/health`, { signal: ctrl.abort });
    if (!h.ok) return null;
    const health = await h.json();
    if (!health.ok) return null;
    const r = await fetch(`${SERVER_URL}/data`);
    if (!r.ok) return null;
    const j = await r.json();
    return j.spot > 10000 ? { ...j, _source: "server" } : null;
  } catch {
    return null;
  }
}

// ═══════════════════════════════════════════════════════════════════
// UI ATOMS
// ═══════════════════════════════════════════════════════════════════
const Card = ({ children, style = {}, borderColor }) => (
  <div style={{
    background: T.card, border: `1px solid ${T.border}`, borderRadius: 8,
    padding: "14px 16px", borderTop: borderColor ? `3px solid ${borderColor}` : undefined,
    ...style,
  }}>{children}</div>
);

const SectionTitle = ({ children }) => (
  <div style={{ color: T.muted, fontSize: 10.5, letterSpacing: "0.08em",
    textTransform: "uppercase", marginBottom: 10, fontWeight: 600 }}>
    {children}
  </div>
);

const KV = ({ label, value, color, highlight }) => (
  <div style={{
    padding: "9px 11px", borderRadius: 6,
    background: highlight ? `${color || T.blue}14` : T.card2,
    border: `1px solid ${highlight ? (color || T.blue) + "60" : T.border}`,
  }}>
    <div style={{ color: T.muted, fontSize: 10, textTransform: "uppercase",
      letterSpacing: "0.05em", marginBottom: 3 }}>{label}</div>
    <div style={{ color: color || T.text, fontSize: 17, fontWeight: 700,
      fontFamily: "'Fira Code', 'JetBrains Mono', monospace" }}>{value}</div>
  </div>
);

const Chip = ({ label, value, color }) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
    <div style={{ color: T.muted, fontSize: 10, letterSpacing: "0.06em",
      textTransform: "uppercase", marginBottom: 2 }}>{label}</div>
    <div style={{ color: color || T.text, fontSize: 13, fontWeight: 600,
      fontFamily: "'Fira Code', 'JetBrains Mono', monospace" }}>{value}</div>
  </div>
);

const QCard = ({ score, category, desc }) => {
  const c = scoreColor(score);
  const bg = score >= 4 ? "#0d2c12" : score >= 3 ? "#2c2000" : score <= 1 ? "#2c0a08" : "#1c1c00";
  return (
    <div style={{
      flex: 1, background: bg, border: `1px solid ${c}40`,
      borderTop: `3px solid ${c}`, borderRadius: 8, padding: "20px 18px", textAlign: "center",
    }}>
      <div style={{ fontSize: 64, fontWeight: 900, color: c, lineHeight: 1, marginBottom: 4,
        fontFamily: "system-ui, sans-serif" }}>{score}</div>
      <div style={{ fontSize: 15, color: c, fontWeight: 700, marginBottom: 6 }}>
        {scoreLabel(score)}
      </div>
      <div style={{ fontSize: 10.5, color: T.muted, letterSpacing: "0.1em",
        textTransform: "uppercase", marginBottom: 10, fontWeight: 600 }}>{category}</div>
      <div style={{ fontSize: 11.5, color: T.text, lineHeight: 1.55, opacity: 0.9 }}>{desc}</div>
    </div>
  );
};

// Custom GEX tooltip
const GEXTip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const v = payload[0]?.value;
  return (
    <div style={{ background: T.card, border: `1px solid ${T.border}`,
      padding: "6px 10px", borderRadius: 6, fontSize: 11 }}>
      <div style={{ color: T.muted }}>${label}</div>
      <div style={{ color: v >= 0 ? T.green : T.orange, fontWeight: 700 }}>
        GEX: {v >= 0 ? "+" : ""}{v}M
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// BINANCE OHLCV FETCH
// ═══════════════════════════════════════════════════════════════════
const BINANCE = "https://api.binance.com/api/v3/klines";

async function fetchOHLCV(interval = "4h", limit = 120) {
  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 6000);
    const r = await fetch(
      `${BINANCE}?symbol=BTCUSDT&interval=${interval}&limit=${limit}`,
      { signal: ctrl.signal }
    );
    clearTimeout(tid);
    if (!r.ok) return null;
    const raw = await r.json();
    return raw.map(k => ({
      t: k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5],
    }));
  } catch { return null; }
}

// ─── Indicators ────────────────────────────────────────────────────
function calcEMA(closes, period) {
  const k = 2 / (period + 1);
  let ema = closes[0];
  return closes.map(c => { ema = c * k + ema * (1 - k); return ema; });
}

function calcRSI(closes, period = 14) {
  let gains = 0, losses = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gains += d; else losses -= d;
  }
  let ag = gains / period, al = losses / period;
  const rsis = new Array(period).fill(null);
  rsis.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    ag = (ag * (period - 1) + Math.max(d, 0)) / period;
    al = (al * (period - 1) + Math.max(-d, 0)) / period;
    rsis.push(al === 0 ? 100 : 100 - 100 / (1 + ag / al));
  }
  return rsis;
}

function calcMACD(closes, fast = 12, slow = 26, sig = 9) {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);
  const macd = emaFast.map((v, i) => v - emaSlow[i]);
  const signal = calcEMA(macd, sig);
  const hist = macd.map((v, i) => v - signal[i]);
  return { macd, signal, hist };
}

function calcBB(closes, period = 20, mult = 2) {
  return closes.map((_, i) => {
    if (i < period - 1) return null;
    const slice = closes.slice(i - period + 1, i + 1);
    const mean = slice.reduce((a, b) => a + b, 0) / period;
    const std = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / period);
    return { upper: mean + mult * std, middle: mean, lower: mean - mult * std };
  });
}

function analyzeCandles(candles) {
  if (!candles || candles.length < 40) return null;
  const closes = candles.map(c => c.c);
  const n = closes.length - 1;

  const ema9  = calcEMA(closes, 9);
  const ema21 = calcEMA(closes, 21);
  const rsis  = calcRSI(closes, 14);
  const { macd, signal, hist } = calcMACD(closes);
  const bbs   = calcBB(closes, 20);

  const price  = closes[n];
  const rsi    = rsis[n];
  const bb     = bbs[n];
  const macdV  = macd[n];
  const sigV   = signal[n];
  const histV  = hist[n];
  const histPrev = hist[n - 1];

  // ── Sinyal puanlama (+/-) ──────────────────────────────
  let score = 0;
  const reasons = [];

  // EMA crossover
  const emaCross = ema9[n] > ema21[n];
  const emaCrossPrev = ema9[n-1] > ema21[n-1];
  const emaBullish = ema9[n] > ema21[n];
  if (emaBullish) { score++; reasons.push({ txt: `EMA9 > EMA21 (${ema9[n].toFixed(0)} > ${ema21[n].toFixed(0)})`, bull: true }); }
  else            { score--; reasons.push({ txt: `EMA9 < EMA21 (${ema9[n].toFixed(0)} < ${ema21[n].toFixed(0)})`, bull: false }); }
  if (emaCross && !emaCrossPrev) reasons.push({ txt: "⚡ EMA Taze Golden Cross!", bull: true, strong: true });
  if (!emaCross && emaCrossPrev) reasons.push({ txt: "⚡ EMA Taze Death Cross!", bull: false, strong: true });

  // RSI
  if (rsi > 70)      { score--; reasons.push({ txt: `RSI ${rsi.toFixed(1)} — Aşırı Alım`, bull: false }); }
  else if (rsi < 30) { score++; reasons.push({ txt: `RSI ${rsi.toFixed(1)} — Aşırı Satım (Rebound Riski)`, bull: true }); }
  else if (rsi > 55) { score++; reasons.push({ txt: `RSI ${rsi.toFixed(1)} — Bullish Bölge`, bull: true }); }
  else if (rsi < 45) { score--; reasons.push({ txt: `RSI ${rsi.toFixed(1)} — Bearish Bölge`, bull: false }); }
  else               { reasons.push({ txt: `RSI ${rsi.toFixed(1)} — Nötr`, bull: null }); }

  // MACD
  if (macdV > sigV) { score++; reasons.push({ txt: `MACD Histogram: +${histV.toFixed(1)} (Bullish)`, bull: true }); }
  else              { score--; reasons.push({ txt: `MACD Histogram: ${histV.toFixed(1)} (Bearish)`, bull: false }); }
  if (histV > histPrev && histV > 0) reasons.push({ txt: "MACD momentum artıyor ▲", bull: true });
  if (histV < histPrev && histV < 0) reasons.push({ txt: "MACD momentum azalıyor ▼", bull: false });

  // BB
  if (bb) {
    const bbPct = (price - bb.lower) / (bb.upper - bb.lower);
    const bbW = (bb.upper - bb.lower) / bb.middle * 100;
    if (bbPct > 0.85)      { score--; reasons.push({ txt: `BB: Üst banda yakın (${(bbPct*100).toFixed(0)}%)`, bull: false }); }
    else if (bbPct < 0.15) { score++; reasons.push({ txt: `BB: Alt banda yakın (${(bbPct*100).toFixed(0)}%)`, bull: true }); }
    else if (bbPct > 0.5)  { score++; reasons.push({ txt: `BB: Orta üstü (${(bbPct*100).toFixed(0)}%)`, bull: true }); }
    if (bbW < 3)           { reasons.push({ txt: `BB Sıkışma! Genişleme bekleniyor`, bull: null, strong: true }); }
  }

  // ── Karar ──────────────────────────────────────────────
  let signal_dir, signal_color, signal_label;
  if (score >= 3)       { signal_dir = "LONG";  signal_color = T.green;  signal_label = "▲ GÜÇLÜ LONG"; }
  else if (score >= 1)  { signal_dir = "LONG";  signal_color = "#58c76e"; signal_label = "▲ ZAYIF LONG"; }
  else if (score <= -3) { signal_dir = "SHORT"; signal_color = T.red;    signal_label = "▼ GÜÇLÜ SHORT"; }
  else if (score <= -1) { signal_dir = "SHORT"; signal_color = T.orange; signal_label = "▼ ZAYIF SHORT"; }
  else                  { signal_dir = "FLAT";  signal_color = T.muted;  signal_label = "— BEKLE"; }

  return {
    price, rsi, macdV, sigV, histV,
    ema9: ema9[n], ema21: ema21[n],
    bb, score, signal_dir, signal_color, signal_label, reasons,
    lastTs: candles[n].t,
  };
}

// ─── Konfluens skoru (teknik + opsiyon) ──────────────────────────
function confluenceScore(tech4h, tech1h, optData) {
  if (!tech4h) return null;
  let score = 0;
  const items = [];

  // 4H teknik
  score += tech4h.score;
  items.push({ src: "4H Teknik", val: tech4h.score, dir: tech4h.signal_dir });

  // 1H teknik (yarı ağırlık)
  if (tech1h) {
    score += Math.round(tech1h.score * 0.5);
    items.push({ src: "1H Teknik", val: tech1h.score, dir: tech1h.signal_dir });
  }

  // GEX rejimi
  if (optData.total_net_gex > 0) { score++; items.push({ src: "GEX POZİTİF", val: 1, dir: "LONG" }); }
  else                           { score--; items.push({ src: "GEX NEGATİF", val: -1, dir: "SHORT" }); }

  // Spot vs HVL
  if (optData.spot > optData.hvl) { score++; items.push({ src: "Spot > HVL", val: 1, dir: "LONG" }); }
  else                             { score--; items.push({ src: "Spot < HVL", val: -1, dir: "SHORT" }); }

  // Call resistance mesafesi
  const distCR = (optData.call_resistance - optData.spot) / optData.spot * 100;
  if (distCR < 3)  { score--; items.push({ src: `Call Direnç Yakın (${distCR.toFixed(1)}%)`, val: -1, dir: "SHORT" }); }
  if (distCR > 8)  { score++; items.push({ src: `Call Direnç Uzak (${distCR.toFixed(1)}%)`,  val: 1,  dir: "LONG"  }); }

  const maxS = 10;
  const pct = Math.max(0, Math.min(100, ((score + maxS) / (2 * maxS)) * 100));

  let label, color;
  if (score >= 5)      { label = "▲ GÜÇLÜ LONG";  color = T.green; }
  else if (score >= 2) { label = "▲ ZAYIF LONG";   color = "#58c76e"; }
  else if (score <= -5){ label = "▼ GÜÇLÜ SHORT";  color = T.red; }
  else if (score <= -2){ label = "▼ ZAYIF SHORT";  color = T.orange; }
  else                 { label = "— NÖTR / BEKLE"; color = T.muted; }

  return { score, pct, label, color, items };
}

// ═══════════════════════════════════════════════════════════════════
// TEKNİK SİNYAL PANEL COMPONENT
// ═══════════════════════════════════════════════════════════════════
function TeknikSignal({ optData }) {
  const [tech4h, setTech4h]     = useState(null);
  const [tech1h, setTech1h]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [tab, setTab]           = useState("4h");

  const loadData = useCallback(async () => {
    setLoading(true); setError(null);
    const [c4h, c1h] = await Promise.all([fetchOHLCV("4h", 120), fetchOHLCV("1h", 100)]);
    if (!c4h && !c1h) { setError("Binance API erişilemiyor"); setLoading(false); return; }
    if (c4h) setTech4h(analyzeCandles(c4h));
    if (c1h) setTech1h(analyzeCandles(c1h));
    setLastUpdate(new Date().toLocaleTimeString("tr-TR"));
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [loadData]);

  const conf = confluenceScore(tech4h, tech1h, optData);
  const current = tab === "4h" ? tech4h : tech1h;

  const ReasonRow = ({ r }) => (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "4px 8px", borderRadius: 4,
      background: r.bull === true ? "#0d2c1228" : r.bull === false ? "#2c0a0828" : `${T.border}20`,
      border: `1px solid ${r.bull === true ? T.green + "25" : r.bull === false ? T.red + "25" : T.border + "40"}`,
    }}>
      <span style={{ fontSize: 10, flexShrink: 0,
        color: r.bull === true ? T.green : r.bull === false ? T.red : T.muted }}>
        {r.bull === true ? "▲" : r.bull === false ? "▼" : "●"}
      </span>
      <span style={{ fontSize: 10.5, color: r.strong ? T.text : T.muted, fontWeight: r.strong ? 700 : 400 }}>
        {r.txt}
      </span>
    </div>
  );

  const GaugeBar = ({ value, color, max = 10 }) => {
    const pct = Math.min(100, Math.max(0, ((value + max) / (max * 2)) * 100));
    return (
      <div style={{ height: 6, background: T.card2, borderRadius: 99, overflow: "hidden", marginTop: 4 }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 99,
          transition: "width 0.5s ease" }} />
      </div>
    );
  };

  return (
    <Card borderColor={conf ? conf.color : T.purple}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <SectionTitle>⚡ Teknik Sinyal — BTC/USDT · Binance Canlı</SectionTitle>
          {loading && <div style={{ color: T.muted, fontSize: 11 }}>⟳ Binance API verisi yükleniyor…</div>}
          {error   && <div style={{ color: T.red, fontSize: 11 }}>✗ {error}</div>}
          {lastUpdate && !loading && <div style={{ color: T.muted, fontSize: 10 }}>Son güncelleme: {lastUpdate} · 5dk yenileme</div>}
        </div>
        <button onClick={loadData} disabled={loading} style={{
          background: "transparent", border: `1px solid ${T.border}`, color: T.muted,
          padding: "3px 10px", borderRadius: 4, cursor: "pointer", fontSize: 10,
        }}>⟳ Yenile</button>
      </div>

      {!loading && conf && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>

          {/* ── Konfluens Özeti ── */}
          <div style={{
            background: `${conf.color}0e`, border: `1px solid ${conf.color}40`,
            borderTop: `3px solid ${conf.color}`, borderRadius: 8, padding: "14px 16px",
          }}>
            <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase",
              letterSpacing: "0.08em", marginBottom: 6 }}>Konfluens Skoru (Teknik + Opsiyon)</div>
            <div style={{ fontSize: 32, fontWeight: 900, color: conf.color, lineHeight: 1, marginBottom: 4,
              fontFamily: "system-ui, sans-serif" }}>
              {conf.score > 0 ? "+" : ""}{conf.score}
            </div>
            <div style={{ fontSize: 16, fontWeight: 800, color: conf.color, marginBottom: 10 }}>
              {conf.label}
            </div>
            <GaugeBar value={conf.score} color={conf.color} max={10} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 12 }}>
              {conf.items.map((it, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between",
                  fontSize: 10, padding: "2px 0", borderBottom: `1px solid ${T.border}` }}>
                  <span style={{ color: T.muted }}>{it.src}</span>
                  <span style={{
                    color: it.val > 0 ? T.green : it.val < 0 ? T.red : T.muted,
                    fontWeight: 700
                  }}>{it.val > 0 ? "+" : ""}{it.val}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Zaman Dilimi Kartları ── */}
          <div style={{ gridColumn: "2 / 4", display: "flex", flexDirection: "column", gap: 10 }}>

            {/* Tab seçici */}
            <div style={{ display: "flex", gap: 6 }}>
              {["4h", "1h"].map(tf => (
                <button key={tf} onClick={() => setTab(tf)} style={{
                  background: tab === tf ? `${T.purple}30` : "transparent",
                  border: `1px solid ${tab === tf ? T.purple : T.border}`,
                  color: tab === tf ? T.purple : T.muted,
                  padding: "3px 16px", borderRadius: 4, cursor: "pointer",
                  fontFamily: "monospace", fontSize: 11, fontWeight: tab === tf ? 700 : 400,
                }}>
                  {tf.toUpperCase()} {tf === "4h" ? tech4h?.signal_label : tech1h?.signal_label}
                </button>
              ))}
            </div>

            {current && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>

                {/* İndikatör özeti */}
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {[
                    { label: "EMA 9",  val: current.ema9?.toFixed(0),  color: current.ema9 > current.ema21 ? T.green : T.red },
                    { label: "EMA 21", val: current.ema21?.toFixed(0), color: T.muted },
                    { label: "RSI 14", val: current.rsi?.toFixed(1),
                      color: current.rsi > 70 ? T.red : current.rsi < 30 ? T.green : current.rsi > 50 ? "#58c76e" : T.orange },
                    { label: "MACD",   val: current.macdV?.toFixed(1),
                      color: current.macdV > current.sigV ? T.green : T.red },
                    { label: "Signal", val: current.sigV?.toFixed(1),  color: T.muted },
                    { label: "Hist",   val: current.histV > 0 ? `+${current.histV.toFixed(1)}` : current.histV?.toFixed(1),
                      color: current.histV > 0 ? T.green : T.red },
                    ...(current.bb ? [
                      { label: "BB Üst",  val: current.bb.upper?.toFixed(0), color: T.muted },
                      { label: "BB Orta", val: current.bb.middle?.toFixed(0),color: T.muted },
                      { label: "BB Alt",  val: current.bb.lower?.toFixed(0), color: T.muted },
                    ] : []),
                  ].map((row, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between",
                      padding: "4px 8px", background: T.card2,
                      border: `1px solid ${T.border}`, borderRadius: 4 }}>
                      <span style={{ color: T.muted, fontSize: 10, textTransform: "uppercase",
                        letterSpacing: "0.05em" }}>{row.label}</span>
                      <span style={{ color: row.color, fontWeight: 700, fontFamily: "monospace",
                        fontSize: 11 }}>{row.val}</span>
                    </div>
                  ))}
                </div>

                {/* Sebepler */}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase",
                    letterSpacing: "0.07em", marginBottom: 2 }}>Sinyal Gerekçeleri</div>
                  {current.reasons.map((r, i) => <ReasonRow key={i} r={r} />)}
                  <div style={{ marginTop: 8, padding: "8px 10px",
                    background: `${current.signal_color}12`,
                    border: `1px solid ${current.signal_color}40`, borderRadius: 6 }}>
                    <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase",
                      letterSpacing: "0.07em", marginBottom: 3 }}>
                      {tab.toUpperCase()} Sinyal Skoru
                    </div>
                    <div style={{ color: current.signal_color, fontWeight: 900, fontSize: 20 }}>
                      {current.signal_label}
                    </div>
                    <GaugeBar value={current.score} color={current.signal_color} max={4} />
                  </div>
                </div>

              </div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════════════
// REGIME TABLE
// ═══════════════════════════════════════════════════════════════════
const REGIME_INFO = {
  IDEAL_LONG:       { txt: "İDEAL LONG",       color: T.green,  sub: "GEX pozitif · opsiyonlar güçlü destek · long momentum" },
  BULLISH_HIGH_VOL: { txt: "BULLISH HIGH VOL",  color: T.gold,   sub: "Long açılabilir, stop sıkı tutulmalı · vol yüksek" },
  BEARISH_VOLATILE: { txt: "BEARISH VOLATİL",   color: T.red,    sub: "Short setup · yüksek volatilite · dikkat" },
  BEARISH_LOW_VOL:  { txt: "BEARISH SIKIŞ",     color: T.red,    sub: "Short setup · düşük vol · yavaş hareket" },
  HIGH_RISK:        { txt: "⚠ YÜKSEK RİSK",    color: T.red,    sub: "Short gamma + vol · kill-switch bölgesi" },
  NEUTRAL:          { txt: "NÖTR / BEKLE",      color: T.muted,  sub: "Net yön yok · bekleme modu" },
};

// ═══════════════════════════════════════════════════════════════════
// APP
// ═══════════════════════════════════════════════════════════════════
export default function App() {
  const [data, setData]   = useState(DEMO);
  const [live, setLive]   = useState(false);
  const [busy, setBusy]   = useState(false);
  const [clock, setClock] = useState("");

  const refresh = useCallback(async () => {
    setBusy(true);
    const d = await fetchLive();
    if (d) { setData(d); setLive(true); }
    else   { setData(DEMO); setLive(false); }
    setClock(new Date().toLocaleTimeString("tr-TR"));
    setBusy(false);
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4 * 60 * 1000);
    return () => clearInterval(id);
  }, [refresh]);

  const d = data;
  const gammaPos  = d.total_net_gex > 0;
  const gexRows   = buildGEXStrikes(d);
  const ivoiRows  = buildIVOI(d);
  const gexMax    = Math.max(32, ...gexRows.map((r) => Math.abs(r.gex)));
  const regime    = REGIME_INFO[d.regime] || REGIME_INFO.NEUTRAL;

  // Reference line labels (nearest 1K)
  const spotK = `${Math.round(d.spot  / 1000)}K`;
  const hvlK  = `${Math.round(d.hvl   / 1000)}K`;
  const crK   = `${Math.round(d.call_resistance / 1000)}K`;
  const psK   = `${Math.round(d.put_support     / 1000)}K`;

  const expMove = ((d.front_iv || 50) / 19.1).toFixed(2);
  const distHVL = (Math.abs(d.spot - d.hvl) / d.spot * 100).toFixed(2);

  // Tooltip styles for recharts
  const tipStyle = { background: T.card, border: `1px solid ${T.border}`,
    fontSize: 11, color: T.text };
  const tickStyle = { fill: T.muted, fontSize: 9.5 };

  return (
    <div style={{ background: T.bg, minHeight: "100vh", color: T.text,
      fontFamily: "'Fira Code','JetBrains Mono',monospace", fontSize: 13 }}>

      {/* ── TOP BAR ──────────────────────────────────────────── */}
      <div style={{ background: "#010409", borderBottom: `1px solid ${T.border}`,
        padding: "9px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <span style={{ color: T.gold, fontWeight: 900, fontSize: 14, letterSpacing: "0.06em" }}>
            ◆ G-DIVE&nbsp;OIM
          </span>
          <span style={{ color: T.muted, fontSize: 11 }}>
            BTC / USD · Deribit · Options Intelligence Module
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontSize: 11, color: live ? T.green : T.gold }}>
            {busy ? "⟳ Yükleniyor…" : live ? `● CANLI · ${clock}` : `◆ DEMO · ${clock}`}
          </span>
          <button onClick={refresh} disabled={busy} style={{
            background: "transparent", border: `1px solid ${T.border}`, color: T.muted,
            padding: "3px 12px", borderRadius: 4, cursor: "pointer", fontSize: 11,
            transition: "color 0.15s",
          }}>YENİLE</button>
        </div>
      </div>

      {/* ── PRICE + STATS BAR ────────────────────────────────── */}
      <div style={{ background: "#0a0d14", borderBottom: `1px solid ${T.border}`,
        padding: "10px 20px", display: "flex", alignItems: "center", gap: 36 }}>
        <div>
          <div style={{ color: T.muted, fontSize: 10, letterSpacing: "0.06em" }}>LAST PRICE</div>
          <div style={{ color: T.text, fontSize: 24, fontWeight: 900, lineHeight: 1 }}>
            {fmtK(d.spot)}
          </div>
        </div>
        <div style={{ width: 1, height: 32, background: T.border }} />
        <Chip label="P/C OI"         value={d.pc_ratio?.toFixed(2)} />
        <Chip label="Gamma Cond."    value={gammaPos ? "Positive" : "Negative"}
              color={gammaPos ? T.green : T.red} />
        <Chip label="Impl. Vol 30D"  value={pct(d.front_iv)} />
        <Chip label="Hist. Vol 30D"  value={pct(d.hv_30d ?? 67.97)} color={T.muted} />
        <Chip label="IV Rank"        value={pct(d.iv_rank)}
              color={d.iv_rank > 60 ? T.red : d.iv_rank > 35 ? T.gold : T.green} />
        <Chip label="1D Exp. Move"   value={`±${expMove}%`} color={T.purple} />
        <div style={{ width: 1, height: 32, background: T.border }} />
        <Chip label="Net GEX"        value={`$${d.total_net_gex >= 0 ? "+" : ""}${d.total_net_gex?.toFixed(0)}M`}
              color={gammaPos ? T.green : T.orange} />
        <Chip label="Kontratlar"     value={(d.n_contracts || 0).toLocaleString()} color={T.muted} />
      </div>

      {/* ── BODY ─────────────────────────────────────────────── */}
      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>

        {/* QSCORE ROW */}
        <div>
          <SectionTitle>QSCORE — Composite Options Intelligence Signal</SectionTitle>
          <div style={{ display: "flex", gap: 12 }}>
            <QCard score={d.option_score ?? 0} category="Option"
              desc={`Option score is ${scoreLabel(d.option_score)} and we are in a ${(d.option_score ?? 0) >= 3 ? "Bullish" : "Bearish"} Option Positioning environment.`} />
            <QCard score={d.vol_score ?? 0} category="Volatility"
              desc={`Volatility score is ${scoreLabel(d.vol_score)} and we are in a ${(d.vol_score ?? 0) >= 4 ? "Volatile" : (d.vol_score ?? 0) >= 2 ? "Moderate" : "Low Volatility"} environment.`} />
            <QCard score={d.momentum_score ?? 3} category="Momentum"
              desc={`Momentum score is ${scoreLabel(d.momentum_score ?? 3)} and we are in a ${(d.momentum_score ?? 3) >= 4 ? "Bullish" : (d.momentum_score ?? 3) >= 3 ? "Neutral" : "Bearish"} Momentum environment.`} />
          </div>
        </div>

        {/* TEKNİK SİNYAL PANELİ */}
        <TeknikSignal optData={d} />

        {/* KEY LEVELS + NET GEX CHART */}
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 14 }}>

          {/* KEY LEVELS */}
          <Card>
            <SectionTitle>Key Levels</SectionTitle>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 7 }}>
              <KV label="Spot Price"         value={fmtK(d.spot)} color={T.blue} highlight />
              <KV label="High Vol Level"     value={fmtK(d.hvl)}  color={T.gold} highlight />
              <KV label="Call Resistance"    value={fmtK(d.call_resistance)}    color={T.green} />
              <KV label="Put Support"        value={fmtK(d.put_support)}        color={T.orange} />
              <KV label="Call Resist. 0DTE"  value={fmtK(d.call_resistance_0dte)} color="#58c76e" />
              <KV label="Put Support 0DTE"   value={fmtK(d.put_support_0dte)}    color="#f9a86a" />
              <KV label="IV Rank 30D"        value={pct(d.iv_rank)} />
              <KV label="Term Shape"         value={d.term_shape}
                color={d.term_shape === "CONTANGO" ? T.green : d.term_shape === "BACKWARDATION" ? T.red : T.muted} />
              <KV label="Dist. to HVL"       value={`${distHVL}%`} />
              <KV label="P/C OI Ratio"       value={d.pc_ratio?.toFixed(3)}
                color={d.pc_ratio > 1.2 ? T.red : d.pc_ratio < 0.8 ? T.green : T.text} />
            </div>
          </Card>

          {/* NET GEX HORIZONTAL BAR CHART */}
          <Card>
            <SectionTitle>
              Net GEX — All Expirations (Deribit)
              <span style={{ marginLeft: 14, color: gammaPos ? T.green : T.orange }}>
                TOTAL: {gammaPos ? "+" : ""}{d.total_net_gex?.toFixed(1)}M&nbsp;USD
              </span>
            </SectionTitle>

            {/* Legend */}
            <div style={{ display: "flex", gap: 20, marginBottom: 8, fontSize: 10.5 }}>
              <span><span style={{ color: T.green }}>──</span>&nbsp;Call Resistance {fmtK(d.call_resistance)}</span>
              <span><span style={{ color: T.gold  }}>──</span>&nbsp;HVL {fmtK(d.hvl)}</span>
              <span><span style={{ color: T.orange }}>──</span>&nbsp;Put Support {fmtK(d.put_support)}</span>
              <span><span style={{ color: "rgba(230,237,243,0.6)" }}>- -</span>&nbsp;Spot {fmtK(d.spot)}</span>
            </div>

            <ResponsiveContainer width="100%" height={340}>
              <BarChart layout="vertical" data={gexRows} barSize={6}
                margin={{ top: 4, right: 36, bottom: 4, left: 8 }}>
                <CartesianGrid strokeDasharray="2 3" stroke={T.border} horizontal={false} />
                <XAxis type="number" domain={[-gexMax * 1.05, gexMax * 1.05]}
                  tickFormatter={(v) => `${v}M`} tick={tickStyle}
                  axisLine={{ stroke: T.border }} tickLine={false} />
                <YAxis type="category" dataKey="label" width={34}
                  tick={tickStyle} axisLine={false} tickLine={false} />
                <Tooltip content={<GEXTip />} />
                <ReferenceLine x={0} stroke={T.border} strokeWidth={1} />
                <ReferenceLine y={spotK} stroke="rgba(230,237,243,0.65)" strokeDasharray="5 3" strokeWidth={1.5} />
                <ReferenceLine y={hvlK}  stroke={T.gold}   strokeDasharray="5 3" strokeWidth={1.5} />
                <ReferenceLine y={crK}   stroke={T.green}  strokeDasharray="5 3" strokeWidth={1.5} />
                <ReferenceLine y={psK}   stroke={T.orange} strokeDasharray="5 3" strokeWidth={1.5} />
                <Bar dataKey="gex" isAnimationActive={false} radius={[0, 2, 2, 0]}>
                  {gexRows.map((row, i) => (
                    <Cell key={i} fill={row.gex >= 0 ? T.green : T.orange} fillOpacity={0.88} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* IV×OI · TERM STRUCTURE · G-DIVE SIGNAL */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>

          {/* IV × OI */}
          <Card>
            <SectionTitle>Implied Vol × Open Interest</SectionTitle>
            <div style={{ display: "flex", gap: 14, marginBottom: 8, fontSize: 10.5 }}>
              <span><span style={{ color: T.green  }}>█</span> IV×OI Calls</span>
              <span><span style={{ color: T.orange }}>█</span> IV×OI Puts</span>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart layout="vertical" data={ivoiRows} barSize={4} barGap={1}
                margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                <CartesianGrid strokeDasharray="2 3" stroke={T.border} horizontal={false} />
                <XAxis type="number" tick={tickStyle} axisLine={{ stroke: T.border }} tickLine={false} />
                <YAxis type="category" dataKey="label" width={34}
                  tick={tickStyle} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={tipStyle} labelStyle={{ color: T.muted }}
                  formatter={(v, name) => [v, name === "calls" ? "Call OI" : "Put OI"]}
                />
                <ReferenceLine y={spotK} stroke="rgba(230,237,243,0.5)" strokeDasharray="4 2" />
                <Bar dataKey="calls" fill={T.green}  fillOpacity={0.82} isAnimationActive={false} />
                <Bar dataKey="puts"  fill={T.orange} fillOpacity={0.82} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </Card>

          {/* ATM TERM STRUCTURE */}
          <Card>
            <SectionTitle>ATM Term Structure</SectionTitle>
            <div style={{ marginBottom: 6, fontSize: 10.5 }}>
              <span style={{ color: d.term_shape === "CONTANGO" ? T.green : d.term_shape === "BACKWARDATION" ? T.red : T.muted }}>
                {d.term_shape}
              </span>
              <span style={{ color: T.muted, marginLeft: 10 }}>Front IV: {d.front_iv?.toFixed(2)}%</span>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={d.term_ivs || []}
                margin={{ top: 8, right: 16, bottom: 8, left: -4 }}>
                <CartesianGrid strokeDasharray="2 3" stroke={T.border} />
                <XAxis dataKey="expiry" tick={{ ...tickStyle, fontSize: 8.5 }}
                  axisLine={{ stroke: T.border }} tickLine={false} />
                <YAxis domain={["auto", "auto"]} tickFormatter={(v) => `${v}%`}
                  tick={tickStyle} axisLine={{ stroke: T.border }} tickLine={false} />
                <Tooltip
                  contentStyle={tipStyle} labelStyle={{ color: T.muted }}
                  formatter={(v) => [`${v}%`, "ATM IV"]}
                />
                <Line type="monotone" dataKey="iv" stroke={T.blue} strokeWidth={2.5}
                  dot={{ fill: T.blue, r: 3.5, strokeWidth: 0 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          {/* G-DIVE SIGNAL PANEL */}
          <Card borderColor={regime.color}>
            <SectionTitle>G-DIVE V4 — Entry Signal</SectionTitle>

            {/* Main signal */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 26, fontWeight: 900, color: regime.color, marginBottom: 2 }}>
                {d.long_ok ? "▲  LONG OK" : d.short_ok ? "▼  SHORT OK" : "—  BEKLE"}
              </div>
              <div style={{ fontSize: 12.5, color: regime.color, fontWeight: 700, marginBottom: 3 }}>
                {regime.txt}
              </div>
              <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.5 }}>{regime.sub}</div>
            </div>

            {/* Stop / Target */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
              <div style={{ padding: "8px 10px", background: "#2c0a08", border: `1px solid ${T.red}40`,
                borderRadius: 6 }}>
                <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase",
                  letterSpacing: "0.06em", marginBottom: 3 }}>Stop Loss</div>
                <div style={{ color: T.red, fontWeight: 800, fontSize: 15, fontFamily: "monospace" }}>
                  {fmtK(d.put_support)}
                </div>
                <div style={{ color: T.muted, fontSize: 9.5 }}>Put Support</div>
              </div>
              <div style={{ padding: "8px 10px", background: "#0d2c12", border: `1px solid ${T.green}40`,
                borderRadius: 6 }}>
                <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase",
                  letterSpacing: "0.06em", marginBottom: 3 }}>TP Hedefi</div>
                <div style={{ color: T.green, fontWeight: 800, fontSize: 15, fontFamily: "monospace" }}>
                  {fmtK(d.call_resistance)}
                </div>
                <div style={{ color: T.muted, fontSize: 9.5 }}>Call Resistance</div>
              </div>
            </div>

            {/* Gamma Regime */}
            <div style={{ padding: "8px 12px",
              background: d.gamma_regime === "LONG_GAMMA" ? "#0d2c1266" : "#2c0a0866",
              border: `1px solid ${d.gamma_regime === "LONG_GAMMA" ? T.green : T.red}40`,
              borderRadius: 6, marginBottom: 12 }}>
              <span style={{ color: d.gamma_regime === "LONG_GAMMA" ? T.green : T.red,
                fontWeight: 700, fontSize: 12 }}>
                {d.gamma_regime === "LONG_GAMMA" ? "● LONG GAMMA" : "● SHORT GAMMA"}
              </span>
              <div style={{ color: T.muted, fontSize: 10.5, marginTop: 3 }}>
                {d.gamma_regime === "LONG_GAMMA"
                  ? `Spot > HVL ($${d.hvl?.toLocaleString()}) · Dealer söndürür`
                  : `Spot < HVL ($${d.hvl?.toLocaleString()}) · Dealer momentum büyütür`}
              </div>
            </div>

            {/* Top GEX Nodes */}
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 6, textTransform: "uppercase",
              letterSpacing: "0.06em" }}>Kritik GEX Düğümleri</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {[...(d.pos_gex_nodes || []).slice(0, 2).map(n => ({...n, color: T.green})),
                ...(d.neg_gex_nodes || []).slice(0, 2).map(n => ({...n, color: T.orange}))
              ].sort((a, b) => a.strike - b.strike).map((n, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between",
                  fontSize: 10.5, padding: "2px 0" }}>
                  <span style={{ color: T.muted, fontFamily: "monospace" }}>
                    ${n.strike.toLocaleString()}
                  </span>
                  <span style={{ color: n.color, fontWeight: 700 }}>
                    {n.net_gex >= 0 ? "+" : ""}{n.net_gex?.toFixed(1)}M
                  </span>
                </div>
              ))}
            </div>

            {/* Footer stats */}
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${T.border}`,
              display: "flex", justifyContent: "space-between", fontSize: 9.5, color: T.muted }}>
              <span>OPT {d.option_score}/5</span>
              <span>VOL {d.vol_score}/5</span>
              <span>MOM {d.momentum_score ?? 3}/5</span>
              <span>{(d.n_contracts || 0).toLocaleString()} ktrt</span>
            </div>
          </Card>
        </div>

        {/* BOTTOM INFO BAR */}
        <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10,
          display: "flex", justifyContent: "space-between", fontSize: 10, color: T.muted }}>
          <span>G-DIVE V4 Options Intelligence Module · Deribit Public API · 4H cache</span>
          <span>
            {live
              ? `● Canlı veri · Son güncelleme: ${clock}`
              : `◆ Demo modu · Gerçek veri için terminalde: python gdive_server.py`}
          </span>
        </div>

      </div>
    </div>
  );
}
