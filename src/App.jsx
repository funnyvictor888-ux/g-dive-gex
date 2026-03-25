import { useState, useEffect, useCallback, useRef } from "react";

// ── Config ────────────────────────────────────────────────────────
const SERVER_URL = window.location.hostname === "localhost"
  ? "http://localhost:7432"
  : "https://web-production-909e6.up.railway.app";

// ── Theme ─────────────────────────────────────────────────────────
const C = {
  bg:      "#080b10",
  surface: "#0d1117",
  card:    "#111720",
  card2:   "#161d28",
  border:  "#1e2a3a",
  border2: "#243040",
  text:    "#e2eaf4",
  muted:   "#4a6080",
  dim:     "#2a3a50",
  green:   "#00d68f",
  greenDim:"#003d28",
  red:     "#ff4d6a",
  redDim:  "#3d0010",
  orange:  "#ff8c42",
  gold:    "#ffc947",
  blue:    "#4db8ff",
  purple:  "#a78bfa",
  cyan:    "#22d3ee",
};

const DEMO = {
  spot:68129,ts:"2026-03-25 15:59 UTC",total_net_gex:3055.2,
  put_support:60000,call_resistance:75000,hvl:67000,
  put_support_0dte:68500,call_resistance_0dte:71000,
  front_iv:50.20,iv_rank:58.43,term_shape:"CONTANGO",
  pc_ratio:0.68,hv_30d:67.97,option_score:5,vol_score:5,momentum_score:3,
  gamma_regime:"LONG_GAMMA",regime:"BULLISH_HIGH_VOL",long_ok:true,short_ok:false,
  term_ivs:[{expiry:"25MAR",iv:55.2},{expiry:"28MAR",iv:52.1},{expiry:"4APR",iv:50.8},{expiry:"11APR",iv:50.2},{expiry:"25APR",iv:49.8},{expiry:"30MAY",iv:49.1},{expiry:"27JUN",iv:48.5},{expiry:"26SEP",iv:47.9}],
  call_walls:[75000,71000,80000,85000],put_walls:[60000,68500,65000,58000],
  pos_gex_nodes:[{strike:75000,net_gex:28.3},{strike:70000,net_gex:18.5},{strike:80000,net_gex:12.1},{strike:72000,net_gex:9.4}],
  neg_gex_nodes:[{strike:60000,net_gex:-25.8},{strike:65000,net_gex:-18.4},{strike:62000,net_gex:-12.1},{strike:66000,net_gex:-8.9}],
  n_contracts:8247,_source:"demo",
  menthorq:{gamma_z:0.8,dealer_bias:0.4,flow_score:0.3,scalar:1.04,regime:"positive",score:0.65,wall_adj:0},
  funding:{rate:0.0003,score:1,scalar:0.98,regime:"cautious"},
  layer_budget:{final_scalar:1.02,menthorq_scalar:1.04,funding_scalar:0.98},
  multi_asset:{weights:{BTC:0.55,GLD:0.28,TLT:0.17},realized_vol:0.42,posture:"RISK_ON",vol_target:0.20},
};

// ── Helpers ───────────────────────────────────────────────────────
const fmt  = n => n?.toLocaleString("en-US",{maximumFractionDigits:0});
const fmtK = n => `$${fmt(n)}`;
const pct  = n => `${(+n).toFixed(2)}%`;
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));

// ── Fetch ─────────────────────────────────────────────────────────
async function fetchLive() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 4000);
    const h = await fetch(`${SERVER_URL}/health`, {signal: ctrl.signal});
    if (!h.ok) return null;
    const r = await fetch(`${SERVER_URL}/data`);
    if (!r.ok) return null;
    const j = await r.json();
    return j.spot > 10000 ? {...j, _source:"server"} : null;
  } catch { return null; }
}

async function fetchBinancePrice() {
  try {
    const r = await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");
    if (!r.ok) return null;
    return +(await r.json()).price;
  } catch { return null; }
}

const BINANCE = "https://api.binance.com/api/v3/klines";
async function fetchOHLCV(interval="4h", limit=120) {
  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 7000);
    const r = await fetch(`${BINANCE}?symbol=BTCUSDT&interval=${interval}&limit=${limit}`, {signal: ctrl.signal});
    clearTimeout(tid);
    if (!r.ok) return null;
    const raw = await r.json();
    return raw.map(k => ({t:k[0],o:+k[1],h:+k[2],l:+k[3],c:+k[4],v:+k[5]}));
  } catch { return null; }
}

// ── Indicators ────────────────────────────────────────────────────
function calcEMA(c, p) { const k=2/(p+1); let e=c[0]; return c.map(v=>{e=v*k+e*(1-k);return e;}); }
function calcRSI(c, p=14) {
  let g=0,l=0;
  for(let i=1;i<=p;i++){const d=c[i]-c[i-1];d>=0?g+=d:l-=d;}
  let ag=g/p,al=l/p;
  const r=new Array(p).fill(null);
  r.push(al===0?100:100-100/(1+ag/al));
  for(let i=p+1;i<c.length;i++){const d=c[i]-c[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;r.push(al===0?100:100-100/(1+ag/al));}
  return r;
}
function calcMACD(c,f=12,s=26,sig=9) {
  const ef=calcEMA(c,f),es=calcEMA(c,s),m=ef.map((v,i)=>v-es[i]),signal=calcEMA(m,sig);
  return {macd:m,signal,hist:m.map((v,i)=>v-signal[i])};
}
function calcBB(c,p=20,mult=2) {
  return c.map((_,i)=>{
    if(i<p-1)return null;
    const s=c.slice(i-p+1,i+1),mean=s.reduce((a,b)=>a+b,0)/p,std=Math.sqrt(s.reduce((a,b)=>a+(b-mean)**2,0)/p);
    return {upper:mean+mult*std,middle:mean,lower:mean-mult*std};
  });
}

function analyzeCandles(candles) {
  if(!candles||candles.length<40) return null;
  const closes=candles.map(c=>c.c),n=closes.length-1;
  const ema9=calcEMA(closes,9),ema21=calcEMA(closes,21),rsis=calcRSI(closes,14);
  const {macd,signal,hist}=calcMACD(closes);
  const bbs=calcBB(closes,20);
  const price=closes[n],rsi=rsis[n],bb=bbs[n],macdV=macd[n],sigV=signal[n],histV=hist[n];
  let score=0;const reasons=[];
  const ec=ema9[n]>ema21[n],ecp=ema9[n-1]>ema21[n-1];
  if(ec){score++;reasons.push({txt:`EMA9 > EMA21`,bull:true});}
  else{score--;reasons.push({txt:`EMA9 < EMA21`,bull:false});}
  if(ec&&!ecp) reasons.push({txt:"⚡ Golden Cross",bull:true,strong:true});
  if(!ec&&ecp) reasons.push({txt:"⚡ Death Cross",bull:false,strong:true});
  if(rsi>70){score--;reasons.push({txt:`RSI ${rsi.toFixed(1)} OB`,bull:false});}
  else if(rsi<30){score++;reasons.push({txt:`RSI ${rsi.toFixed(1)} OS`,bull:true});}
  else if(rsi>55){score++;reasons.push({txt:`RSI ${rsi.toFixed(1)} Bull`,bull:true});}
  else if(rsi<45){score--;reasons.push({txt:`RSI ${rsi.toFixed(1)} Bear`,bull:false});}
  else reasons.push({txt:`RSI ${rsi.toFixed(1)} Nötr`,bull:null});
  if(macdV>sigV){score++;reasons.push({txt:`MACD Bull +${histV.toFixed(0)}`,bull:true});}
  else{score--;reasons.push({txt:`MACD Bear ${histV.toFixed(0)}`,bull:false});}
  if(bb){const bp=(price-bb.lower)/(bb.upper-bb.lower);
    if(bp>0.85){score--;reasons.push({txt:`BB Üst`,bull:false});}
    else if(bp<0.15){score++;reasons.push({txt:`BB Alt`,bull:true});}
    else if(bp>0.5){score++;reasons.push({txt:`BB Orta+`,bull:true});}}
  let sc,sl;
  if(score>=3){sc=C.green;sl="GÜÇLÜ LONG";}
  else if(score>=1){sc="#44e8a0";sl="ZAYIF LONG";}
  else if(score<=-3){sc=C.red;sl="GÜÇLÜ SHORT";}
  else if(score<=-1){sc=C.orange;sl="ZAYIF SHORT";}
  else{sc=C.muted;sl="BEKLE";}
  return {price,rsi,macdV,sigV,histV,ema9:ema9[n],ema21:ema21[n],bb,score,signal_color:sc,signal_label:sl,reasons};
}

function confluenceScore(t4,t1,opt) {
  if(!t4) return null;
  let score=0;const items=[];
  score+=t4.score; items.push({src:"4H Teknik",val:t4.score});
  if(t1){score+=Math.round(t1.score*0.5);items.push({src:"1H Teknik",val:Math.round(t1.score*0.5)});}
  if(opt.total_net_gex>0){score++;items.push({src:"GEX Pozitif",val:1});}
  else{score--;items.push({src:"GEX Negatif",val:-1});}
  if(opt.spot>opt.hvl){score++;items.push({src:"Spot > HVL",val:1});}
  else{score--;items.push({src:"Spot < HVL",val:-1});}
  const dc=(opt.call_resistance-opt.spot)/opt.spot*100;
  if(dc<3){score--;items.push({src:`CR Yakın ${dc.toFixed(1)}%`,val:-1});}
  if(dc>8){score++;items.push({src:`CR Uzak ${dc.toFixed(1)}%`,val:1});}
  let label,color;
  if(score>=5){label="GÜÇLÜ LONG";color=C.green;}
  else if(score>=2){label="ZAYIF LONG";color="#44e8a0";}
  else if(score<=-5){label="GÜÇLÜ SHORT";color=C.red;}
  else if(score<=-2){label="ZAYIF SHORT";color=C.orange;}
  else{label="NÖTR";color:C.muted;}
  return {score,label,color,items};
}

// ── Risk & Backtest ───────────────────────────────────────────────
const RISK_CONFIG = {initialCapital:10000,maxDailyLossPct:0.02,maxDrawdownPct:0.10,maxOpenPositions:2,killSwitchEnabled:true};

function getRiskStatus(trades) {
  const today=new Date().toISOString().slice(0,10),capital=RISK_CONFIG.initialCapital;
  const todayTrades=trades.filter(t=>t.status==="CLOSED"&&t.exitDate?.startsWith(today));
  const dailyPnl=todayTrades.reduce((a,t)=>a+(t.pnl||0),0);
  const dailyLossLimit=capital*RISK_CONFIG.maxDailyLossPct;
  const dailyLimitHit=dailyPnl<=-dailyLossLimit;
  let peak=capital,equity=capital,maxDD=0;
  trades.filter(t=>t.status==="CLOSED").sort((a,b)=>new Date(a.exitDate)-new Date(b.exitDate)).forEach(t=>{equity+=(t.pnl||0);if(equity>peak)peak=equity;const dd=(peak-equity)/peak;if(dd>maxDD)maxDD=dd;});
  const drawdownLimitHit=maxDD>=RISK_CONFIG.maxDrawdownPct;
  const openCount=trades.filter(t=>t.status==="OPEN").length;
  const killSwitch=RISK_CONFIG.killSwitchEnabled&&(dailyLimitHit||drawdownLimitHit);
  return {dailyPnl:+dailyPnl.toFixed(2),dailyLossLimit:+dailyLossLimit.toFixed(2),dailyLimitHit,maxDD:+(maxDD*100).toFixed(2),drawdownLimitHit,openCount,maxPosHit:openCount>=RISK_CONFIG.maxOpenPositions,killSwitch,equity:+equity.toFixed(2)};
}

function runBacktest(candles) {
  if(!candles||candles.length<60) return null;
  const closes=candles.map(c=>c.c),highs=candles.map(c=>c.h),lows=candles.map(c=>c.l);
  function ema(arr,p){const k=2/(p+1);let e=arr[0];return arr.map(v=>{e=v*k+e*(1-k);return e;});}
  function rsiArr(arr,p=14){let g=0,l=0;for(let i=1;i<=p;i++){const d=arr[i]-arr[i-1];d>=0?g+=d:l-=d;}let ag=g/p,al=l/p;const r=new Array(p).fill(null);r.push(al===0?100:100-100/(1+ag/al));for(let i=p+1;i<arr.length;i++){const d=arr[i]-arr[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;r.push(al===0?100:100-100/(1+ag/al));}return r;}
  function atr(h,l,c,p=14){const tr=h.map((hv,i)=>i===0?hv-l[i]:Math.max(hv-l[i],Math.abs(hv-c[i-1]),Math.abs(l[i]-c[i-1])));return ema(tr,p);}
  const ema9=ema(closes,9),ema21=ema(closes,21),rsis=rsiArr(closes,14);
  const macdLine=ema(closes,12).map((v,i)=>v-ema(closes,26)[i]),sig=ema(macdLine,9),atrs=atr(highs,lows,closes,14);
  const trades=[];let inTrade=false,tradeDir=null,entry=0,stop=0,tp=0,tradeSize=0;
  let equity=10000,peak=10000,maxDD=0;
  for(let i=30;i<closes.length-1;i++){
    const price=closes[i],atrV=atrs[i];
    if(inTrade){
      if(tradeDir==="LONG"){
        if(price<=stop){const pnl=(stop-entry)*tradeSize;trades.push({pnl:+pnl.toFixed(2),result:"STOP",dir:"LONG"});equity+=pnl;inTrade=false;}
        else if(price>=tp){const pnl=(tp-entry)*tradeSize;trades.push({pnl:+pnl.toFixed(2),result:"TP",dir:"LONG"});equity+=pnl;inTrade=false;}
      } else {
        if(price>=stop){const pnl=(entry-stop)*tradeSize;trades.push({pnl:+pnl.toFixed(2),result:"STOP",dir:"SHORT"});equity+=pnl;inTrade=false;}
        else if(price<=tp){const pnl=(entry-tp)*tradeSize;trades.push({pnl:+pnl.toFixed(2),result:"TP",dir:"SHORT"});equity+=pnl;inTrade=false;}
      }
      if(equity>peak)peak=equity;const dd=(peak-equity)/peak;if(dd>maxDD)maxDD=dd;
    }
    if(!inTrade&&atrV>0){
      const bull=ema9[i]>ema21[i]&&rsis[i]>50&&rsis[i]<70&&macdLine[i]>sig[i];
      const bear=ema9[i]<ema21[i]&&rsis[i]<50&&rsis[i]>30&&macdLine[i]<sig[i];
      const riskAmt=equity*0.04;
      if(bull){entry=price;stop=price-atrV*2;tp=price+atrV*6;tradeSize=riskAmt/(atrV*2);inTrade=true;tradeDir="LONG";}
      else if(bear){entry=price;stop=price+atrV*2;tp=price-atrV*6;tradeSize=riskAmt/(atrV*2);inTrade=true;tradeDir="SHORT";}
    }
  }
  if(!trades.length) return null;
  const wins=trades.filter(t=>t.pnl>0),losses=trades.filter(t=>t.pnl<0);
  const totalPnl=trades.reduce((a,t)=>a+t.pnl,0);
  const winRate=wins.length/trades.length*100;
  const avgWin=wins.length?wins.reduce((a,t)=>a+t.pnl,0)/wins.length:0;
  const avgLoss=losses.length?Math.abs(losses.reduce((a,t)=>a+t.pnl,0)/losses.length):1;
  const pf=avgLoss>0?Math.abs(wins.reduce((a,t)=>a+t.pnl,0))/Math.abs(losses.reduce((a,t)=>a+t.pnl,0)||1):0;
  const meanP=totalPnl/trades.length,stdP=Math.sqrt(trades.reduce((a,t)=>a+(t.pnl-meanP)**2,0)/trades.length);
  const sharpe=stdP>0?(meanP/stdP)*Math.sqrt(12):0;
  return {trades:trades.length,wins:wins.length,winRate:+winRate.toFixed(1),totalPnl:+totalPnl.toFixed(2),finalEquity:+equity.toFixed(2),maxDD:+(maxDD*100).toFixed(2),profitFactor:+pf.toFixed(2),sharpe:+sharpe.toFixed(2),avgWin:+avgWin.toFixed(2),avgLoss:+avgLoss.toFixed(2),expectancy:+((winRate/100*avgWin-(1-winRate/100)*avgLoss)).toFixed(2)};
}

// ── Smart Notes Generator ─────────────────────────────────────────
function generateNotes(d, conf, bt) {
  const notes = [];
  if(!d) return notes;
  // GEX notu
  if(d.total_net_gex > 5000) notes.push({type:"bull",icon:"◆",text:`Net GEX +${d.total_net_gex.toFixed(0)}M — Dealer hedge alımları spot'u destekliyor`});
  else if(d.total_net_gex < -2000) notes.push({type:"bear",icon:"◆",text:`Net GEX ${d.total_net_gex.toFixed(0)}M — Dealer hedge satışları volatiliteyi artırabilir`});
  // IV notu
  if(d.iv_rank > 70) notes.push({type:"warn",icon:"⚡",text:`IV Rank ${d.iv_rank.toFixed(0)}% — Opsiyon primleri pahalı, satış stratejileri avantajlı`});
  else if(d.iv_rank < 25) notes.push({type:"info",icon:"⚡",text:`IV Rank ${d.iv_rank.toFixed(0)}% — IV düşük, yakın volatilite patlama olabilir`});
  // Term structure
  if(d.term_shape==="BACKWARDATION") notes.push({type:"warn",icon:"📉",text:`Backwardation — Kısa vade IV yüksek, piyasa yakın hareketi fiyatlıyor`});
  // HVL mesafesi
  const distHVL = Math.abs(d.spot-d.hvl)/d.spot*100;
  if(distHVL < 1) notes.push({type:"warn",icon:"🎯",text:`Spot HVL'e ${distHVL.toFixed(2)}% yakın — Kritik Gamma flip bölgesi`});
  // Konfluens
  if(conf && conf.score >= 4) notes.push({type:"bull",icon:"✦",text:`Konfluens +${conf.score} — Güçlü çoklu sinyal uyumu, yüksek güven`});
  else if(conf && conf.score <= -4) notes.push({type:"bear",icon:"✦",text:`Konfluens ${conf.score} — Güçlü aşağı baskı, short setup`});
  // PC ratio
  if(d.pc_ratio > 1.3) notes.push({type:"bull",icon:"📊",text:`P/C OI ${d.pc_ratio.toFixed(2)} — Aşırı put birikimi, contrarian yükseliş sinyali`});
  else if(d.pc_ratio < 0.6) notes.push({type:"warn",icon:"📊",text:`P/C OI ${d.pc_ratio.toFixed(2)} — Call ağırlıklı, dikkatli ol`});
  // Backtest
  if(bt && bt.profitFactor < 1) notes.push({type:"warn",icon:"⚠",text:`Backtest Profit Factor ${bt.profitFactor}x — Mevcut sinyal parametreleri optimize edilmeli`});
  else if(bt && bt.profitFactor > 2) notes.push({type:"bull",icon:"⚠",text:`Backtest Profit Factor ${bt.profitFactor}x — Güçlü sinyal kalitesi`});
  // MenthorQ
  if(d.menthorq?.regime === "stress") notes.push({type:"bear",icon:"🔴",text:`MenthorQ Stress — Kurumsal pozisyonlama savunmacı, scalar 0.85x`});
  else if(d.menthorq?.regime === "strong_squeeze") notes.push({type:"bull",icon:"🟢",text:`MenthorQ Squeeze — Kurumsal alım baskısı yüksek, scalar ${d.menthorq.scalar}x`});
  return notes.slice(0,5);
}

// ── SVG Charts ────────────────────────────────────────────────────
function GEXChart({data, spot, hvl, callRes, putSup}) {
  const W=580,H=300,PL=44,PR=16,PT=8,PB=16;
  const cw=W-PL-PR,ch=H-PT-PB;
  const maxV=Math.max(30,...data.map(r=>Math.abs(r.gex)));
  const rowH=ch/data.length,barH=Math.max(3,rowH-3),x0=PL+cw/2;
  const xS=v=>(v/maxV)*(cw/2);
  const refs={[`${Math.round(spot/1000)}K`]:"rgba(226,234,244,0.5)",[`${Math.round(hvl/1000)}K`]:C.gold,[`${Math.round(callRes/1000)}K`]:C.green,[`${Math.round(putSup/1000)}K`]:C.red};
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs>
        <linearGradient id="gpos" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={C.green} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={C.green} stopOpacity="0.9"/>
        </linearGradient>
        <linearGradient id="gneg" x1="100%" y1="0%" x2="0%" y2="0%">
          <stop offset="0%" stopColor={C.orange} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={C.orange} stopOpacity="0.9"/>
        </linearGradient>
      </defs>
      <line x1={x0} y1={PT} x2={x0} y2={H-PB} stroke={C.border2} strokeWidth={1}/>
      {[-2,-1,1,2].map(v=>{const x=x0+xS(v*(maxV/2));return <line key={v} x1={x} y1={PT} x2={x} y2={H-PB} stroke={C.border} strokeWidth={0.5} strokeDasharray="3,3"/>;})}
      {data.map((row,i)=>{
        const y=PT+i*rowH+(rowH-barH)/2;
        const bw=Math.abs(xS(row.gex));
        const bx=row.gex>=0?x0:x0-bw;
        const refColor=refs[row.label];
        return(
          <g key={i}>
            {refColor&&<line x1={PL} y1={PT+i*rowH+rowH/2} x2={W-PR} y2={PT+i*rowH+rowH/2} stroke={refColor} strokeWidth={1.5} strokeDasharray="6,3"/>}
            <rect x={bx} y={y} width={Math.max(bw,1)} height={barH} fill={row.gex>=0?"url(#gpos)":"url(#gneg)"} rx={2}/>
            <text x={PL-5} y={PT+i*rowH+rowH/2+3} fill={C.muted} fontSize={8.5} textAnchor="end" fontFamily="monospace">{row.label}</text>
          </g>
        );
      })}
    </svg>
  );
}

function TermChart({data}) {
  const W=280,H=220,PL=36,PR=12,PT=16,PB=24;
  const cw=W-PL-PR,ch=H-PT-PB;
  if(!data||data.length<2) return <div style={{color:C.muted,fontSize:11,padding:20}}>Veri yükleniyor...</div>;
  const ivs=data.map(d=>d.iv);
  const minIV=Math.min(...ivs)-2,maxIV=Math.max(...ivs)+2;
  const xS=i=>PL+i*(cw/(data.length-1));
  const yS=v=>PT+ch-(v-minIV)/(maxIV-minIV)*ch;
  const pts=data.map((d,i)=>`${xS(i)},${yS(d.iv)}`).join(" ");
  const isContango=ivs[ivs.length-1]>ivs[0];
  const lineColor=isContango?C.green:C.red;
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs>
        <linearGradient id="termgrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={lineColor} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {[0,1,2,3].map(i=>{const v=minIV+i*(maxIV-minIV)/3;return(<g key={i}><line x1={PL} y1={yS(v)} x2={W-PR} y2={yS(v)} stroke={C.border} strokeWidth={0.5} strokeDasharray="3,3"/><text x={PL-4} y={yS(v)+3} fill={C.muted} fontSize={8} textAnchor="end">{v.toFixed(0)}%</text></g>);})}
      <polygon points={`${data.map((d,i)=>`${xS(i)},${yS(d.iv)}`).join(" ")} ${xS(data.length-1)},${H-PB} ${PL},${H-PB}`} fill="url(#termgrad)"/>
      <polyline points={pts} fill="none" stroke={lineColor} strokeWidth={2.5}/>
      {data.map((d,i)=>(<g key={i}><circle cx={xS(i)} cy={yS(d.iv)} r={3.5} fill={lineColor} stroke={C.bg} strokeWidth={1.5}/><text x={xS(i)} y={H-6} fill={C.muted} fontSize={7.5} textAnchor="middle">{d.expiry.replace("26","").replace("25","")}</text></g>))}
    </svg>
  );
}

function IVOIChart({data, spot}) {
  const W=280,H=220,PL=36,PR=8,PT=8,PB=8;
  const cw=W-PL-PR,ch=H-PT-PB;
  const maxV=Math.max(...data.map(r=>Math.max(r.calls,r.puts)));
  const rowH=ch/data.length,barH=Math.max(2,(rowH-4)/2);
  const spotLbl=`${Math.round(spot/1000)}K`;
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      {data.map((row,i)=>{
        const y=PT+i*rowH,isSpot=row.label===spotLbl;
        return(<g key={i}>
          {isSpot&&<rect x={PL} y={y} width={cw} height={rowH} fill={C.blue} fillOpacity={0.06}/>}
          <rect x={PL} y={y+(rowH-barH*2-2)/2} width={Math.max((row.calls/maxV)*cw,1)} height={barH} fill={C.green} opacity={0.8} rx={1}/>
          <rect x={PL} y={y+(rowH-barH*2-2)/2+barH+2} width={Math.max((row.puts/maxV)*cw,1)} height={barH} fill={C.red} opacity={0.8} rx={1}/>
          <text x={PL-5} y={y+rowH/2+3} fill={isSpot?C.text:C.muted} fontSize={8.5} textAnchor="end" fontFamily="monospace">{row.label}</text>
        </g>);
      })}
    </svg>
  );
}

function MiniBarChart({value, max, color}) {
  const pct = clamp((value/max)*100,0,100);
  return(
    <div style={{height:4,background:C.dim,borderRadius:99,overflow:"hidden",marginTop:4}}>
      <div style={{height:"100%",width:`${pct}%`,background:color,borderRadius:99,transition:"width 0.5s ease"}}/>
    </div>
  );
}

// ── GEX Data Builder ──────────────────────────────────────────────
function buildGEXData(d) {
  const nm={};[...(d.pos_gex_nodes||[]),...(d.neg_gex_nodes||[])].forEach(n=>{nm[n.strike]=n.net_gex;});
  const spot=d.spot,lo=Math.ceil((spot*0.74)/1000)*1000,hi=Math.ceil((spot*1.26)/1000)*1000;
  const rows=[];
  for(let s=hi;s>=lo;s-=1000){const k=nm[s];let gex=k!==undefined?k:(s<spot?-6*Math.exp(-Math.abs((s-spot)/spot)*6):5*Math.exp(-Math.abs((s-spot)/spot)*7));rows.push({label:`${(s/1000).toFixed(0)}K`,gex:Math.round(gex*10)/10});}
  return rows;
}
function buildIVOIData(d) {
  const{spot,call_walls:cw=[],put_walls:pw=[]}=d;
  const lo=Math.ceil((spot*0.8)/1000)*1000,hi=Math.ceil((spot*1.2)/1000)*1000;const rows=[];
  for(let s=hi;s>=lo;s-=1000){const dist=Math.abs(s-spot)/spot,base=Math.max(5,280*Math.exp(-dist*9));rows.push({label:`${(s/1000).toFixed(0)}K`,calls:Math.round(base*(cw.includes(s)?3.8:s>spot?1.1:0.45)),puts:Math.round(base*(pw.includes(s)?3.8:s<spot?1.1:0.45))});}
  return rows;
}

// ── Regime Config ─────────────────────────────────────────────────
const REGIME = {
  IDEAL_LONG:      {label:"İDEAL LONG",     color:C.green,  bg:C.greenDim},
  BULLISH_HIGH_VOL:{label:"BULLISH HIGH VOL",color:C.gold,   bg:"#3d2800"},
  BEARISH_VOLATILE:{label:"BEARISH VOLATİL", color:C.red,    bg:C.redDim},
  BEARISH_LOW_VOL: {label:"BEARISH SIKIŞ",   color:C.orange, bg:"#3d1800"},
  HIGH_RISK:       {label:"⚠ YÜKSEK RİSK",  color:C.red,    bg:C.redDim},
  NEUTRAL:         {label:"NÖTR / BEKLE",    color:C.muted,  bg:C.card2},
};

// ── UI Atoms ──────────────────────────────────────────────────────
const Panel = ({children, style={}, accent}) => (
  <div style={{
    background:C.card, border:`1px solid ${C.border}`,
    borderRadius:10, padding:"14px 16px",
    borderTop: accent ? `2px solid ${accent}` : undefined,
    ...style
  }}>{children}</div>
);

const Label = ({children, style={}}) => (
  <div style={{color:C.muted,fontSize:9.5,letterSpacing:"0.1em",textTransform:"uppercase",fontWeight:600,marginBottom:8,...style}}>{children}</div>
);

const Metric = ({label, value, color, sub, big}) => (
  <div style={{display:"flex",flexDirection:"column",gap:2}}>
    <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em"}}>{label}</div>
    <div style={{color:color||C.text,fontSize:big?22:15,fontWeight:700,fontFamily:"'JetBrains Mono','Fira Code',monospace",lineHeight:1}}>{value}</div>
    {sub&&<div style={{color:C.muted,fontSize:9}}>{sub}</div>}
  </div>
);

const Tag = ({children, color}) => (
  <span style={{background:`${color}20`,border:`1px solid ${color}50`,color,borderRadius:4,padding:"2px 7px",fontSize:10,fontWeight:600}}>{children}</span>
);

const ScoreBar = ({score, max=5, color}) => {
  const p = clamp(((score+max)/(max*2))*100,0,100);
  return(
    <div style={{height:5,background:C.dim,borderRadius:99,overflow:"hidden"}}>
      <div style={{height:"100%",width:`${p}%`,background:color,borderRadius:99,transition:"width 0.6s ease"}}/>
    </div>
  );
};

// ── TeknikSignal ──────────────────────────────────────────────────
function TeknikSignal({optData, onConfluence}) {
  const [t4,setT4]=useState(null);
  const [t1,setT1]=useState(null);
  const [loading,setLoading]=useState(true);
  const [lastUpdate,setLastUpdate]=useState(null);
  const [tab,setTab]=useState("4h");

  const load = useCallback(async () => {
    setLoading(true);
    const [c4,c1] = await Promise.all([fetchOHLCV("4h",120),fetchOHLCV("1h",100)]);
    if(c4) setT4(analyzeCandles(c4));
    if(c1) setT1(analyzeCandles(c1));
    setLastUpdate(new Date().toLocaleTimeString("tr-TR"));
    setLoading(false);
  },[]);

  useEffect(()=>{load();const id=setInterval(load,5*60*1000);return()=>clearInterval(id);},[load]);

  const conf = confluenceScore(t4,t1,optData);
  useEffect(()=>{if(conf&&onConfluence)onConfluence(conf);},[conf?.score]);

  const current = tab==="4h" ? t4 : t1;

  return(
    <Panel accent={conf?.color}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <Label style={{marginBottom:0}}>Teknik Sinyal — BTC/USDT Binance Canlı</Label>
          {loading && <span style={{color:C.muted,fontSize:10}}>yükleniyor...</span>}
          {lastUpdate && !loading && <span style={{color:C.muted,fontSize:9}}>güncelleme: {lastUpdate}</span>}
        </div>
        <button onClick={load} disabled={loading} style={{background:"transparent",border:`1px solid ${C.border}`,color:C.muted,padding:"3px 10px",borderRadius:4,cursor:"pointer",fontSize:10}}>↺</button>
      </div>
      {!loading && conf && (
        <div style={{display:"grid",gridTemplateColumns:"200px 1fr",gap:14}}>
          {/* Konfluens Kutusu */}
          <div style={{background:`${conf.color}0a`,border:`1px solid ${conf.color}30`,borderRadius:8,padding:"14px"}}>
            <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:6}}>Konfluens</div>
            <div style={{color:conf.color,fontSize:38,fontWeight:900,lineHeight:1,fontFamily:"monospace"}}>{conf.score>0?"+":""}{conf.score}</div>
            <div style={{color:conf.color,fontSize:13,fontWeight:700,marginBottom:8}}>{conf.label}</div>
            <ScoreBar score={conf.score} max={8} color={conf.color}/>
            <div style={{display:"flex",flexDirection:"column",gap:3,marginTop:10}}>
              {conf.items.map((it,i)=>(
                <div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:9.5,padding:"2px 0",borderBottom:`1px solid ${C.border}`}}>
                  <span style={{color:C.muted}}>{it.src}</span>
                  <span style={{color:it.val>0?C.green:it.val<0?C.red:C.muted,fontWeight:700}}>{it.val>0?"+":""}{it.val}</span>
                </div>
              ))}
            </div>
          </div>
          {/* Sağ Panel */}
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            <div style={{display:"flex",gap:6}}>
              {["4h","1h"].map(tf=>{
                const sig = tf==="4h"?t4:t1;
                return(<button key={tf} onClick={()=>setTab(tf)} style={{background:tab===tf?`${sig?.signal_color||C.blue}15`:"transparent",border:`1px solid ${tab===tf?sig?.signal_color||C.blue:C.border}`,color:tab===tf?sig?.signal_color||C.blue:C.muted,padding:"4px 14px",borderRadius:4,cursor:"pointer",fontSize:10.5,fontFamily:"monospace"}}>
                  {tf.toUpperCase()} {sig?`${sig.signal_label}`:"—"}
                </button>);
              })}
            </div>
            {current && (
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
                <div style={{display:"flex",flexDirection:"column",gap:5}}>
                  {[
                    {l:"EMA 9",v:current.ema9?.toFixed(0),c:current.ema9>current.ema21?C.green:C.red},
                    {l:"EMA 21",v:current.ema21?.toFixed(0),c:C.muted},
                    {l:"RSI 14",v:current.rsi?.toFixed(1),c:current.rsi>70?C.red:current.rsi<30?C.green:current.rsi>50?"#44e8a0":C.orange},
                    {l:"MACD",v:current.macdV?.toFixed(1),c:current.macdV>current.sigV?C.green:C.red},
                    {l:"Hist",v:current.histV>0?`+${current.histV?.toFixed(1)}`:current.histV?.toFixed(1),c:current.histV>0?C.green:C.red},
                    ...(current.bb?[{l:"BB %",v:current.bb?((current.price-current.bb.lower)/(current.bb.upper-current.bb.lower)*100).toFixed(0)+"%":"-",c:C.blue}]:[]),
                  ].map((row,i)=>(
                    <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 8px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:4}}>
                      <span style={{color:C.muted,fontSize:9.5,textTransform:"uppercase"}}>{row.l}</span>
                      <span style={{color:row.c,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{row.v}</span>
                    </div>
                  ))}
                </div>
                <div style={{display:"flex",flexDirection:"column",gap:4}}>
                  <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:2}}>Gerekçeler</div>
                  {current.reasons.map((r,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:6,padding:"3px 7px",borderRadius:4,background:r.bull===true?`${C.green}10`:r.bull===false?`${C.red}10`:`${C.border}20`}}>
                      <span style={{fontSize:9,color:r.bull===true?C.green:r.bull===false?C.red:C.muted}}>{r.bull===true?"▲":r.bull===false?"▼":"●"}</span>
                      <span style={{fontSize:10,color:r.strong?C.text:C.muted}}>{r.txt}</span>
                    </div>
                  ))}
                  <div style={{marginTop:6,padding:"8px",background:`${current.signal_color}10`,border:`1px solid ${current.signal_color}30`,borderRadius:6}}>
                    <div style={{color:C.muted,fontSize:9,marginBottom:2}}>{tab.toUpperCase()} Sinyal</div>
                    <div style={{color:current.signal_color,fontWeight:900,fontSize:18}}>{current.score>0?"▲":current.score<0?"▼":"—"} {current.signal_label}</div>
                    <ScoreBar score={current.score} max={4} color={current.signal_color}/>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── Smart Notes Panel ─────────────────────────────────────────────
function NotesPanel({notes}) {
  if(!notes||!notes.length) return null;
  const colors = {bull:C.green, bear:C.red, warn:C.gold, info:C.blue};
  return(
    <Panel>
      <Label>Akıllı Notlar — Sistem Yorumları</Label>
      <div style={{display:"flex",flexDirection:"column",gap:6}}>
        {notes.map((n,i)=>{
          const color = colors[n.type]||C.muted;
          return(
            <div key={i} style={{display:"flex",gap:10,padding:"8px 12px",background:`${color}08`,border:`1px solid ${color}25`,borderLeft:`3px solid ${color}`,borderRadius:6}}>
              <span style={{color,fontSize:14,flexShrink:0}}>{n.icon}</span>
              <span style={{color:C.text,fontSize:11.5,lineHeight:1.5}}>{n.text}</span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ── Main App ──────────────────────────────────────────────────────
export default function App() {
  const [data,setData]     = useState(DEMO);
  const [live,setLive]     = useState(false);
  const [busy,setBusy]     = useState(false);
  const [clock,setClock]   = useState("");
  const [confScore,setConfScore] = useState(null);
  const [riskStatus,setRiskStatus] = useState(null);
  const [btResult,setBtResult]   = useState(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    const [d,bp] = await Promise.all([fetchLive(),fetchBinancePrice()]);
    if(d){setData(d);setLive(true);}
    else{setData(bp?{...DEMO,spot:bp}:DEMO);setLive(false);}
    setClock(new Date().toLocaleTimeString("tr-TR"));
    setBusy(false);
  },[]);

  useEffect(()=>{refresh();const id=setInterval(refresh,4*60*1000);return()=>clearInterval(id);},[refresh]);

  useEffect(()=>{
    try{const t=JSON.parse(localStorage.getItem("gdive:journal:v2")||"[]");setRiskStatus(getRiskStatus(t));}catch(e){}
  },[data]);

  useEffect(()=>{
    fetchOHLCV("4h",500).then(candles=>{if(candles){setBtResult(runBacktest(candles));}});
  },[]);

  // Position Management
  useEffect(()=>{
    if(!data||data._source==="demo") return;
    try{
      const JKEY="gdive:journal:v2";
      const trades=JSON.parse(localStorage.getItem(JKEY)||"[]");
      const spot=data.spot,regime=data.regime;
      const bullish=["IDEAL_LONG","BULLISH_HIGH_VOL"].includes(regime)&&spot>data.hvl&&data.total_net_gex>0;
      const bearish=["BEARISH_VOLATILE","BEARISH_LOW_VOL","HIGH_RISK"].includes(regime)&&spot<data.hvl&&data.total_net_gex<0;
      const rs=getRiskStatus(trades);setRiskStatus(rs);
      if(rs.killSwitch) return;
      const confOK=!confScore||(confScore&&confScore.score>=-10);
      const ivOK=(data.iv_rank||0)<80;
      let changed=false;
      const updated=trades.map(t=>{
        if(t.status!=="OPEN") return t;
        const now=new Date().toISOString().slice(0,16).replace("T"," ");
        if(t.dir==="LONG"){
          if(spot<=t.stop){changed=true;const pnl=+((t.stop-t.entry)*t.size).toFixed(2);alert("STOP HIT LONG @ $"+t.stop+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.stop,exitDate:now,pnl,rr:-1,notes:(t.notes||"")+" | STOP"};}
          if(bearish){changed=true;const pnl=+((spot-t.entry)*t.size).toFixed(2);const rr=+((spot-t.entry)/(t.entry-t.stop)).toFixed(2);alert("REJIM SHORT - LONG kapandi @ $"+spot);return{...t,status:"CLOSED",exitPrice:spot,exitDate:now,pnl,rr,notes:(t.notes||"")+" | Rejim SHORT"};}
          if(spot>=t.tp&&!t.partialClosed){changed=true;if(bullish){const half=+(t.size/2).toFixed(4);const nTP=data.call_walls&&data.call_walls.find(w=>w>t.tp)||t.tp*1.03;alert("TP 50% LONG @ $"+t.tp);return{...t,size:half,partialClosed:true,tp:nTP,notes:(t.notes||"")+" | 50% @"+t.tp};}else{const pnl=+((t.tp-t.entry)*t.size).toFixed(2);const rr=+((t.tp-t.entry)/(t.entry-t.stop)).toFixed(2);alert("TP 100% LONG @ $"+t.tp+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.tp,exitDate:now,pnl,rr,notes:(t.notes||"")+" | TP"};}}
        }
        if(t.dir==="SHORT"){
          if(spot>=t.stop){changed=true;const pnl=+((t.entry-t.stop)*t.size).toFixed(2);alert("STOP HIT SHORT @ $"+t.stop+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.stop,exitDate:now,pnl,rr:-1,notes:(t.notes||"")+" | STOP"};}
          if(bullish){changed=true;const pnl=+((t.entry-spot)*t.size).toFixed(2);const rr=+((t.entry-spot)/(t.stop-t.entry)).toFixed(2);alert("REJIM LONG - SHORT kapandi @ $"+spot);return{...t,status:"CLOSED",exitPrice:spot,exitDate:now,pnl,rr,notes:(t.notes||"")+" | Rejim LONG"};}
          if(spot<=t.tp&&!t.partialClosed){changed=true;if(bearish){const half=+(t.size/2).toFixed(4);const nTP=data.put_walls&&data.put_walls.slice().sort((a,b)=>b-a).find(w=>w<t.tp)||t.tp*0.97;alert("TP 50% SHORT @ $"+t.tp);return{...t,size:half,partialClosed:true,tp:nTP,notes:(t.notes||"")+" | 50% @"+t.tp};}else{const pnl=+((t.entry-t.tp)*t.size).toFixed(2);const rr=+((t.entry-t.tp)/(t.stop-t.entry)).toFixed(2);alert("TP 100% SHORT @ $"+t.tp+" PnL:$"+pnl);return{...t,status:"CLOSED",exitPrice:t.tp,exitDate:now,pnl,rr,notes:(t.notes||"")+" | TP"};}}
        }
        return t;
      });
      if(changed) localStorage.setItem(JKEY,JSON.stringify(updated));
      const today=new Date().toISOString().slice(0,10);
      const hasOpen=updated.find(t=>t.date?.startsWith(today)&&t.status==="OPEN");
      if(!hasOpen&&confOK&&ivOK){
        const finalScalar=data.layer_budget?.final_scalar||1.0;
        const risk=10000*0.02*2*finalScalar;
        if(bullish){const entry=spot,stop=data.put_support,tp=data.call_resistance,size=+(risk/Math.abs(entry-stop)).toFixed(4);const trade={id:Date.now(),date:new Date().toISOString().slice(0,16).replace("T"," "),dir:"LONG",entry,stop,tp,size,regime,signal:"Auto·L·"+regime,notes:"Auto LONG. GEX:"+data.total_net_gex+"M scalar:"+finalScalar,status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,partialClosed:false};localStorage.setItem(JKEY,JSON.stringify([trade,...updated]));alert("AUTO LONG @ $"+entry+" Stop:$"+stop+" TP:$"+tp);}
        else if(bearish){const entry=spot,stop=data.call_resistance,tp=data.put_support,size=+(risk/Math.abs(entry-stop)).toFixed(4);const trade={id:Date.now(),date:new Date().toISOString().slice(0,16).replace("T"," "),dir:"SHORT",entry,stop,tp,size,regime,signal:"Auto·S·"+regime,notes:"Auto SHORT. GEX:"+data.total_net_gex+"M scalar:"+finalScalar,status:"OPEN",pnl:null,rr:null,exitPrice:null,exitDate:null,partialClosed:false};localStorage.setItem(JKEY,JSON.stringify([trade,...updated]));alert("AUTO SHORT @ $"+entry+" Stop:$"+stop+" TP:$"+tp);}
      }
    }catch(e){console.error("posmgmt",e);}
  },[data,confScore]);

  const d=data;
  const gp=d.total_net_gex>0;
  const gexRows=buildGEXData(d);
  const ivoiRows=buildIVOIData(d);
  const regime=REGIME[d.regime]||REGIME.NEUTRAL;
  const expMove=((d.front_iv||50)/19.1).toFixed(2);
  const distHVL=(Math.abs(d.spot-d.hvl)/d.spot*100).toFixed(2);
  const notes=generateNotes(d,confScore,btResult);
  const mq=d.menthorq;
  const lb=d.layer_budget;
  const ma=d.multi_asset;

  const headerItems = [
    {l:"P/C OI",    v:d.pc_ratio?.toFixed(2),         c:d.pc_ratio>1.2?C.green:d.pc_ratio<0.7?C.red:C.text},
    {l:"Gamma",     v:gp?"Positive":"Negative",        c:gp?C.green:C.red},
    {l:"IV 30D",    v:pct(d.front_iv),                 c:d.front_iv>70?C.red:d.front_iv>45?C.gold:C.green},
    {l:"HV 30D",    v:pct(d.hv_30d||68),               c:C.muted},
    {l:"IV Rank",   v:pct(d.iv_rank),                  c:d.iv_rank>70?C.red:d.iv_rank>40?C.gold:C.green},
    {l:"Exp.Move",  v:`±${expMove}%`,                  c:C.purple},
    {l:"Net GEX",   v:`${gp?"+":""}${d.total_net_gex?.toFixed(0)}M`, c:gp?C.green:C.orange},
    {l:"MQ Scalar", v:lb?.final_scalar?.toFixed(3)+"×", c:lb?.final_scalar>=1.02?C.green:lb?.final_scalar<=0.97?C.red:C.gold},
  ];

  return(
    <div style={{background:C.bg,minHeight:"100vh",color:C.text,fontFamily:"'JetBrains Mono','Fira Code',monospace",fontSize:12.5}}>

      {/* Top Bar */}
      <div style={{background:"#060810",borderBottom:`1px solid ${C.border}`,padding:"10px 20px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:16}}>
          <div style={{display:"flex",alignItems:"center",gap:8}}>
            <div style={{width:8,height:8,borderRadius:"50%",background:live?C.green:C.gold,boxShadow:`0 0 8px ${live?C.green:C.gold}`}}/>
            <span style={{color:C.gold,fontWeight:900,fontSize:13,letterSpacing:"0.05em"}}>G-DIVE V4</span>
          </div>
          <span style={{color:C.dim,fontSize:10}}>|</span>
          <span style={{color:C.muted,fontSize:10}}>BTC Options Intelligence · Deribit</span>
          {regime&&<Tag color={regime.color}>{regime.label}</Tag>}
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{color:live?C.green:C.gold,fontSize:10}}>{busy?"⟳ Yükleniyor":live?`● CANLI ${clock}`:`◆ DEMO ${clock}`}</span>
          <button onClick={refresh} disabled={busy} style={{background:`${C.border}`,border:`1px solid ${C.border2}`,color:C.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:10}}>↺ Yenile</button>
        </div>
      </div>

      {/* Price Bar */}
      <div style={{background:"#080c14",borderBottom:`1px solid ${C.border}`,padding:"10px 20px",display:"flex",alignItems:"center",gap:32,flexWrap:"wrap"}}>
        <div>
          <div style={{color:C.muted,fontSize:9,letterSpacing:"0.1em"}}>BTC / USD</div>
          <div style={{color:C.text,fontSize:28,fontWeight:900,lineHeight:1,fontFamily:"monospace"}}>{fmtK(d.spot)}</div>
        </div>
        <div style={{width:1,height:36,background:C.border}}/>
        {headerItems.map((it,i)=>(
          <div key={i} style={{display:"flex",flexDirection:"column",gap:1}}>
            <div style={{color:C.muted,fontSize:8.5,textTransform:"uppercase",letterSpacing:"0.08em"}}>{it.l}</div>
            <div style={{color:it.c,fontSize:12.5,fontWeight:700,fontFamily:"monospace"}}>{it.v}</div>
          </div>
        ))}
      </div>

      {/* Main Content */}
      <div style={{padding:"14px 20px",display:"flex",flexDirection:"column",gap:12}}>

        {/* Row 1: QScores */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:10}}>
          {[
            {score:d.option_score??0,label:"Option Score",desc:d.option_score>=4?"Bullish Positioning":d.option_score>=3?"Nötr":"Bearish Positioning",color:d.option_score>=4?C.green:d.option_score>=3?C.gold:C.red},
            {score:d.vol_score??0,label:"Vol Score",desc:d.vol_score>=4?"Yüksek Volatilite":d.vol_score>=3?"Orta":"Düşük Vol",color:d.vol_score>=4?C.orange:d.vol_score>=3?C.gold:C.green},
            {score:d.momentum_score??3,label:"Momentum",desc:d.momentum_score>=4?"Bullish":d.momentum_score>=3?"Nötr":"Bearish",color:d.momentum_score>=4?C.green:d.momentum_score>=3?C.gold:C.red},
          ].map((s,i)=>(
            <div key={i} style={{background:C.card,border:`1px solid ${C.border}`,borderTop:`2px solid ${s.color}`,borderRadius:10,padding:"16px"}}>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:6}}>{s.label}</div>
              <div style={{display:"flex",alignItems:"flex-end",gap:10,marginBottom:8}}>
                <div style={{color:s.color,fontSize:52,fontWeight:900,lineHeight:1}}>{s.score}</div>
                <div style={{color:s.color,fontSize:13,fontWeight:700,marginBottom:6}}>{s.desc}</div>
              </div>
              <MiniBarChart value={s.score} max={5} color={s.color}/>
            </div>
          ))}
        </div>

        {/* Row 2: Smart Notes */}
        <NotesPanel notes={notes}/>

        {/* Row 3: Teknik Sinyal */}
        <TeknikSignal optData={d} onConfluence={setConfScore}/>

        {/* Row 4: MenthorQ + Multi-Asset */}
        {mq && (
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
            <Panel accent={mq.scalar>=1.04?C.green:mq.scalar<=0.96?C.red:C.gold}>
              <Label>MenthorQ Institutional Layer</Label>
              <div style={{display:"grid",gridTemplateColumns:"repeat(2,1fr)",gap:8,marginBottom:10}}>
                {[
                  {l:"Gamma Z",v:mq.gamma_z?.toFixed(3),c:mq.gamma_z>0.5?C.green:mq.gamma_z<-0.5?C.red:C.gold},
                  {l:"Dealer Bias",v:mq.dealer_bias?.toFixed(3),c:mq.dealer_bias>0.2?C.green:mq.dealer_bias<-0.2?C.red:C.muted},
                  {l:"Flow Score",v:mq.flow_score?.toFixed(3),c:mq.flow_score>0.2?C.green:mq.flow_score<-0.2?C.red:C.muted},
                  {l:"MQ Score",v:mq.score?.toFixed(3),c:mq.score>0.2?C.green:mq.score<-0.2?C.red:C.gold},
                ].map((s,i)=>(
                  <div key={i} style={{padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                    <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:2}}>{s.l}</div>
                    <div style={{color:s.c,fontWeight:900,fontSize:18,fontFamily:"monospace"}}>{s.v}</div>
                  </div>
                ))}
              </div>
              <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8}}>
                {[
                  {l:"MQ Scalar",v:mq.scalar?.toFixed(3)+"×",c:mq.scalar>=1.04?C.green:mq.scalar<=0.96?C.red:C.gold,sub:mq.regime},
                  {l:"Funding",v:d.funding?.scalar?.toFixed(3)+"×",c:d.funding?.scalar>=1?C.green:C.orange,sub:d.funding?.regime},
                  {l:"Final",v:lb?.final_scalar?.toFixed(3)+"×",c:lb?.final_scalar>=1.02?C.green:lb?.final_scalar<=0.97?C.red:C.gold,sub:"layer budget"},
                ].map((s,i)=>(
                  <div key={i} style={{padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6,textAlign:"center"}}>
                    <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:2}}>{s.l}</div>
                    <div style={{color:s.c,fontWeight:900,fontSize:16,fontFamily:"monospace"}}>{s.v}</div>
                    <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginTop:1}}>{s.sub}</div>
                  </div>
                ))}
              </div>
            </Panel>

            {ma && (
              <Panel accent={C.purple}>
                <Label>Multi-Asset Weights — BTC · GLD · TLT</Label>
                <div style={{display:"flex",flexDirection:"column",gap:10}}>
                  {[
                    {l:"BTC",v:ma.weights?.BTC||0,c:C.orange},
                    {l:"GLD",v:ma.weights?.GLD||0,c:C.gold},
                    {l:"TLT",v:ma.weights?.TLT||0,c:C.blue},
                  ].map((a,i)=>(
                    <div key={i}>
                      <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                        <span style={{color:C.muted,fontSize:10}}>{a.l}</span>
                        <span style={{color:a.c,fontWeight:700,fontSize:11,fontFamily:"monospace"}}>{(a.v*100).toFixed(1)}%</span>
                      </div>
                      <div style={{height:6,background:C.dim,borderRadius:99,overflow:"hidden"}}>
                        <div style={{height:"100%",width:`${Math.abs(a.v)*100}%`,background:a.c,borderRadius:99,opacity:a.v<0?0.4:1}}/>
                      </div>
                    </div>
                  ))}
                  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginTop:4}}>
                    <div style={{padding:"8px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                      <div style={{color:C.muted,fontSize:9,textTransform:"uppercase"}}>Realized Vol</div>
                      <div style={{color:ma.realized_vol>0.6?C.red:ma.realized_vol>0.4?C.gold:C.green,fontWeight:700,fontSize:16,fontFamily:"monospace"}}>{((ma.realized_vol||0)*100).toFixed(1)}%</div>
                    </div>
                    <div style={{padding:"8px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                      <div style={{color:C.muted,fontSize:9,textTransform:"uppercase"}}>Posture</div>
                      <div style={{color:ma.posture==="RISK_ON"?C.green:C.orange,fontWeight:700,fontSize:14}}>{ma.posture}</div>
                    </div>
                  </div>
                </div>
              </Panel>
            )}
          </div>
        )}

        {/* Row 5: Key Levels + GEX Chart */}
        <div style={{display:"grid",gridTemplateColumns:"280px 1fr",gap:12}}>
          <Panel>
            <Label>Key Levels</Label>
            <div style={{display:"flex",flexDirection:"column",gap:6}}>
              {[
                {l:"Spot",     v:fmtK(d.spot),            c:C.blue,   highlight:true},
                {l:"HVL",      v:fmtK(d.hvl),             c:C.gold,   highlight:true},
                {l:"Call Res", v:fmtK(d.call_resistance),  c:C.green},
                {l:"Put Sup",  v:fmtK(d.put_support),      c:C.red},
                {l:"CR 0DTE",  v:fmtK(d.call_resistance_0dte), c:"#44e8a0"},
                {l:"PS 0DTE",  v:fmtK(d.put_support_0dte), c:"#ff7a5c"},
                {l:"Dist HVL", v:`${distHVL}%`,            c:+distHVL<2?C.gold:C.muted},
                {l:"P/C OI",   v:d.pc_ratio?.toFixed(3),   c:d.pc_ratio>1.2?C.green:d.pc_ratio<0.7?C.red:C.text},
                {l:"Term",     v:d.term_shape,             c:d.term_shape==="CONTANGO"?C.green:C.red},
                {l:"IV Rank",  v:pct(d.iv_rank),           c:d.iv_rank>70?C.red:d.iv_rank>40?C.gold:C.green},
              ].map((row,i)=>(
                <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"6px 8px",background:row.highlight?`${row.c}10`:C.card2,border:`1px solid ${row.highlight?row.c+"40":C.border}`,borderRadius:5}}>
                  <span style={{color:C.muted,fontSize:10,textTransform:"uppercase"}}>{row.l}</span>
                  <span style={{color:row.c,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{row.v}</span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
              <Label style={{marginBottom:0}}>Net GEX — Deribit</Label>
              <span style={{color:gp?C.green:C.orange,fontWeight:700,fontSize:11,fontFamily:"monospace"}}>{gp?"+":""}{d.total_net_gex?.toFixed(1)}M USD</span>
            </div>
            <div style={{display:"flex",gap:16,marginBottom:8,fontSize:10}}>
              <span><span style={{color:C.green}}>──</span> CR {fmtK(d.call_resistance)}</span>
              <span><span style={{color:C.gold}}>──</span> HVL {fmtK(d.hvl)}</span>
              <span><span style={{color:C.red}}>──</span> PS {fmtK(d.put_support)}</span>
            </div>
            <GEXChart data={gexRows} spot={d.spot} hvl={d.hvl} callRes={d.call_resistance} putSup={d.put_support}/>
          </Panel>
        </div>

        {/* Row 6: IV×OI + Term + Entry Signal */}
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:12}}>
          <Panel>
            <Label>IV × OI Dağılımı</Label>
            <div style={{display:"flex",gap:12,marginBottom:8,fontSize:10}}>
              <span><span style={{color:C.green}}>█</span> Calls</span>
              <span><span style={{color:C.red}}>█</span> Puts</span>
            </div>
            <IVOIChart data={ivoiRows} spot={d.spot}/>
          </Panel>
          <Panel>
            <Label>ATM Term Structure</Label>
            <div style={{display:"flex",gap:10,marginBottom:6,fontSize:10,alignItems:"center"}}>
              <Tag color={d.term_shape==="CONTANGO"?C.green:C.red}>{d.term_shape}</Tag>
              <span style={{color:C.muted}}>Front IV: {d.front_iv?.toFixed(2)}%</span>
            </div>
            <TermChart data={d.term_ivs||[]}/>
          </Panel>
          <Panel accent={regime.color}>
            <Label>G-DIVE Entry Signal</Label>
            <div style={{background:regime.bg,border:`1px solid ${regime.color}40`,borderRadius:8,padding:"14px",marginBottom:10}}>
              <div style={{color:regime.color,fontSize:22,fontWeight:900,marginBottom:2}}>{d.long_ok?"▲ LONG OK":d.short_ok?"▼ SHORT OK":"— BEKLE"}</div>
              <div style={{color:regime.color,fontSize:11,fontWeight:700}}>{regime.label}</div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:8}}>
              <div style={{padding:"8px",background:C.redDim,border:`1px solid ${C.red}30`,borderRadius:6}}>
                <div style={{color:C.muted,fontSize:9,marginBottom:2}}>STOP</div>
                <div style={{color:C.red,fontWeight:800,fontSize:13,fontFamily:"monospace"}}>{fmtK(d.put_support)}</div>
              </div>
              <div style={{padding:"8px",background:C.greenDim,border:`1px solid ${C.green}30`,borderRadius:6}}>
                <div style={{color:C.muted,fontSize:9,marginBottom:2}}>TP</div>
                <div style={{color:C.green,fontWeight:800,fontSize:13,fontFamily:"monospace"}}>{fmtK(d.call_resistance)}</div>
              </div>
            </div>
            <div style={{padding:"8px",background:d.gamma_regime==="LONG_GAMMA"?C.greenDim:C.redDim,border:`1px solid ${d.gamma_regime==="LONG_GAMMA"?C.green:C.red}30`,borderRadius:6,marginBottom:8}}>
              <span style={{color:d.gamma_regime==="LONG_GAMMA"?C.green:C.red,fontSize:11,fontWeight:700}}>{d.gamma_regime==="LONG_GAMMA"?"● LONG GAMMA":"● SHORT GAMMA"}</span>
              <div style={{color:C.muted,fontSize:9.5,marginTop:2}}>{d.gamma_regime==="LONG_GAMMA"?`Spot > HVL · Dealer söndürür`:`Spot < HVL · Dealer büyütür`}</div>
            </div>
            <div style={{fontSize:9,color:C.muted,marginBottom:4,textTransform:"uppercase"}}>GEX Düğümleri</div>
            {[...(d.pos_gex_nodes||[]).slice(0,2).map(n=>({...n,c:C.green})),...(d.neg_gex_nodes||[]).slice(0,2).map(n=>({...n,c:C.orange}))].sort((a,b)=>a.strike-b.strike).map((n,i)=>(
              <div key={i} style={{display:"flex",justifyContent:"space-between",fontSize:10,padding:"2px 0",borderBottom:`1px solid ${C.border}`}}>
                <span style={{color:C.muted,fontFamily:"monospace"}}>${n.strike?.toLocaleString()}</span>
                <span style={{color:n.c,fontWeight:700}}>{n.net_gex>=0?"+":""}{n.net_gex?.toFixed(1)}M</span>
              </div>
            ))}
            <div style={{marginTop:8,paddingTop:6,borderTop:`1px solid ${C.border}`,display:"flex",justifyContent:"space-between",fontSize:9,color:C.muted}}>
              <span>OPT {d.option_score}/5</span><span>VOL {d.vol_score}/5</span><span>MOM {d.momentum_score||3}/5</span>
            </div>
          </Panel>
        </div>

        {/* Row 7: Risk + Backtest */}
        {riskStatus && (
          <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10}}>
            {[
              {l:"Günlük P&L",v:(riskStatus.dailyPnl>=0?"+":"")+riskStatus.dailyPnl.toFixed(0)+" / -$"+riskStatus.dailyLossLimit,c:riskStatus.dailyLimitHit?C.red:riskStatus.dailyPnl>=0?C.green:C.orange,alert:riskStatus.dailyLimitHit},
              {l:"Max Drawdown",v:riskStatus.maxDD+"% / limit %"+(RISK_CONFIG.maxDrawdownPct*100),c:riskStatus.drawdownLimitHit?C.red:riskStatus.maxDD>5?C.gold:C.green,alert:riskStatus.drawdownLimitHit},
              {l:"Açık Pozisyon",v:riskStatus.openCount+" / max "+RISK_CONFIG.maxOpenPositions,c:riskStatus.maxPosHit?C.orange:C.green},
              {l:"Kill Switch",v:riskStatus.killSwitch?"⚠ AKTİF":"✓ NORMAL",c:riskStatus.killSwitch?C.red:C.green,alert:riskStatus.killSwitch},
            ].map((s,i)=>(
              <div key={i} style={{background:s.alert?`${s.c}10`:C.card,border:`1px solid ${s.alert?s.c:C.border}`,borderTop:`2px solid ${s.c}`,borderRadius:8,padding:"10px 12px"}}>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:4}}>{s.l}</div>
                <div style={{color:s.c,fontWeight:700,fontSize:12,fontFamily:"monospace"}}>{s.v}</div>
              </div>
            ))}
          </div>
        )}

        {btResult && (
          <Panel>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
              <Label style={{marginBottom:0}}>Backtest — 4H BTC 500 Bar · 2x Kaldıraç · ATR Bazlı</Label>
              <Tag color={btResult.profitFactor>=1.5?C.green:btResult.profitFactor>=1?C.gold:C.red}>PF {btResult.profitFactor}x</Tag>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:8}}>
              {[
                {l:"Trade",       v:btResult.trades,                                          c:C.muted},
                {l:"Win Rate",    v:btResult.winRate+"%",                                     c:btResult.winRate>=50?C.green:C.orange},
                {l:"Sharpe",      v:btResult.sharpe,                                          c:btResult.sharpe>=1?C.green:btResult.sharpe>=0?C.gold:C.red},
                {l:"Max DD",      v:btResult.maxDD+"%",                                       c:btResult.maxDD<10?C.green:btResult.maxDD<20?C.gold:C.red},
                {l:"Toplam PnL",  v:(btResult.totalPnl>=0?"+":"")+btResult.totalPnl.toFixed(0), c:btResult.totalPnl>=0?C.green:C.red},
                {l:"Avg Win",     v:"+$"+btResult.avgWin.toFixed(0),                         c:C.green},
                {l:"Avg Loss",    v:"-$"+btResult.avgLoss.toFixed(0),                        c:C.red},
                {l:"Expectancy",  v:(btResult.expectancy>=0?"+":"")+btResult.expectancy.toFixed(0), c:btResult.expectancy>=0?C.green:C.red},
                {l:"Final Equity",v:"$"+btResult.finalEquity.toFixed(0),                     c:btResult.finalEquity>=10000?C.green:C.red},
                {l:"Profit Factor",v:btResult.profitFactor+"×",                              c:btResult.profitFactor>=1.5?C.green:btResult.profitFactor>=1?C.gold:C.red},
              ].map((s,i)=>(
                <div key={i} style={{padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                  <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:2}}>{s.l}</div>
                  <div style={{color:s.c,fontWeight:700,fontSize:13,fontFamily:"monospace"}}>{s.v}</div>
                </div>
              ))}
            </div>
            {btResult.expectancy<0&&<div style={{marginTop:8,padding:"8px 12px",background:`${C.red}10`,border:`1px solid ${C.red}30`,borderRadius:6,fontSize:10.5,color:C.orange}}>⚠ Negatif beklenti — ATR stop mesafesi veya RR oranı optimize edilmeli. Mevcut: {btResult.avgWin.toFixed(0)} vs {btResult.avgLoss.toFixed(0)} kaybediyor.</div>}
          </Panel>
        )}

        <div style={{borderTop:`1px solid ${C.border}`,paddingTop:8,display:"flex",justifyContent:"space-between",fontSize:9,color:C.dim}}>
          <span>G-DIVE V4 Options Intelligence · Deribit Public API · Railway</span>
          <span>{live?`● Canlı · ${clock}`:`◆ Demo`}</span>
        </div>
      </div>
    </div>
  );
}
