import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Journal from "./Journal.jsx";

const T = { bg:"#0d1117", border:"#30363d", gold:"#e3b341", muted:"#7d8590" };

function Root() {
  const [page, setPage] = useState("dashboard");
  return (
    <div>
      <div style={{ background:"#010409", borderBottom:`1px solid ${T.border}`, padding:"0 20px", display:"flex", gap:0 }}>
        {[{id:"dashboard",label:"◆ Dashboard"},{id:"journal",label:"◎ Journal"}].map(p => (
          <button key={p.id} onClick={() => setPage(p.id)} style={{
            background:"transparent", border:"none",
            borderBottom: page === p.id ? `2px solid ${T.gold}` : "2px solid transparent",
            color: page === p.id ? T.gold : T.muted,
            padding:"10px 20px", cursor:"pointer",
            fontFamily:"monospace", fontSize:12, fontWeight: page === p.id ? 700 : 400,
          }}>{p.label}</button>
        ))}
      </div>
      {page === "dashboard" ? <App /> : <Journal />}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<StrictMode><Root /></StrictMode>);
