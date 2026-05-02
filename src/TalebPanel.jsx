// TalebPanel.jsx
// ═══════════════════════════════════════════════════════════════
// G-DIVE V4 — Taleb Modülleri Paneli
// Shadow GEX + Rehedge Band + Pin Risk görselleştirmesi
// MenthorQ dark tema uyumlu
//
// Kullanım (App.jsx içinde):
//   import TalebPanel from './TalebPanel';
//   <TalebPanel taleb={serverData?.taleb} spot={serverData?.spot} />
// ═══════════════════════════════════════════════════════════════

import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Cell,
} from "recharts";

// ── Tema sabitleri (MenthorQ dark) ──────────────────────────────
const C = {
  bg:       "#06080e",
  card:     "#0e1520",
  border:   "#1a2535",
  green:    "#00e599",
  red:      "#ff3d5a",
  yellow:   "#f5c518",
  blue:     "#3b82f6",
  muted:    "#4a5568",
  text:     "#e2e8f0",
  textSub:  "#718096",
};

// ── Küçük yardımcı bileşenler ───────────────────────────────────
const Card = ({ children, style = {} }) => (
  <div style={{
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 10,
    padding: "14px 16px",
    marginBottom: 10,
    ...style,
  }}>
    {children}
  </div>
);

const Label = ({ children }) => (
  <div style={{
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "0.8px",
    textTransform: "uppercase",
    color: C.textSub,
    marginBottom: 6,
  }}>
    {children}
  </div>
);

const Row = ({ label, value, color, sub }) => (
  <div style={{
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "5px 0",
    borderBottom: `0.5px solid ${C.border}`,
    fontSize: 12,
  }}>
    <span style={{ color: C.textSub }}>{label}</span>
    <div style={{ textAlign: "right" }}>
      <span style={{ color: color || C.text, fontWeight: 600 }}>{value}</span>
      {sub && <div style={{ fontSize: 10, color: C.textSub }}>{sub}</div>}
    </div>
  </div>
);

const Badge = ({ label, color = C.green, bg }) => (
  <span style={{
    display: "inline-block",
    fontSize: 11,
    fontWeight: 600,
    padding: "2px 9px",
    borderRadius: 20,
    background: bg || `${color}22`,
    color: color,
    border: `0.5px solid ${color}44`,
  }}>
    {label}
  </span>
);

// ── Pin Risk gauge ───────────────────────────────────────────────
const PinGauge = ({ score }) => {
  const color = score >= 7.5 ? C.red : score >= 5 ? C.yellow : score >= 2.5 ? C.blue : C.green;
  const pct = (score / 10) * 100;
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: C.textSub, marginBottom: 4 }}>
        <span>0</span><span>Pin Risk Skoru</span><span>10</span>
      </div>
      <div style={{ background: C.border, borderRadius: 6, height: 10, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`,
          height: "100%",
          background: color,
          borderRadius: 6,
          transition: "width 0.4s",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, alignItems: "center" }}>
        <span style={{ fontSize: 22, fontWeight: 700, color }}>{score}</span>
        <Badge label={
          score >= 7.5 ? "KRİTİK" : score >= 5 ? "YÜKSEK" : score >= 2.5 ? "ORTA" : "DÜŞÜK"
        } color={color} />
      </div>
    </div>
  );
};

// ── Rehedge Band görselleştirmesi ────────────────────────────────
const RehedgeBandViz = ({ band, spot }) => {
  if (!band || !spot) return null;
  const { upper_band, lower_band, band_pct } = band;

  return (
    <div style={{ marginTop: 8 }}>
      {/* Bant görseli */}
      <div style={{ position: "relative", height: 48, marginBottom: 8 }}>
        {/* Bant alanı */}
        <div style={{
          position: "absolute",
          left: "10%", right: "10%",
          top: "20%", bottom: "20%",
          background: `${C.blue}22`,
          border: `1px dashed ${C.blue}88`,
          borderRadius: 4,
        }} />
        {/* Spot çizgisi */}
        <div style={{
          position: "absolute",
          left: "50%",
          top: 0, bottom: 0,
          width: 2,
          background: C.green,
          transform: "translateX(-50%)",
        }} />
        {/* Etiketler */}
        <div style={{ position: "absolute", left: "8%", top: 2, fontSize: 10, color: C.blue }}>
          ${lower_band?.toLocaleString()}
        </div>
        <div style={{ position: "absolute", right: "8%", top: 2, fontSize: 10, color: C.blue, textAlign: "right" }}>
          ${upper_band?.toLocaleString()}
        </div>
        <div style={{ position: "absolute", left: "50%", bottom: 2, transform: "translateX(-50%)", fontSize: 10, color: C.green }}>
          SPOT
        </div>
      </div>

      {/* Metrikler */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
        {[
          ["Alt Bant", `$${lower_band?.toLocaleString()}`, C.red],
          ["Genişlik", `±%${band_pct}`, C.blue],
          ["Üst Bant", `$${upper_band?.toLocaleString()}`, C.green],
        ].map(([l, v, c]) => (
          <div key={l} style={{
            background: `${c}11`,
            border: `0.5px solid ${c}33`,
            borderRadius: 6, padding: "6px 8px", textAlign: "center",
          }}>
            <div style={{ fontSize: 10, color: C.textSub }}>{l}</div>
            <div style={{ fontSize: 12, fontWeight: 600, color: c }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Shadow GEX bar chart ─────────────────────────────────────────
const ShadowGexChart = ({ byStrike, spot }) => {
  if (!byStrike || byStrike.length === 0) {
    return <div style={{ color: C.textSub, fontSize: 12, textAlign: "center", padding: 16 }}>Veri yok</div>;
  }

  const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 6, padding: "8px 12px", fontSize: 11 }}>
        <div style={{ color: C.text, fontWeight: 600 }}>Strike ${d.strike?.toLocaleString()}</div>
        <div style={{ color: C.blue }}>BSM GEX: {d.bsm_gex_m}M</div>
        <div style={{ color: C.green }}>Shadow GEX: {d.shadow_gex_m}M</div>
        <div style={{ color: d.diff_m > 0 ? C.green : C.red }}>Fark: {d.diff_m > 0 ? "+" : ""}{d.diff_m}M</div>
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={byStrike} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
        <XAxis
          dataKey="strike"
          tickFormatter={v => `$${(v/1000).toFixed(0)}K`}
          tick={{ fill: C.textSub, fontSize: 10 }}
          axisLine={{ stroke: C.border }}
        />
        <YAxis tick={{ fill: C.textSub, fontSize: 10 }} axisLine={{ stroke: C.border }} />
        <Tooltip content={<CustomTooltip />} />
        <ReferenceLine y={0} stroke={C.muted} />
        <Bar dataKey="bsm_gex_m" name="BSM GEX" fill={C.blue} opacity={0.6} radius={[2,2,0,0]} />
        <Bar dataKey="shadow_gex_m" name="Shadow GEX" radius={[2,2,0,0]}>
          {byStrike.map((entry, i) => (
            <Cell key={i} fill={entry.shadow_gex_m >= 0 ? C.green : C.red} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
};

// ── ANA BILEŞEN ──────────────────────────────────────────────────
export default function TalebPanel({ taleb, spot }) {
  const data = taleb;

  // Veri yoksa skeleton
  if (!data) {
    return (
      <Card>
        <Label>Taleb Modülleri (Shadow GEX · Rehedge · Pin Risk)</Label>
        <div style={{ color: C.textSub, fontSize: 12, textAlign: "center", padding: 20 }}>
          Veri bekleniyor — backend'den taleb objesi gelmiyor.
          <br />
          <span style={{ fontSize: 11 }}>gdive_server.py'ye taleb_integration_patch.py'yi ekle.</span>
        </div>
      </Card>
    );
  }

  const { shadow_gex, rehedge_band, pin_risk, summary, vol_regime } = data;

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", color: C.text }}>

      {/* ── Başlık + Özet alert ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
          Taleb Risk Modülleri
        </div>
        <Badge
          label={vol_regime === "high" ? "Yüksek Vol" : vol_regime === "low" ? "Düşük Vol" : "Normal Vol"}
          color={vol_regime === "high" ? C.red : vol_regime === "low" ? C.green : C.blue}
        />
      </div>

      {summary?.alert && (
        <div style={{
          background: `${C.red}15`,
          border: `1px solid ${C.red}44`,
          borderRadius: 8, padding: "8px 12px",
          marginBottom: 10, fontSize: 12, color: C.red,
        }}>
          {summary.alert}
        </div>
      )}

      {/* ── Grid: 3 kart ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>

        {/* Shadow GEX özet */}
        <Card style={{ marginBottom: 0 }}>
          <Label>Shadow GEX (Taleb Ch.8)</Label>
          <Row
            label="BSM GEX"
            value={`${shadow_gex?.total_bsm_gex_m > 0 ? "+" : ""}${shadow_gex?.total_bsm_gex_m}M`}
            color={shadow_gex?.total_bsm_gex_m > 0 ? C.green : C.red}
          />
          <Row
            label="Shadow GEX"
            value={`${shadow_gex?.total_shadow_gex_m > 0 ? "+" : ""}${shadow_gex?.total_shadow_gex_m}M`}
            color={shadow_gex?.total_shadow_gex_m > 0 ? C.green : C.red}
            sub="Vol etkisi dahil"
          />
          <Row
            label="GEX Amplifier"
            value={`${shadow_gex?.gex_amplifier}x`}
            color={shadow_gex?.gex_amplifier > 1.2 ? C.yellow : C.text}
            sub={shadow_gex?.gex_amplifier > 1.2 ? "Vol etkisi büyütüyor" : "Normal"}
          />
          <div style={{ marginTop: 8 }}>
            <Badge
              label={shadow_gex?.regime === "SHADOW_POSITIVE" ? "Shadow Pozitif" : "Shadow Negatif"}
              color={shadow_gex?.regime === "SHADOW_POSITIVE" ? C.green : C.red}
            />
          </div>
        </Card>

        {/* Pin Risk */}
        <Card style={{ marginBottom: 0 }}>
          <Label>Pin Risk (Taleb Ch.14)</Label>
          <PinGauge score={pin_risk?.pin_score || 0} />
          <div style={{ marginTop: 8 }}>
            <Row label="Max Pain" value={`$${pin_risk?.max_pain?.toLocaleString()}`} />
            <Row
              label="Spot → Max Pain"
              value={`${pin_risk?.spot_to_max_pain_pct}%`}
              color={pin_risk?.spot_to_max_pain_pct < 2 ? C.red : C.text}
            />
            <Row label="Expiry" value={`${pin_risk?.expiry_days} gün`} color={pin_risk?.expiry_days <= 2 ? C.red : C.text} />
          </div>
        </Card>
      </div>

      {/* Rehedge Band */}
      <Card>
        <Label>Dinamik Rehedge Bandı (Taleb Ch.11-14)</Label>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
          <span style={{ fontSize: 12, color: C.textSub }}>
            {rehedge_band?.interpretation}
          </span>
          <Badge label={`k = ${rehedge_band?.k_used}`} color={C.blue} />
        </div>
        <RehedgeBandViz band={rehedge_band} spot={spot} />
        <div style={{ marginTop: 8, fontSize: 11, color: C.textSub, lineHeight: 1.5 }}>
          Bu bant, dealer'ın hedge yapmaya zorlandığı eşiği gösterir.
          Spot bu bandın dışına çıkarsa hedge baskısı artar.
          BSM'nin sabit ±%0.5'i yerine vol rejimine ({vol_regime}) göre dinamik hesaplanır.
        </div>
      </Card>

      {/* Shadow GEX chart */}
      <Card>
        <Label>BSM vs Shadow GEX — Strike Bazlı Karşılaştırma</Label>
        <div style={{ fontSize: 11, color: C.textSub, marginBottom: 8 }}>
          Mavi: BSM (standart) · Renkli: Shadow (vol etkisi dahil) · Fark = vol'ün gizli ağırlığı
        </div>
        <ShadowGexChart byStrike={shadow_gex?.by_strike} spot={spot} />
      </Card>

      {/* Pin Risk bileşenleri */}
      <Card>
        <Label>Pin Risk Bileşenleri</Label>
        {pin_risk?.components && Object.entries(pin_risk.components).map(([key, val]) => (
          <div key={key} style={{ marginBottom: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
              <span style={{ color: C.textSub }}>
                {{ proximity: "Max Pain Yakınlığı", time: "Zamana Yakınlık", concentration: "OI Konsantrasyonu", front_weight: "Front Vade Ağırlığı" }[key]}
              </span>
              <span style={{ color: C.text, fontWeight: 600 }}>{val} / 10</span>
            </div>
            <div style={{ background: C.border, borderRadius: 3, height: 4 }}>
              <div style={{
                width: `${val * 10}%`,
                height: "100%",
                background: val >= 7 ? C.red : val >= 4 ? C.yellow : C.green,
                borderRadius: 3,
                transition: "width 0.3s",
              }} />
            </div>
          </div>
        ))}
        {pin_risk?.action && (
          <div style={{
            marginTop: 10, fontSize: 11, color: C.textSub,
            background: `${C.border}88`, borderRadius: 6, padding: "7px 10px",
          }}>
            💡 {pin_risk.action}
          </div>
        )}
      </Card>

    </div>
  );
}
