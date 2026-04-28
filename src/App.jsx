import { useState, useEffect, useCallback, useRef } from "react";

const SERVER_URL = "https://gigkmjutnucssgwcnegn.supabase.co";
const SUPABASE_KEY = "sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW";

const C = {
  bg:"#06080e", surface:"#0a0f18", card:"#0e1520", card2:"#121c2a",
  border:"#1a2535", border2:"#223040",
  text:"#dce8f5", muted:"#3d5470", dim:"#1a2840",
  green:"#00e599", greenDim:"#002a1a", greenMid:"#00b377",
  red:"#ff3d5a", redDim:"#2a0010",
  orange:"#ff7a2f", gold:"#ffbe2e", goldDim:"#2a1e00",
  blue:"#3db8ff", blueDim:"#001a2a",
  purple:"#9d7aff", cyan:"#1de9d6",
};

const DEMO = {
  spot:68129, total_net_gex:3055.2, put_support:60000, call_resistance:75000, hvl:67000,
  put_support_0dte:68500, call_resistance_0dte:71000, front_iv:50.20, iv_rank:58.43,
  term_shape:"CONTANGO", pc_ratio:0.68, hv_30d:67.97, option_score:5, vol_score:5, momentum_score:3,
  gamma_regime:"LONG_GAMMA", regime:"BULLISH_HIGH_VOL", long_ok:true, short_ok:false,
  term_ivs:[{expiry:"25MAR",iv:55.2},{expiry:"28MAR",iv:52.1},{expiry:"4APR",iv:50.8},{expiry:"11APR",iv:50.2},{expiry:"25APR",iv:49.8},{expiry:"27JUN",iv:48.5},{expiry:"26SEP",iv:47.9}],
  call_walls:[75000,71000,80000,85000], put_walls:[60000,68500,65000,58000],
  pos_gex_nodes:[{strike:75000,net_gex:28.3},{strike:70000,net_gex:18.5},{strike:80000,net_gex:12.1}],
  neg_gex_nodes:[{strike:60000,net_gex:-25.8},{strike:65000,net_gex:-18.4},{strike:62000,net_gex:-12.1}],
  n_contracts:8247, _source:"demo",
  menthorq:{gamma_z:0.8,dealer_bias:0.4,flow_score:0.3,scalar:1.04,regime:"positive",score:0.65,wall_adj:0},
  funding:{rate:0.0003,score:1,scalar:0.98,regime:"cautious"},
  layer_budget:{final_scalar:1.02,menthorq_scalar:1.04,funding_scalar:0.98},
  multi_asset:{weights:{BTC:0.55,GLD:0.28,TLT:0.17},realized_vol:0.42,posture:"RISK_ON",vol_target:0.20},
};

const fmtK = n => `$${n?.toLocaleString("en-US",{maximumFractionDigits:0})}`;
const pct = n => `${(+n).toFixed(2)}%`;
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const sign = n => n >= 0 ? "+" : "";

async function fetchLive() {
  try {
    const r = await fetch(
      `${SERVER_URL}/rest/v1/snapshots?order=id.desc&limit=1`,
      {headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}}
    );
    if(!r.ok) return null;
    const rows = await r.json();
    if(!rows||!rows.length) return null;
    const d = rows[0];
    return d.spot>10000?{...d,_source:"supabase"}:null;
  } catch { return null; }
}
async function fetchBinancePrice() {
  try { const r=await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"); return r.ok?+(await r.json()).price:null; } catch { return null; }
}
async function fetchOHLCV(interval="4h",limit=120) {
  try {
    const ctrl=new AbortController(); const tid=setTimeout(()=>ctrl.abort(),7000);
    const r=await fetch(`https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=${interval}&limit=${limit}`,{signal:ctrl.signal});
    clearTimeout(tid); if(!r.ok) return null;
    return (await r.json()).map(k=>({t:k[0],o:+k[1],h:+k[2],l:+k[3],c:+k[4],v:+k[5]}));
  } catch { return null; }
}

function ema(c,p){const k=2/(p+1);let e=c[0];return c.map(v=>{e=v*k+e*(1-k);return e;});}
function rsiArr(c,p=14){let g=0,l=0;for(let i=1;i<=p;i++){const d=c[i]-c[i-1];d>=0?g+=d:l-=d;}let ag=g/p,al=l/p;const r=new Array(p).fill(null);r.push(al===0?100:100-100/(1+ag/al));for(let i=p+1;i<c.length;i++){const d=c[i]-c[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;r.push(al===0?100:100-100/(1+ag/al));}return r;}
function macdCalc(c,f=12,s=26,sig=9){const ef=ema(c,f),es=ema(c,s),m=ef.map((v,i)=>v-es[i]),signal=ema(m,sig);return{macd:m,signal,hist:m.map((v,i)=>v-signal[i])};}
function bbCalc(c,p=20,mult=2){return c.map((_,i)=>{if(i<p-1)return null;const sl=c.slice(i-p+1,i+1),mean=sl.reduce((a,b)=>a+b,0)/p,std=Math.sqrt(sl.reduce((a,b)=>a+(b-mean)**2,0)/p);return{upper:mean+mult*std,middle:mean,lower:mean-mult*std};});}
function atr(h,l,c,p=14){const tr=h.map((hv,i)=>i===0?hv-l[i]:Math.max(hv-l[i],Math.abs(hv-c[i-1]),Math.abs(l[i]-c[i-1])));return ema(tr,p);}

function analyzeCandles(candles) {
  if(!candles||candles.length<40) return null;
  const closes=candles.map(c=>c.c),n=closes.length-1;
  const ema9=ema(closes,9),ema21=ema(closes,21),rsis=rsiArr(closes,14);
  const {macd,signal,hist}=macdCalc(closes); const bbs=bbCalc(closes,20);
  const price=closes[n],rsi=rsis[n],bb=bbs[n],macdV=macd[n],sigV=signal[n],histV=hist[n];
  let score=0; const signals=[];
  if(ema9[n]>ema21[n]){score++;signals.push({k:"EMA",v:`9>${ema9[n].toFixed(0)} vs 21>${ema21[n].toFixed(0)}`,bull:true,weight:1});}
  else{score--;signals.push({k:"EMA",v:`9<${ema9[n].toFixed(0)} — Bearish`,bull:false,weight:1});}
  if(ema9[n]>ema21[n]&&ema9[n-1]<ema21[n-1]) signals.push({k:"CROSS",v:"⚡ Golden Cross",bull:true,weight:2,strong:true});
  if(rsi>70){score--;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Aşırı Alım`,bull:false,weight:1});}
  else if(rsi<30){score++;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Aşırı Satım`,bull:true,weight:1});}
  else if(rsi>55){score++;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Bullish`,bull:true,weight:1});}
  else if(rsi<45){score--;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Bearish`,bull:false,weight:1});}
  else signals.push({k:"RSI",v:`${rsi.toFixed(1)} Nötr`,bull:null,weight:0});
  if(macdV>sigV){score++;signals.push({k:"MACD",v:`+${histV.toFixed(0)} Bullish`,bull:true,weight:1});}
  else{score--;signals.push({k:"MACD",v:`${histV.toFixed(0)} Bearish`,bull:false,weight:1});}
  if(bb){const bp=(price-bb.lower)/(bb.upper-bb.lower);
    if(bp>0.85){score--;signals.push({k:"BB",v:"Üst Band Yakın",bull:false,weight:1});}
    else if(bp<0.15){score++;signals.push({k:"BB",v:"Alt Band Yakın",bull:true,weight:1});}
    else if(bp>0.5){score++;signals.push({k:"BB",v:"Orta Üstü",bull:true,weight:0.5});}
    else signals.push({k:"BB",v:"Orta Altı",bull:false,weight:0.5});}
  const sc=score>=3?C.green:score>=1?"#44e8a0":score<=-3?C.red:score<=-1?C.orange:C.muted;
  const sl=score>=3?"GÜÇLÜ LONG":score>=1?"ZAYIF LONG":score<=-3?"GÜÇLÜ SHORT":score<=-1?"ZAYIF SHORT":"BEKLE";
  return{price,rsi,macdV,sigV,histV,ema9:ema9[n],ema21:ema21[n],bb,score,sc,sl,signals};
}

function confluenceScore(t4,t1,opt) {
  if(!t4) return null;
  let score=0; const breakdown=[];
  const t4w=t4.score; score+=t4w; breakdown.push({src:"4H Teknik Analiz",val:t4w,desc:t4.sl});
  if(t1){const t1w=Math.round(t1.score*0.5);score+=t1w;breakdown.push({src:"1H Teknik Analiz",val:t1w,desc:t1.sl});}
  if(opt.total_net_gex>0){score++;breakdown.push({src:"GEX Pozitif",val:1,desc:`+${opt.total_net_gex?.toFixed(0)}M Dealer alım`});}
  else{score--;breakdown.push({src:"GEX Negatif",val:-1,desc:`${opt.total_net_gex?.toFixed(0)}M Dealer satış`});}
  if(opt.spot>opt.hvl){score++;breakdown.push({src:"Spot > HVL",val:1,desc:`${((opt.spot-opt.hvl)/opt.spot*100).toFixed(1)}% üstünde`});}
  else{score--;breakdown.push({src:"Spot < HVL",val:-1,desc:`HVL ${fmtK(opt.hvl)} altında`});}
  const dc=(opt.call_resistance-opt.spot)/opt.spot*100;
  if(dc<3){score--;breakdown.push({src:"Call Res. Yakın",val:-1,desc:`${dc.toFixed(1)}% uzakta — baskı`});}
  else if(dc>8){score++;breakdown.push({src:"Call Res. Uzak",val:1,desc:`${dc.toFixed(1)}% uzakta — yer var`});}
  const label=score>=5?"GÜÇLÜ LONG":score>=2?"ZAYIF LONG":score<=-5?"GÜÇLÜ SHORT":score<=-2?"ZAYIF SHORT":"NÖTR";
  const color=score>=5?C.green:score>=2?"#44e8a0":score<=-5?C.red:score<=-2?C.orange:C.muted;
  return{score,label,color,breakdown};
}

function runBacktest(candles) {
  if(!candles||candles.length<60) return null;
  const closes=candles.map(c=>c.c),highs=candles.map(c=>c.h),lows=candles.map(c=>c.l);
  const e9=ema(closes,9),e21=ema(closes,21),rsis=rsiArr(closes,14);
  const ml=ema(closes,12).map((v,i)=>v-ema(closes,26)[i]),sig=ema(ml,9),atrs=atr(highs,lows,closes,14);
  const trades=[];let inT=false,dir=null,entry=0,stop=0,tp=0,sz=0,eq=10000,pk=10000,mdd=0;
  for(let i=30;i<closes.length-1;i++){
    const p=closes[i],a=atrs[i];
    if(inT){
      if(dir==="L"){if(p<=stop){trades.push({pnl:(stop-entry)*sz,r:"SL"});eq+=(stop-entry)*sz;inT=false;}else if(p>=tp){trades.push({pnl:(tp-entry)*sz,r:"TP"});eq+=(tp-entry)*sz;inT=false;}}
      else{if(p>=stop){trades.push({pnl:(entry-stop)*sz,r:"SL"});eq+=(entry-stop)*sz;inT=false;}else if(p<=tp){trades.push({pnl:(entry-tp)*sz,r:"TP"});eq+=(entry-tp)*sz;inT=false;}}
      if(eq>pk)pk=eq;const dd=(pk-eq)/pk;if(dd>mdd)mdd=dd;
    }
    if(!inT&&a>0){
      const bull=e9[i]>e21[i]&&rsis[i]>50&&rsis[i]<70&&ml[i]>sig[i];
      const bear=e9[i]<e21[i]&&rsis[i]<50&&rsis[i]>30&&ml[i]<sig[i];
      const ra=eq*0.04;
      if(bull){entry=p;stop=p-a*2;tp=p+a*6;sz=ra/(a*2);inT=true;dir="L";}
      else if(bear){entry=p;stop=p+a*2;tp=p-a*6;sz=ra/(a*2);inT=true;dir="S";}
    }
  }
  if(!trades.length) return null;
  const wins=trades.filter(t=>t.pnl>0),losses=trades.filter(t=>t.pnl<0);
  const tp2=trades.reduce((a,t)=>a+t.pnl,0),wr=wins.length/trades.length*100;
  const aw=wins.length?wins.reduce((a,t)=>a+t.pnl,0)/wins.length:0;
  const al=losses.length?Math.abs(losses.reduce((a,t)=>a+t.pnl,0)/losses.length):1;
  const pf=al>0?Math.abs(wins.reduce((a,t)=>a+t.pnl,0))/Math.abs(losses.reduce((a,t)=>a+t.pnl,0)||1):0;
  return{trades:trades.length,wins:wins.length,wr:+wr.toFixed(1),totalPnl:+tp2.toFixed(0),finalEq:+eq.toFixed(0),maxDD:+(mdd*100).toFixed(1),pf:+pf.toFixed(2),aw:+aw.toFixed(0),al:+al.toFixed(0),exp:+((wr/100*aw-(1-wr/100)*al)).toFixed(0)};
}

function getRiskStatus(trades){
  const today=new Date().toISOString().slice(0,10),cap=10000;
  const dPnl=trades.filter(t=>t.status==="CLOSED"&&t.exitDate?.startsWith(today)).reduce((a,t)=>a+(t.pnl||0),0);
  let pk=cap,eq=cap,mdd=0;
  trades.filter(t=>t.status==="CLOSED").sort((a,b)=>new Date(a.exitDate)-new Date(b.exitDate)).forEach(t=>{eq+=(t.pnl||0);if(eq>pk)pk=eq;const dd=(pk-eq)/pk;if(dd>mdd)mdd=dd;});
  const dLimit=cap*0.02,ddLimit=0.10,killSwitch=dPnl<=-dLimit||mdd>=ddLimit;
  return{dPnl:+dPnl.toFixed(0),dLimit:+dLimit.toFixed(0),mdd:+(mdd*100).toFixed(1),killSwitch,openCount:trades.filter(t=>t.status==="OPEN").length,equity:+eq.toFixed(0)};
}

// ── SVG: GEX BAR ──────────────────────────────────────────────────
function GEXBar({data,spot,hvl,callRes,putSup}){
  const W=560,H=280,PL=44,PR=14,PT=6,PB=14,cw=W-PL-PR,ch=H-PT-PB;
  const maxV=Math.max(30,...data.map(r=>Math.abs(r.gex)));
  const rowH=ch/data.length,barH=Math.max(3,rowH-3),x0=PL+cw/2;
  const xS=v=>(v/maxV)*(cw/2);
  const refMap={[`${Math.round(spot/1000)}K`]:{c:"rgba(220,232,245,0.6)",label:"Spot"},[`${Math.round(hvl/1000)}K`]:{c:C.gold,label:"HVL"},[`${Math.round(callRes/1000)}K`]:{c:C.green,label:"CR"},[`${Math.round(putSup/1000)}K`]:{c:C.red,label:"PS"}};
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs>
        <linearGradient id="gp" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stopColor={C.green} stopOpacity="0.2"/><stop offset="100%" stopColor={C.green} stopOpacity="0.85"/></linearGradient>
        <linearGradient id="gn" x1="100%" y1="0%" x2="0%" y2="0%"><stop offset="0%" stopColor={C.red} stopOpacity="0.2"/><stop offset="100%" stopColor={C.red} stopOpacity="0.85"/></linearGradient>
      </defs>
      <line x1={x0} y1={PT} x2={x0} y2={H-PB} stroke={C.border2} strokeWidth={1}/>
      {data.map((row,i)=>{
        const y=PT+i*rowH+(rowH-barH)/2,bw=Math.abs(xS(row.gex)),bx=row.gex>=0?x0:x0-bw;
        const ref=refMap[row.label];
        return(<g key={i}>
          {ref&&<line x1={PL} y1={PT+i*rowH+rowH/2} x2={W-PR} y2={PT+i*rowH+rowH/2} stroke={ref.c} strokeWidth={1.5} strokeDasharray="5,3"/>}
          <rect x={bx} y={y} width={Math.max(bw,1)} height={barH} fill={row.gex>=0?"url(#gp)":"url(#gn)"} rx={2}/>
          <text x={PL-5} y={PT+i*rowH+rowH/2+3} fill={ref?C.text:C.muted} fontSize={8.5} textAnchor="end" fontFamily="monospace">{row.label}</text>
        </g>);
      })}
    </svg>
  );
}

function TermLine({data}){
  const W=260,H=180,PL=32,PR=10,PT=12,PB=20,cw=W-PL-PR,ch=H-PT-PB;
  if(!data||data.length<2) return null;
  const ivs=data.map(d=>d.iv),minIV=Math.min(...ivs)-2,maxIV=Math.max(...ivs)+2;
  const xS=i=>PL+i*(cw/(data.length-1)),yS=v=>PT+ch-(v-minIV)/(maxIV-minIV)*ch;
  const pts=data.map((d,i)=>`${xS(i)},${yS(d.iv)}`).join(" ");
  const rising=ivs[ivs.length-1]>ivs[0],lc=rising?C.green:C.red;
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs><linearGradient id="tg" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stopColor={lc} stopOpacity="0.25"/><stop offset="100%" stopColor={lc} stopOpacity="0"/></linearGradient></defs>
      {[0,1,2].map(i=>{const v=minIV+i*(maxIV-minIV)/2;return <line key={i} x1={PL} y1={yS(v)} x2={W-PR} y2={yS(v)} stroke={C.border} strokeWidth={0.5} strokeDasharray="3,3"/>;})}
      <polygon points={`${data.map((d,i)=>`${xS(i)},${yS(d.iv)}`).join(" ")} ${xS(data.length-1)},${H-PB} ${PL},${H-PB}`} fill="url(#tg)"/>
      <polyline points={pts} fill="none" stroke={lc} strokeWidth={2}/>
      {data.map((d,i)=>(<g key={i}><circle cx={xS(i)} cy={yS(d.iv)} r={3} fill={lc} stroke={C.bg} strokeWidth={1}/><text x={xS(i)} y={H-4} fill={C.muted} fontSize={7} textAnchor="middle">{d.expiry.replace("26","").replace("25","")}</text></g>))}
    </svg>
  );
}

function buildGEX(d){
  const nm={};[...(d.pos_gex_nodes||[]),...(d.neg_gex_nodes||[])].forEach(n=>{nm[n.strike]=n.net_gex;});
  const s=d.spot,lo=Math.ceil((s*0.74)/1000)*1000,hi=Math.ceil((s*1.26)/1000)*1000,rows=[];
  for(let k=hi;k>=lo;k-=1000){const v=nm[k];let g=v!==undefined?v:(k<s?-6*Math.exp(-Math.abs((k-s)/s)*6):5*Math.exp(-Math.abs((k-s)/s)*7));rows.push({label:`${(k/1000).toFixed(0)}K`,gex:Math.round(g*10)/10});}
  return rows;
}

// ── UI ATOMS ──────────────────────────────────────────────────────
const Pill = ({children,color,dim}) => (
  <span style={{background:dim||`${color}18`,border:`1px solid ${color}40`,color,borderRadius:4,padding:"2px 8px",fontSize:10,fontWeight:700,letterSpacing:"0.04em"}}>{children}</span>
);

const Bar = ({pct,color,height=4}) => (
  <div style={{height,background:C.dim,borderRadius:99,overflow:"hidden"}}>
    <div style={{height:"100%",width:`${clamp(pct,0,100)}%`,background:color,borderRadius:99}}/>
  </div>
);

const LayerHead = ({num, title, subtitle, status, statusColor}) => (
  <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:14}}>
    <div style={{width:28,height:28,borderRadius:"50%",background:`${statusColor||C.muted}20`,border:`1.5px solid ${statusColor||C.muted}60`,display:"flex",alignItems:"center",justifyContent:"center",color:statusColor||C.muted,fontSize:11,fontWeight:900,flexShrink:0}}>{num}</div>
    <div style={{flex:1}}>
      <div style={{color:C.text,fontWeight:700,fontSize:12.5,letterSpacing:"0.03em"}}>{title}</div>
      {subtitle&&<div style={{color:C.muted,fontSize:10,marginTop:1}}>{subtitle}</div>}
    </div>
    {status&&<Pill color={statusColor||C.muted}>{status}</Pill>}
  </div>
);

const Divider = ({label}) => (
  <div style={{display:"flex",alignItems:"center",gap:10,margin:"4px 0 12px"}}>
    <div style={{flex:1,height:1,background:C.border}}/>
    {label&&<span style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em"}}>{label}</span>}
    {label&&<div style={{flex:1,height:1,background:C.border}}/>}
  </div>
);

const InsightBox = ({icon,text,type}) => {
  const colors = {bull:C.green,bear:C.red,warn:C.gold,info:C.blue,neutral:C.muted};
  const c = colors[type]||C.muted;
  return(
    <div style={{display:"flex",gap:8,padding:"7px 10px",background:`${c}08`,border:`1px solid ${c}20`,borderLeft:`2px solid ${c}`,borderRadius:5}}>
      <span style={{color:c,flexShrink:0}}>{icon}</span>
      <span style={{color:C.text,fontSize:10.5,lineHeight:1.5}}>{text}</span>
    </div>
  );
};

// ── LLM FILTER PANEL ─────────────────────────────────────────────
function LLMFilterPanel({ gammaScore, regime, isLive }) {
  const [state, setState] = useState({
    verdict: null, confidence: null, action: null,
    reasoning: null, vetoReasons: null,
    fomcTitle: null, fomcDate: null,
    loading: false, error: null, lastUpdate: null,
  });
  const debounceRef = useRef(null);
  const lastFetchRef = useRef({ score: null, regime: null });

  const GROQ_KEY = "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";

  const runFilter = useCallback(async (forceRefresh = false) => {
    const roundedScore = Math.round(gammaScore * 100) / 100;
    if (!forceRefresh &&
        lastFetchRef.current.score === roundedScore &&
        lastFetchRef.current.regime === regime) return;

    setState(s => ({ ...s, loading: true, error: null }));

    const threshold = 0.25;
    let action = "BEKLE";
    if (roundedScore >= threshold) action = "LONG";
    else if (roundedScore <= -threshold) action = "SHORT";

    if (action === "BEKLE") {
      lastFetchRef.current = { score: roundedScore, regime };
      setState(s => ({ ...s, loading: false, verdict: "NÖTR", confidence: 1.0, action: "BEKLE",
        reasoning: "Gamma skoru eşik altında, trade sinyali yok.", vetoReasons: null,
        fomcTitle: "—", fomcDate: "—", lastUpdate: new Date().toLocaleTimeString("tr-TR") }));
      return;
    }

    try {
      const prompt = "Sen bir BTC options trading risk filtresinsin. Gamma sistemi " + action + " sinyali uretti (skor: " + roundedScore + ", rejim: " + regime + "). Sadece JSON dondur: {"verdict":"ONAYLA","confidence":0.7,"reasoning":"50 kelime Turkce gerekcesi","veto_reasons":null}";
      const ctrl = new AbortController();
      setTimeout(() => ctrl.abort(), 30000);
      const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + GROQ_KEY },
        body: JSON.stringify({ model: "llama3-70b-8192", max_tokens: 200, messages: [{ role: "user", content: prompt }] }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("Groq HTTP " + res.status);
      const groqData = await res.json();
      const raw = groqData.choices[0].message.content.replace(/```json|```/g,"").trim();
      const match = raw.match(/\{[\s\S]*\}/);
      const result = JSON.parse(match ? match[0] : raw);
      lastFetchRef.current = { score: roundedScore, regime };
      setState({
        verdict: result.verdict, confidence: result.confidence, action: action,
        reasoning: result.reasoning, vetoReasons: result.veto_reasons,
        fomcTitle: "Groq llama3-70b", fomcDate: new Date().toLocaleTimeString("tr-TR"),
        loading: false, error: null, lastUpdate: new Date().toLocaleTimeString("tr-TR"),
      });
    } catch (err) {
      setState(s => ({ ...s, loading: false, error: err.name === "AbortError" ? "Timeout (30s)" : err.message }));
    }
  }, [gammaScore, regime]);

  // Gamma skoru veya rejim değişince 3sn debounce ile çalıştır
  useEffect(() => {
    if (!isLive) return; // Demo modda çalıştırma
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runFilter(), 3000);
    return () => clearTimeout(debounceRef.current);
  }, [gammaScore, regime, isLive]);

  const verdictCfg = {
    ONAYLA: { color: C.green, bg: "#002a1a", border: "#00e59940", label: "ONAYLA", finalText: a => `${a} — AL`, desc: "LLM onayladı. Trade alınabilir." },
    VETO:   { color: C.red,   bg: "#2a0010", border: "#ff3d5a40", label: "VETO",   finalText: () => "TRADE ALMA", desc: "LLM veto etti. Gamma sinyali geçersiz." },
    NÖTR:   { color: C.gold,  bg: "#2a1e00", border: "#ffbe2e40", label: "NÖTR",   finalText: () => "KARAR SANA KALDI", desc: "LLM kararsız. Sinyali değerlendirin." },
  };
  const vc = state.verdict ? verdictCfg[state.verdict] : null;
  const actionColor = state.action === "LONG" ? C.green : state.action === "SHORT" ? C.red : C.gold;

  return (
    <div>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <div style={{ fontSize: 10, color: C.muted }}>
          {state.fomcDate && state.fomcDate !== "—"
            ? `FOMC kaynak: ${state.fomcDate.slice(0, 22)}`
            : "FOMC · Deribit · GEX verileri otomatik çekilir"}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {state.lastUpdate && <span style={{ fontSize: 10, color: C.muted }}>son: {state.lastUpdate}</span>}
          <button
            onClick={() => runFilter(true)}
            disabled={state.loading}
            style={{ background: "transparent", border: `1px solid ${C.border}`, color: state.loading ? C.muted : C.text, padding: "3px 12px", borderRadius: 4, cursor: state.loading ? "not-allowed" : "pointer", fontFamily: "monospace", fontSize: 10 }}
          >
            {state.loading ? "⟳ analiz..." : "↺ Yenile"}
          </button>
        </div>
      </div>

      {/* Demo uyarısı */}
      {!isLive && (
        <div style={{ padding: "10px 14px", background: `${C.gold}10`, border: `1px solid ${C.gold}30`, borderRadius: 6, color: C.gold, fontSize: 10.5, marginBottom: 12 }}>
          Demo modda LLM filtresi çalışmaz. Canlı sunucuya bağlanınca otomatik devreye girer.
        </div>
      )}

      {/* Loading */}
      {state.loading && (
        <div style={{ textAlign: "center", padding: "24px 0", color: C.muted, fontSize: 11 }}>
          FOMC metni + Deribit sentiment + GEX → Claude analiz yapıyor...
          <div style={{ height: 2, background: C.dim, borderRadius: 1, overflow: "hidden", marginTop: 10, maxWidth: 300, margin: "10px auto 0" }}>
            <div style={{ height: "100%", width: "70%", background: C.purple, borderRadius: 1 }} />
          </div>
        </div>
      )}

      {/* Error */}
      {state.error && !state.loading && (
        <InsightBox icon="⚠" type="warn" text={`LLM Filtre hatası: ${state.error}. Yenile butonuna bas.`} />
      )}

      {/* Sonuç */}
      {vc && !state.loading && (
        <>
          {/* Gamma | LLM kararı */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <div style={{ textAlign: "center", padding: "16px 10px", background: C.card2, border: `1px solid ${C.border}`, borderRadius: 8 }}>
              <div style={{ color: C.muted, fontSize: 9, textTransform: "uppercase", marginBottom: 6 }}>GAMMA SİNYALİ</div>
              <div style={{ color: actionColor, fontSize: 30, fontWeight: 900, letterSpacing: 2, marginBottom: 4 }}>{state.action}</div>
              <div style={{ color: C.muted, fontSize: 10 }}>{gammaScore >= 0 ? "+" : ""}{gammaScore?.toFixed(2)} · {regime}</div>
            </div>
            <div style={{ textAlign: "center", padding: "16px 10px", background: vc.bg, border: `2px solid ${vc.border}`, borderRadius: 8 }}>
              <div style={{ color: C.muted, fontSize: 9, textTransform: "uppercase", marginBottom: 6 }}>LLM FİLTRE KARARI</div>
              <div style={{ color: vc.color, fontSize: 30, fontWeight: 900, letterSpacing: 2, marginBottom: 4 }}>{vc.label}</div>
              <div style={{ color: C.muted, fontSize: 10 }}>güven: {((state.confidence || 0) * 100).toFixed(0)}%</div>
            </div>
          </div>

          {/* Final karar kutusu */}
          <div style={{ textAlign: "center", padding: "14px 20px", background: vc.bg, border: `1.5px solid ${vc.border}`, borderRadius: 8, marginBottom: 12 }}>
            <div style={{ color: C.muted, fontSize: 9, textTransform: "uppercase", marginBottom: 4 }}>SONUÇ</div>
            <div style={{ color: vc.color, fontSize: 20, fontWeight: 900, letterSpacing: 1, marginBottom: 4 }}>{vc.finalText(state.action)}</div>
            <div style={{ color: C.text, fontSize: 10.5 }}>{vc.desc}</div>
          </div>

          {/* Gerekçe */}
          <div style={{ background: C.card2, border: `1px solid ${C.border}`, borderRadius: 7, padding: "12px 14px", marginBottom: state.vetoReasons ? 10 : 0 }}>
            <div style={{ color: C.muted, fontSize: 9, textTransform: "uppercase", marginBottom: 6 }}>LLM GEREKÇESİ</div>
            <div style={{ color: C.text, fontSize: 11, lineHeight: 1.75 }}>{state.reasoning}</div>
          </div>

          {/* Veto sebepleri */}
          {state.vetoReasons && Array.isArray(state.vetoReasons) && (
            <div style={{ background: `${C.red}08`, border: `1px solid ${C.red}30`, borderLeft: `3px solid ${C.red}`, borderRadius: 7, padding: "10px 14px", marginTop: 10 }}>
              <div style={{ color: C.red, fontSize: 9, textTransform: "uppercase", marginBottom: 6 }}>VETO SEBEPLERİ</div>
              {state.vetoReasons.map((r, i) => (
                <div key={i} style={{ color: C.red, fontSize: 11, marginBottom: 3 }}>• {r}</div>
              ))}
            </div>
          )}

          {/* FOMC kaynak */}
          {state.fomcTitle && state.fomcTitle !== "—" && (
            <div style={{ marginTop: 10, fontSize: 9.5, color: C.muted, paddingTop: 8, borderTop: `1px solid ${C.border}` }}>
              FOMC: {state.fomcTitle}
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!vc && !state.loading && !state.error && isLive && (
        <div style={{ textAlign: "center", padding: "20px 0", color: C.muted, fontSize: 11 }}>
          Gamma sinyali değişince otomatik analiz başlar (3sn debounce).
        </div>
      )}
    </div>
  );
}

// ── TEKNIK PANEL ──────────────────────────────────────────────────
function TeknikPanel({optData,onConf}){
  const [t4,setT4]=useState(null),[t1,setT1]=useState(null),[loading,setLoading]=useState(true),[tab,setTab]=useState("4h"),[lastUpd,setLastUpd]=useState(null);
  const load=useCallback(async()=>{setLoading(true);const[c4,c1]=await Promise.all([fetchOHLCV("4h",120),fetchOHLCV("1h",100)]);if(c4)setT4(analyzeCandles(c4));if(c1)setT1(analyzeCandles(c1));setLastUpd(new Date().toLocaleTimeString("tr-TR"));setLoading(false);},[]);
  useEffect(()=>{load();const id=setInterval(load,5*60*1000);return()=>clearInterval(id);},[load]);
  const conf=confluenceScore(t4,t1,optData);
  useEffect(()=>{if(conf&&onConf)onConf(conf);},[conf?.score]);
  const cur=tab==="4h"?t4:t1;
  return(
    <div>
      {loading&&<div style={{color:C.muted,fontSize:10,padding:"8px 0"}}>Binance verisi yükleniyor...</div>}
      {!loading&&conf&&(
        <div style={{display:"grid",gridTemplateColumns:"180px 1fr",gap:14}}>
          <div style={{background:`${conf.color}08`,border:`1px solid ${conf.color}25`,borderRadius:8,padding:"12px"}}>
            <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:4}}>Toplam Konfluens</div>
            <div style={{color:conf.color,fontSize:42,fontWeight:900,lineHeight:1,fontFamily:"monospace"}}>{sign(conf.score)}{conf.score}</div>
            <div style={{color:conf.color,fontSize:12,fontWeight:700,marginBottom:8}}>{conf.label}</div>
            <Bar pct={clamp(((conf.score+8)/16)*100,0,100)} color={conf.color} height={5}/>
            <div style={{display:"flex",flexDirection:"column",gap:4,marginTop:10}}>
              {conf.breakdown.map((b,i)=>(
                <div key={i} style={{fontSize:9.5}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:1}}>
                    <span style={{color:C.muted}}>{b.src}</span>
                    <span style={{color:b.val>0?C.green:b.val<0?C.red:C.muted,fontWeight:700}}>{sign(b.val)}{b.val}</span>
                  </div>
                  <div style={{color:C.dim,fontSize:8.5}}>{b.desc}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div style={{display:"flex",gap:6,marginBottom:10}}>
              {[{k:"4h",sig:t4},{k:"1h",sig:t1}].map(({k,sig})=>(
                <button key={k} onClick={()=>setTab(k)} style={{background:tab===k?`${sig?.sc||C.blue}12`:"transparent",border:`1px solid ${tab===k?sig?.sc||C.blue:C.border}`,color:tab===k?sig?.sc||C.blue:C.muted,padding:"3px 14px",borderRadius:4,cursor:"pointer",fontFamily:"monospace",fontSize:10.5}}>
                  {k.toUpperCase()} {sig?sig.sl:"—"}
                </button>
              ))}
              <button onClick={load} style={{marginLeft:"auto",background:"transparent",border:`1px solid ${C.border}`,color:C.muted,padding:"3px 10px",borderRadius:4,cursor:"pointer",fontSize:9}}>↺ {lastUpd}</button>
            </div>
            {cur&&(
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
                <div style={{display:"flex",flexDirection:"column",gap:4}}>
                  {[{l:"EMA9",v:cur.ema9?.toFixed(0),c:cur.ema9>cur.ema21?C.green:C.red},{l:"EMA21",v:cur.ema21?.toFixed(0),c:C.muted},{l:"RSI14",v:cur.rsi?.toFixed(1),c:cur.rsi>70?C.red:cur.rsi<30?C.green:cur.rsi>50?C.green:C.orange},{l:"MACD",v:cur.macdV?.toFixed(0),c:cur.macdV>cur.sigV?C.green:C.red},{l:"Hist",v:(cur.histV>=0?"+":"")+cur.histV?.toFixed(0),c:cur.histV>0?C.green:C.red},{l:"BB %B",v:cur.bb?((cur.price-cur.bb.lower)/(cur.bb.upper-cur.bb.lower)*100).toFixed(0)+"%":"—",c:C.blue}].map((row,i)=>(
                    <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 7px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:4}}>
                      <span style={{color:C.muted,fontSize:9.5,textTransform:"uppercase"}}>{row.l}</span>
                      <span style={{color:row.c,fontWeight:700,fontFamily:"monospace",fontSize:10.5}}>{row.v}</span>
                    </div>
                  ))}
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:3}}>
                  <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:2}}>Sinyal Bileşenleri</div>
                  {cur.signals.map((s,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:6,padding:"3px 6px",borderRadius:3,background:s.bull===true?`${C.green}08`:s.bull===false?`${C.red}08`:C.dim+"20"}}>
                      <span style={{color:s.bull===true?C.green:s.bull===false?C.red:C.muted,fontSize:9,flexShrink:0}}>{s.bull===true?"▲":s.bull===false?"▼":"●"}</span>
                      <span style={{color:s.strong?C.text:C.muted,fontSize:9.5}}>{s.k}: {s.v}</span>
                    </div>
                  ))}
                  <div style={{marginTop:6,padding:"8px",background:`${cur.sc}10`,border:`1px solid ${cur.sc}30`,borderRadius:6}}>
                    <div style={{color:C.muted,fontSize:9,marginBottom:2}}>{tab.toUpperCase()} NET SİNYAL</div>
                    <div style={{color:cur.sc,fontWeight:900,fontSize:17}}>{cur.score>=0?"▲":"▼"} {cur.sl}</div>
                    <Bar pct={clamp(((cur.score+4)/8)*100,0,100)} color={cur.sc} height={4}/>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── MAIN ──────────────────────────────────────────────────────────
export default function App(){
  const [data,setData]=useState(DEMO),[live,setLive]=useState(false),[busy,setBusy]=useState(false),[clock,setClock]=useState("");
  const [conf,setConf]=useState(null),[risk,setRisk]=useState(null),[bt,setBt]=useState(null);

  const refresh=useCallback(async()=>{setBusy(true);const[d,bp]=await Promise.all([fetchLive(),fetchBinancePrice()]);if(d){setData(d);setLive(true);}else{setData(bp?{...DEMO,spot:bp}:DEMO);setLive(false);}setClock(new Date().toLocaleTimeString("tr-TR"));setBusy(false);},[]);
  useEffect(()=>{refresh();const id=setInterval(refresh,4*60*1000);return()=>clearInterval(id);},[refresh]);
  useEffect(()=>{
    fetch(`${SERVER_URL}/trades`).then(r=>r.json()).then(t=>{setRisk(getRiskStatus(t));}).catch(()=>{});
  },[data]);
  useEffect(()=>{fetchOHLCV("4h",500).then(c=>{if(c)setBt(runBacktest(c));});},[]);

  // Gamma score hesapla (MenthorQ score'dan türet)
  const gammaScore = data.menthorq?.score || 0;
  const gammaRegime = data.gamma_regime || "NEUTRAL";

  useEffect(()=>{
    (async()=>{
    if(!data||data.spot<1000) return;
    try{
      const JKEY="gdive:journal:v2";
      let trades=[];
      try{ const r=await fetch(`${SERVER_URL}/trades`); trades=await r.json(); }catch{
        trades=JSON.parse(localStorage.getItem(JKEY)||"[]");
      }
      const s=data.spot,reg=data.regime;
      const bull=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(reg)&&s>data.hvl&&data.total_net_gex>0;
      const ga=data.gamma_analysis||{};
      const flipNear=ga.flip_near||false;
      const inNegPocket=ga.in_neg_pocket||false;
      const nearPosWall=ga.near_pos_wall||false;
      const expD=data.expiry||{};
      const expiryDay=expD.expiry_day||false;
      const expiryWeek=expD.expiry_week||false;
      const expiryScalar=expD.expiry_scalar||1.0;
      const maxPain=data.max_pain||null;
      const bear=["BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK"].includes(reg)&&s<data.hvl&&data.total_net_gex<0;
      const rs=getRiskStatus(trades);setRisk(rs);
      if(rs.killSwitch) return;
      if(expiryDay){return;}
      if(flipNear){return;}
      const gammaConflict = (bull && data.gamma_regime==="SHORT_GAMMA") || (bear && data.gamma_regime==="LONG_GAMMA");
      if(gammaConflict){return;}
      const regimeConflict = bull && ["BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK"].includes(data.regime);
      if(regimeConflict){return;}
      const confOK=!conf||(conf&&conf.score>=-10);
      const ivOK=(data.iv_rank||0)<80;
      let changed=false;
      const updated=trades.map(t=>{
        if(t.status!=="OPEN") return t;
        const now=new Date().toISOString().slice(0,16).replace("T"," ");
        if(t.dir==="LONG"){
          let effectiveStop=t.stop;
          if(inNegPocket&&data.neg_pockets&&data.neg_pockets.length>0){
            const nearerStop=data.neg_pockets.find(p=>p.strike>t.stop&&p.strike<s);
            if(nearerStop) effectiveStop=Math.max(t.stop,nearerStop.strike*0.995);
          }
          if(data.term_shape==="BACKWARDATION"&&!t.notes?.includes("Backwardation")){
            effectiveStop=Math.max(effectiveStop,t.entry-(t.entry-t.stop)*0.8);
          }
          if(s<=effectiveStop){changed=true;const pnl=+((effectiveStop-t.entry)*t.size).toFixed(2);alert("STOP HIT LONG @$"+effectiveStop.toFixed(0)+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:effectiveStop,exitDate:now,pnl,rr:-1,notes:(t.notes||"")+" |STOP"};}
          if(bear){changed=true;const pnl=+((s-t.entry)*t.size).toFixed(2);alert("REJİM DEĞİŞTİ - LONG kapanıyor @$"+s);return{...t,status:"CLOSED",exitPrice:s,exitDate:now,pnl,rr:+((s-t.entry)/(t.entry-t.stop)).toFixed(2),notes:(t.notes||"")+" |REJIM"};}
          if(s>=t.tp&&!t.partialClosed){changed=true;if(bull){const h=+(t.size/2).toFixed(4),nTP=data.call_walls?.find(w=>w>t.tp)||t.tp*1.03;alert("TP %50 LONG @$"+t.tp);return{...t,size:h,partialClosed:true,tp:nTP,notes:(t.notes||"")+" |TP50@"+t.tp};}else{const pnl=+((t.tp-t.entry)*t.size).toFixed(2);alert("TP %100 LONG @$"+t.tp+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.tp,exitDate:now,pnl,rr:+((t.tp-t.entry)/(t.entry-t.stop)).toFixed(2),notes:(t.notes||"")+" |TP"};}}
        }
        if(t.dir==="SHORT"){
          if(s>=t.stop){changed=true;const pnl=+((t.entry-t.stop)*t.size).toFixed(2);alert("STOP HIT SHORT @$"+t.stop+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.stop,exitDate:now,pnl,rr:-1,notes:(t.notes||"")+" |STOP"};}
          if(bull){changed=true;const pnl=+((t.entry-s)*t.size).toFixed(2);alert("REJİM DEĞİŞTİ - SHORT kapanıyor @$"+s);return{...t,status:"CLOSED",exitPrice:s,exitDate:now,pnl,rr:+((t.entry-s)/(t.stop-t.entry)).toFixed(2),notes:(t.notes||"")+" |REJIM"};}
          if(s<=t.tp&&!t.partialClosed){changed=true;if(bear){const h=+(t.size/2).toFixed(4),nTP=data.put_walls?.slice().sort((a,b)=>b-a).find(w=>w<t.tp)||t.tp*0.97;alert("TP %50 SHORT @$"+t.tp);return{...t,size:h,partialClosed:true,tp:nTP,notes:(t.notes||"")+" |TP50@"+t.tp};}else{const pnl=+((t.entry-t.tp)*t.size).toFixed(2);alert("TP %100 SHORT @$"+t.tp+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.tp,exitDate:now,pnl,rr:+((t.entry-t.tp)/(t.stop-t.entry)).toFixed(2),notes:(t.notes||"")+" |TP"};}}
        }
        return t;
      });
      if(changed){
        localStorage.setItem(JKEY,JSON.stringify(updated));
        fetch(`${SERVER_URL}/trades/sync`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(updated)}).catch(()=>{});
      }
      const today=new Date().toISOString().slice(0,10);
      const hasOpen=updated.find(t=>t.date?.startsWith(today)&&t.status==="OPEN");
      if(!hasOpen&&confOK&&ivOK){
        const fs=(data.layer_budget?.final_scalar||1.0)*expiryScalar,risk2=10000*0.02*3*fs;
        if(nearPosWall&&!inNegPocket){return;}
        if(bull){
          // LLM Filtre kontrolü
          let llmOk = false;
          try{
            const gs = data.menthorq?.score || 0;
            const lr = await fetch(`${SERVER_URL}/llm-filter?gamma_score=${gs}&regime=${data.gamma_regime||'NEUTRAL'}`);
            const ld = await lr.json();
            llmOk = ld.verdict === "ONAYLA";
            if(!llmOk){ console.log("[AUTO] LLM VETO/NÖTR - LONG açılmadı:", ld.verdict, ld.reasoning); }
          }catch(e){ console.log("[AUTO] LLM filtre hatası, trade açılmadı"); llmOk=false; }
          if(llmOk){
          const e=s;
          const pctStop=e*0.95;
          const sp=Math.max(data.put_support||0, pctStop);
          const tp2=expiryWeek&&maxPain?maxPain:data.call_resistance;
          const sz=+(risk2/Math.abs(e-sp)).toFixed(4);
          const notes="Auto LONG GEX:"+data.total_net_gex+"M scalar:"+fs+(expiryWeek?" [Expiry Haftası TP=MaxPain "+maxPain+"]":"")+(data.term_shape==="BACKWARDATION"?" [Backwardation]":"")+" [LLM:ONAYLA]";
          const tr={id:Date.now(),date:new Date().toISOString().slice(0,16).replace("T"," "),dir:"LONG",entry:e,stop:sp,tp:tp2,size:sz,regime:reg,signal:"Auto·L·"+reg+(expiryWeek?"·Expiry":""),notes,status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,partialClosed:false};
          const newTradesL=[tr,...updated];
          localStorage.setItem(JKEY,JSON.stringify(newTradesL));
          fetch("https://gigkmjutnucssgwcnegn.supabase.co/rest/v1/trades",{method:"POST",headers:{"apikey":"sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW","Authorization":"Bearer sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW","Content-Type":"application/json","Prefer":"return=minimal"},body:JSON.stringify({trade_id:String(tr.id),date:tr.date,dir:tr.dir,entry:tr.entry,stop:tr.stop,tp:tr.tp,size:tr.size,status:"OPEN",regime:tr.regime,signal:tr.signal,notes:tr.notes})}).catch(()=>{});
          alert("AUTO LONG @$"+e+" Stop:$"+sp+" TP:$"+tp2+(expiryWeek?" [Expiry TP=MaxPain]":"")+" [LLM ONAYLA]");
          }
        }
        else if(bear){
          // LLM Filtre kontrolü
          let llmOkS = false;
          try{
            const gs = data.menthorq?.score || 0;
            const lr = await fetch(`${SERVER_URL}/llm-filter?gamma_score=${gs}&regime=${data.gamma_regime||'NEUTRAL'}`);
            const ld = await lr.json();
            llmOkS = ld.verdict === "ONAYLA";
            if(!llmOkS){ console.log("[AUTO] LLM VETO/NÖTR - SHORT açılmadı:", ld.verdict, ld.reasoning); }
          }catch(e){ console.log("[AUTO] LLM filtre hatası, trade açılmadı"); llmOkS=false; }
          if(llmOkS){
          const e=s;
          const negPocketTP=data.neg_pockets&&data.neg_pockets.length>1?data.neg_pockets[1].strike:null;
          const tp2=expiryWeek&&maxPain?maxPain:negPocketTP||data.put_support;
          const backwardation=data.term_shape==="BACKWARDATION";
          const stopDist=Math.abs(e-data.call_resistance)*(backwardation?1.2:1.0);
          const sp=e+stopDist;
          const sz=+(risk2/Math.abs(e-sp)).toFixed(4);
          const notes="Auto SHORT GEX:"+data.total_net_gex+"M scalar:"+fs+(backwardation?" [Backwardation +%20 stop]":"")+(inNegPocket?" [Neg Pocket Aktif]":"")+" [LLM:ONAYLA]";
          const tr={id:Date.now(),date:new Date().toISOString().slice(0,16).replace("T"," "),dir:"SHORT",entry:e,stop:sp,tp:tp2,size:sz,regime:reg,signal:"Auto·S·"+reg+(inNegPocket?"·NegPocket":""),notes,status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,partialClosed:false};
          const newTradesS=[tr,...updated];
          localStorage.setItem(JKEY,JSON.stringify(newTradesS));
          fetch(`${SERVER_URL}/trades/sync`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(newTradesS)}).catch(()=>{});
          alert("AUTO SHORT @$"+e+" Stop:$"+sp.toFixed(0)+" TP:$"+tp2+(backwardation?" [Backwardation]":""));
          }
        }
      }
    }catch(e){console.error("pm",e);}
    })();
  },[data,conf]);

  const d=data,gp=d.total_net_gex>0,gexRows=buildGEX(d);
  const mq=d.menthorq,lb=d.layer_budget,ma=d.multi_asset;
  const distHVL=(Math.abs(d.spot-d.hvl)/d.spot*100).toFixed(1);
  const aboveHVL=d.spot>d.hvl;
  const regimeColor=d.long_ok?C.green:d.short_ok?C.red:d.regime==="BULLISH_HIGH_VOL"?C.gold:C.muted;

  return(
    <div style={{background:C.bg,minHeight:"100vh",color:C.text,fontFamily:"'JetBrains Mono','Fira Code',monospace",fontSize:12.5}}>

      {/* TOPBAR */}
      <div style={{background:"#040609",borderBottom:`1px solid ${C.border}`,padding:"9px 20px",display:"flex",alignItems:"center",justifyContent:"space-between",position:"sticky",top:0,zIndex:100}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <div style={{width:7,height:7,borderRadius:"50%",background:live?C.green:C.gold,boxShadow:`0 0 6px ${live?C.green:C.gold}`}}/>
          <span style={{color:C.gold,fontWeight:900,fontSize:13}}>G-DIVE V4</span>
          <span style={{color:C.border2,fontSize:10}}>|</span>
          <span style={{color:C.muted,fontSize:10}}>BTC Options Intelligence · Deribit + Binance</span>
          <Pill color={regimeColor}>{d.regime?.replace("_"," ")}</Pill>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{fontSize:28,fontWeight:900,fontFamily:"monospace",color:C.text}}>{fmtK(d.spot)}</span>
          <span style={{color:live?C.green:C.gold,fontSize:10}}>{busy?"⟳":live?`● ${clock}`:`◆ DEMO`}</span>
          <button onClick={refresh} disabled={busy} style={{background:C.card,border:`1px solid ${C.border}`,color:C.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:10}}>↺</button>
        </div>
      </div>

      <div style={{padding:"16px 20px",display:"flex",flexDirection:"column",gap:0}}>

        {/* KATMAN 1 */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${aboveHVL?C.green:C.orange}`}}>
          <LayerHead num="1" title="Piyasa Temeli — Neredeyiz?" subtitle="Spot konumu, Gamma Rejimi ve HVL seviyesi tüm kararların temelidir" status={aboveHVL?"LONG BÖLGE":"SHORT BÖLGE"} statusColor={aboveHVL?C.green:C.orange}/>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:10,marginBottom:14}}>
            {[
              {l:"BTC Spot",v:fmtK(d.spot),c:C.blue,sub:"Son işlem fiyatı"},
              {l:"High Vol Level",v:fmtK(d.hvl),c:C.gold,sub:`Spot ${aboveHVL?`+${distHVL}% üstünde`:`-${distHVL}% altında`}`},
              {l:"Gamma Rejimi",v:d.gamma_regime==="LONG_GAMMA"?"LONG GAMMA":d.gamma_regime==="TRANSITION"?"GEÇİŞ":"SHORT GAMMA",c:d.gamma_regime==="LONG_GAMMA"?C.green:d.gamma_regime==="TRANSITION"?C.gold:C.red,sub:d.gamma_regime==="LONG_GAMMA"?"Dealer vol söndürür":d.gamma_regime==="TRANSITION"?"Flip yakını dikkat":"Dealer vol büyütür"},
              {l:"Net GEX",v:`${gp?"+":""}${d.total_net_gex?.toFixed(0)}M`,c:gp?C.green:C.orange,sub:"Toplam dealer gamma"},
            ].map((s,i)=>(
              <div key={i} style={{padding:"10px 12px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:7}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:3}}>{s.l}</div>
                <div style={{color:s.c,fontSize:18,fontWeight:900,fontFamily:"monospace",lineHeight:1,marginBottom:2}}>{s.v}</div>
                <div style={{color:C.muted,fontSize:9}}>{s.sub}</div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
            <InsightBox icon="◆" type={aboveHVL?"bull":"warn"} text={aboveHVL?`Spot ${fmtK(d.spot)} > HVL ${fmtK(d.hvl)}. POZİTİF GAMMA — Dealer vol söndürür, LONG bölge.`:`Spot ${fmtK(d.spot)} < HVL ${fmtK(d.hvl)}. NEGATİF GAMMA — Dealer vol büyütür, volatilite üretir. Dikkatli.`}/>
            <InsightBox icon="◆" type={gp?"bull":"bear"} text={gp?`Net GEX +${d.total_net_gex?.toFixed(0)}M — Piyasada call ağırlıklı open interest hakim. Dealer, fiyat yükselince satar (söndürür).`:`Net GEX ${d.total_net_gex?.toFixed(0)}M — Put baskısı hakim. Dealer, fiyat düşünce alır (büyütür). Dikkatli ol.`}/>
          </div>
        </div>

        <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}><div style={{width:1,height:20,background:`linear-gradient(${C.border},${C.border2})`}}/></div>

        {/* KATMAN 2 */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${C.blue}`}}>
          <LayerHead num="2" title="Opsiyon Piyasası — Ne Fiyatlanıyor?" subtitle="GEX haritası, IV durumu, term structure ve MenthorQ kurumsal akış analizi" status={`IV ${d.iv_rank?.toFixed(0)}%`} statusColor={d.iv_rank>70?C.red:d.iv_rank>40?C.gold:C.green}/>

          {d.gamma_analysis&&(
            <div style={{background:d.gamma_analysis.regime==="POSITIVE_GAMMA"?"#002a1a":d.gamma_analysis.regime==="FLIP_ZONE"?"#2a1e00":"#2a0010",border:"1px solid "+(d.gamma_analysis.regime==="POSITIVE_GAMMA"?"#00e59940":d.gamma_analysis.regime==="FLIP_ZONE"?"#ffbe2e40":"#ff3d5a40"),borderRadius:8,padding:"12px 16px",marginBottom:12}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
                <div style={{display:"flex",alignItems:"center",gap:10}}>
                  <div style={{width:10,height:10,borderRadius:"50%",background:d.gamma_analysis.regime==="POSITIVE_GAMMA"?"#00e599":d.gamma_analysis.regime==="FLIP_ZONE"?"#ffbe2e":"#ff3d5a"}}/>
                  <span style={{color:d.gamma_analysis.regime==="POSITIVE_GAMMA"?"#00e599":d.gamma_analysis.regime==="FLIP_ZONE"?"#ffbe2e":"#ff3d5a",fontWeight:700,fontSize:11}}>
                    {d.gamma_analysis.regime==="POSITIVE_GAMMA"?"✓ Pozitif Gamma — LONG Bölge":d.gamma_analysis.regime==="FLIP_ZONE"?"⚡ FLIP — Trade Açma":d.gamma_analysis.regime==="MIXED_NEGATIVE"?"⚡ Geçiş — GEX Pozitif ama Spot HVL Altında (Bekle)":"● Negatif Gamma — SHORT Bölge"}
                  </span>
                </div>
                <div style={{display:"flex",gap:8}}>
                  {d.max_pain&&<span style={{color:"#9d7aff",fontSize:9,background:"#9d7aff15",border:"1px solid #9d7aff30",padding:"2px 8px",borderRadius:4}}>Max Pain ${d.max_pain.toLocaleString()}</span>}
                  {d.expiry&&<span style={{color:d.expiry.expiry_week?"#ffbe2e":"#3d5470",fontSize:9,background:"#ffffff08",border:"1px solid #1a2535",padding:"2px 8px",borderRadius:4}}>Expiry {d.expiry.days_to_expiry}g</span>}
                </div>
              </div>
              <div style={{color:"#dce8f5",fontSize:11,lineHeight:1.7,marginBottom:8}}>{d.gamma_analysis.description}</div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8}}>
                {[
                  {l:"Flip Noktası",v:d.flip_point?"$"+d.flip_point.toLocaleString("en-US",{maximumFractionDigits:0}):"—",c:"#ffbe2e"},
                  {l:"Flip Mesafesi",v:d.gamma_analysis.flip_distance_pct?.toFixed(1)+"%",c:d.gamma_analysis.flip_near?"#ff3d5a":d.gamma_analysis.flip_distance_pct<5?"#ffbe2e":"#00e599"},
                  {l:"Max Pain",v:d.max_pain?"$"+d.max_pain.toLocaleString():"—",c:"#9d7aff"},
                  {l:"Expiry",v:d.expiry?d.expiry.days_to_expiry+"g kaldı":"—",c:d.expiry?.expiry_week?"#ffbe2e":"#3d5470"},
                ].map((s,i)=>(
                  <div key={i} style={{padding:"6px 8px",background:"rgba(0,0,0,0.3)",borderRadius:5}}>
                    <div style={{color:"#3d5470",fontSize:8.5,marginBottom:2}}>{s.l}</div>
                    <div style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{s.v}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:8,marginBottom:14}}>
            {[
              {l:"Front IV",v:pct(d.front_iv),c:d.front_iv>65?C.red:d.front_iv>45?C.gold:C.green,sub:"30 günlük ATM"},
              {l:"IV Rank",v:pct(d.iv_rank),c:d.iv_rank>70?C.red:d.iv_rank>40?C.gold:C.green,sub:"52 haftalık yüzdelik"},
              {l:"HV 30D",v:pct(d.hv_30d||68),c:C.muted,sub:"Gerçekleşen volatilite"},
              {l:"P/C OI",v:d.pc_ratio?.toFixed(2),c:d.pc_ratio>1.2?C.green:d.pc_ratio<0.7?C.red:C.text,sub:d.pc_ratio>1.2?"Put ağırlıklı":d.pc_ratio<0.7?"Call ağırlıklı":"Dengeli"},
            ].map((s,i)=>(
              <div key={i} style={{padding:"10px 12px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:7}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:3}}>{s.l}</div>
                <div style={{color:s.c,fontSize:18,fontWeight:900,fontFamily:"monospace"}}>{s.v}</div>
                <div style={{color:C.muted,fontSize:9}}>{s.sub}</div>
              </div>
            ))}
          </div>

          <div style={{display:"grid",gridTemplateColumns:"560px 1fr 1fr",gap:14,marginBottom:14}}>
            <div>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:8}}>Net GEX Haritası — Tüm Vadeler</div>
              <GEXBar data={gexRows} spot={d.spot} hvl={d.hvl} callRes={d.call_resistance} putSup={d.put_support}/>
              <div style={{display:"flex",gap:14,fontSize:9.5,marginTop:4,color:C.muted}}>
                <span><span style={{color:C.green}}>──</span> CR {fmtK(d.call_resistance)}</span>
                <span><span style={{color:C.gold}}>──</span> HVL {fmtK(d.hvl)}</span>
                <span><span style={{color:C.red}}>──</span> PS {fmtK(d.put_support)}</span>
              </div>
            </div>
            <div>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:8}}>
                ATM Term Structure
                <Pill color={d.term_shape==="CONTANGO"?C.green:C.red}>{d.term_shape}</Pill>
              </div>
              <TermLine data={d.term_ivs||[]}/>
              <InsightBox icon="📈" type={d.term_shape==="CONTANGO"?"info":"warn"} text={d.term_shape==="CONTANGO"?"Contango: Uzun vadeli IV > kısa vadeli. Normal beklenti yapısı, büyük yakın hareket fiyatlanmıyor.":"Backwardation: Kısa vadeli IV yüksek. Piyasa yakın dönemde önemli hareket bekliyor."}/>
            </div>
            <div>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:8}}>Kritik Seviyeler</div>
              {[{l:"Call Resistance",v:fmtK(d.call_resistance),c:C.green,sub:"Üst GEX duvarı"},{l:"Spot",v:fmtK(d.spot),c:C.blue,sub:"Şu anki fiyat"},{l:"HVL",v:fmtK(d.hvl),c:C.gold,sub:"Gamma flip noktası"},{l:"Put Support",v:fmtK(d.put_support),c:C.red,sub:"Alt GEX duvarı"},{l:"CR 0DTE",v:fmtK(d.call_resistance_0dte),c:"#44e8a0",sub:"Bugünlük direnç"},{l:"PS 0DTE",v:fmtK(d.put_support_0dte),c:"#ff6b50",sub:"Bugünlük destek"}].map((s,i)=>(
                <div key={i} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 7px",background:s.l==="Spot"?`${C.blue}10`:C.card2,border:`1px solid ${s.l==="Spot"?C.blue+"40":C.border}`,borderRadius:4,marginBottom:3}}>
                  <div><div style={{color:C.muted,fontSize:8.5}}>{s.l}</div><div style={{color:C.dim,fontSize:8}}>{s.sub}</div></div>
                  <span style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{s.v}</span>
                </div>
              ))}
            </div>
          </div>

          {(d.funding_manipulation||d.carry_arb)&&(
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:14}}>
              <div style={{background:d.funding_manipulation?.alert?"#ff3d5a08":C.card2,border:`1px solid ${d.funding_manipulation?.alert?"#ff3d5a40":C.border}`,borderLeft:`3px solid ${d.funding_manipulation?.alert?"#ff3d5a":C.border}`,borderRadius:8,padding:"10px 14px"}}>
                <div style={{color:d.funding_manipulation?.alert?"#ff3d5a":C.muted,fontSize:9,textTransform:"uppercase",marginBottom:5}}>{d.funding_manipulation?.alert?"⚡ MANIPULATION ALERT":"Funding Durumu"}</div>
                <div style={{color:C.text,fontSize:10.5,lineHeight:1.6,marginBottom:5}}>{d.funding_manipulation?.description||"Veri bekleniyor..."}</div>
                <div style={{display:"flex",gap:12,fontSize:9.5}}>
                  <span style={{color:C.muted}}>Yıllık: <span style={{color:C.gold,fontFamily:"monospace"}}>{d.funding_manipulation?.annualized_pct?.toFixed(1)}%</span></span>
                  <span style={{color:d.funding_manipulation?.signal==="CONTRARIAN_LONG"?C.green:d.funding_manipulation?.signal==="CONTRARIAN_SHORT"?C.red:C.muted,fontWeight:700}}>{d.funding_manipulation?.signal}</span>
                </div>
              </div>
              <div style={{background:d.carry_arb?.profitable?C.greenDim:C.card2,border:`1px solid ${d.carry_arb?.profitable?"#00e59930":C.border}`,borderRadius:8,padding:"10px 14px"}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:5}}>Cash & Carry Arb</div>
                <div style={{color:d.carry_arb?.profitable?C.green:C.red,fontSize:22,fontWeight:700,fontFamily:"monospace"}}>{d.carry_arb?.total_return_pct?.toFixed(1)}%<span style={{fontSize:10,color:C.muted}}> yıllık</span></div>
                <div style={{color:d.carry_arb?.profitable?C.green:C.muted,fontSize:10,fontWeight:700,marginBottom:4}}>{d.carry_arb?.verdict}</div>
                <div style={{fontSize:9,color:C.muted}}>Break-even: {d.carry_arb?.break_even_funding_pct?.toFixed(1)}%</div>
                {d.carry_arb?.profitable&&<div style={{marginTop:4,fontSize:9,color:C.green}}>Spot LONG + Perp SHORT → funding topla</div>}
              </div>
            </div>
          )}
          {mq&&(
            <div style={{background:C.card2,border:`1px solid ${C.border}`,borderRadius:8,padding:"12px 14px"}}>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:10}}>MenthorQ Kurumsal Akış Analizi — Gamma · Dealer · Flow</div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr) 2fr",gap:10}}>
                {[
                  {l:"Gamma Z",v:mq.gamma_z?.toFixed(3),c:mq.gamma_z>0.5?C.green:mq.gamma_z<-0.5?C.red:C.gold,desc:"Wall konsantrasyon yoğunluğu"},
                  {l:"Dealer Bias",v:mq.dealer_bias?.toFixed(3),c:mq.dealer_bias>0.2?C.green:mq.dealer_bias<-0.2?C.red:C.muted,desc:"(Call-Put OI)/Total OI"},
                  {l:"Flow Score",v:mq.flow_score?.toFixed(3),c:mq.flow_score>0.2?C.green:mq.flow_score<-0.2?C.red:C.muted,desc:"ATM ağırlıklı yön akışı"},
                  {l:"MQ Score",v:mq.score?.toFixed(3),c:mq.score>0.2?C.green:mq.score<-0.2?C.red:C.gold,desc:"0.5γ+0.3bias+0.2flow"},
                ].map((s,i)=>(
                  <div key={i} style={{padding:"8px 10px",background:C.card,border:`1px solid ${C.border}`,borderRadius:6}}>
                    <div style={{color:C.muted,fontSize:8.5,marginBottom:2}}>{s.l}</div>
                    <div style={{color:s.c,fontWeight:900,fontSize:20,fontFamily:"monospace"}}>{s.v}</div>
                    <div style={{color:C.dim,fontSize:8,marginTop:2}}>{s.desc}</div>
                  </div>
                ))}
                <div style={{display:"flex",flexDirection:"column",gap:6}}>
                  {[{l:"MQ Scalar",v:mq.scalar?.toFixed(3)+"×",c:mq.scalar>=1.04?C.green:mq.scalar<=0.96?C.red:C.gold,sub:mq.regime},{l:"Final Layer",v:lb?.final_scalar?.toFixed(3)+"×",c:lb?.final_scalar>=1.02?C.green:lb?.final_scalar<=0.97?C.red:C.gold,sub:"Funding×MQ"},{l:"Posisyon",v:lb?.final_scalar>=1?"Normal":"Küçültülmüş",c:lb?.final_scalar>=1?C.green:C.orange,sub:`$${(10000*0.02*2*(lb?.final_scalar||1)).toFixed(0)} risk`}].map((s,i)=>(
                    <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 7px",background:C.card,border:`1px solid ${C.border}`,borderRadius:4}}>
                      <div><div style={{color:C.muted,fontSize:8.5}}>{s.l}</div><div style={{color:C.dim,fontSize:7.5}}>{s.sub}</div></div>
                      <span style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:12}}>{s.v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}><div style={{width:1,height:20,background:`linear-gradient(${C.border},${C.border2})`}}/></div>

        {/* KATMAN 3 */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${conf?.color||C.purple}`}}>
          <LayerHead num="3" title="Teknik Analiz — Fiyat Ne Yapıyor?" subtitle="Binance 4H ve 1H mum verisi üzerinde EMA, RSI, MACD, Bollinger Bands analizi" status={conf?conf.label:"Yükleniyor"} statusColor={conf?.color||C.muted}/>
          <TeknikPanel optData={d} onConf={setConf}/>
        </div>

        <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}><div style={{width:1,height:20,background:`linear-gradient(${C.border},${C.border2})`}}/></div>

        {/* KATMAN 4 */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${C.cyan}`}}>
          <LayerHead num="4" title="Sinyal Sentezi — Ne Diyor?" subtitle="QScore opsiyon zekası ile teknik sinyal bir araya geliyor" status="OPSİYON PUANLAR" statusColor={C.cyan}/>
          <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:10,marginBottom:14}}>
            {[
              {score:d.option_score??0,label:"Option Score",meaning:aboveHVL&&d.option_score>=4?"Bullish + HVL ustunde":!aboveHVL&&d.option_score>=4?"OI bullish ama Spot HVL altinda - bekleme":d.option_score>=3?"Notr opsiyon akisi":"Bearish opsiyon yapisi",color:d.option_score>=4&&aboveHVL?C.green:d.option_score>=4?C.gold:d.option_score>=3?C.gold:C.red,detail:`P/C: ${d.pc_ratio?.toFixed(2)} - GEX: ${gp?"+":""}${d.total_net_gex?.toFixed(0)}M - Gamma: ${d.gamma_regime==="LONG_GAMMA"?"Pozitif":"Negatif"}`},
              {score:d.vol_score??0,label:"Volatilite Score",meaning:d.vol_score>=4?"Yüksek IV — Piyasa büyük hareket fiyatlıyor":d.vol_score>=3?"Orta volatilite":"Düşük IV, hareket beklentisi yok",color:d.vol_score>=4?C.orange:d.vol_score>=3?C.gold:C.green,detail:`Front IV: ${d.front_iv?.toFixed(1)}% · Rank: ${d.iv_rank?.toFixed(0)}%`},
              {score:d.momentum_score??3,label:"Momentum Score",meaning:d.momentum_score>=4?"Güçlü yukarı momentum":d.momentum_score>=3?"Nötr momentum":"Bearish momentum",color:d.momentum_score>=4?C.green:d.momentum_score>=3?C.gold:C.red,detail:`Spot ${aboveHVL?">":"<"} HVL · ${d.regime?.replace("_"," ")}`},
            ].map((s,i)=>(
              <div key={i} style={{background:C.card2,border:`1px solid ${C.border}`,borderTop:`2px solid ${s.color}`,borderRadius:8,padding:"14px"}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:6}}>{s.label}</div>
                <div style={{display:"flex",alignItems:"flex-end",gap:8,marginBottom:4}}>
                  <div style={{color:s.color,fontSize:48,fontWeight:900,lineHeight:1}}>{s.score}</div>
                  <div style={{paddingBottom:6}}><span style={{color:C.text,fontSize:13,fontWeight:700}}>/5</span></div>
                </div>
                <Bar pct={(s.score/5)*100} color={s.color} height={4}/>
                <div style={{color:s.color,fontSize:10.5,fontWeight:600,marginTop:6}}>{s.meaning}</div>
                <div style={{color:C.muted,fontSize:9.5,marginTop:2}}>{s.detail}</div>
              </div>
            ))}
          </div>
          {bt&&(
            <div style={{background:C.card2,border:`1px solid ${C.border}`,borderRadius:8,padding:"12px 14px"}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase"}}>Backtest Performansı — 4H 500 Bar ATR Bazlı Sistem</div>
                <div style={{display:"flex",gap:6}}>
                  <Pill color={bt.pf>=1.5?C.green:bt.pf>=1?C.gold:C.red}>PF {bt.pf}×</Pill>
                  <Pill color={bt.wr>=55?C.green:bt.wr>=45?C.gold:C.red}>WR {bt.wr}%</Pill>
                </div>
              </div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:6,marginBottom:8}}>
                {[{l:"Trade",v:bt.trades,c:C.muted},{l:"Win Rate",v:bt.wr+"%",c:bt.wr>=50?C.green:C.orange},{l:"Max DD",v:bt.maxDD+"%",c:bt.maxDD<10?C.green:bt.maxDD<20?C.gold:C.red},{l:"Avg Win",v:"+$"+bt.aw,c:C.green},{l:"Avg Loss",v:"-$"+bt.al,c:C.red},{l:"Beklenti",v:(bt.exp>=0?"+":"")+bt.exp,c:bt.exp>=0?C.green:C.red},{l:"Toplam PnL",v:(bt.totalPnl>=0?"+":"")+bt.totalPnl,c:bt.totalPnl>=0?C.green:C.red},{l:"Son Equity",v:"$"+bt.finalEq,c:bt.finalEq>=10000?C.green:C.red},{l:"Profit Factor",v:bt.pf+"×",c:bt.pf>=1.5?C.green:bt.pf>=1?C.gold:C.red},{l:"R:R Oran",v:(bt.aw/bt.al).toFixed(1)+"×",c:(bt.aw/bt.al)>=2?C.green:C.gold}].map((s,i)=>(
                  <div key={i} style={{padding:"6px 8px",background:C.card,border:`1px solid ${C.border}`,borderRadius:5}}>
                    <div style={{color:C.muted,fontSize:8.5,marginBottom:1}}>{s.l}</div>
                    <div style={{color:s.c,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{s.v}</div>
                  </div>
                ))}
              </div>
              {bt.exp<0&&<InsightBox icon="⚠" type="warn" text={`Negatif beklenti $${bt.exp}/trade — ATR stop mesafesi 2× çok geniş olabilir. RR 3:1 → 2:1'e düşürmeyi veya daha sıkı filtreler eklemeyi düşün.`}/>}
              {bt.exp>=0&&<InsightBox icon="✦" type="bull" text={`Pozitif beklenti +$${bt.exp}/trade. ${bt.trades} trade, WR ${bt.wr}% — sistem istatistiksel olarak kârlı.`}/>}
            </div>
          )}
        </div>

        <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}><div style={{width:1,height:20,background:`linear-gradient(${C.border2},${C.purple})`}}/></div>

        {/* ═══════════════════════════════════════════════════════════
            KATMAN 5 — LLM FİLTRE (YENİ)
        ════════════════════════════════════════════════════════════ */}
        <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${C.purple}`}}>
          <LayerHead
            num="5"
            title="LLM Makro Filtre — Gamma Sinyalini Onaylıyor mu?"
            subtitle="Fed/FOMC metni + Deribit sentiment + GEX verileri otomatik çekilir, Claude gamma sinyalini filtreler"
            status="ONAYLA / VETO / NÖTR"
            statusColor={C.purple}
          />
          <LLMFilterPanel
            gammaScore={gammaScore}
            regime={gammaRegime}
            isLive={live}
          />
        </div>

        <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}><div style={{width:1,height:20,background:`linear-gradient(${C.purple},${d.long_ok?C.green:d.short_ok?C.red:C.muted})`}}/></div>

        {/* KATMAN 6 — TRADE KOMUTA MERKEZİ */}
        <div style={{background:C.card,border:`1px solid ${d.long_ok?C.green:d.short_ok?C.red:C.border}`,borderRadius:12,padding:"16px 18px",borderLeft:`4px solid ${d.long_ok?C.green:d.short_ok?C.red:C.muted}`,boxShadow:d.long_ok?`0 0 20px ${C.green}15`:d.short_ok?`0 0 20px ${C.red}15`:"none"}}>
          <LayerHead num="6" title="Trade Komuta Merkezi — Plan Ne?" subtitle="Sistem kararı, giriş/çıkış planı, risk yönetimi ve açık pozisyon durumu" status={d.long_ok?"▲ LONG OK":d.short_ok?"▼ SHORT OK":"— BEKLE"} statusColor={d.long_ok?C.green:d.short_ok?C.red:C.muted}/>

          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:14}}>
            <div>
              <Divider label="Sistem Kararı"/>
              <div style={{background:d.long_ok?C.greenDim:d.short_ok?C.redDim:C.card2,border:`1px solid ${d.long_ok?C.green:d.short_ok?C.red:C.border}40`,borderRadius:8,padding:"14px",marginBottom:12}}>
                <div style={{color:d.long_ok?C.green:d.short_ok?C.red:C.muted,fontSize:26,fontWeight:900,marginBottom:4}}>{d.long_ok?"▲ LONG AÇILIYOR":d.short_ok?"▼ SHORT AÇILIYOR":"— HENÜZ YOK"}</div>
                <div style={{color:C.muted,fontSize:10.5,lineHeight:1.6}}>
                  {d.long_ok?`Regime ${d.regime?.replace("_"," ")} · Spot HVL üstünde · GEX pozitif.`:d.short_ok?`Regime ${d.regime?.replace("_"," ")} · Spot HVL altında · GEX negatif. SHORT koşulları sağlandı.`:`Regime ${d.regime?.replace("_"," ")} · ${aboveHVL?"Teknik sinyal bekleniyor":"Spot HVL altında — LONG için bekleme"}.`}
                </div>
              </div>
              <Divider label="Giriş/Çıkış Planı"/>
              <div style={{display:"flex",flexDirection:"column",gap:6}}>
                {[
                  {l:"Stop Loss",v:fmtK(d.put_support),c:C.red,bg:C.redDim,desc:"Put Support — burası kırılırsa çık",icon:"✕"},
                  {l:"1. TP (50%)",v:fmtK(d.call_resistance),c:C.green,bg:C.greenDim,desc:"Call Resistance — yarısını kapat, kalan devam",icon:"◆"},
                  {l:"2. TP (50%)",v:d.call_walls?.[1]?fmtK(d.call_walls[1]):"Sonraki Wall",c:"#44e8a0",bg:C.greenDim,desc:"Sonraki Call Wall — kalan pozisyon",icon:"◆"},
                  {l:"Çıkış (Rejim)",v:"Koşul bozulunca",c:C.orange,bg:C.goldDim,desc:"Regime SHORT'a dönerse → tüm poz kapat",icon:"↩"},
                ].map((s,i)=>(
                  <div key={i} style={{display:"flex",gap:10,alignItems:"center",padding:"8px 10px",background:s.bg||C.card2,border:`1px solid ${s.c}25`,borderRadius:6}}>
                    <span style={{color:s.c,fontSize:13,flexShrink:0}}>{s.icon}</span>
                    <div style={{flex:1}}>
                      <div style={{display:"flex",justifyContent:"space-between",marginBottom:1}}>
                        <span style={{color:C.muted,fontSize:9.5,textTransform:"uppercase"}}>{s.l}</span>
                        <span style={{color:s.c,fontWeight:900,fontFamily:"monospace",fontSize:13}}>{s.v}</span>
                      </div>
                      <div style={{color:C.dim,fontSize:9}}>{s.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <Divider label="Risk Yönetimi"/>
              {risk&&(
                <div style={{display:"flex",flexDirection:"column",gap:6,marginBottom:12}}>
                  {[
                    {l:"Sermaye",v:"$"+risk.equity,c:risk.equity>=10000?C.green:C.red,desc:`Başlangıç: $10,000`},
                    {l:"Günlük P&L",v:(risk.dPnl>=0?"+":"")+risk.dPnl+" / limit -$"+risk.dLimit,c:risk.dPnl<-risk.dLimit?C.red:risk.dPnl>=0?C.green:C.orange,desc:"Günlük zarar limiti: sermayenin %2'si"},
                    {l:"Max Drawdown",v:risk.mdd+"% / limit %10",c:risk.mdd>=10?C.red:risk.mdd>=5?C.gold:C.green,desc:"Peak'ten düşüş — %10 aşılırsa kill switch"},
                    {l:"Açık Pozisyon",v:risk.openCount+" / max 2",c:risk.openCount>=2?C.orange:C.green,desc:"Aynı anda max 2 pozisyon"},
                    {l:"Kill Switch",v:risk.killSwitch?"⚠ AKTİF — SİSTEM DURDU":"✓ Normal",c:risk.killSwitch?C.red:C.green,desc:"Günlük limit veya max DD aşılırsa aktif"},
                  ].map((s,i)=>(
                    <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"7px 10px",background:s.l==="Kill Switch"&&risk.killSwitch?`${C.red}10`:C.card2,border:`1px solid ${s.l==="Kill Switch"&&risk.killSwitch?C.red:C.border}`,borderRadius:5}}>
                      <div><div style={{color:C.muted,fontSize:9}}>{s.l}</div><div style={{color:C.dim,fontSize:8}}>{s.desc}</div></div>
                      <span style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:10.5,textAlign:"right",maxWidth:160}}>{s.v}</span>
                    </div>
                  ))}
                </div>
              )}
              <Divider label="Pozisyon Büyüklüğü"/>
              <div style={{background:C.card2,border:`1px solid ${C.border}`,borderRadius:6,padding:"10px 12px"}}>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
                  {[
                    {l:"Risk/Trade",v:`$${(10000*0.02*2*(lb?.final_scalar||1)).toFixed(0)}`,c:C.text,desc:"2x kaldıraç, %4 nominal"},
                    {l:"Layer Scalar",v:(lb?.final_scalar||1)?.toFixed(3)+"×",c:lb?.final_scalar>=1?C.green:C.orange,desc:"MenthorQ × Funding"},
                    {l:"BTC Ağırlık",v:((ma?.weights?.BTC||0)*100).toFixed(1)+"%",c:C.orange,desc:"Multi-asset portföy"},
                    {l:"Realized Vol",v:((ma?.realized_vol||0)*100).toFixed(1)+"%",c:(ma?.realized_vol||0)>0.6?C.red:C.green,desc:"30 günlük volatilite"},
                  ].map((s,i)=>(
                    <div key={i} style={{padding:"7px 8px",background:C.card,border:`1px solid ${C.border}`,borderRadius:4}}>
                      <div style={{color:C.muted,fontSize:8.5,marginBottom:1}}>{s.l}</div>
                      <div style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:13}}>{s.v}</div>
                      <div style={{color:C.dim,fontSize:8}}>{s.desc}</div>
                    </div>
                  ))}
                </div>
              </div>

              <Divider label="Kritik GEX Seviyeleri"/>
              <div style={{display:"flex",flexDirection:"column",gap:3}}>
                {[...(d.pos_gex_nodes||[]).slice(0,3).map(n=>({...n,c:C.green})),...(d.neg_gex_nodes||[]).slice(0,3).map(n=>({...n,c:C.red}))].sort((a,b)=>b.strike-a.strike).map((n,i)=>(
                  <div key={i} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"4px 7px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:4}}>
                    <span style={{color:C.muted,fontFamily:"monospace",fontSize:10}}>${n.strike?.toLocaleString()}</span>
                    <div style={{display:"flex",alignItems:"center",gap:8}}>
                      <div style={{width:clamp(Math.abs(n.net_gex)/35*60,2,60),height:4,background:n.c,borderRadius:99,opacity:0.7}}/>
                      <span style={{color:n.c,fontWeight:700,fontFamily:"monospace",fontSize:10.5}}>{n.net_gex>=0?"+":""}{n.net_gex?.toFixed(1)}M</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div style={{marginTop:12,padding:"8px 0",display:"flex",justifyContent:"space-between",fontSize:9,color:C.dim,borderTop:`1px solid ${C.border}`}}>
          <span>G-DIVE V4 · Deribit + Binance · Railway API · {d.n_contracts?.toLocaleString()} kontrat analiz edildi</span>
          <span>{live?`● Canlı · ${clock} · ${d._elapsed}s`:`◆ Demo · ${clock}`}</span>
        </div>
      </div>
    </div>
  );
}
