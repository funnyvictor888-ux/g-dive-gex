// ──────────────────────────────────────────────────────────────────
// FlipZoneBadge.jsx — G-DIVE Flip-Zone durum kartı
// ──────────────────────────────────────────────────────────────────

const DEFAULT_COLORS = {
  card: "#0e1520",
  border: "#1a2535",
  text: "#dce8f5",
  muted: "#3d5470",
  green: "#00e599",
  red: "#ff3d5a",
  gold: "#ffbe2e",
  orange: "#ff7a2f",
};

function getZoneStyle(zone, C) {
  switch (zone) {
    case "DANGER":
      return { color: C.red, bg: `${C.red}10`, border: `${C.red}50`, label: "DANGER" };
    case "CAUTION":
      return { color: C.gold, bg: `${C.gold}10`, border: `${C.gold}50`, label: "CAUTION" };
    case "CLEAR":
    default:
      return { color: C.green, bg: `${C.green}08`, border: `${C.green}30`, label: "CLEAR" };
  }
}

const DECISION_LABELS = {
  BEKLE: "BEKLE",
  VETO: "VETO",
  REDUCE: "POZ × 0.5",
  OK: "GEÇ",
};

export function FlipZoneBadge({ flipZone, C = DEFAULT_COLORS }) {
  if (!flipZone) return null;

  const style = getZoneStyle(flipZone.zone, C);
  const decisionLabel = DECISION_LABELS[flipZone.decision] || flipZone.decision;
  const showMultiplier =
    flipZone.position_multiplier !== undefined &&
    flipZone.position_multiplier < 1 &&
    flipZone.position_multiplier > 0;

  return (
    <div
      style={{
        marginTop: 10,
        background: C.card,
        border: `1px solid ${style.border}`,
        borderLeft: `3px solid ${style.color}`,
        borderRadius: 8,
        padding: "10px 12px",
        fontFamily: "monospace",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <div style={{ color: C.muted, fontSize: 9, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Flip-Zone ·{" "}
          <span style={{ color: style.color, fontWeight: 700 }}>{style.label}</span>
        </div>
        <span
          style={{
            color: style.color,
            fontWeight: 700,
            fontSize: 9,
            padding: "2px 7px",
            background: style.bg,
            border: `1px solid ${style.border}`,
            borderRadius: 3,
          }}
        >
          {decisionLabel}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6, marginBottom: 6 }}>
        {[
          { l: "Mesafe", v: `%${flipZone.flip_dist_pct?.toFixed?.(2) ?? flipZone.flip_dist_pct}` },
          { l: "ATR 4H", v: `%${flipZone.atr_pct?.toFixed?.(2) ?? flipZone.atr_pct}` },
          { l: "Oran", v: `${flipZone.flip_dist_atr_ratio?.toFixed?.(2) ?? flipZone.flip_dist_atr_ratio}×` },
        ].map((s, i) => (
          <div key={i} style={{ padding: "4px 6px", background: "rgba(0,0,0,0.25)", borderRadius: 4 }}>
            <div style={{ color: C.muted, fontSize: 8, marginBottom: 1 }}>{s.l}</div>
            <div style={{ color: C.text, fontWeight: 700, fontSize: 10.5 }}>{s.v}</div>
          </div>
        ))}
      </div>

      <div style={{ color: C.text, fontSize: 9.5, lineHeight: 1.5, opacity: 0.85 }}>
        {flipZone.reason}
      </div>

      {showMultiplier && (
        <div
          style={{
            marginTop: 6,
            paddingTop: 6,
            borderTop: `1px dashed ${C.gold}40`,
            color: C.gold,
            fontSize: 9.5,
            fontWeight: 600,
          }}
        >
          ⚠ Pozisyon otomatik {flipZone.position_multiplier}× sınırlı
        </div>
      )}
    </div>
  );
}

export default FlipZoneBadge;
