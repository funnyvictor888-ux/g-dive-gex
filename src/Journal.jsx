import { useState, useEffect, useCallback } from "react";

const SUPABASE_URL = "https://gigkmjutnucssgwcnegn.supabase.co";
const SUPABASE_KEY = "sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW";

const C = {
  bg:"#06080e",card:"#0e1520",card2:"#121c2a",
  border:"#1a2535",border2:"#223040",
  text:"#dce8f5",muted:"#3d5470",dim:"#1a2840",
  green:"#00e599",greenDim:"#002a1a",
  red:"#ff3d5a",redDim:"#2a0010",
  gold:"#ffbe2e",blue:"#3db8ff",purple:"#9d7aff",
};

const fK = n => `$${(+n||0).toLocaleString("en-US",{maximumFractionDigits:0})}`;
const fPnl = n => `${(+n||0)>=0?"+":""}$${Math.abs(+n||0).toFixed(0)}`;

function timeSince(d){
  if(!d) return "—";
  const diff=(Date.now()-new Date(d.replace(" ","T")+"Z").getTime())/1000;
  if(diff<3600) return Math.floor(diff/60)+"dk";
  if(diff<86400) return Math.floor(diff/3600)+"sa";
  return Math.floor(diff/86400)+"g";
}

async function fetchPrice(){
  try{const r=await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");return r.ok?+(await r.json()).price:null;}catch{return null;}
}

function EquityCurve({trades}){
  const W=600,H=110,PL=50,PR=16,PT=8,PB=18;
  const cw=W-PL-PR,ch=H-PT-PB;
  const closed=trades.filter(t=>t.status==="CLOSED"&&t.pnl!=null);
  if(!closed.length) return(
    <div style={{height:H,display:"flex",alignItems:"center",justifyContent:"center",color:C.muted,fontSize:11}}>Henüz kapatılmış trade yok</div>
  );
  const CAP=10000;let cum=0;
  const pts=[{i:0,y:CAP}];
  closed.forEach((t,i)=>{cum+=t.pnl||0;pts.push({i:i+1,y:CAP+cum});});
  const minY=Math.min(...pts.map(p=>p.y))*0.997;
  const maxY=Math.max(...pts.map(p=>p.y))*1.003;
  const xS=i=>PL+i/(pts.length-1||1)*cw;
  const yS=y=>PT+ch-(y-minY)/(maxY-minY||1)*ch;
  const path=pts.map((p,i)=>`${i===0?"M":"L"}${xS(i)},${yS(p.y)}`).join(" ");
  const fill=`${path} L${xS(pts.length-1)},${PT+ch} L${PL},${PT+ch} Z`;
  const last=pts[pts.length-1];const isUp=last.y>=CAP;
  return(
    <svg width={W} height={H} style={{display:"block",maxWidth:"100%"}}>
      <defs><linearGradient id="eg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={isUp?C.green:C.red} stopOpacity="0.25"/>
        <stop offset="100%" stopColor={isUp?C.green:C.red} stopOpacity="0"/>
      </linearGradient></defs>
      <path d={fill} fill="url(#eg)"/>
      <path d={path} fill="none" stroke={isUp?C.green:C.red} strokeWidth={1.5}/>
      <line x1={PL} y1={yS(CAP)} x2={W-PR} y2={yS(CAP)} stroke={C.border2} strokeWidth={1} strokeDasharray="4,3"/>
      <text x={PL-4} y={yS(CAP)+3} fill={C.muted} fontSize={9} textAnchor="end" fontFamily="monospace">${CAP.toLocaleString()}</text>
      <circle cx={xS(pts.length-1)} cy={yS(last.y)} r={3} fill={isUp?C.green:C.red}/>
      <text x={xS(pts.length-1)+6} y={yS(last.y)+3} fill={isUp?C.green:C.red} fontSize={9} fontFamily="monospace">{fK(last.y)}</text>
    </svg>
  );
}

function ThesisChecker({trade,snapshot}){
  const checks=[
    {l:"GEX Flip OK",ok:!snapshot?.gamma_analysis?.flip_near,warn:snapshot?.gamma_analysis?.flip_near},
    {l:"Regime devam",ok:(trade.dir==="LONG"&&["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(snapshot?.regime))||(trade.dir==="SHORT"&&["BEARISH_VOLATILE","BEARISH_LOW_VOL"].includes(snapshot?.regime)),warn:false},
    {l:"GEX yön OK",ok:(trade.dir==="LONG"&&(snapshot?.total_net_gex||0)>0)||(trade.dir==="SHORT"&&(snapshot?.total_net_gex||0)<0),warn:false},
    {l:"Expiry",ok:(snapshot?.expiry?.days_to_expiry||30)>14,warn:(snapshot?.expiry?.days_to_expiry||30)<=14},
  ];
  return(
    <div style={{display:"flex",gap:5,flexWrap:"wrap"}}>
      {checks.map((c,i)=>(
        <span key={i} style={{fontSize:9,padding:"2px 7px",borderRadius:4,
          background:c.ok?`${C.green}15`:c.warn?`${C.gold}15`:`${C.red}15`,
          color:c.ok?C.green:c.warn?C.gold:C.red,
          border:`1px solid ${c.ok?C.green+"30":c.warn?C.gold+"30":C.red+"30"}`}}>
          {c.ok?"✓":c.warn?"⚡":"✗"} {c.l}
        </span>
      ))}
    </div>
  );
}

function TradeCard({trade,price,snapshot}){
  const isOpen=trade.status==="OPEN";
  const dir=trade.dir||"LONG";
  const entry=trade.entry||0;
  const stop=trade.stop||0;
  const tp=trade.tp||0;
  const size=trade.size||0;
  const cur=price||entry;
  const unrealized=isOpen?(dir==="LONG"?(cur-entry)*size:(entry-cur)*size):(trade.pnl||0);
  const isWin=unrealized>=0;
  const range=Math.abs(tp-stop)||1;
  const spotPos=Math.min(100,Math.max(0,Math.abs(cur-stop)/range*100));
  const entryPos=Math.min(100,Math.max(0,Math.abs(entry-stop)/range*100));
  const accent=isOpen?(dir==="LONG"?C.green:C.red):(isWin?C.green:C.red);
  const rr=tp&&stop&&entry?Math.abs((tp-entry)/(entry-stop)).toFixed(1):"—";
  return(
    <div style={{background:C.card,border:`0.5px solid ${C.border}`,borderLeft:`3px solid ${accent}`,borderRadius:10,padding:"12px 14px",marginBottom:8,opacity:isOpen?1:0.85}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <span style={{fontSize:9,padding:"1px 7px",borderRadius:3,fontWeight:700,
            background:isOpen?`${C.green}15`:C.dim,color:isOpen?C.green:C.muted,
            border:`1px solid ${isOpen?C.green+"30":C.border}`}}>{isOpen?"● AÇIK":"KAPALI"}</span>
          <span style={{fontWeight:700,fontSize:12}}>{dir} #{(trade.trade_id||trade.id||"").toString().slice(-6)}</span>
          <span style={{color:C.muted,fontSize:9}}>{trade.signal||""} · {(trade.date||"").slice(0,16)}</span>
        </div>
        <div style={{fontSize:18,fontWeight:900,fontFamily:"monospace",color:isWin?C.green:C.red}}>{fPnl(unrealized)}</div>
      </div>
      {trade.notes&&(
        <div style={{background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"5px 9px",marginBottom:8,fontSize:9.5,color:C.muted,lineHeight:1.6}}>
          <span style={{color:C.text,fontWeight:700}}>Neden: </span>{trade.notes}
        </div>
      )}
      {isOpen&&(
        <div style={{marginBottom:8}}>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:8.5,color:C.muted,marginBottom:3}}>
            <span style={{color:C.red}}>Stop {fK(stop)}</span>
            <span style={{color:C.blue}}>Spot {fK(cur)}</span>
            <span style={{color:C.green}}>TP {fK(tp)}</span>
          </div>
          <div style={{position:"relative",height:6,background:C.dim,borderRadius:99,overflow:"hidden"}}>
            <div style={{position:"absolute",left:0,top:0,height:"100%",width:`${spotPos}%`,
              background:`linear-gradient(90deg,${C.red}40,${accent})`,borderRadius:99}}/>
            <div style={{position:"absolute",left:`${entryPos}%`,top:-1,width:2,height:8,background:C.blue,borderRadius:99}}/>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:8,color:C.muted,marginTop:2}}>
            <span>RR: {rr}:1</span><span>Süre: {timeSince(trade.date)}</span>
          </div>
        </div>
      )}
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:5,marginBottom:isOpen?8:0}}>
        {[
          {l:"Giriş",v:fK(entry)},
          {l:isOpen?"Anlık":"Çıkış",v:isOpen?fK(cur):fK(trade.exit_price||0)},
          {l:"Boyut",v:`${(size||0).toFixed(3)} BTC`},
          {l:"RR",v:isOpen?`${rr}:1`:(trade.pnl||0)>=0?`+${rr}`:"-1.0",c:isOpen?C.text:(trade.pnl||0)>=0?C.green:C.red},
        ].map((s,i)=>(
          <div key={i} style={{padding:"4px 7px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:4}}>
            <div style={{color:C.muted,fontSize:8.5}}>{s.l}</div>
            <div style={{color:s.c||C.text,fontFamily:"monospace",fontSize:10.5,fontWeight:700}}>{s.v}</div>
          </div>
        ))}
      </div>
      {isOpen&&snapshot&&(
        <div style={{borderTop:`1px solid ${C.border}`,paddingTop:7}}>
          <div style={{color:C.muted,fontSize:8.5,marginBottom:4}}>Thesis Invalidation</div>
          <ThesisChecker trade={trade} snapshot={snapshot}/>
        </div>
      )}
      {!isOpen&&(
        <div style={{fontSize:9,color:C.muted,marginTop:4}}>
          Çıkış: {(trade.exit_date||"").slice(0,16)} · {(trade.notes||"").split("|").pop()?.trim()||"—"}
        </div>
      )}
    </div>
  );
}

export default function Journal(){
  const [trades,setTrades]=useState([]);
  const [snapshot,setSnapshot]=useState(null);
  const [price,setPrice]=useState(null);
  const [filter,setFilter]=useState("ALL");
  const [busy,setBusy]=useState(false);

  const load=useCallback(async()=>{
    setBusy(true);
    try{
      const r=await fetch(`${SUPABASE_URL}/rest/v1/trades?order=id.desc&limit=100`,{headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}});
      if(r.ok){const rows=await r.json();setTrades(rows.map(t=>({...t,exitDate:t.exit_date,exitPrice:t.exit_price})));}
      const r2=await fetch(`${SUPABASE_URL}/rest/v1/snapshots?order=id.desc&limit=1`,{headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}});
      if(r2.ok){const rows2=await r2.json();if(rows2.length)setSnapshot(rows2[0]);}
      const p=await fetchPrice();if(p)setPrice(p);
    }catch(e){console.error(e);}
    setBusy(false);
  },[]);

  useEffect(()=>{load();const iv=setInterval(()=>fetchPrice().then(p=>p&&setPrice(p)),30000);return()=>clearInterval(iv);},[load]);

  const closed=trades.filter(t=>t.status==="CLOSED"&&t.pnl!=null);
  const open=trades.filter(t=>t.status==="OPEN");
  const wins=closed.filter(t=>t.pnl>0);
  const totalPnl=closed.reduce((a,t)=>a+(t.pnl||0),0);
  const wr=closed.length?wins.length/closed.length*100:0;
  const aw=wins.length?wins.reduce((a,t)=>a+(t.pnl||0),0)/wins.length:0;
  const al=(closed.length-wins.length)>0?Math.abs(closed.filter(t=>t.pnl<=0).reduce((a,t)=>a+(t.pnl||0),0)/(closed.length-wins.length)):1;
  const pf=al>0?Math.abs(wins.reduce((a,t)=>a+(t.pnl||0),0))/Math.abs(closed.filter(t=>t.pnl<=0).reduce((a,t)=>a+(t.pnl||0),0)||1):0;
  const exp=wr/100*aw-(1-wr/100)*al;
  let eq=10000,pk=10000,mdd=0;
  closed.forEach(t=>{eq+=t.pnl||0;if(eq>pk)pk=eq;const dd=(pk-eq)/pk;if(dd>mdd)mdd=dd;});
  const filtered=trades.filter(t=>filter==="ALL"?true:filter==="OPEN"?t.status==="OPEN":t.status==="CLOSED");

  return(
    <div style={{background:C.bg,minHeight:"100vh",color:C.text,fontFamily:"'JetBrains Mono','Fira Code',monospace",padding:"16px 20px"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <span style={{color:C.gold,fontWeight:900,fontSize:13}}>G-DIVE JOURNAL V5</span>
          <span style={{background:`${C.purple}20`,color:C.purple,fontSize:9,padding:"2px 8px",borderRadius:4}}>{snapshot?.regime||"—"}</span>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{fontSize:20,fontWeight:900}}>{fK(price||snapshot?.spot||0)}</span>
          <button onClick={load} disabled={busy} style={{background:C.card,border:`1px solid ${C.border}`,color:C.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:10}}>{busy?"...":"↺"}</button>
        </div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:7,marginBottom:12}}>
        {[
          {l:"Toplam P&L",v:`${totalPnl>=0?"+":""}$${totalPnl.toFixed(0)}`,c:totalPnl>=0?C.green:C.red},
          {l:"Sermaye",v:fK(10000+totalPnl),c:C.text},
          {l:"Win Rate",v:`${wr.toFixed(1)}%`,c:wr>=55?C.green:wr>=45?C.gold:C.red},
          {l:"Profit Factor",v:pf.toFixed(2),c:pf>=1.5?C.green:pf>=1?C.gold:C.red},
          {l:"Max DD",v:`${(mdd*100).toFixed(1)}%`,c:mdd<0.1?C.green:mdd<0.2?C.gold:C.red},
          {l:"Beklenti",v:`${exp>=0?"+":""}$${exp.toFixed(0)}`,c:exp>=0?C.green:C.red},
        ].map((s,i)=>(
          <div key={i} style={{padding:"7px 9px",background:C.card,border:`1px solid ${C.border}`,borderRadius:6}}>
            <div style={{color:C.muted,fontSize:8.5,marginBottom:1}}>{s.l}</div>
            <div style={{color:s.c,fontFamily:"monospace",fontSize:13,fontWeight:900}}>{s.v}</div>
          </div>
        ))}
      </div>
      <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:10,padding:"10px 14px",marginBottom:12}}>
        <div style={{color:C.muted,fontSize:9,marginBottom:6}}>EQUITY CURVE — {closed.length} trade</div>
        <EquityCurve trades={trades}/>
      </div>
      <div style={{display:"flex",gap:6,marginBottom:10}}>
        {["ALL","OPEN","CLOSED"].map(f=>(
          <button key={f} onClick={()=>setFilter(f)} style={{
            background:filter===f?`${C.blue}20`:C.card,border:`1px solid ${filter===f?C.blue:C.border}`,
            color:filter===f?C.blue:C.muted,padding:"4px 14px",borderRadius:5,cursor:"pointer",fontSize:10,fontWeight:700
          }}>{f} {f==="OPEN"?open.length:f==="CLOSED"?closed.length:trades.length}</button>
        ))}
        <span style={{color:C.muted,fontSize:9,alignSelf:"center",marginLeft:"auto"}}>UTC: {snapshot?.timestamp?.slice(11,16)||"—"}</span>
      </div>
      {filtered.length===0?(
        <div style={{color:C.muted,fontSize:11,textAlign:"center",padding:30}}>Trade geçmişi boş</div>
      ):filtered.map(t=>(
        <TradeCard key={t.id||t.trade_id} trade={t} price={price} snapshot={snapshot}/>
      ))}
    </div>
  );
}
