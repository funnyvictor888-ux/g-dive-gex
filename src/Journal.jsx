import { useState, useEffect, useCallback } from "react";

const SERVER_URL = window.location.hostname === "localhost"
  ? "http://localhost:7432"
  : "https://web-production-909e6.up.railway.app";

const C = {
  bg:"#06080e", surface:"#0a0f18", card:"#0e1520", card2:"#121c2a",
  border:"#1a2535", border2:"#223040",
  text:"#dce8f5", muted:"#3d5470", dim:"#1a2840",
  green:"#00e599", greenDim:"#002a1a",
  red:"#ff3d5a", redDim:"#2a0010",
  orange:"#ff7a2f", gold:"#ffbe2e", goldDim:"#2a1e00",
  blue:"#3db8ff", purple:"#9d7aff",
};

const INITIAL_CAPITAL = 10000;
const RISK_PCT = 0.02;
const RR = 3;
const STORAGE_KEY = "gdive:journal:v2";

const fmtK = n => `$${n?.toLocaleString("en-US",{maximumFractionDigits:0})}`;
const fmtPnl = n => `${n>=0?"+":""}$${Math.abs(n||0).toFixed(0)}`;
const fmtPct = n => `${n>=0?"+":""}${(+n).toFixed(2)}%`;
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));

async function fetchServerData(){try{const r=await fetch(SERVER_URL+"/data");return r.ok?await r.json():null;}catch{return null;}}

function loadTrades(){try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||"[]");}catch{return[];}}
function saveTrades(t){localStorage.setItem(STORAGE_KEY,JSON.stringify(t));}

function timeSince(d){if(!d)return"—";const diff=(Date.now()-new Date(d.replace(" ","T")+"Z").getTime())/1000;if(diff<3600)return Math.floor(diff/60)+"dk";if(diff<86400)return Math.floor(diff/3600)+"sa "+Math.floor((diff%3600)/60)+"dk";return Math.floor(diff/86400)+"g";}

async function fetchPrice(){
  try{const r=await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");return r.ok?+(await r.json()).price:null;}catch{return null;}
}

// ── PnL Equity Curve SVG ──────────────────────────────────────────
function EquityCurve({trades}){
  const W=500, H=140, PL=50, PR=16, PT=10, PB=20;
  const cw=W-PL-PR, ch=H-PT-PB;
  const closed=trades.filter(t=>t.status==="CLOSED"&&t.pnl!=null);
  if(!closed.length) return(
    <div style={{height:H,display:"flex",alignItems:"center",justifyContent:"center",color:C.muted,fontSize:11}}>
      Henüz kapatılmış trade yok
    </div>
  );
  let cum=0;
  const points=[{i:0,y:INITIAL_CAPITAL}];
  closed.forEach((t,i)=>{cum+=t.pnl||0;points.push({i:i+1,y:INITIAL_CAPITAL+cum});});
  const minY=Math.min(...points.map(p=>p.y))*0.997;
  const maxY=Math.max(...points.map(p=>p.y))*1.003;
  const xS=i=>PL+i*(cw/(points.length-1));
  const yS=v=>PT+ch-(v-minY)/(maxY-minY)*ch;
  const pts=points.map(p=>`${xS(p.i)},${yS(p.y)}`).join(" ");
  const last=points[points.length-1];
  const color=last.y>=INITIAL_CAPITAL?C.green:C.red;
  const totalReturn=((last.y-INITIAL_CAPITAL)/INITIAL_CAPITAL*100).toFixed(1);
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs>
        <linearGradient id="eqg" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {[0,1,2,3].map(i=>{
        const v=minY+i*(maxY-minY)/3;
        return <line key={i} x1={PL} y1={yS(v)} x2={W-PR} y2={yS(v)} stroke={C.border} strokeWidth={0.5} strokeDasharray="3,3"/>;
      })}
      <line x1={PL} y1={yS(INITIAL_CAPITAL)} x2={W-PR} y2={yS(INITIAL_CAPITAL)} stroke={C.border2} strokeWidth={1} strokeDasharray="5,3"/>
      <text x={PL-4} y={yS(INITIAL_CAPITAL)+3} fill={C.muted} fontSize={8} textAnchor="end">${(INITIAL_CAPITAL/1000).toFixed(0)}K</text>
      <polygon points={`${pts} ${xS(points.length-1)},${H-PB} ${PL},${H-PB}`} fill="url(#eqg)"/>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2.5}/>
      {points.map((p,i)=>(
        <circle key={i} cx={xS(p.i)} cy={yS(p.y)} r={i===points.length-1?4:2.5} fill={color} stroke={C.bg} strokeWidth={1}/>
      ))}
      <text x={W-PR} y={yS(last.y)-8} fill={color} fontSize={9} textAnchor="end" fontWeight="700">${last.y.toFixed(0)} ({totalReturn>0?"+":""}{totalReturn}%)</text>
    </svg>
  );
}

// ── Win/Loss Distribution Bar ─────────────────────────────────────
function WinLossBar({wins,total}){
  const pct=total>0?wins/total*100:0;
  return(
    <div style={{height:6,background:C.redDim,borderRadius:99,overflow:"hidden"}}>
      <div style={{height:"100%",width:`${pct}%`,background:C.green,borderRadius:99}}/>
    </div>
  );
}

// ── Trade Row ─────────────────────────────────────────────────────
function OpenCard({trade,price,sData,onClose,onDelete}){
  const [ex,setEx]=useState("");
  const unreal=price?((trade.dir==="LONG"?price-trade.entry:trade.entry-price)*trade.size):0;
  const uColor=unreal>=0?"#00e599":"#ff3d5a";
  const range=Math.abs(trade.tp-trade.stop);
  const prog=price&&range>0?Math.max(0,Math.min(100,(trade.dir==="LONG"?price-trade.stop:trade.stop-price)/range*100)):50;
  const dStop=price?(Math.abs(price-trade.stop)/price*100).toFixed(1):"?";
  const dTP=price?(Math.abs(trade.tp-price)/price*100).toFixed(1):"?";
  let adv=null;
  if(sData){const r=sData.regime,sp=sData.spot,h=sData.hvl,g=sData.total_net_gex;const bull=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(r)&&sp>h&&g>0;const bear=["BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK"].includes(r)&&sp<h&&g<0;if(trade.dir==="LONG"){if(bull)adv={c:"#00e599",t:"✓ Devam Et — "+r.replace(/_/g," ")+" koşullar sağlam, GEX +"+g.toFixed(0)+"M"};else if(bear)adv={c:"#ff3d5a",t:"⚠ KAPAT — Rejim SHORT döndü ("+r.replace(/_/g," ")+")"};else adv={c:"#ffbe2e",t:"⚡ Dikkatli — Koşullar zayıfladı, takip et"};}else{if(bear)adv={c:"#00e599",t:"✓ Devam Et — SHORT koşullar sağlam"};else if(bull)adv={c:"#ff3d5a",t:"⚠ KAPAT — Rejim LONG döndü"};else adv={c:"#ffbe2e",t:"⚡ Dikkatli"};}}
  return(
    <div style={{background:"#0e1520",border:"2px solid #ffbe2e40",borderRadius:12,overflow:"hidden",marginBottom:4}}>
      <div style={{background:"#ffbe2e10",borderBottom:"1px solid #ffbe2e25",padding:"10px 16px",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
        <div style={{display:"flex",gap:10,alignItems:"center"}}>
          <span style={{width:8,height:8,borderRadius:"50%",background:"#ffbe2e",display:"inline-block"}}/>
          <span style={{color:"#ffbe2e",fontWeight:900,fontSize:11}}>AKTİF POZİSYON</span>
          <span style={{color:trade.dir==="LONG"?"#00e599":"#ff3d5a",fontWeight:900}}>{trade.dir==="LONG"?"▲":"▼"} {trade.dir}</span>
          <span style={{color:"#3d5470",fontSize:9.5}}>{trade.date}</span>
        </div>
        <button onClick={()=>onDelete(trade.id)} style={{background:"transparent",border:"1px solid #1a2535",color:"#3d5470",padding:"2px 8px",borderRadius:4,cursor:"pointer",fontSize:9}}>✕</button>
      </div>
      <div style={{padding:16}}>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12,marginBottom:14}}>
          <div style={{background:uColor+"08",border:"1px solid "+uColor+"30",borderRadius:10,padding:"14px 16px",textAlign:"center"}}>
            <div style={{color:"#3d5470",fontSize:9,textTransform:"uppercase",marginBottom:6}}>Anlık Kâr / Zarar</div>
            <div style={{color:uColor,fontSize:38,fontWeight:900,fontFamily:"monospace",lineHeight:1}}>{unreal>=0?"+":""}{unreal.toFixed(0)}<span style={{fontSize:16}}> $</span></div>
            <div style={{color:uColor,fontSize:11,marginTop:4}}>{((unreal/10000)*100).toFixed(2)}% sermaye</div>
            <div style={{color:"#3d5470",fontSize:9.5,marginTop:2}}>{price?"$"+price.toLocaleString("en-US",{maximumFractionDigits:0}):"—"} anlık</div>
          </div>
          <div style={{background:"#121c2a",border:"1px solid #1a2535",borderRadius:10,padding:"12px 14px"}}>
            <div style={{color:"#3d5470",fontSize:9,textTransform:"uppercase",marginBottom:8}}>Pozisyon</div>
            {[{l:"Giriş",v:"$"+trade.entry.toLocaleString(),c:"#3db8ff"},{l:"Lot",v:trade.size+" BTC",c:"#dce8f5"},{l:"Nominal",v:"$"+(trade.entry*trade.size).toFixed(0),c:"#3d5470"},{l:"Risk",v:"$"+(Math.abs(trade.entry-trade.stop)*trade.size).toFixed(0),c:"#ff7a2f"}].map((s,i)=>(
              <div key={i} style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
                <span style={{color:"#3d5470",fontSize:9.5}}>{s.l}</span>
                <span style={{color:s.c,fontFamily:"monospace",fontSize:11,fontWeight:700}}>{s.v}</span>
              </div>
            ))}
          </div>
          <div style={{background:"#121c2a",border:"1px solid #1a2535",borderRadius:10,padding:"12px 14px"}}>
            <div style={{color:"#3d5470",fontSize:9,textTransform:"uppercase",marginBottom:8}}>Stop & TP</div>
            {[{l:"Stop Loss",v:"$"+trade.stop.toLocaleString(),c:"#ff3d5a",sub:dStop+"% uzak"},{l:"TP (50%)",v:"$"+trade.tp.toLocaleString(),c:"#00e599",sub:dTP+"% uzak"},{l:"Hedef PnL",v:"+$"+(Math.abs(trade.tp-trade.entry)*trade.size).toFixed(0),c:"#44e8a0"}].map((s,i)=>(
              <div key={i} style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
                <span style={{color:"#3d5470",fontSize:9.5}}>{s.l}</span>
                <div style={{textAlign:"right"}}><div style={{color:s.c,fontFamily:"monospace",fontSize:11,fontWeight:700}}>{s.v}</div>{s.sub&&<div style={{color:"#3d5470",fontSize:8}}>{s.sub}</div>}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{marginBottom:12}}>
          <div style={{color:"#3d5470",fontSize:9,textTransform:"uppercase",marginBottom:5}}>Stop → Şu An → TP</div>
          <div style={{position:"relative",height:10,background:"#1a2840",borderRadius:99,overflow:"hidden",marginBottom:5}}>
            <div style={{position:"absolute",inset:0,width:prog+"%",background:"linear-gradient(90deg,#ff3d5a50,#00e59970)",borderRadius:99}}/>
            <div style={{position:"absolute",top:-1,left:prog+"%",height:12,width:3,background:"#3db8ff",borderRadius:99,transform:"translateX(-50%)"}}/>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:9}}>
            <div><span style={{color:"#ff3d5a",fontWeight:700}}>✕ Stop </span><span style={{color:"#3d5470",fontFamily:"monospace"}}>${trade.stop.toLocaleString()}</span></div>
            <div style={{textAlign:"center"}}><span style={{color:"#3db8ff",fontWeight:700}}>● Şu An </span><span style={{color:"#3db8ff",fontFamily:"monospace",fontWeight:900}}>{price?"$"+price.toLocaleString("en-US",{maximumFractionDigits:0}):"—"}</span></div>
            <div style={{textAlign:"right"}}><span style={{color:"#00e599",fontWeight:700}}>◆ TP </span><span style={{color:"#3d5470",fontFamily:"monospace"}}>${trade.tp.toLocaleString()}</span></div>
          </div>
        </div>
        <div style={{background:"#9d7aff08",border:"1px solid #9d7aff20",borderLeft:"3px solid #9d7aff",borderRadius:8,padding:"10px 12px",marginBottom:adv?10:12}}>
          <div style={{color:"#9d7aff",fontSize:9,textTransform:"uppercase",marginBottom:5}}>◆ Neden Açıldı?</div>
          <div style={{color:"#dce8f5",fontSize:11,lineHeight:1.7}}>{trade.notes||"Sistem otomatik sinyal"}</div>
          {trade.signal&&<div style={{color:"#9d7aff",fontSize:9.5,marginTop:4}}>Sinyal: {trade.signal}</div>}
          <div style={{color:"#3d5470",fontSize:9,marginTop:3}}>Regime: {trade.regime||"—"} · {trade.date}</div>
        </div>
        {adv&&<div style={{background:adv.c+"08",border:"1px solid "+adv.c+"30",borderLeft:"3px solid "+adv.c,borderRadius:8,padding:"10px 12px",marginBottom:12,color:"#dce8f5",fontSize:11,lineHeight:1.6}}>{adv.t}</div>}
        <div style={{display:"flex",gap:8,borderTop:"1px solid #1a2535",paddingTop:12}}>
          <input type="number" value={ex} onChange={e=>setEx(e.target.value)} placeholder="Çıkış fiyatı..." style={{background:"#121c2a",border:"1px solid #1a2535",borderRadius:5,padding:"7px 10px",color:"#dce8f5",fontFamily:"monospace",fontSize:12,width:150}}/>
          {price&&<button onClick={()=>setEx(price.toFixed(0))} style={{background:"#3db8ff12",border:"1px solid #3db8ff25",color:"#3db8ff",padding:"7px 12px",borderRadius:5,cursor:"pointer",fontSize:10}}>Market ${price.toLocaleString("en-US",{maximumFractionDigits:0})}</button>}
          <button onClick={()=>onClose(trade.id,ex||price)} style={{background:"#00e59912",border:"1px solid #00e59930",color:"#00e599",padding:"7px 20px",borderRadius:5,cursor:"pointer",fontFamily:"monospace",fontSize:11,fontWeight:900}}>✓ Kapat</button>
        </div>
      </div>
    </div>
  );
}

function TradeRow({trade,price,serverData,onClose,onDelete}){
  const [exitVal,setExitVal]=useState("");
  const C={bg:"#06080e",card:"#0e1520",card2:"#121c2a",border:"#1a2535",text:"#dce8f5",muted:"#3d5470",dim:"#1a2840",green:"#00e599",greenDim:"#002a1a",red:"#ff3d5a",redDim:"#2a0010",orange:"#ff7a2f",gold:"#ffbe2e",blue:"#3db8ff",purple:"#9d7aff"};
  const isOpen=trade.status==="OPEN";
  const dirColor=trade.dir==="LONG"?C.green:C.red;
  const pnlColor=(trade.pnl||0)>0?C.green:(trade.pnl||0)<0?C.red:C.muted;
  const liveUnrealized=isOpen&&price?((trade.dir==="LONG"?price-trade.entry:trade.entry-price)*trade.size):null;
  const liveColor=liveUnrealized>0?C.green:liveUnrealized<0?C.red:C.muted;
  const totalRange=Math.abs(trade.tp-trade.stop);
  const progress=price&&totalRange>0?Math.max(0,Math.min(100,(trade.dir==="LONG"?price-trade.stop:trade.stop-price)/totalRange*100)):50;
  let advice=null;
  if(isOpen&&serverData){
    const reg=serverData.regime,sp=serverData.spot,hvl=serverData.hvl,gex=serverData.total_net_gex;
    const bull=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(reg)&&sp>hvl&&gex>0;
    const bear=["BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK"].includes(reg)&&sp<hvl&&gex<0;
    if(trade.dir==="LONG") advice=bull?{c:C.green,t:"✓ Devam Et — "+reg.replace(/_/g," ")+" koşullar sağlam"}:bear?{c:C.red,t:"⚠ KAPAT — Rejim SHORT döndü"}:{c:C.gold,t:"⚡ Dikkatli — Koşullar zayıfladı"};
    else advice=bear?{c:C.green,t:"✓ Devam Et — SHORT koşullar sağlam"}:bull?{c:C.red,t:"⚠ KAPAT — Rejim LONG döndü"}:{c:C.gold,t:"⚡ Dikkatli"};
  }
  return(
    <div style={{background:C.card2,border:`1px solid ${isOpen?C.gold+"50":C.border}`,borderLeft:`3px solid ${isOpen?C.gold:pnlColor||C.border}`,borderRadius:8,padding:"12px 14px",transition:"all 0.2s"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:8}}>
        <div style={{display:"flex",gap:8,alignItems:"center",flexWrap:"wrap"}}>
          <span style={{color:dirColor,fontWeight:900,fontSize:13}}>{trade.dir==="LONG"?"▲":"▼"} {trade.dir}</span>
          <span style={{color:C.muted,fontSize:9.5}}>{trade.date}</span>
          {isOpen&&<span style={{color:C.gold,fontSize:8.5,background:`${C.gold}15`,border:`1px solid ${C.gold}30`,padding:"1px 7px",borderRadius:99}}>● AÇIK</span>}
          {trade.regime&&<span style={{color:C.purple,fontSize:8.5,background:`${C.purple}10`,border:`1px solid ${C.purple}20`,padding:"1px 7px",borderRadius:3}}>{trade.regime?.replace("_"," ")}</span>}
          {trade.signal&&<span style={{color:C.muted,fontSize:8.5}}>{trade.signal}</span>}
        </div>
        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          {!isOpen&&trade.pnl!=null&&(
            <div style={{textAlign:"right"}}>
              <div style={{color:pnlColor,fontWeight:900,fontSize:14,fontFamily:"monospace"}}>{fmtPnl(trade.pnl)}</div>
              {trade.rr!=null&&<div style={{color:pnlColor,fontSize:9.5}}>{trade.rr>0?"+":""}{trade.rr}R</div>}
            </div>
          )}
          {isOpen&&price&&serverData&&(()=>{
        const reg=serverData.regime,sp=serverData.spot,hvl=serverData.hvl,gex=serverData.total_net_gex;
        const bull=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(reg)&&sp>hvl&&gex>0;
        const bear=["BEARISH_VOLATILE","BEARISH_LOW_VOL"].includes(reg)&&sp<hvl&&gex<0;
        const advice=trade.dir==="LONG"?(bull?"✓ Devam Et — "+reg.replace("_"," ")+" Koşullar sağlam":bear?"⚠ KAPAT — Rejim SHORT'a döndü":"⚡ Dikkatli — Koşullar zayıfladı"):(bear?"✓ Devam Et — SHORT koşullar sağlam":bull?"⚠ KAPAT — Rejim LONG'a döndü":"⚡ Dikkatli");
        const adviceColor=advice.startsWith("✓")?C.green:advice.startsWith("⚠")?C.red:C.gold;
        return(<div style={{padding:"7px 10px",background:adviceColor+"10",border:"1px solid "+adviceColor+"30",borderLeft:"3px solid "+adviceColor,borderRadius:5,marginBottom:8,fontSize:10.5,color:C.text}}>{advice}</div>);
      })()}
      {isOpen&&liveUnrealized!=null&&(
        <div style={{marginBottom:10,padding:"12px",background:liveColor+"08",border:"1px solid "+liveColor+"30",borderRadius:8}}>
          <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:4}}>Anlık Kâr / Zarar</div>
          <div style={{color:liveColor,fontSize:32,fontWeight:900,fontFamily:"monospace",lineHeight:1}}>{liveUnrealized>=0?"+":""}{liveUnrealized.toFixed(0)} USD</div>
          <div style={{color:C.muted,fontSize:9.5,marginTop:2}}>@ {price?.toLocaleString("en-US",{maximumFractionDigits:0})} anlık fiyat · Giriş {trade.entry?.toLocaleString()}</div>
        </div>
      )}
      {isOpen&&price&&(
        <div style={{marginBottom:10}}>
          <div style={{position:"relative",height:8,background:C.dim,borderRadius:99,overflow:"hidden",marginBottom:4}}>
            <div style={{position:"absolute",left:0,top:0,height:"100%",width:progress+"%",background:"linear-gradient(90deg,"+C.red+"60,"+C.green+"80)",borderRadius:99}}/>
            <div style={{position:"absolute",left:progress+"%",top:-1,height:10,width:3,background:C.blue,transform:"translateX(-50%)",borderRadius:99}}/>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:9,color:C.muted}}>
            <span style={{color:C.red}}>Stop ${trade.stop?.toLocaleString()}</span>
            <span style={{color:C.blue,fontWeight:700}}>Şu an ${price?.toLocaleString("en-US",{maximumFractionDigits:0})}</span>
            <span style={{color:C.green}}>TP ${trade.tp?.toLocaleString()}</span>
          </div>
        </div>
      )}
      {advice&&<div style={{marginBottom:8,padding:"7px 10px",background:advice.c+"10",border:"1px solid "+advice.c+"30",borderLeft:"3px solid "+advice.c,borderRadius:5,fontSize:10.5,color:C.text}}>{advice.t}</div>}
      {isOpen&&liveUnrealized!=null&&(
            <div style={{textAlign:"right"}}>
              <div style={{color:liveColor,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{liveUnrealized>0?"+":""}{liveUnrealized.toFixed(0)} <span style={{fontSize:9}}>live</span></div>
              <div style={{color:C.blue,fontSize:9}}>@{fmtK(price)}</div>
            </div>
          )}
          <button onClick={()=>onDelete(trade.id)} style={{background:"transparent",border:`1px solid ${C.border}`,color:C.muted,padding:"2px 8px",borderRadius:4,cursor:"pointer",fontSize:9}}>✕</button>
        </div>
      </div>

      <div style={{display:"flex",gap:20,fontSize:10,flexWrap:"wrap",marginBottom:8}}>
        <span>Giriş: <span style={{color:C.text,fontWeight:700,fontFamily:"monospace"}}>{fmtK(trade.entry)}</span></span>
        <span>Stop: <span style={{color:C.red,fontFamily:"monospace"}}>{fmtK(trade.stop)}</span></span>
        <span>TP: <span style={{color:C.green,fontFamily:"monospace"}}>{fmtK(trade.tp)}</span></span>
        <span>Lot: <span style={{color:C.muted,fontFamily:"monospace"}}>{trade.size} BTC</span></span>
        {!isOpen&&trade.exitPrice&&<span>Çıkış: <span style={{color:C.text,fontFamily:"monospace"}}>{fmtK(trade.exitPrice)}</span></span>}
        {!isOpen&&trade.exitDate&&<span style={{color:C.muted}}>{trade.exitDate}</span>}
        {trade.partialClosed&&<span style={{color:C.gold}}>◆ %50 Kısmi</span>}
      </div>

      {/* Risk/Reward görsel */}
      {isOpen&&(
        <div style={{marginBottom:8}}>
          <div style={{position:"relative",height:6,background:C.dim,borderRadius:99,overflow:"hidden"}}>
            {price&&(()=>{
              const total=Math.abs(trade.tp-trade.stop);
              if(total===0) return null;
              const progress=clamp((price-trade.stop)/(trade.tp-trade.stop)*100,0,100);
              const stopPct=0;
              const tpPct=100;
              return(<>
                <div style={{position:"absolute",left:`${progress}%`,top:0,height:"100%",width:2,background:C.blue,transform:"translateX(-50%)"}}/>
                <div style={{position:"absolute",left:0,top:0,height:"100%",width:`${progress}%`,background:`${C.green}40`}}/>
              </>);
            })()}
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:8.5,marginTop:2}}>
            <span style={{color:C.red}}>Stop {fmtK(trade.stop)}</span>
            <span style={{color:C.blue}}>Şu an {fmtK(price)}</span>
            <span style={{color:C.green}}>TP {fmtK(trade.tp)}</span>
          </div>
        </div>
      )}

      {trade.notes&&<div style={{color:C.muted,fontSize:9.5,fontStyle:"italic",borderTop:`1px solid ${C.border}`,paddingTop:6,marginBottom:isOpen?8:0,lineHeight:1.5}}>{trade.notes}</div>}

      {isOpen&&(
        <div style={{display:"flex",gap:7,alignItems:"center",flexWrap:"wrap"}}>
          <input type="number" value={exitVal} onChange={e=>setExitVal(e.target.value)} placeholder="Çıkış fiyatı..."
            style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:4,padding:"5px 8px",color:C.text,fontFamily:"monospace",fontSize:11,width:130}}/>
          {price&&<button onClick={()=>setExitVal(price.toFixed(0))} style={{background:`${C.blue}15`,border:`1px solid ${C.blue}30`,color:C.blue,padding:"5px 10px",borderRadius:4,cursor:"pointer",fontSize:9.5}}>Market {fmtK(price)}</button>}
          <button onClick={()=>onClose(trade.id,exitVal||price)} style={{background:`${C.green}15`,border:`1px solid ${C.green}40`,color:C.green,padding:"5px 14px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:10.5,fontWeight:700}}>✓ Kapat</button>
        </div>
      )}
    </div>
  );
}

// ── MAIN JOURNAL ──────────────────────────────────────────────────
export default function Journal(){
  const [trades,setTrades]=useState([]);
  const [price,setPrice]=useState(null);
  const [serverData,setServerData]=useState(null);
  const [showForm,setShowForm]=useState(false);
  const [form,setForm]=useState({dir:"LONG",entry:"",stop:"",tp:"",size:"",notes:"",regime:"",signal:""});
  const [filter,setFilter]=useState("ALL");
  const [sortBy,setSortBy]=useState("date");

  const syncFromServer=useCallback(async()=>{
    try{
      const r=await fetch(SERVER_URL+"/trades");
      if(!r.ok) return;
      const st=await r.json();
      if(Array.isArray(st)&&st.length>0){setTrades(st);saveTrades(st);}
    }catch{}
  },[]);

  useEffect(()=>{
    setTrades(loadTrades());
    fetchPrice().then(p=>p&&setPrice(p));
    syncFromServer();
    fetchServerData().then(d=>d&&setServerData(d));
    const i1=setInterval(()=>fetchPrice().then(p=>p&&setPrice(p)),15000);
    const i2=setInterval(()=>{syncFromServer();fetchServerData().then(d=>d&&setServerData(d));},60000);
    return()=>{clearInterval(i1);clearInterval(i2);};
  },[]);

  const closed=trades.filter(t=>t.status==="CLOSED");
  const open=trades.filter(t=>t.status==="OPEN");
  const totalPnl=closed.reduce((a,t)=>a+(t.pnl||0),0);
  const wins=closed.filter(t=>(t.pnl||0)>0);
  const losses=closed.filter(t=>(t.pnl||0)<0);
  const equity=INITIAL_CAPITAL+totalPnl;
  const winRate=closed.length?wins.length/closed.length*100:0;
  const avgWin=wins.length?wins.reduce((a,t)=>a+(t.pnl||0),0)/wins.length:0;
  const avgLoss=losses.length?Math.abs(losses.reduce((a,t)=>a+(t.pnl||0),0)/losses.length):1;
  const pf=losses.length&&avgLoss?Math.abs(wins.reduce((a,t)=>a+(t.pnl||0),0))/Math.abs(losses.reduce((a,t)=>a+(t.pnl||0),0)):0;
  const avgRR=closed.length?closed.filter(t=>t.rr!=null).reduce((a,t)=>a+(t.rr||0),0)/(closed.filter(t=>t.rr!=null).length||1):0;
  const expectancy=((winRate/100)*avgWin-(1-winRate/100)*avgLoss);

  const addTrade=()=>{
    if(!form.entry||!form.stop) return;
    const entry=+form.entry,stop=+form.stop;
    const tp=form.tp?+form.tp:(form.dir==="LONG"?entry+(entry-stop)*RR:entry-(stop-entry)*RR);
    const size=form.size?+form.size:(INITIAL_CAPITAL*RISK_PCT)/Math.abs(entry-stop);
    const t={id:Date.now(),date:new Date().toISOString().slice(0,16).replace("T"," "),dir:form.dir,entry,stop,tp,size:+size.toFixed(4),notes:form.notes,regime:form.regime,signal:form.signal,status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,partialClosed:false};
    const next=[t,...trades];setTrades(next);saveTrades(next);
    setShowForm(false);setForm({dir:"LONG",entry:"",stop:"",tp:"",size:"",notes:"",regime:"",signal:""});
  };

  const closeTrade=(id,exitPrice)=>{
    const next=trades.map(t=>{
      if(t.id!==id) return t;
      const ep=+exitPrice;
      const raw=t.dir==="LONG"?(ep-t.entry)*t.size:(t.entry-ep)*t.size;
      const rr=t.dir==="LONG"?(ep-t.entry)/(t.entry-t.stop):(t.entry-ep)/(t.stop-t.entry);
      return{...t,status:"CLOSED",exitPrice:ep,exitDate:new Date().toISOString().slice(0,16).replace("T"," "),pnl:+raw.toFixed(2),rr:+rr.toFixed(2)};
    });
    setTrades(next);saveTrades(next);
  };

  const deleteTrade=id=>{const next=trades.filter(t=>t.id!==id);setTrades(next);saveTrades(next);};

  const filtered=trades.filter(t=>filter==="ALL"?true:t.status===filter);

  const Inp=({label,field,placeholder,type="number"})=>(
    <div>
      <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:3}}>{label}</div>
      <input type={type} value={form[field]} placeholder={placeholder} onChange={e=>setForm(f=>({...f,[field]:e.target.value}))}
        style={{width:"100%",background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"6px 8px",color:C.text,fontFamily:"monospace",fontSize:11,boxSizing:"border-box"}}/>
    </div>
  );

  return(
    <div style={{background:C.bg,minHeight:"100vh",color:C.text,fontFamily:"'JetBrains Mono','Fira Code',monospace",fontSize:12.5}}>

      {/* Header */}
      <div style={{background:"#040609",borderBottom:`1px solid ${C.border}`,padding:"10px 20px",display:"flex",alignItems:"center",justifyContent:"space-between",position:"sticky",top:0,zIndex:100}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{color:C.gold,fontWeight:900,fontSize:13}}>◎ G-DIVE JOURNAL</span>
          <span style={{color:C.border2,fontSize:10}}>|</span>
          <span style={{color:C.muted,fontSize:10}}>BTC/USDT Trade Takip · ${INITIAL_CAPITAL.toLocaleString()} Başlangıç</span>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          {price&&<span style={{color:C.blue,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>{`$${price.toLocaleString("en-US",{maximumFractionDigits:0})}`}</span>}
          <button onClick={()=>setShowForm(!showForm)} style={{background:showForm?`${C.gold}20`:"transparent",border:`1px solid ${showForm?C.gold:C.border}`,color:showForm?C.gold:C.muted,padding:"4px 14px",borderRadius:5,cursor:"pointer",fontSize:10.5}}>
            {showForm?"✕ İptal":"+ Yeni Trade"}
          </button>
        </div>
      </div>

      <div style={{padding:"16px 20px",display:"flex",flexDirection:"column",gap:14}}>

        {/* Stats Grid */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:10}}>
          {[
            {l:"Sermaye",v:fmtK(equity),c:equity>=INITIAL_CAPITAL?C.green:C.red,sub:fmtPct((equity-INITIAL_CAPITAL)/INITIAL_CAPITAL*100)+" toplam"},
            {l:"Toplam P&L",v:fmtPnl(totalPnl),c:totalPnl>=0?C.green:C.red,sub:`${closed.length} kapatılmış trade`},
            {l:"Win Rate",v:`${winRate.toFixed(0)}%`,c:winRate>=55?C.green:winRate>=45?C.gold:C.red,sub:`${wins.length}W / ${losses.length}L`},
            {l:"Profit Factor",v:`${pf.toFixed(2)}×`,c:pf>=1.5?C.green:pf>=1?C.gold:C.red,sub:`Avg Win $${avgWin.toFixed(0)}`},
            {l:"Beklenti",v:(expectancy>=0?"+":"")+expectancy.toFixed(0)+"/trade",c:expectancy>=0?C.green:C.red,sub:`Avg R:R ${avgRR.toFixed(2)}`},
          ].map((s,i)=>(
            <div key={i} style={{background:C.card,border:`1px solid ${C.border}`,borderTop:`2px solid ${s.c}`,borderRadius:9,padding:"12px 14px"}}>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:4}}>{s.l}</div>
              <div style={{color:s.c,fontSize:20,fontWeight:900,fontFamily:"monospace",lineHeight:1,marginBottom:2}}>{s.v}</div>
              <div style={{color:C.muted,fontSize:9}}>{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Equity Curve */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:10,padding:"14px 16px"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
            <div style={{color:C.muted,fontSize:9.5,textTransform:"uppercase",letterSpacing:"0.08em"}}>Equity Curve</div>
            <div style={{display:"flex",gap:16,fontSize:10}}>
              <span><span style={{color:C.green}}>▲</span> {wins.length} Kazanç Avg +${avgWin.toFixed(0)}</span>
              <span><span style={{color:C.red}}>▼</span> {losses.length} Kayıp Avg -${avgLoss.toFixed(0)}</span>
            </div>
          </div>
          <EquityCurve trades={trades}/>
          <div style={{marginTop:6}}>
            <WinLossBar wins={wins.length} total={closed.length}/>
            <div style={{display:"flex",justifyContent:"space-between",fontSize:8.5,marginTop:2}}>
              <span style={{color:C.green}}>{winRate.toFixed(0)}% Kazanma</span>
              <span style={{color:C.red}}>{(100-winRate).toFixed(0)}% Kayıp</span>
            </div>
          </div>
        </div>

        {/* Açık Pozisyonlar */}
        {open.length>0&&(
          <div style={{background:C.card,border:`1px solid ${C.gold}30`,borderTop:`2px solid ${C.gold}`,borderRadius:10,padding:"14px 16px"}}>
            <div style={{color:C.gold,fontSize:9.5,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>● Açık Pozisyonlar — {open.length}</div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              {open.map(t=><OpenCard key={t.id} trade={t} price={price} sData={sData||serverData} onClose={closeTrade} onDelete={deleteTrade}/>)}
            </div>
          </div>
        )}

        {/* Yeni Trade Formu */}
        {showForm&&(
          <div style={{background:C.card,border:`1px solid ${C.gold}40`,borderTop:`2px solid ${C.gold}`,borderRadius:10,padding:"16px 18px"}}>
            <div style={{color:C.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:12}}>Yeni Trade</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:10,marginBottom:10}}>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>Yön</div>
                <div style={{display:"flex",gap:6}}>
                  {["LONG","SHORT"].map(d=>(
                    <button key={d} onClick={()=>setForm(f=>({...f,dir:d}))} style={{flex:1,background:form.dir===d?(d==="LONG"?`${C.green}15`:`${C.red}15`):"transparent",border:`1px solid ${form.dir===d?(d==="LONG"?C.green:C.red):C.border}`,color:form.dir===d?(d==="LONG"?C.green:C.red):C.muted,padding:"6px",borderRadius:5,cursor:"pointer",fontFamily:"monospace",fontSize:10.5,fontWeight:700}}>
                      {d==="LONG"?"▲ LONG":"▼ SHORT"}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>Giriş Fiyatı</div>
                <div style={{display:"flex",gap:4}}>
                  <input type="number" value={form.entry} placeholder={price?.toFixed(0)} onChange={e=>setForm(f=>({...f,entry:e.target.value}))}
                    style={{flex:1,background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"6px 8px",color:C.text,fontFamily:"monospace",fontSize:11}}/>
                  <button onClick={()=>price&&setForm(f=>({...f,entry:price.toFixed(0)}))} style={{background:`${C.blue}15`,border:`1px solid ${C.blue}30`,color:C.blue,padding:"6px 8px",borderRadius:5,cursor:"pointer",fontSize:10}}>↑</button>
                </div>
              </div>
              <Inp label="Stop Loss" field="stop" placeholder="örn: 67000"/>
              <Inp label="TP (opsiyonel)" field="tp" placeholder={`auto: ${RR}:1 RR`}/>
              <Inp label="Lot (BTC)" field="size" placeholder="auto: 2% risk"/>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>Regime</div>
                <input type="text" value={form.regime} placeholder="örn: BULLISH_HIGH_VOL" onChange={e=>setForm(f=>({...f,regime:e.target.value}))}
                  style={{width:"100%",background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"6px 8px",color:C.text,fontFamily:"monospace",fontSize:10.5,boxSizing:"border-box"}}/>
              </div>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>Sinyal</div>
                <input type="text" value={form.signal} placeholder="örn: Konfluens +5" onChange={e=>setForm(f=>({...f,signal:e.target.value}))}
                  style={{width:"100%",background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"6px 8px",color:C.text,fontFamily:"monospace",fontSize:10.5,boxSizing:"border-box"}}/>
              </div>
            </div>
            <div style={{marginBottom:10}}>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>Notlar</div>
              <textarea value={form.notes} onChange={e=>setForm(f=>({...f,notes:e.target.value}))} placeholder="Trade gerekçesi, piyasa durumu, plan..."
                style={{width:"100%",background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"7px 9px",color:C.text,fontFamily:"monospace",fontSize:10.5,resize:"vertical",minHeight:64,boxSizing:"border-box"}}/>
            </div>
            {form.entry&&form.stop&&(
              <div style={{display:"flex",gap:16,padding:"8px 12px",background:C.card2,borderRadius:6,fontSize:10.5,marginBottom:10}}>
                <span>Risk: <span style={{color:C.orange,fontWeight:700}}>~${(INITIAL_CAPITAL*RISK_PCT).toFixed(0)}</span></span>
                <span>TP Hedef: <span style={{color:C.green,fontWeight:700}}>~${(INITIAL_CAPITAL*RISK_PCT*RR).toFixed(0)}</span></span>
                <span>R:R: <span style={{color:C.gold,fontWeight:700}}>{RR}:1</span></span>
                <span>Lot: <span style={{color:C.blue,fontWeight:700}}>{((INITIAL_CAPITAL*RISK_PCT)/Math.abs(+form.entry-+form.stop)).toFixed(4)} BTC</span></span>
              </div>
            )}
            <button onClick={addTrade} style={{background:C.gold,border:"none",color:"#000",padding:"8px 24px",borderRadius:5,cursor:"pointer",fontFamily:"monospace",fontSize:12,fontWeight:900}}>✓ Trade Ekle</button>
          </div>
        )}

        {/* Trade History */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:10,padding:"14px 16px"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
            <div style={{color:C.muted,fontSize:9.5,textTransform:"uppercase",letterSpacing:"0.08em"}}>Trade Geçmişi — {filtered.length} kayıt</div>
            <div style={{display:"flex",gap:6}}>
              {["ALL","OPEN","CLOSED"].map(f=>(
                <button key={f} onClick={()=>setFilter(f)} style={{background:filter===f?`${C.blue}15`:"transparent",border:`1px solid ${filter===f?C.blue:C.border}`,color:filter===f?C.blue:C.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:9.5}}>
                  {f} {f==="ALL"?trades.length:f==="OPEN"?open.length:closed.length}
                </button>
              ))}
            </div>
          </div>

          {filtered.length===0&&(
            <div style={{color:C.muted,fontSize:11,textAlign:"center",padding:32}}>
              {filter==="OPEN"?"Açık trade yok":"Trade geçmişi boş"}
            </div>
          )}

          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            {filtered.filter(t=>t.status!=="OPEN").map(t=>(
              <TradeRow key={t.id} trade={t} price={price} serverData={serverData} onClose={closeTrade} onDelete={deleteTrade}/>
            ))}
          </div>
        </div>

        <div style={{borderTop:`1px solid ${C.border}`,paddingTop:8,display:"flex",justifyContent:"space-between",fontSize:9,color:C.dim}}>
          <span>G-DIVE Journal · ${INITIAL_CAPITAL.toLocaleString()} sermaye · {RISK_PCT*100}% risk · {RR}:1 RR · 2× kaldıraç</span>
          <span>Veriler tarayıcıda ve Railway sunucusunda saklanır</span>
        </div>
      </div>
    </div>
  );
}
