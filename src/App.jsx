import { useState, useEffect, useCallback } from "react";

const SERVER_URL = window.location.hostname === "localhost" ? "http://localhost:7432" : "https://web-production-909e6.up.railway.app";
const T = { bg:"#0d1117",card:"#161b22",card2:"#1c2128",border:"#30363d",text:"#e6edf3",muted:"#7d8590",green:"#3fb950",red:"#f85149",orange:"#f78166",gold:"#e3b341",blue:"#79c0ff",purple:"#bc8cff" };

const DEMO = {
  spot:68129,ts:"2026-03-06 15:59 EST",total_net_gex:3055.2,
  put_support:60000,call_resistance:75000,hvl:67000,
  put_support_0dte:68500,call_resistance_0dte:71000,
  front_iv:50.20,iv_rank:58.43,term_shape:"CONTANGO",
  pc_ratio:0.68,hv_30d:67.97,option_score:5,vol_score:5,momentum_score:3,
  gamma_regime:"LONG_GAMMA",regime:"BULLISH_HIGH_VOL",long_ok:true,short_ok:false,
  term_ivs:[
    {expiry:"0DTE",iv:55.2},{expiry:"7MAR",iv:52.1},{expiry:"14MAR",iv:50.8},
    {expiry:"21MAR",iv:50.2},{expiry:"28MAR",iv:49.8},{expiry:"25APR",iv:49.1},
    {expiry:"27JUN",iv:48.5},{expiry:"26SEP",iv:47.9},
  ],
  call_walls:[75000,71000,80000,85000],put_walls:[60000,68500,65000,58000],
  pos_gex_nodes:[{strike:75000,net_gex:28.3},{strike:70000,net_gex:18.5},{strike:80000,net_gex:12.1},{strike:72000,net_gex:9.4}],
  neg_gex_nodes:[{strike:60000,net_gex:-25.8},{strike:65000,net_gex:-18.4},{strike:62000,net_gex:-12.1},{strike:66000,net_gex:-8.9}],
  n_contracts:8247,_source:"demo",
};

const fmt=(n)=>n?.toLocaleString("en-US",{maximumFractionDigits:0});
const fmtK=(n)=>`$${fmt(n)}`;
const pct=(n)=>`${(+n).toFixed(2)}%`;
const scoreColor=(s)=>s>=4?T.green:s>=3?T.gold:s>=2?"#e09b39":T.red;
const scoreLabel=(s)=>["Very Low","Low","Neutral","High","Very High","Very High"][Math.min(+s,5)];

// ── SVG CHARTS ────────────────────────────────────────────────────

function GEXChart({ data, spot, hvl, callRes, putSup }) {
  const W=620, H=320, PL=42, PR=20, PT=8, PB=8;
  const cw=W-PL-PR, ch=H-PT-PB;
  const maxV=Math.max(32,...data.map(r=>Math.abs(r.gex)));
  const xScale=v=>(v/maxV)*(cw/2)+cw/2;
  const barH=Math.max(3, ch/data.length - 2);
  const rowH=ch/data.length;
  const spotIdx=data.findIndex(r=>r.label===`${Math.round(spot/1000)}K`);
  const hvlIdx=data.findIndex(r=>r.label===`${Math.round(hvl/1000)}K`);
  const crIdx=data.findIndex(r=>r.label===`${Math.round(callRes/1000)}K`);
  const psIdx=data.findIndex(r=>r.label===`${Math.round(putSup/1000)}K`);
  const refY=(idx)=>idx>=0?PT+idx*rowH+rowH/2:null;
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      {/* Grid */}
      {[-3,-2,-1,0,1,2,3].map(v=>{
        const x=PL+xScale(v*(maxV/3));
        return <line key={v} x1={x} y1={PT} x2={x} y2={H-PB} stroke={T.border} strokeWidth={v===0?1.5:0.5} strokeDasharray={v===0?"":"3,3"}/>;
      })}
      {/* X axis labels */}
      {[-2,-1,0,1,2].map(v=>{
        const x=PL+xScale(v*(maxV/2));
        return <text key={v} x={x} y={H} fill={T.muted} fontSize={8} textAnchor="middle">{v*(maxV/2).toFixed(0)}M</text>;
      })}
      {/* Bars */}
      {data.map((row,i)=>{
        const y=PT+i*rowH+(rowH-barH)/2;
        const x0=PL+cw/2;
        const barW=Math.abs(xScale(row.gex)-cw/2);
        const bx=row.gex>=0?x0:x0-barW;
        return(
          <g key={i}>
            <rect x={bx} y={y} width={barW} height={barH} fill={row.gex>=0?T.green:T.orange} opacity={0.88} rx={2}/>
            <text x={PL-4} y={PT+i*rowH+rowH/2+4} fill={T.muted} fontSize={9} textAnchor="end">{row.label}</text>
          </g>
        );
      })}
      {/* Reference lines */}
      {refY(spotIdx)&&<line x1={PL} y1={refY(spotIdx)} x2={W-PR} y2={refY(spotIdx)} stroke="rgba(230,237,243,0.6)" strokeWidth={1.5} strokeDasharray="5,3"/>}
      {refY(hvlIdx)&&<line x1={PL} y1={refY(hvlIdx)} x2={W-PR} y2={refY(hvlIdx)} stroke={T.gold} strokeWidth={1.5} strokeDasharray="5,3"/>}
      {refY(crIdx)&&<line x1={PL} y1={refY(crIdx)} x2={W-PR} y2={refY(crIdx)} stroke={T.green} strokeWidth={1.5} strokeDasharray="5,3"/>}
      {refY(psIdx)&&<line x1={PL} y1={refY(psIdx)} x2={W-PR} y2={refY(psIdx)} stroke={T.orange} strokeWidth={1.5} strokeDasharray="5,3"/>}
    </svg>
  );
}

function IVOIChart({ data, spot }) {
  const W=300, H=260, PL=38, PR=10, PT=8, PB=8;
  const cw=W-PL-PR, ch=H-PT-PB;
  const maxV=Math.max(...data.map(r=>Math.max(r.calls,r.puts)));
  const xScale=v=>(v/maxV)*cw;
  const rowH=ch/data.length;
  const barH=Math.max(2,(rowH-4)/2);
  const spotIdx=data.findIndex(r=>r.label===`${Math.round(spot/1000)}K`);
  const refY=spotIdx>=0?PT+spotIdx*rowH+rowH/2:null;
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      {data.map((row,i)=>{
        const y=PT+i*rowH;
        return(
          <g key={i}>
            <rect x={PL} y={y+(rowH-barH*2-2)/2} width={xScale(row.calls)} height={barH} fill={T.green} opacity={0.82} rx={1}/>
            <rect x={PL} y={y+(rowH-barH*2-2)/2+barH+2} width={xScale(row.puts)} height={barH} fill={T.orange} opacity={0.82} rx={1}/>
            <text x={PL-4} y={y+rowH/2+4} fill={T.muted} fontSize={9} textAnchor="end">{row.label}</text>
          </g>
        );
      })}
      {refY&&<line x1={PL} y1={refY} x2={W-PR} y2={refY} stroke="rgba(230,237,243,0.5)" strokeWidth={1} strokeDasharray="4,2"/>}
    </svg>
  );
}

function TermChart({ data }) {
  const W=300, H=260, PL=38, PR=16, PT=16, PB=24;
  const cw=W-PL-PR, ch=H-PT-PB;
  const ivs=data.map(d=>d.iv);
  const minIV=Math.min(...ivs)-1, maxIV=Math.max(...ivs)+1;
  const xScale=i=>PL+i*(cw/(data.length-1));
  const yScale=v=>PT+ch-(v-minIV)/(maxIV-minIV)*ch;
  const pts=data.map((d,i)=>`${xScale(i)},${yScale(d.iv)}`).join(" ");
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      {/* Grid */}
      {[0,1,2,3].map(i=>{
        const v=minIV+i*(maxIV-minIV)/3;
        const y=yScale(v);
        return <line key={i} x1={PL} y1={y} x2={W-PR} y2={y} stroke={T.border} strokeWidth={0.5} strokeDasharray="3,3"/>;
      })}
      {/* Y labels */}
      {[0,1,2,3].map(i=>{
        const v=minIV+i*(maxIV-minIV)/3;
        return <text key={i} x={PL-4} y={yScale(v)+4} fill={T.muted} fontSize={8} textAnchor="end">{v.toFixed(0)}%</text>;
      })}
      {/* Line */}
      <polyline points={pts} fill="none" stroke={T.blue} strokeWidth={2.5}/>
      {/* Dots + X labels */}
      {data.map((d,i)=>(
        <g key={i}>
          <circle cx={xScale(i)} cy={yScale(d.iv)} r={3.5} fill={T.blue}/>
          <text x={xScale(i)} y={H-6} fill={T.muted} fontSize={8} textAnchor="middle">{d.expiry}</text>
        </g>
      ))}
    </svg>
  );
}

// ── FETCH ─────────────────────────────────────────────────────────
async function fetchLive(){
  try{const ctrl=new AbortController();setTimeout(()=>ctrl.abort(),3000);const h=await fetch(`${SERVER_URL}/health`,{signal:ctrl.signal});if(!h.ok)return null;const health=await h.json();if(!health.ok)return null;const r=await fetch(`${SERVER_URL}/data`);if(!r.ok)return null;const j=await r.json();return j.spot>10000?{...j,_source:"server"}:null;}catch{return null;}
}
async function fetchBinancePrice(){try{const r=await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");if(!r.ok)return null;return +(await r.json()).price;}catch{return null;}}
const BINANCE="https://api.binance.com/api/v3/klines";
async function fetchOHLCV(interval="4h",limit=120){
  try{const ctrl=new AbortController();const tid=setTimeout(()=>ctrl.abort(),6000);const r=await fetch(`${BINANCE}?symbol=BTCUSDT&interval=${interval}&limit=${limit}`,{signal:ctrl.signal});clearTimeout(tid);if(!r.ok)return null;const raw=await r.json();return raw.map(k=>({t:k[0],o:+k[1],h:+k[2],l:+k[3],c:+k[4],v:+k[5]}));}catch{return null;}
}
function calcEMA(c,p){const k=2/(p+1);let e=c[0];return c.map(v=>{e=v*k+e*(1-k);return e;});}
function calcRSI(c,p=14){let g=0,l=0;for(let i=1;i<=p;i++){const d=c[i]-c[i-1];d>=0?g+=d:l-=d;}let ag=g/p,al=l/p;const r=new Array(p).fill(null);r.push(al===0?100:100-100/(1+ag/al));for(let i=p+1;i<c.length;i++){const d=c[i]-c[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;r.push(al===0?100:100-100/(1+ag/al));}return r;}
function calcMACD(c,f=12,s=26,sig=9){const ef=calcEMA(c,f),es=calcEMA(c,s),m=ef.map((v,i)=>v-es[i]),signal=calcEMA(m,sig);return{macd:m,signal,hist:m.map((v,i)=>v-signal[i])};}
function calcBB(c,p=20,mult=2){return c.map((_,i)=>{if(i<p-1)return null;const s=c.slice(i-p+1,i+1),mean=s.reduce((a,b)=>a+b,0)/p,std=Math.sqrt(s.reduce((a,b)=>a+(b-mean)**2,0)/p);return{upper:mean+mult*std,middle:mean,lower:mean-mult*std};});}
function analyzeCandles(candles){
  if(!candles||candles.length<40)return null;
  const closes=candles.map(c=>c.c),n=closes.length-1;
  const ema9=calcEMA(closes,9),ema21=calcEMA(closes,21),rsis=calcRSI(closes,14);
  const{macd,signal,hist}=calcMACD(closes);const bbs=calcBB(closes,20);
  const price=closes[n],rsi=rsis[n],bb=bbs[n],macdV=macd[n],sigV=signal[n],histV=hist[n],histPrev=hist[n-1];
  let score=0;const reasons=[];
  const ec=ema9[n]>ema21[n],ecp=ema9[n-1]>ema21[n-1];
  if(ec){score++;reasons.push({txt:`EMA9 > EMA21 (${ema9[n].toFixed(0)} > ${ema21[n].toFixed(0)})`,bull:true});}
  else{score--;reasons.push({txt:`EMA9 < EMA21 (${ema9[n].toFixed(0)} < ${ema21[n].toFixed(0)})`,bull:false});}
  if(ec&&!ecp)reasons.push({txt:"⚡ EMA Golden Cross!",bull:true,strong:true});
  if(!ec&&ecp)reasons.push({txt:"⚡ EMA Death Cross!",bull:false,strong:true});
  if(rsi>70){score--;reasons.push({txt:`RSI ${rsi.toFixed(1)} — Aşırı Alım`,bull:false});}
  else if(rsi<30){score++;reasons.push({txt:`RSI ${rsi.toFixed(1)} — Aşırı Satım`,bull:true});}
  else if(rsi>55){score++;reasons.push({txt:`RSI ${rsi.toFixed(1)} — Bullish`,bull:true});}
  else if(rsi<45){score--;reasons.push({txt:`RSI ${rsi.toFixed(1)} — Bearish`,bull:false});}
  else reasons.push({txt:`RSI ${rsi.toFixed(1)} — Nötr`,bull:null});
  if(macdV>sigV){score++;reasons.push({txt:`MACD +${histV.toFixed(1)} Bullish`,bull:true});}
  else{score--;reasons.push({txt:`MACD ${histV.toFixed(1)} Bearish`,bull:false});}
  if(bb){const bp=(price-bb.lower)/(bb.upper-bb.lower);
    if(bp>0.85){score--;reasons.push({txt:`BB Üst banda yakın`,bull:false});}
    else if(bp<0.15){score++;reasons.push({txt:`BB Alt banda yakın`,bull:true});}
    else if(bp>0.5){score++;reasons.push({txt:`BB Orta üstü`,bull:true});}}
  let sc,sl;
  if(score>=3){sc=T.green;sl="▲ GÜÇLÜ LONG";}
  else if(score>=1){sc="#58c76e";sl="▲ ZAYIF LONG";}
  else if(score<=-3){sc=T.red;sl="▼ GÜÇLÜ SHORT";}
  else if(score<=-1){sc=T.orange;sl="▼ ZAYIF SHORT";}
  else{sc=T.muted;sl="— BEKLE";}
  return{price,rsi,macdV,sigV,histV,ema9:ema9[n],ema21:ema21[n],bb,score,signal_color:sc,signal_label:sl,reasons};
}
function confluenceScore(t4,t1,opt){
  if(!t4)return null;
  let score=0;const items=[];
  score+=t4.score;items.push({src:"4H Teknik",val:t4.score});
  if(t1){score+=Math.round(t1.score*0.5);items.push({src:"1H Teknik",val:t1.score});}
  if(opt.total_net_gex>0){score++;items.push({src:"GEX POZİTİF",val:1});}else{score--;items.push({src:"GEX NEGATİF",val:-1});}
  if(opt.spot>opt.hvl){score++;items.push({src:"Spot > HVL",val:1});}else{score--;items.push({src:"Spot < HVL",val:-1});}
  const dc=(opt.call_resistance-opt.spot)/opt.spot*100;
  if(dc<3){score--;items.push({src:`Call Direnç Yakın (${dc.toFixed(1)}%)`,val:-1});}
  if(dc>8){score++;items.push({src:`Call Direnç Uzak (${dc.toFixed(1)}%)`,val:1});}
  let label,color;
  if(score>=5){label="▲ GÜÇLÜ LONG";color=T.green;}
  else if(score>=2){label="▲ ZAYIF LONG";color="#58c76e";}
  else if(score<=-5){label="▼ GÜÇLÜ SHORT";color=T.red;}
  else if(score<=-2){label="▼ ZAYIF SHORT";color=T.orange;}
  else{label="— NÖTR / BEKLE";color=T.muted;}
  return{score,label,color,items};
}

// ── UI ATOMS ──────────────────────────────────────────────────────
const Card=({children,style={},borderColor})=>(
  <div style={{background:T.card,border:`1px solid ${T.border}`,borderRadius:8,padding:"14px 16px",borderTop:borderColor?`3px solid ${borderColor}`:undefined,...style}}>{children}</div>
);
const ST=({children})=>(
  <div style={{color:T.muted,fontSize:10.5,letterSpacing:"0.08em",textTransform:"uppercase",marginBottom:10,fontWeight:600}}>{children}</div>
);
const KV=({label,value,color,highlight})=>(
  <div style={{padding:"9px 11px",borderRadius:6,background:highlight?`${color||T.blue}14`:T.card2,border:`1px solid ${highlight?(color||T.blue)+"60":T.border}`}}>
    <div style={{color:T.muted,fontSize:10,textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:3}}>{label}</div>
    <div style={{color:color||T.text,fontSize:17,fontWeight:700,fontFamily:"monospace"}}>{value}</div>
  </div>
);
const Chip=({label,value,color})=>(
  <div style={{display:"flex",flexDirection:"column",alignItems:"center"}}>
    <div style={{color:T.muted,fontSize:10,letterSpacing:"0.06em",textTransform:"uppercase",marginBottom:2}}>{label}</div>
    <div style={{color:color||T.text,fontSize:13,fontWeight:600,fontFamily:"monospace"}}>{value}</div>
  </div>
);
const QCard=({score,category,desc})=>{
  const c=scoreColor(score);const bg=score>=4?"#0d2c12":score>=3?"#2c2000":score<=1?"#2c0a08":"#1c1c00";
  return(<div style={{flex:1,background:bg,border:`1px solid ${c}40`,borderTop:`3px solid ${c}`,borderRadius:8,padding:"20px 18px",textAlign:"center"}}>
    <div style={{fontSize:64,fontWeight:900,color:c,lineHeight:1,marginBottom:4}}>{score}</div>
    <div style={{fontSize:15,color:c,fontWeight:700,marginBottom:6}}>{scoreLabel(score)}</div>
    <div style={{fontSize:10.5,color:T.muted,letterSpacing:"0.1em",textTransform:"uppercase",marginBottom:10,fontWeight:600}}>{category}</div>
    <div style={{fontSize:11.5,color:T.text,lineHeight:1.55,opacity:0.9}}>{desc}</div>
  </div>);
};

function TeknikSignal({optData, onConfluence}){
  const[t4,setT4]=useState(null);const[t1,setT1]=useState(null);
  const[loading,setLoading]=useState(true);const[error,setError]=useState(null);
  const[lastUpdate,setLastUpdate]=useState(null);const[tab,setTab]=useState("4h");
  const load=useCallback(async()=>{
    setLoading(true);setError(null);
    const[c4,c1]=await Promise.all([fetchOHLCV("4h",120),fetchOHLCV("1h",100)]);
    if(!c4&&!c1){setError("Binance API erişilemiyor");setLoading(false);return;}
    if(c4)setT4(analyzeCandles(c4));if(c1)setT1(analyzeCandles(c1));
    setLastUpdate(new Date().toLocaleTimeString("tr-TR"));setLoading(false);
  },[]);
  useEffect(()=>{load();const id=setInterval(load,5*60*1000);return()=>clearInterval(id);},[load]);
  const conf=confluenceScore(t4,t1,optData);const current=tab==="4h"?t4:t1;
  useEffect(()=>{if(conf&&onConfluence)onConfluence(conf);},[conf?.score]);
  const GB=({value,color,max=10})=>{const p=Math.min(100,Math.max(0,((value+max)/(max*2))*100));return(<div style={{height:6,background:T.card2,borderRadius:99,overflow:"hidden",marginTop:4}}><div style={{height:"100%",width:`${p}%`,background:color,borderRadius:99}}/></div>);};
  return(
    <Card borderColor={conf?conf.color:T.purple}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:12}}>
        <div>
          <ST>⚡ Teknik Sinyal — BTC/USDT · Binance Canlı</ST>
          {loading&&<div style={{color:T.muted,fontSize:11}}>⟳ Yükleniyor…</div>}
          {error&&<div style={{color:T.red,fontSize:11}}>✗ {error}</div>}
          {lastUpdate&&!loading&&<div style={{color:T.muted,fontSize:10}}>Son güncelleme: {lastUpdate}</div>}
        </div>
        <button onClick={load} disabled={loading} style={{background:"transparent",border:`1px solid ${T.border}`,color:T.muted,padding:"3px 10px",borderRadius:4,cursor:"pointer",fontSize:10}}>⟳ Yenile</button>
      </div>
      {!loading&&conf&&(
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12}}>
          <div style={{background:`${conf.color}0e`,border:`1px solid ${conf.color}40`,borderTop:`3px solid ${conf.color}`,borderRadius:8,padding:"14px 16px"}}>
            <div style={{color:T.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:6}}>Konfluens Skoru</div>
            <div style={{fontSize:32,fontWeight:900,color:conf.color,lineHeight:1,marginBottom:4}}>{conf.score>0?"+":""}{conf.score}</div>
            <div style={{fontSize:16,fontWeight:800,color:conf.color,marginBottom:10}}>{conf.label}</div>
            <GB value={conf.score} color={conf.color} max={10}/>
            <div style={{display:"flex",flexDirection:"column",gap:4,marginTop:12}}>
              {conf.items.map((it,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10,padding:"2px 0",borderBottom:`1px solid ${T.border}`}}><span style={{color:T.muted}}>{it.src}</span><span style={{color:it.val>0?T.green:it.val<0?T.red:T.muted,fontWeight:700}}>{it.val>0?"+":""}{it.val}</span></div>))}
            </div>
          </div>
          <div style={{gridColumn:"2 / 4",display:"flex",flexDirection:"column",gap:10}}>
            <div style={{display:"flex",gap:6}}>
              {["4h","1h"].map(tf=>(<button key={tf} onClick={()=>setTab(tf)} style={{background:tab===tf?`${T.purple}30`:"transparent",border:`1px solid ${tab===tf?T.purple:T.border}`,color:tab===tf?T.purple:T.muted,padding:"3px 16px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:11}}>{tf.toUpperCase()} {tf==="4h"?t4?.signal_label:t1?.signal_label}</button>))}
            </div>
            {current&&(<div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
              <div style={{display:"flex",flexDirection:"column",gap:6}}>
                {[{label:"EMA 9",val:current.ema9?.toFixed(0),color:current.ema9>current.ema21?T.green:T.red},{label:"EMA 21",val:current.ema21?.toFixed(0),color:T.muted},{label:"RSI 14",val:current.rsi?.toFixed(1),color:current.rsi>70?T.red:current.rsi<30?T.green:current.rsi>50?"#58c76e":T.orange},{label:"MACD",val:current.macdV?.toFixed(1),color:current.macdV>current.sigV?T.green:T.red},{label:"Signal",val:current.sigV?.toFixed(1),color:T.muted},{label:"Hist",val:current.histV>0?`+${current.histV.toFixed(1)}`:current.histV?.toFixed(1),color:current.histV>0?T.green:T.red},...(current.bb?[{label:"BB Üst",val:current.bb.upper?.toFixed(0),color:T.muted},{label:"BB Orta",val:current.bb.middle?.toFixed(0),color:T.muted},{label:"BB Alt",val:current.bb.lower?.toFixed(0),color:T.muted}]:[])].map((row,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 8px",background:T.card2,border:`1px solid ${T.border}`,borderRadius:4}}><span style={{color:T.muted,fontSize:10,textTransform:"uppercase"}}>{row.label}</span><span style={{color:row.color,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{row.val}</span></div>))}
              </div>
              <div style={{display:"flex",flexDirection:"column",gap:4}}>
                <div style={{color:T.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:2}}>Sinyal Gerekçeleri</div>
                {current.reasons.map((r,i)=>(<div key={i} style={{display:"flex",alignItems:"center",gap:8,padding:"4px 8px",borderRadius:4,background:r.bull===true?"#0d2c1228":r.bull===false?"#2c0a0828":`${T.border}20`}}><span style={{fontSize:10,color:r.bull===true?T.green:r.bull===false?T.red:T.muted}}>{r.bull===true?"▲":r.bull===false?"▼":"●"}</span><span style={{fontSize:10.5,color:r.strong?T.text:T.muted}}>{r.txt}</span></div>))}
                <div style={{marginTop:8,padding:"8px 10px",background:`${current.signal_color}12`,border:`1px solid ${current.signal_color}40`,borderRadius:6}}>
                  <div style={{color:T.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:3}}>{tab.toUpperCase()} Sinyal</div>
                  <div style={{color:current.signal_color,fontWeight:900,fontSize:20}}>{current.signal_label}</div>
                  <GB value={current.score} color={current.signal_color} max={4}/>
                </div>
              </div>
            </div>)}
          </div>
        </div>
      )}
    </Card>
  );
}

function buildGEXData(d){
  const nm={};[...(d.pos_gex_nodes||[]),...(d.neg_gex_nodes||[])].forEach(n=>{nm[n.strike]=n.net_gex;});
  const spot=d.spot,lo=Math.ceil((spot*0.72)/1000)*1000,hi=Math.ceil((spot*1.28)/1000)*1000;
  const rows=[];
  for(let s=hi;s>=lo;s-=1000){const k=nm[s];let gex=k!==undefined?k:(s<spot?-6*Math.exp(-Math.abs((s-spot)/spot)*6):5*Math.exp(-Math.abs((s-spot)/spot)*7));rows.push({strike:s,label:`${(s/1000).toFixed(0)}K`,gex:Math.round(gex*10)/10});}
  return rows;
}
function buildIVOIData(d){
  const{spot,call_walls=[],put_walls=[]}=d;
  const lo=Math.ceil((spot*0.78)/1000)*1000,hi=Math.ceil((spot*1.22)/1000)*1000;const rows=[];
  for(let s=hi;s>=lo;s-=1000){const dist=Math.abs(s-spot)/spot,base=Math.max(5,280*Math.exp(-dist*9));rows.push({label:`${(s/1000).toFixed(0)}K`,calls:Math.round(base*(call_walls.includes(s)?3.8:s>spot?1.1:0.45)),puts:Math.round(base*(put_walls.includes(s)?3.8:s<spot?1.1:0.45))});}
  return rows;
}

const REGIME_INFO={IDEAL_LONG:{txt:"İDEAL LONG",color:T.green,sub:"GEX pozitif · opsiyonlar güçlü destek"},BULLISH_HIGH_VOL:{txt:"BULLISH HIGH VOL",color:T.gold,sub:"Long açılabilir, stop sıkı · vol yüksek"},BEARISH_VOLATILE:{txt:"BEARISH VOLATİL",color:T.red,sub:"Short setup · yüksek volatilite"},BEARISH_LOW_VOL:{txt:"BEARISH SIKIŞ",color:T.red,sub:"Short setup · düşük vol"},HIGH_RISK:{txt:"⚠ YÜKSEK RİSK",color:T.red,sub:"Short gamma + vol · kill-switch"},NEUTRAL:{txt:"NÖTR / BEKLE",color:T.muted,sub:"Net yön yok · bekleme modu"}};

export default function App(){
  const[data,setData]=useState(DEMO);const[live,setLive]=useState(false);const[busy,setBusy]=useState(false);const[clock,setClock]=useState("");const[confScore,setConfScore]=useState(null);
  const refresh=useCallback(async()=>{setBusy(true);const[d,bp]=await Promise.all([fetchLive(),fetchBinancePrice()]);if(d){setData(d);setLive(true);}else{setData(bp?{...DEMO,spot:bp}:DEMO);setLive(false);}setClock(new Date().toLocaleTimeString("tr-TR"));setBusy(false);},[]);

  // Auto-trade: koşullar sağlanınca journal'a otomatik kaydet
  useEffect(()=>{
    if(!data||data._source==="demo")return;
    const regime=data.regime;
    const bullish=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(regime);
    const aboveHVL=data.spot>data.hvl;
    const gexPos=data.total_net_gex>0;
    if(!bullish||!aboveHVL||!gexPos)return;
      const confOK=confScore&&confScore.score>=2;
      const ivOK=(data.iv_rank||0)<75;
      if(!confOK||!ivOK)return;
    // Bugün zaten trade var mı?
    try{
      const trades=JSON.parse(localStorage.getItem("gdive:journal:v2")||"[]");
      const today=new Date().toISOString().slice(0,10);
      const todayTrade=trades.find(t=>t.date&&t.date.startsWith(today)&&t.status==="OPEN");
      if(todayTrade)return;
      // Yeni trade ekle
      const entry=data.spot;
      const stop=data.put_support;
      const tp=data.call_resistance;
      const riskAmt=200; // $200 risk
      const size=+(riskAmt/Math.abs(entry-stop)).toFixed(4);
      const trade={
        id:Date.now(),
        date:new Date().toISOString().slice(0,16).replace("T"," "),
        dir:"LONG",entry,stop,tp,size,
        regime,
        signal:`Auto · Konfluens · ${data.total_net_gex>0?"GEX+":"GEX-"} · ${regime}`,
        notes:`Otomatik sinyal. Spot ${entry} > HVL ${data.hvl}. Net GEX: ${data.total_net_gex}M. IV: ${data.front_iv}%`,
        status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,
      };
      const next=[trade,...trades];
      localStorage.setItem("gdive:journal:v2",JSON.stringify(next));
      alert("G-DIVE Auto Trade - LONG @ $" + entry + " Stop: $" + stop + " TP: $" + tp);
    }catch(e){console.error("autotrade err",e);}
  },[data,confScore]);
  useEffect(()=>{refresh();const id=setInterval(refresh,4*60*1000);return()=>clearInterval(id);},[refresh]);
  const d=data,gammaPos=d.total_net_gex>0;
  const gexRows=buildGEXData(d),ivoiRows=buildIVOIData(d);
  const regime=REGIME_INFO[d.regime]||REGIME_INFO.NEUTRAL;
  const expMove=((d.front_iv||50)/19.1).toFixed(2);
  const distHVL=(Math.abs(d.spot-d.hvl)/d.spot*100).toFixed(2);
  return(
    <div style={{background:T.bg,minHeight:"100vh",color:T.text,fontFamily:"'Fira Code','JetBrains Mono',monospace",fontSize:13}}>
      <div style={{background:"#010409",borderBottom:`1px solid ${T.border}`,padding:"9px 20px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:18}}>
          <span style={{color:T.gold,fontWeight:900,fontSize:14}}>◆ G-DIVE OIM</span>
          <span style={{color:T.muted,fontSize:11}}>BTC / USD · Deribit · Options Intelligence Module</span>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:14}}>
          <span style={{fontSize:11,color:live?T.green:T.gold}}>{busy?"⟳ Yükleniyor…":live?`● CANLI · ${clock}`:`◆ DEMO · ${clock}`}</span>
          <button onClick={refresh} disabled={busy} style={{background:"transparent",border:`1px solid ${T.border}`,color:T.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:11}}>YENİLE</button>
        </div>
      </div>
      <div style={{background:"#0a0d14",borderBottom:`1px solid ${T.border}`,padding:"10px 20px",display:"flex",alignItems:"center",gap:36,flexWrap:"wrap"}}>
        <div><div style={{color:T.muted,fontSize:10}}>LAST PRICE</div><div style={{color:T.text,fontSize:24,fontWeight:900,lineHeight:1}}>{fmtK(d.spot)}</div></div>
        <div style={{width:1,height:32,background:T.border}}/>
        <Chip label="P/C OI" value={d.pc_ratio?.toFixed(2)}/>
        <Chip label="Gamma" value={gammaPos?"Positive":"Negative"} color={gammaPos?T.green:T.red}/>
        <Chip label="IV 30D" value={pct(d.front_iv)}/>
        <Chip label="HV 30D" value={pct(d.hv_30d??67.97)} color={T.muted}/>
        <Chip label="IV Rank" value={pct(d.iv_rank)} color={d.iv_rank>60?T.red:d.iv_rank>35?T.gold:T.green}/>
        <Chip label="Exp.Move" value={`±${expMove}%`} color={T.purple}/>
        <div style={{width:1,height:32,background:T.border}}/>
        <Chip label="Net GEX" value={`$${gammaPos?"+":""}${d.total_net_gex?.toFixed(0)}M`} color={gammaPos?T.green:T.orange}/>
      </div>
      <div style={{padding:"16px 20px",display:"flex",flexDirection:"column",gap:14}}>
        <div>
          <ST>QSCORE — Composite Options Intelligence Signal</ST>
          <div style={{display:"flex",gap:12}}>
            <QCard score={d.option_score??0} category="Option" desc={`${scoreLabel(d.option_score)} — ${(d.option_score??0)>=3?"Bullish":"Bearish"} Option Positioning.`}/>
            <QCard score={d.vol_score??0} category="Volatility" desc={`${scoreLabel(d.vol_score)} — ${(d.vol_score??0)>=4?"Volatile":(d.vol_score??0)>=2?"Moderate":"Low"} Volatility.`}/>
            <QCard score={d.momentum_score??3} category="Momentum" desc={`${scoreLabel(d.momentum_score??3)} — ${(d.momentum_score??3)>=4?"Bullish":(d.momentum_score??3)>=3?"Neutral":"Bearish"} Momentum.`}/>
          </div>
        </div>
        <TeknikSignal optData={d} onConfluence={setConfScore}/>
        <div style={{display:"grid",gridTemplateColumns:"300px 1fr",gap:14,alignItems:"start"}}>
          <Card>
            <ST>Key Levels</ST>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:7}}>
              <KV label="Spot Price" value={fmtK(d.spot)} color={T.blue} highlight/>
              <KV label="High Vol Level" value={fmtK(d.hvl)} color={T.gold} highlight/>
              <KV label="Call Resistance" value={fmtK(d.call_resistance)} color={T.green}/>
              <KV label="Put Support" value={fmtK(d.put_support)} color={T.orange}/>
              <KV label="CR 0DTE" value={fmtK(d.call_resistance_0dte)} color="#58c76e"/>
              <KV label="PS 0DTE" value={fmtK(d.put_support_0dte)} color="#f9a86a"/>
              <KV label="IV Rank 30D" value={pct(d.iv_rank)}/>
              <KV label="Term Shape" value={d.term_shape} color={d.term_shape==="CONTANGO"?T.green:T.red}/>
              <KV label="Dist. HVL" value={`${distHVL}%`}/>
              <KV label="P/C OI" value={d.pc_ratio?.toFixed(3)} color={d.pc_ratio>1.2?T.red:d.pc_ratio<0.8?T.green:T.text}/>
            </div>
          </Card>
          <Card>
            <ST>Net GEX — All Expirations (Deribit) <span style={{color:gammaPos?T.green:T.orange}}>TOTAL: {gammaPos?"+":""}{d.total_net_gex?.toFixed(1)}M USD</span></ST>
            <div style={{display:"flex",gap:20,marginBottom:8,fontSize:10.5}}>
              <span><span style={{color:T.green}}>──</span> CR {fmtK(d.call_resistance)}</span>
              <span><span style={{color:T.gold}}>──</span> HVL {fmtK(d.hvl)}</span>
              <span><span style={{color:T.orange}}>──</span> PS {fmtK(d.put_support)}</span>
            </div>
            <GEXChart data={gexRows} spot={d.spot} hvl={d.hvl} callRes={d.call_resistance} putSup={d.put_support}/>
          </Card>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:14,alignItems:"start"}}>
          <Card>
            <ST>Implied Vol × Open Interest</ST>
            <div style={{display:"flex",gap:14,marginBottom:8,fontSize:10.5}}>
              <span><span style={{color:T.green}}>█</span> Calls</span>
              <span><span style={{color:T.orange}}>█</span> Puts</span>
            </div>
            <IVOIChart data={ivoiRows} spot={d.spot}/>
          </Card>
          <Card>
            <ST>ATM Term Structure</ST>
            <div style={{marginBottom:6,fontSize:10.5}}>
              <span style={{color:d.term_shape==="CONTANGO"?T.green:T.red}}>{d.term_shape}</span>
              <span style={{color:T.muted,marginLeft:10}}>Front IV: {d.front_iv?.toFixed(2)}%</span>
            </div>
            <TermChart data={d.term_ivs||[]}/>
          </Card>
          <Card borderColor={regime.color}>
            <ST>G-DIVE V4 — Entry Signal</ST>
            <div style={{marginBottom:14}}>
              <div style={{fontSize:26,fontWeight:900,color:regime.color,marginBottom:2}}>{d.long_ok?"▲  LONG OK":d.short_ok?"▼  SHORT OK":"—  BEKLE"}</div>
              <div style={{fontSize:12.5,color:regime.color,fontWeight:700,marginBottom:3}}>{regime.txt}</div>
              <div style={{fontSize:11,color:T.muted,lineHeight:1.5}}>{regime.sub}</div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:12}}>
              <div style={{padding:"8px 10px",background:"#2c0a08",border:`1px solid ${T.red}40`,borderRadius:6}}>
                <div style={{color:T.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:3}}>Stop Loss</div>
                <div style={{color:T.red,fontWeight:800,fontSize:15,fontFamily:"monospace"}}>{fmtK(d.put_support)}</div>
                <div style={{color:T.muted,fontSize:9.5}}>Put Support</div>
              </div>
              <div style={{padding:"8px 10px",background:"#0d2c12",border:`1px solid ${T.green}40`,borderRadius:6}}>
                <div style={{color:T.muted,fontSize:9.5,textTransform:"uppercase",marginBottom:3}}>TP Hedefi</div>
                <div style={{color:T.green,fontWeight:800,fontSize:15,fontFamily:"monospace"}}>{fmtK(d.call_resistance)}</div>
                <div style={{color:T.muted,fontSize:9.5}}>Call Resistance</div>
              </div>
            </div>
            <div style={{padding:"8px 12px",background:d.gamma_regime==="LONG_GAMMA"?"#0d2c1266":"#2c0a0866",border:`1px solid ${d.gamma_regime==="LONG_GAMMA"?T.green:T.red}40`,borderRadius:6,marginBottom:12}}>
              <span style={{color:d.gamma_regime==="LONG_GAMMA"?T.green:T.red,fontWeight:700,fontSize:12}}>{d.gamma_regime==="LONG_GAMMA"?"● LONG GAMMA":"● SHORT GAMMA"}</span>
              <div style={{color:T.muted,fontSize:10.5,marginTop:3}}>{d.gamma_regime==="LONG_GAMMA"?`Spot > HVL ($${d.hvl?.toLocaleString()}) · Dealer söndürür`:`Spot < HVL ($${d.hvl?.toLocaleString()}) · Dealer büyütür`}</div>
            </div>
            <div style={{fontSize:10,color:T.muted,marginBottom:6,textTransform:"uppercase"}}>Kritik GEX Düğümleri</div>
            <div style={{display:"flex",flexDirection:"column",gap:3}}>
              {[...(d.pos_gex_nodes||[]).slice(0,2).map(n=>({...n,color:T.green})),...(d.neg_gex_nodes||[]).slice(0,2).map(n=>({...n,color:T.orange}))].sort((a,b)=>a.strike-b.strike).map((n,i)=>(<div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10.5,padding:"2px 0"}}><span style={{color:T.muted,fontFamily:"monospace"}}>${n.strike.toLocaleString()}</span><span style={{color:n.color,fontWeight:700}}>{n.net_gex>=0?"+":""}{n.net_gex?.toFixed(1)}M</span></div>))}
            </div>
            <div style={{marginTop:12,paddingTop:10,borderTop:`1px solid ${T.border}`,display:"flex",justifyContent:"space-between",fontSize:9.5,color:T.muted}}>
              <span>OPT {d.option_score}/5</span><span>VOL {d.vol_score}/5</span><span>MOM {d.momentum_score??3}/5</span>
            </div>
          </Card>
        </div>
        <div style={{borderTop:`1px solid ${T.border}`,paddingTop:10,display:"flex",justifyContent:"space-between",fontSize:10,color:T.muted}}>
          <span>G-DIVE V4 Options Intelligence Module · Deribit Public API</span>
          <span>{live?`● Canlı · ${clock}`:`◆ Demo modu`}</span>
        </div>
      </div>
    </div>
  );
}
