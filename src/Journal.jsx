import { useState, useEffect, useCallback } from "react";

const T = { bg:"#0d1117",card:"#161b22",card2:"#1c2128",border:"#30363d",text:"#e6edf3",muted:"#7d8590",green:"#3fb950",red:"#f85149",orange:"#f78166",gold:"#e3b341",blue:"#79c0ff",purple:"#bc8cff" };

const INITIAL_CAPITAL = 10000;
const RISK_PCT = 0.02;
const RR = 3;
const STORAGE_KEY = "gdive:journal:v2";

const fmt = (n) => n?.toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtK = (n) => `$${fmt(n)}`;
const fmtPct = (n) => `${n >= 0 ? "+" : ""}${(+n).toFixed(2)}%`;
const fmtPnl = (n) => `${n >= 0 ? "+" : ""}$${Math.abs(n).toFixed(0)}`;

function loadTrades() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
  catch { return []; }
}
function saveTrades(trades) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(trades));
}

async function fetchPrice() {
  try {
    const r = await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");
    if (!r.ok) return null;
    return +(await r.json()).price;
  } catch { return null; }
}

// PnL curve SVG
function PnLChart({ trades }) {
  const W = 500, H = 160, PL = 50, PR = 16, PT = 12, PB = 24;
  const cw = W - PL - PR, ch = H - PT - PB;
  if (!trades.length) return (
    <div style={{ height: H, display: "flex", alignItems: "center", justifyContent: "center", color: T.muted, fontSize: 11 }}>
      Henüz trade yok
    </div>
  );
  let cum = 0;
  const points = [{ x: 0, y: INITIAL_CAPITAL }];
  trades.filter(t => t.status === "CLOSED").forEach((t, i) => {
    cum += t.pnl || 0;
    points.push({ x: i + 1, y: INITIAL_CAPITAL + cum });
  });
  if (points.length < 2) return null;
  const minY = Math.min(...points.map(p => p.y)) * 0.998;
  const maxY = Math.max(...points.map(p => p.y)) * 1.002;
  const xS = (i) => PL + i * (cw / (points.length - 1));
  const yS = (v) => PT + ch - (v - minY) / (maxY - minY) * ch;
  const pts = points.map((p, i) => `${xS(i)},${yS(p.y)}`).join(" ");
  const last = points[points.length - 1];
  const color = last.y >= INITIAL_CAPITAL ? T.green : T.red;
  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      <line x1={PL} y1={yS(INITIAL_CAPITAL)} x2={W - PR} y2={yS(INITIAL_CAPITAL)} stroke={T.border} strokeWidth={1} strokeDasharray="4,3" />
      <text x={PL - 4} y={yS(INITIAL_CAPITAL) + 3} fill={T.muted} fontSize={8} textAnchor="end">${(INITIAL_CAPITAL / 1000).toFixed(0)}K</text>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={i} cx={xS(i)} cy={yS(p.y)} r={3} fill={color} />
      ))}
      <text x={W - PR} y={yS(last.y) - 6} fill={color} fontSize={9} textAnchor="end" fontWeight={700}>
        ${last.y.toFixed(0)}
      </text>
    </svg>
  );
}

const Card = ({ children, style = {}, bc }) => (
  <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: "14px 16px", borderTop: bc ? `3px solid ${bc}` : undefined, ...style }}>
    {children}
  </div>
);
const ST = ({ children }) => (
  <div style={{ color: T.muted, fontSize: 10.5, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, fontWeight: 600 }}>{children}</div>
);

export default function Journal() {
  const [trades, setTrades] = useState([]);
  const [price, setPrice] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ dir: "LONG", entry: "", stop: "", tp: "", size: "", notes: "", regime: "", signal: "" });
  const [filter, setFilter] = useState("ALL");

  useEffect(() => {
    setTrades(loadTrades());
    fetchPrice().then(p => p && setPrice(p));
    const id = setInterval(() => fetchPrice().then(p => p && setPrice(p)), 30000);
    return () => clearInterval(id);
  }, []);

  const closedTrades = trades.filter(t => t.status === "CLOSED");
  const openTrades = trades.filter(t => t.status === "OPEN");
  const totalPnl = closedTrades.reduce((a, t) => a + (t.pnl || 0), 0);
  const wins = closedTrades.filter(t => (t.pnl || 0) > 0).length;
  const winRate = closedTrades.length ? (wins / closedTrades.length * 100).toFixed(0) : 0;
  const equity = INITIAL_CAPITAL + totalPnl;
  const avgRR = closedTrades.length ? (closedTrades.reduce((a, t) => a + (t.rr || 0), 0) / closedTrades.length).toFixed(2) : 0;

  const addTrade = () => {
    if (!form.entry || !form.stop) return;
    const entry = +form.entry, stop = +form.stop;
    const tp = form.tp ? +form.tp : (form.dir === "LONG" ? entry + (entry - stop) * RR : entry - (stop - entry) * RR);
    const size = form.size ? +form.size : (INITIAL_CAPITAL * RISK_PCT) / Math.abs(entry - stop);
    const t = {
      id: Date.now(), date: new Date().toISOString().slice(0, 16).replace("T", " "),
      dir: form.dir, entry, stop, tp, size: +size.toFixed(4),
      notes: form.notes, regime: form.regime, signal: form.signal,
      status: "OPEN", pnl: null, rr: null, exitPrice: null, exitDate: null,
    };
    const next = [t, ...trades];
    setTrades(next); saveTrades(next);
    setShowForm(false);
    setForm({ dir: "LONG", entry: "", stop: "", tp: "", size: "", notes: "", regime: "", signal: "" });
  };

  const closeTrade = (id, exitPrice) => {
    const next = trades.map(t => {
      if (t.id !== id) return t;
      const ep = +exitPrice;
      const raw = t.dir === "LONG" ? (ep - t.entry) * t.size : (t.entry - ep) * t.size;
      const rr = t.dir === "LONG" ? (ep - t.entry) / (t.entry - t.stop) : (t.entry - ep) / (t.stop - t.entry);
      return { ...t, status: "CLOSED", exitPrice: ep, exitDate: new Date().toISOString().slice(0, 16).replace("T", " "), pnl: +raw.toFixed(2), rr: +rr.toFixed(2) };
    });
    setTrades(next); saveTrades(next);
  };

  const deleteTrade = (id) => {
    const next = trades.filter(t => t.id !== id);
    setTrades(next); saveTrades(next);
  };

  const fillFromPrice = () => {
    if (price) setForm(f => ({ ...f, entry: price.toFixed(0) }));
  };

  const filtered = trades.filter(t => filter === "ALL" ? true : t.status === filter);

  const Input = ({ label, field, placeholder, type = "text" }) => (
    <div>
      <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
      <input
        type={type} value={form[field]} placeholder={placeholder}
        onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
        style={{ width: "100%", background: T.card2, border: `1px solid ${T.border}`, borderRadius: 4, padding: "6px 8px", color: T.text, fontFamily: "monospace", fontSize: 12, boxSizing: "border-box" }}
      />
    </div>
  );

  return (
    <div style={{ background: T.bg, minHeight: "100vh", color: T.text, fontFamily: "'Fira Code','JetBrains Mono',monospace", fontSize: 13 }}>
      {/* TOP BAR */}
      <div style={{ background: "#010409", borderBottom: `1px solid ${T.border}`, padding: "9px 20px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <span style={{ color: T.gold, fontWeight: 900, fontSize: 14 }}>◆ G-DIVE JOURNAL</span>
          <span style={{ color: T.muted, fontSize: 11 }}>BTC/USDT · Trade Takip Sistemi</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {price && <span style={{ color: T.blue, fontWeight: 700, fontSize: 13 }}>BTC {fmtK(price)}</span>}
          <button onClick={() => setShowForm(!showForm)} style={{ background: showForm ? `${T.gold}20` : "transparent", border: `1px solid ${showForm ? T.gold : T.border}`, color: showForm ? T.gold : T.muted, padding: "4px 14px", borderRadius: 4, cursor: "pointer", fontSize: 11 }}>
            {showForm ? "✕ İptal" : "+ Yeni Trade"}
          </button>
        </div>
      </div>

      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>

        {/* STATS */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10 }}>
          {[
            { label: "Sermaye", value: fmtK(equity), color: equity >= INITIAL_CAPITAL ? T.green : T.red },
            { label: "Toplam P&L", value: fmtPnl(totalPnl), color: totalPnl >= 0 ? T.green : T.red },
            { label: "Kazanma Oranı", value: `${winRate}%`, color: +winRate >= 50 ? T.green : T.orange },
            { label: "Trade Sayısı", value: `${closedTrades.length} kapandı`, color: T.muted },
            { label: "Ort. R:R", value: `${avgRR}R`, color: +avgRR >= 1 ? T.green : T.orange },
          ].map((s, i) => (
            <Card key={i} bc={s.color}>
              <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase", marginBottom: 6 }}>{s.label}</div>
              <div style={{ color: s.color, fontSize: 22, fontWeight: 900, fontFamily: "monospace" }}>{s.value}</div>
            </Card>
          ))}
        </div>

        {/* PNL CURVE */}
        <Card>
          <ST>Equity Curve</ST>
          <PnLChart trades={trades} />
        </Card>

        {/* YENİ TRADE FORMU */}
        {showForm && (
          <Card bc={T.gold}>
            <ST>Yeni Trade Ekle</ST>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 10 }}>
              <div>
                <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase", marginBottom: 3 }}>Yön</div>
                <div style={{ display: "flex", gap: 6 }}>
                  {["LONG", "SHORT"].map(d => (
                    <button key={d} onClick={() => setForm(f => ({ ...f, dir: d }))} style={{ flex: 1, background: form.dir === d ? (d === "LONG" ? `${T.green}20` : `${T.red}20`) : "transparent", border: `1px solid ${form.dir === d ? (d === "LONG" ? T.green : T.red) : T.border}`, color: form.dir === d ? (d === "LONG" ? T.green : T.red) : T.muted, padding: "6px", borderRadius: 4, cursor: "pointer", fontFamily: "monospace", fontSize: 11, fontWeight: 700 }}>
                      {d === "LONG" ? "▲ LONG" : "▼ SHORT"}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase", marginBottom: 3 }}>Giriş Fiyatı</div>
                <div style={{ display: "flex", gap: 4 }}>
                  <input type="number" value={form.entry} placeholder={price?.toFixed(0)} onChange={e => setForm(f => ({ ...f, entry: e.target.value }))}
                    style={{ flex: 1, background: T.card2, border: `1px solid ${T.border}`, borderRadius: 4, padding: "6px 8px", color: T.text, fontFamily: "monospace", fontSize: 12 }} />
                  <button onClick={fillFromPrice} style={{ background: `${T.blue}20`, border: `1px solid ${T.blue}`, color: T.blue, padding: "6px 8px", borderRadius: 4, cursor: "pointer", fontSize: 10 }}>↑</button>
                </div>
              </div>
              <Input label="Stop Loss" field="stop" placeholder="örn: 67000" />
              <Input label="TP (opsiyonel)" field="tp" placeholder={`auto: ${RR}:1 RR`} />
              <Input label="Pozisyon Büyüklüğü (BTC)" field="size" placeholder="auto (2% risk)" />
              <Input label="Regime" field="regime" placeholder="BULLISH_HIGH_VOL" />
              <Input label="Sinyal" field="signal" placeholder="GÜÇLÜ LONG +7" />
            </div>
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: T.muted, fontSize: 9.5, textTransform: "uppercase", marginBottom: 3 }}>Notlar</div>
              <textarea value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Trade gerekçesi, piyasa durumu..."
                style={{ width: "100%", background: T.card2, border: `1px solid ${T.border}`, borderRadius: 4, padding: "6px 8px", color: T.text, fontFamily: "monospace", fontSize: 11, resize: "vertical", minHeight: 60, boxSizing: "border-box" }} />
            </div>
            {form.entry && form.stop && (
              <div style={{ display: "flex", gap: 16, marginBottom: 10, fontSize: 11, color: T.muted, padding: "8px 12px", background: T.card2, borderRadius: 6 }}>
                <span>Risk: <span style={{ color: T.orange }}>~${(INITIAL_CAPITAL * RISK_PCT).toFixed(0)}</span></span>
                <span>TP: <span style={{ color: T.green }}>~${(INITIAL_CAPITAL * RISK_PCT * RR).toFixed(0)}</span></span>
                <span>RR: <span style={{ color: T.gold }}>{RR}:1</span></span>
                {form.entry && form.stop && <span>Lot: <span style={{ color: T.blue }}>{((INITIAL_CAPITAL * RISK_PCT) / Math.abs(+form.entry - +form.stop)).toFixed(4)} BTC</span></span>}
              </div>
            )}
            <button onClick={addTrade} style={{ background: T.gold, border: "none", color: "#000", padding: "8px 24px", borderRadius: 4, cursor: "pointer", fontFamily: "monospace", fontSize: 12, fontWeight: 900 }}>
              ✓ Trade Ekle
            </button>
          </Card>
        )}

        {/* TRADE LİSTESİ */}
        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <ST>Trade Geçmişi</ST>
            <div style={{ display: "flex", gap: 6 }}>
              {["ALL", "OPEN", "CLOSED"].map(f => (
                <button key={f} onClick={() => setFilter(f)} style={{ background: filter === f ? `${T.blue}20` : "transparent", border: `1px solid ${filter === f ? T.blue : T.border}`, color: filter === f ? T.blue : T.muted, padding: "3px 12px", borderRadius: 4, cursor: "pointer", fontSize: 10 }}>
                  {f}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 && (
            <div style={{ color: T.muted, fontSize: 11, textAlign: "center", padding: 24 }}>Trade yok</div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {filtered.map(trade => {
              const isOpen = trade.status === "OPEN";
              const dirColor = trade.dir === "LONG" ? T.green : T.red;
              const pnlColor = trade.pnl > 0 ? T.green : trade.pnl < 0 ? T.red : T.muted;
              const [exitVal, setExitVal] = useState("");
              return (
                <div key={trade.id} style={{ background: T.card2, border: `1px solid ${isOpen ? T.gold + "60" : T.border}`, borderLeft: `3px solid ${isOpen ? T.gold : pnlColor || T.border}`, borderRadius: 6, padding: "10px 14px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                      <span style={{ color: dirColor, fontWeight: 900, fontSize: 13 }}>{trade.dir === "LONG" ? "▲" : "▼"} {trade.dir}</span>
                      <span style={{ color: T.muted, fontSize: 10 }}>{trade.date}</span>
                      {isOpen && <span style={{ color: T.gold, fontSize: 9, background: `${T.gold}20`, border: `1px solid ${T.gold}40`, padding: "1px 6px", borderRadius: 99 }}>AÇIK</span>}
                      {trade.regime && <span style={{ color: T.muted, fontSize: 9 }}>{trade.regime}</span>}
                      {trade.signal && <span style={{ color: T.purple, fontSize: 9 }}>{trade.signal}</span>}
                    </div>
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      {!isOpen && trade.pnl !== null && (
                        <span style={{ color: pnlColor, fontWeight: 700, fontSize: 13, fontFamily: "monospace" }}>
                          {fmtPnl(trade.pnl)} ({trade.rr > 0 ? "+" : ""}{trade.rr}R)
                        </span>
                      )}
                      {isOpen && price && (
                        <span style={{ color: T.blue, fontSize: 11, fontFamily: "monospace" }}>
                          Live: {fmtK(price)}
                        </span>
                      )}
                      <button onClick={() => deleteTrade(trade.id)} style={{ background: "transparent", border: `1px solid ${T.border}`, color: T.muted, padding: "2px 8px", borderRadius: 4, cursor: "pointer", fontSize: 9 }}>✕</button>
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: 20, marginTop: 8, fontSize: 10.5 }}>
                    <span>Giriş: <span style={{ color: T.text, fontWeight: 700 }}>{fmtK(trade.entry)}</span></span>
                    <span>Stop: <span style={{ color: T.red }}>{fmtK(trade.stop)}</span></span>
                    <span>TP: <span style={{ color: T.green }}>{fmtK(trade.tp)}</span></span>
                    <span>Lot: <span style={{ color: T.muted }}>{trade.size} BTC</span></span>
                    {!isOpen && <span>Çıkış: <span style={{ color: T.text }}>{fmtK(trade.exitPrice)}</span></span>}
                    {!isOpen && <span>Tarih: <span style={{ color: T.muted }}>{trade.exitDate}</span></span>}
                  </div>

                  {trade.notes && (
                    <div style={{ marginTop: 6, color: T.muted, fontSize: 10.5, fontStyle: "italic", borderTop: `1px solid ${T.border}`, paddingTop: 6 }}>{trade.notes}</div>
                  )}

                  {isOpen && (
                    <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
                      <input type="number" value={exitVal} onChange={e => setExitVal(e.target.value)} placeholder="Çıkış fiyatı..."
                        style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 4, padding: "5px 8px", color: T.text, fontFamily: "monospace", fontSize: 11, width: 140 }} />
                      <button onClick={() => { if (price) setExitVal(price.toFixed(0)); }} style={{ background: `${T.blue}20`, border: `1px solid ${T.blue}`, color: T.blue, padding: "5px 10px", borderRadius: 4, cursor: "pointer", fontSize: 10 }}>
                        Market {fmtK(price)}
                      </button>
                      <button onClick={() => closeTrade(trade.id, exitVal || price)} style={{ background: `${T.green}20`, border: `1px solid ${T.green}`, color: T.green, padding: "5px 14px", borderRadius: 4, cursor: "pointer", fontFamily: "monospace", fontSize: 11, fontWeight: 700 }}>
                        ✓ Kapat
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>

        <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10, display: "flex", justifyContent: "space-between", fontSize: 10, color: T.muted }}>
          <span>G-DIVE V4 Trade Journal · ${INITIAL_CAPITAL.toLocaleString()} başlangıç sermayesi · 2% risk · {RR}:1 RR</span>
          <span>Veriler tarayıcıda saklanır (localStorage)</span>
        </div>
      </div>
    </div>
  );
}
