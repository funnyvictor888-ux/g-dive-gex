import { useState, useEffect, useCallback } from "react";

const SUPABASE_URL = "https://gigkmjutnucssgwcnegn.supabase.co";
const SUPABASE_KEY = "sb_publishable_jiFBPVGeFXKl1myvEjTI8g_KKUenCmW";

const C = {
  bg:"#06080e",card:"#0e1520",card2:"#121c2a",card3:"#0a1018",
  border:"#1a2535",border2:"#223040",
  text:"#dce8f5",muted:"#3d5470",dim:"#1a2840",
  green:"#00e599",greenDim:"#002a1a",
  red:"#ff3d5a",redDim:"#2a0010",
  orange:"#ff7a2f",gold:"#ffbe2e",goldDim:"#2a1e00",
  blue:"#3db8ff",purple:"#9d7aff",cyan:"#1de9d6",
};

const fK = n => `$${(+n).toLocaleString("en-US",{maximumFractionDigits:0})}`;
const pct = n => `${(+n).toFixed(2)}%`;
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const sign = n => n>=0?"+":"";

// ── DATA FETCHERS ─────────────────────────────────────────────────
async function fetchSnapshot(){
  try{
    const r=await fetch(`${SUPABASE_URL}/rest/v1/snapshots?order=id.desc&limit=1`,{
      headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}
    });
    if(!r.ok) return null;
    const rows=await r.json();
    return rows&&rows.length?{...rows[0],_source:"supabase"}:null;
  }catch{return null;}
}

async function fetchBinancePrice(){
  try{const r=await fetch("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT");return r.ok?+(await r.json()).price:null;}catch{return null;}
}

async function fetchOHLCV(interval="4h",limit=120){
  try{
    const r=await fetch(`https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=${interval}&limit=${limit}`);
    if(!r.ok)return null;
    return (await r.json()).map(k=>({t:k[0],o:+k[1],h:+k[2],l:+k[3],c:+k[4],v:+k[5]}));
  }catch{return null;}
}

async function fetchOptNotes(){
  try{
    const r=await fetch(`${SUPABASE_URL}/rest/v1/option_notes?order=id.desc&limit=5`,{
      headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}
    });
    return r.ok?await r.json():[];
  }catch{return[];}
}

// ── TECHNICAL ANALYSIS ───────────────────────────────────────────
function ema(c,p){const k=2/(p+1);let e=c[0];return c.map(v=>{e=v*k+e*(1-k);return e;});}
function rsiArr(c,p=14){let g=0,l=0;for(let i=1;i<=p;i++){const d=c[i]-c[i-1];d>=0?g+=d:l-=d;}let ag=g/p,al=l/p;const r=new Array(p).fill(null);r.push(al===0?100:100-100/(1+ag/al));for(let i=p+1;i<c.length;i++){const d=c[i]-c[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;r.push(al===0?100:100-100/(1+ag/al));}return r;}
function macdCalc(c,f=12,s=26,sig=9){const ef=ema(c,f),es=ema(c,s),m=ef.map((v,i)=>v-es[i]),signal=ema(m,sig);return{macd:m,signal,hist:m.map((v,i)=>v-signal[i])};}
function bbCalc(c,p=20,mult=2){return c.map((_,i)=>{if(i<p-1)return null;const sl=c.slice(i-p+1,i+1),mean=sl.reduce((a,b)=>a+b,0)/p,std=Math.sqrt(sl.reduce((a,b)=>a+(b-mean)**2,0)/p);return{upper:mean+mult*std,middle:mean,lower:mean-mult*std};});}
function atrArr(h,l,c,p=14){const tr=h.map((hv,i)=>i===0?hv-l[i]:Math.max(hv-l[i],Math.abs(hv-c[i-1]),Math.abs(l[i]-c[i-1])));return ema(tr,p);}

function analyzeCandles(candles){
  if(!candles||candles.length<40)return null;
  const closes=candles.map(c=>c.c),n=closes.length-1;
  const e9=ema(closes,9),e21=ema(closes,21),rsis=rsiArr(closes,14);
  const {macd,signal,hist}=macdCalc(closes);const bbs=bbCalc(closes,20);
  const price=closes[n],rsi=rsis[n],bb=bbs[n],macdV=macd[n],sigV=signal[n],histV=hist[n];
  let score=0;const signals=[];
  if(e9[n]>e21[n]){score++;signals.push({k:"EMA",v:`9>${e9[n].toFixed(0)} Bullish`,bull:true});}
  else{score--;signals.push({k:"EMA",v:`9<${e9[n].toFixed(0)} Bearish`,bull:false});}
  if(rsi>70){score--;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Aşırı Alım`,bull:false});}
  else if(rsi<30){score++;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Aşırı Satım`,bull:true});}
  else if(rsi>55){score++;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Bullish`,bull:true});}
  else if(rsi<45){score--;signals.push({k:"RSI",v:`${rsi.toFixed(1)} Bearish`,bull:false});}
  else signals.push({k:"RSI",v:`${rsi.toFixed(1)} Nötr`,bull:null});
  if(macdV>sigV){score++;signals.push({k:"MACD",v:`+${histV.toFixed(0)} Bullish`,bull:true});}
  else{score--;signals.push({k:"MACD",v:`${histV.toFixed(0)} Bearish`,bull:false});}
  if(bb){const bp=(price-bb.lower)/(bb.upper-bb.lower);
    if(bp>0.85){score--;signals.push({k:"BB",v:"Üst Band",bull:false});}
    else if(bp<0.15){score++;signals.push({k:"BB",v:"Alt Band",bull:true});}
    else if(bp>0.5){score++;signals.push({k:"BB",v:"Orta Üstü",bull:true});}
    else signals.push({k:"BB",v:"Orta Altı",bull:false});}
  const sc=score>=3?C.green:score>=1?"#44e8a0":score<=-3?C.red:score<=-1?C.orange:C.muted;
  const sl=score>=3?"GÜÇLÜ LONG":score>=2?"LONG":score>=1?"ZAYIF LONG":score<=-3?"GÜÇLÜ SHORT":score<=-1?"SHORT":"BEKLE";
  return{price,rsi,macdV,sigV,histV,ema9:e9[n],ema21:e21[n],bb,score,sc,sl,signals};
}

function runBacktest(candles){
  if(!candles||candles.length<60)return null;
  const closes=candles.map(c=>c.c),highs=candles.map(c=>c.h),lows=candles.map(c=>c.l);
  const e9=ema(closes,9),e21=ema(closes,21),rsis=rsiArr(closes,14);
  const ml=ema(closes,12).map((v,i)=>v-ema(closes,26)[i]),sig=ema(ml,9),atrs=atrArr(highs,lows,closes,14);
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
  if(!trades.length)return null;
  const wins=trades.filter(t=>t.pnl>0),losses=trades.filter(t=>t.pnl<0);
  const totalPnl=trades.reduce((a,t)=>a+t.pnl,0),wr=wins.length/trades.length*100;
  const aw=wins.length?wins.reduce((a,t)=>a+t.pnl,0)/wins.length:0;
  const al=losses.length?Math.abs(losses.reduce((a,t)=>a+t.pnl,0)/losses.length):1;
  const pf=al>0?Math.abs(wins.reduce((a,t)=>a+t.pnl,0))/Math.abs(losses.reduce((a,t)=>a+t.pnl,0)||1):0;
  return{trades:trades.length,wins:wins.length,wr:+wr.toFixed(1),totalPnl:+totalPnl.toFixed(0),finalEq:+eq.toFixed(0),maxDD:+(mdd*100).toFixed(1),pf:+pf.toFixed(2),aw:+aw.toFixed(0),al:+al.toFixed(0),exp:+((wr/100*aw-(1-wr/100)*al)).toFixed(0)};
}

function getRiskStatus(trades){
  const today=new Date().toISOString().slice(0,10),cap=10000;
  const dPnl=trades.filter(t=>t.status==="CLOSED"&&(t.exit_date||t.exitDate||"").startsWith(today)).reduce((a,t)=>a+(t.pnl||0),0);
  let pk=cap,eq=cap,mdd=0;
  trades.filter(t=>t.status==="CLOSED").forEach(t=>{eq+=(t.pnl||0);if(eq>pk)pk=eq;const dd=(pk-eq)/pk;if(dd>mdd)mdd=dd;});
  const dLimit=cap*0.02,ddLimit=0.10,killSwitch=dPnl<=-dLimit||mdd>=ddLimit;
  return{dPnl:+dPnl.toFixed(0),dLimit:+dLimit.toFixed(0),mdd:+(mdd*100).toFixed(1),killSwitch,openCount:trades.filter(t=>t.status==="OPEN").length,equity:+eq.toFixed(0)};
}

// ── KARAR KATMANI ─────────────────────────────────────────────────
function buildDecisionLayers(d, t4, risk, optNotes){
  const layers = [];
  const spot = d?.spot||0, hvl = d?.hvl||0, gex = d?.total_net_gex||0;
  const regime = d?.regime||"", gamma = d?.gamma_regime||"";
  const flipDist = d?.gamma_analysis?.flip_distance_pct||0;
  const flipNear = d?.gamma_analysis?.flip_near||false;
  const expiry = d?.expiry||{};
  const maxPain = d?.max_pain;
  
  // Katman 1: Gamma Rejimi
  const gammaOk = gamma==="LONG_GAMMA" && spot>hvl;
  layers.push({
    id:1, title:"Gamma Rejimi",
    signal: gammaOk?1:flipNear?0:-1,
    status: gammaOk?"POZİTİF":flipNear?"FLIP YAKINI":"NEGATİF",
    color: gammaOk?C.green:flipNear?C.gold:C.red,
    detail: gammaOk
      ?`Spot ${fK(spot)} > HVL ${fK(hvl)} · Dealer vol söndürür · Pin mantığı aktif`
      :flipNear
      ?`Flip noktasına ${flipDist?.toFixed(1)}% yakın · Yeni trade açma`
      :`Spot ${fK(spot)} < HVL ${fK(hvl)} · Dealer vol büyütür · Volatilite modu`,
  });
  
  // Katman 2: Opsiyon Yapısı
  const ivRank = d?.iv_rank||0;
  const gexOk = gex>0;
  const ivOk = ivRank<75;
  const optScore = gexOk&&ivOk?1:!gexOk?-1:0;
  layers.push({
    id:2, title:"Opsiyon Yapısı",
    signal: optScore,
    status: optScore>0?"BULLISH OI":optScore<0?"BEARISH":ivRank>=75?"IV YÜKSEK":"NÖTR",
    color: optScore>0?C.green:optScore<0?C.red:C.gold,
    detail: `GEX ${gexOk?"+":""}${(gex/1000).toFixed(0)}K · IV ${d?.front_iv?.toFixed(1)||"?"}% · Rank ${ivRank?.toFixed(0)}% · ${d?.term_shape||"?"}`
      +(maxPain?` · Max Pain ${fK(maxPain)}`:"")+
      (expiry.days_to_expiry!==undefined?` · Expiry ${expiry.days_to_expiry}g`:""),
  });
  
  // Katman 3: Teknik Sinyal
  const techScore = t4?Math.sign(t4.score):0;
  layers.push({
    id:3, title:"Teknik Sinyal",
    signal: techScore,
    status: t4?(t4.score>=3?"GÜÇLÜ LONG":t4.score>=1?"LONG":t4.score<=-3?"GÜÇLÜ SHORT":t4.score<=-1?"SHORT":"NÖTR"):"Yükleniyor",
    color: techScore>0?C.green:techScore<0?C.red:C.muted,
    detail: t4?`4H EMA${t4.ema9>t4.ema21?"▲":"▼"} · RSI ${t4.rsi?.toFixed(1)} · MACD ${t4.histV>=0?"+":""}${t4.histV?.toFixed(0)} · BB %${t4.bb?((t4.price-t4.bb.lower)/(t4.bb.upper-t4.bb.lower)*100).toFixed(0):"?"}`:"Binance verisi bekleniyor",
  });
  
  // Katman 4: Opsiyon Notu
  const noteSignal = (()=>{
    if(!optNotes.length)return 0;
    const t=(optNotes[0].text||"").toLowerCase();
    const bull=["long","bull","alim","pozitif","yukari","break","kir"].some(k=>t.includes(k));
    const bear=["short","bear","satim","negatif","asagi","kirik","dusus"].some(k=>t.includes(k));
    return bull&&!bear?1:bear&&!bull?-1:0;
  })();
  layers.push({
    id:4, title:"Opsiyon Notu",
    signal: noteSignal,
    status: noteSignal>0?"BULLISH":noteSignal<0?"BEARISH":"NÖTR",
    color: noteSignal>0?C.green:noteSignal<0?C.red:C.muted,
    detail: optNotes.length?`"${optNotes[0].text?.slice(0,80)}"`:  "Not girilmedi — karar skorunu etkiler",
    noteDate: optNotes[0]?.date,
  });
  
  // Katman 5: Risk Filtre
  const killSwitch = risk?.killSwitch||false;
  const expDay = expiry.expiry_day||false;
  const riskScore = killSwitch||expDay||flipNear?-1:0;
  layers.push({
    id:5, title:"Risk Filtre",
    signal: riskScore,
    status: killSwitch?"KILL SWITCH":expDay?"EXPIRY GÜNÜ":flipNear?"FLIP YAKINI":"TEMİZ",
    color: riskScore<0?C.red:C.green,
    detail: killSwitch?"Günlük limit veya DD aşıldı — sistem durduruldu"
      :expDay?"Expiry günü — yeni trade açılmıyor"
      :flipNear?`Flip noktasına ${flipDist?.toFixed(1)}% yakın — bekleme`
      :`Kill switch: ${risk?.dPnl>=0?"+":""}${risk?.dPnl||0}$ · DD ${risk?.mdd||0}%`,
  });
  
  // Toplam skor ve karar
  const totalScore = layers.reduce((a,l)=>a+l.signal, 0);
  const blocked = killSwitch||expDay;
  const decision = blocked?"BLOKE"
    :totalScore>=3?"LONG AÇILIYOR"
    :totalScore>=2?"LONG HAZIR"
    :totalScore<=-3?"SHORT AÇILIYOR"
    :totalScore<=-2?"SHORT HAZIR"
    :"BEKLE";
  const decColor = blocked?C.red
    :totalScore>=2?C.green
    :totalScore<=-2?C.red
    :C.gold;
  
  // Katman 6: Taleb Shadow (karar skoruna giriyor)
  const taleb = d?.taleb;
  if(taleb){
    const pinScore = taleb.pin_risk?.pin_score||0;
    const amplifier = taleb.shadow_gex?.gex_amplifier||1;
    const bandPct = taleb.rehedge_band?.band_pct||0;
    
    let talebSignal = 0;
    let talebStatus = "NÖTR";
    let talebDetail = "";
    
    if(pinScore>=7.5){
      talebSignal=-1;talebStatus="PIN RİSKİ YÜKSEK";
      talebDetail=`Pin skoru ${pinScore.toFixed(1)}/10 — Expiry yakın, fiyat sabitlenebilir. Band ±${bandPct.toFixed(2)}%`;
    } else if(amplifier>1.3){
      talebSignal=-1;talebStatus="VOL ETKİSİ BÜYÜK";
      talebDetail=`Shadow GEX BSM'den ${amplifier.toFixed(2)}× büyük — Vol etkisi var. Band ±${bandPct.toFixed(2)}%`;
    } else if(pinScore<3&&amplifier<1.1){
      talebSignal=1;talebStatus="SHADOW NORMAL";
      talebDetail=`Pin ${pinScore.toFixed(1)}/10 düşük · Amplifier ${amplifier.toFixed(2)}× normal · Band ±${bandPct.toFixed(2)}%`;
    } else {
      talebStatus="SHADOW İZLENİYOR";
      talebDetail=`Pin ${pinScore.toFixed(1)}/10 · Amplifier ${amplifier.toFixed(2)}× · Band ±${bandPct.toFixed(2)}%`;
    }
    
    layers.push({
      id:6, title:"Taleb Shadow",
      signal:talebSignal,
      status:talebStatus,
      color:talebSignal>0?C.green:talebSignal<0?C.red:C.purple,
      detail:talebDetail+(taleb.summary?.alert?` ⚡ ${taleb.summary.alert}`:""),
      shadow:true
    });
  }

  return{layers, totalScore:layers.reduce((a,l)=>a+l.signal,0), decision:
    (layers.find(l=>l.id===5)?.signal<0&&(d?.expiry?.expiry_day||risk?.killSwitch))?"BLOKE"
    :layers.reduce((a,l)=>a+l.signal,0)>=3?"LONG AÇILIYOR"
    :layers.reduce((a,l)=>a+l.signal,0)>=2?"LONG HAZIR"
    :layers.reduce((a,l)=>a+l.signal,0)<=-3?"SHORT AÇILIYOR"
    :layers.reduce((a,l)=>a+l.signal,0)<=-2?"SHORT HAZIR"
    :"BEKLE",
    decColor:layers.reduce((a,l)=>a+l.signal,0)>=2?C.green:layers.reduce((a,l)=>a+l.signal,0)<=-2?C.red:C.gold,
    blocked:d?.expiry?.expiry_day||risk?.killSwitch||false};
}

// ── GEX BAR ──────────────────────────────────────────────────────
function GEXBar({data,spot,hvl,callRes,putSup}){
  const W=520,H=260,PL=40,PR=14,PT=6,PB=14,cw=W-PL-PR,ch=H-PT-PB;
  const maxV=Math.max(30,...data.map(r=>Math.abs(r.gex)));
  const rowH=ch/data.length,barH=Math.max(3,rowH-3),x0=PL+cw/2;
  const xS=v=>(v/maxV)*(cw/2);
  const refs={[`${Math.round((spot||0)/1000)}K`]:{c:"rgba(220,232,245,0.6)"},[`${Math.round((hvl||0)/1000)}K`]:{c:C.gold},[`${Math.round((callRes||0)/1000)}K`]:{c:C.green},[`${Math.round((putSup||0)/1000)}K`]:{c:C.red}};
  return(
    <svg width={W} height={H} style={{display:"block"}}>
      <defs>
        <linearGradient id="gp" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stopColor={C.green} stopOpacity="0.2"/><stop offset="100%" stopColor={C.green} stopOpacity="0.85"/></linearGradient>
        <linearGradient id="gn" x1="100%" y1="0%" x2="0%" y2="0%"><stop offset="0%" stopColor={C.red} stopOpacity="0.2"/><stop offset="100%" stopColor={C.red} stopOpacity="0.85"/></linearGradient>
      </defs>
      <line x1={x0} y1={PT} x2={x0} y2={H-PB} stroke={C.border2} strokeWidth={1}/>
      {data.map((row,i)=>{
        const y=PT+i*rowH+(rowH-barH)/2,bw=Math.abs(xS(row.gex)),bx=row.gex>=0?x0:x0-bw;
        const ref=refs[row.label];
        return(<g key={i}>
          {ref&&<line x1={PL} y1={PT+i*rowH+rowH/2} x2={W-PR} y2={PT+i*rowH+rowH/2} stroke={ref.c} strokeWidth={1.5} strokeDasharray="5,3"/>}
          <rect x={bx} y={y} width={Math.max(bw,1)} height={barH} fill={row.gex>=0?"url(#gp)":"url(#gn)"} rx={2}/>
          <text x={PL-4} y={PT+i*rowH+rowH/2+3} fill={ref?C.text:C.muted} fontSize={8.5} textAnchor="end" fontFamily="monospace">{row.label}</text>
        </g>);
      })}
    </svg>
  );
}

function buildGEX(d){
  const nm={};[...(d.pos_gex_nodes||[]),...(d.neg_gex_nodes||[])].forEach(n=>{nm[n.strike]=n.net_gex;});
  const s=d.spot||70000,lo=Math.ceil((s*0.74)/1000)*1000,hi=Math.ceil((s*1.26)/1000)*1000,rows=[];
  for(let k=hi;k>=lo;k-=1000){const v=nm[k];let g=v!==undefined?v:(k<s?-6*Math.exp(-Math.abs((k-s)/s)*6):5*Math.exp(-Math.abs((k-s)/s)*7));rows.push({label:`${(k/1000).toFixed(0)}K`,gex:Math.round(g*10)/10});}
  return rows;
}

// ── DECISION PYRAMID ─────────────────────────────────────────────
function DecisionPyramid({layers, totalScore, decision, decColor, blocked}){
  return(
    <div style={{display:"flex",flexDirection:"column",gap:3}}>
      {layers.map((layer,i)=>(
        <div key={layer.id}>
          <div style={{background:layer.signal>0?`${C.green}08`:layer.signal<0?`${C.red}08`:`${C.muted}08`,border:`0.5px solid ${layer.signal>0?C.green+"40":layer.signal<0?C.red+"40":C.border}`,borderLeft:`3px solid ${layer.color}`,borderRadius:6,padding:"8px 12px"}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:3}}>
              <div style={{display:"flex",alignItems:"center",gap:8}}>
                <span style={{color:C.muted,fontSize:9,fontFamily:"monospace",background:C.dim,padding:"1px 5px",borderRadius:3}}>{String(layer.id).padStart(2,"0")}</span>
                <span style={{color:C.text,fontWeight:700,fontSize:11}}>{layer.title}</span>
              </div>
              <div style={{display:"flex",alignItems:"center",gap:8}}>
                <span style={{color:layer.color,fontSize:9,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.06em"}}>{layer.status}</span>
                <span style={{color:layer.color,fontFamily:"monospace",fontSize:12,fontWeight:900,minWidth:20,textAlign:"right"}}>{layer.signal>0?"+1":layer.signal<0?"-1":"0"}</span>
              </div>
            </div>
            <div style={{color:C.muted,fontSize:9.5,lineHeight:1.5}}>{layer.detail}</div>
          </div>
          {i<layers.length-1&&<div style={{display:"flex",justifyContent:"center",padding:"2px 0"}}>
            <div style={{width:1,height:8,background:C.border}}/>
          </div>}
        </div>
      ))}
      
      {/* Karar */}
      <div style={{display:"flex",justifyContent:"center",padding:"4px 0"}}>
        <div style={{width:1,height:12,background:`linear-gradient(${C.border},${decColor})`}}/>
      </div>
      <div style={{background:`${decColor}10`,border:`1.5px solid ${decColor}50`,borderRadius:8,padding:"12px 16px",textAlign:"center"}}>
        <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:4}}>Sistem Kararı — {totalScore>0?"+":""}{totalScore} Toplam</div>
        <div style={{color:decColor,fontSize:20,fontWeight:900,letterSpacing:"0.04em"}}>{decision}</div>
        <div style={{marginTop:6,display:"flex",justifyContent:"center",gap:3}}>
          {layers.map(l=>(
            <div key={l.id} style={{width:20,height:4,borderRadius:99,background:l.signal>0?C.green:l.signal<0?C.red:C.dim}}/>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── MAIN ──────────────────────────────────────────────────────────
export default function App(){
  const [data,setData]=useState(null);
  const [price,setPrice]=useState(null);
  const [live,setLive]=useState(false);
  const [clock,setClock]=useState("");
  const [busy,setBusy]=useState(false);
  const [t4,setT4]=useState(null);
  const [t1,setT1]=useState(null);
  const [bt,setBt]=useState(null);
  const [risk,setRisk]=useState(null);
  const [optNotes,setOptNotes]=useState([]);
  const [newNote,setNewNote]=useState("");
  const [trades,setTrades]=useState([]);

  const refresh=useCallback(async()=>{
    setBusy(true);
    const [snap,bp]=await Promise.all([fetchSnapshot(),fetchBinancePrice()]);
    if(snap){setData(d=>({...snap,spot:bp||snap.spot}));setLive(true);}
    else if(bp){setData(d=>d?{...d,spot:bp}:null);}
    if(bp) setPrice(bp);
    setClock(new Date().toLocaleTimeString("tr-TR"));
    setBusy(false);
  },[]);

  useEffect(()=>{
    refresh();
    const i1=setInterval(refresh,60*1000);
    return()=>clearInterval(i1);
  },[refresh]);

  useEffect(()=>{
    fetchOHLCV("4h",120).then(c=>{if(c)setT4(analyzeCandles(c));});
    fetchOHLCV("1h",100).then(c=>{if(c)setT1(analyzeCandles(c));});
    fetchOHLCV("4h",500).then(c=>{if(c)setBt(runBacktest(c));});
  },[]);

  useEffect(()=>{
    fetchOptNotes().then(rows=>setOptNotes(rows||[]));
    // Supabase trades
    fetch(`${SUPABASE_URL}/rest/v1/trades?order=id.desc`,{
      headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`}
    }).then(r=>r.ok?r.json():null).then(rows=>{
      if(rows&&rows.length){
        const mapped=rows.map(r=>({...r,exitDate:r.exit_date,exitPrice:r.exit_price,partialClosed:r.partial_closed}));
        setTrades(mapped);
        setRisk(getRiskStatus(mapped));
      }
    }).catch(()=>{});
  },[data]);

  const addNote=()=>{
    if(!newNote.trim()||!data)return;
    const n={text:newNote,date:new Date().toISOString().slice(0,16).replace("T"," "),spot:data.spot,regime:data.regime};
    fetch(`${SUPABASE_URL}/rest/v1/option_notes`,{
      method:"POST",
      headers:{"apikey":SUPABASE_KEY,"Authorization":`Bearer ${SUPABASE_KEY}`,"Content-Type":"application/json","Prefer":"return=minimal"},
      body:JSON.stringify(n)
    }).then(()=>{setOptNotes(p=>[n,...p.slice(0,4)]);setNewNote("");});
  };

  const d=data;
  const dec=buildDecisionLayers(d,t4,risk,optNotes);
  const gexRows=d?buildGEX(d):[];
  const mq=d?.menthorq;
  const lb=d?.layer_budget;
  const expiry=d?.expiry||{};
  const ga=d?.gamma_analysis||{};

  // Render
  if(!d) return(
    <div style={{background:C.bg,minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",fontFamily:"monospace",color:C.muted,fontSize:12}}>
      <div style={{textAlign:"center"}}>
        <div style={{color:C.green,fontSize:18,fontWeight:700,marginBottom:8}}>G-DIVE V5</div>
        <div>Supabase verisi yükleniyor...</div>
        <div style={{marginTop:8,fontSize:10}}>GitHub Actions her 5 dakikada günceller</div>
      </div>
    </div>
  );

  return(
    <div style={{background:C.bg,minHeight:"100vh",color:C.text,fontFamily:"'JetBrains Mono','Fira Code',monospace",fontSize:12.5}}>

      {/* TOPBAR */}
      <div style={{background:"#040609",borderBottom:`1px solid ${C.border}`,padding:"9px 20px",display:"flex",alignItems:"center",justifyContent:"space-between",position:"sticky",top:0,zIndex:100}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <div style={{width:7,height:7,borderRadius:"50%",background:live?C.green:C.gold,boxShadow:`0 0 6px ${live?C.green:C.gold}`}}/>
          <span style={{color:C.gold,fontWeight:900,fontSize:13}}>G-DIVE V5</span>
          <span style={{color:C.muted,fontSize:10}}>BTC Options Intelligence · Deribit + Supabase</span>
          <span style={{background:`${dec.decColor}15`,border:`1px solid ${dec.decColor}40`,color:dec.decColor,fontSize:9,padding:"2px 8px",borderRadius:4,fontWeight:700}}>{dec.decision}</span>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <span style={{fontSize:26,fontWeight:900,color:C.text}}>{fK(price||d.spot)}</span>
          <span style={{color:live?C.green:C.gold,fontSize:10}}>{busy?"⟳":live?`● ${clock}`:"◆ CACHED"}</span>
          <button onClick={refresh} disabled={busy} style={{background:C.card,border:`1px solid ${C.border}`,color:C.muted,padding:"3px 12px",borderRadius:4,cursor:"pointer",fontSize:10}}>↺</button>
        </div>
      </div>

      <div style={{padding:"16px 20px",display:"grid",gridTemplateColumns:"280px 1fr",gap:16,alignItems:"start"}}>

        {/* SOL: Karar Piramidi */}
        <div style={{position:"sticky",top:60}}>
          <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:10}}>Karar Piramidi</div>
          <DecisionPyramid {...dec}/>

          {/* Risk özeti */}
          {risk&&<div style={{marginTop:10,background:C.card,border:`1px solid ${risk.killSwitch?C.red:C.border}`,borderRadius:8,padding:"10px 12px"}}>
            <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:6}}>Risk Durumu</div>
            {[
              {l:"Sermaye",v:`$${risk.equity}`,c:risk.equity>=10000?C.green:C.red},
              {l:"Günlük P&L",v:`${sign(risk.dPnl)}$${risk.dPnl} / -$${risk.dLimit}`,c:risk.dPnl<-risk.dLimit?C.red:risk.dPnl>=0?C.green:C.orange},
              {l:"Max DD",v:`${risk.mdd}% / limit %10`,c:risk.mdd>=10?C.red:risk.mdd>=5?C.gold:C.green},
              {l:"Kill Switch",v:risk.killSwitch?"AKTİF":"Normal",c:risk.killSwitch?C.red:C.green},
            ].map((s,i)=>(
              <div key={i} style={{display:"flex",justifyContent:"space-between",marginBottom:3,fontSize:9.5}}>
                <span style={{color:C.muted}}>{s.l}</span>
                <span style={{color:s.c,fontWeight:700,fontFamily:"monospace"}}>{s.v}</span>
              </div>
            ))}
          </div>}
        </div>

        {/* SAĞ: Detay Panelleri */}
        <div style={{display:"flex",flexDirection:"column",gap:12}}>

          {/* ── BÖLÜM 1: Piyasa Verileri ── */}
          <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"14px 16px",borderLeft:`3px solid ${ga.regime==="POSITIVE_GAMMA"?C.green:ga.flip_near?C.gold:C.red}`}}>
            <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>Piyasa Verileri</div>
            
            {/* Gamma Rejim Kutusu */}
            {d.gamma_analysis&&(
              <div style={{background:`${ga.regime==="POSITIVE_GAMMA"?C.green:ga.flip_near?C.gold:C.red}08`,border:`1px solid ${ga.regime==="POSITIVE_GAMMA"?C.green+"40":ga.flip_near?C.gold+"40":C.red+"40"}`,borderRadius:7,padding:"10px 12px",marginBottom:10}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                  <span style={{color:ga.regime==="POSITIVE_GAMMA"?C.green:ga.flip_near?C.gold:C.red,fontWeight:700,fontSize:11}}>
                    {ga.regime==="POSITIVE_GAMMA"?"✓ Pozitif Gamma — LONG Bölge":ga.flip_near?"⚡ Flip Bölgesi — Bekle":"● Negatif Gamma — Volatilite Modu"}
                  </span>
                  <div style={{display:"flex",gap:6}}>
                    {d.max_pain&&<span style={{color:C.purple,fontSize:9,background:`${C.purple}15`,padding:"2px 7px",borderRadius:3}}>Max Pain {fK(d.max_pain)}</span>}
                    {expiry.days_to_expiry!==undefined&&<span style={{color:expiry.expiry_week?C.gold:C.muted,fontSize:9,background:`${C.muted}15`,padding:"2px 7px",borderRadius:3}}>Expiry {expiry.days_to_expiry}g</span>}
                  </div>
                </div>
                <div style={{color:C.text,fontSize:10.5,lineHeight:1.6,marginBottom:6}}>{ga.description}</div>
                <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:6}}>
                  {[
                    {l:"Flip",v:d.flip_point?fK(d.flip_point):"—",c:C.gold},
                    {l:"Mesafe",v:`${ga.flip_distance_pct?.toFixed(1)}%`,c:ga.flip_near?C.red:ga.flip_distance_pct<5?C.gold:C.green},
                    {l:"GEX",v:`${d.total_net_gex>=0?"+":""}${(d.total_net_gex/1000)?.toFixed(0)}K`,c:d.total_net_gex>0?C.green:C.red},
                    {l:"IV Rank",v:pct(d.iv_rank||0),c:d.iv_rank>70?C.red:d.iv_rank>40?C.gold:C.green},
                  ].map((s,i)=>(
                    <div key={i} style={{padding:"5px 8px",background:"rgba(0,0,0,0.25)",borderRadius:4}}>
                      <div style={{color:C.muted,fontSize:8.5,marginBottom:2}}>{s.l}</div>
                      <div style={{color:s.c,fontWeight:700,fontFamily:"monospace",fontSize:11}}>{s.v}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 4 Metrik */}
            <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8,marginBottom:12}}>
              {[
                {l:"BTC Spot",v:fK(price||d.spot),c:C.blue},
                {l:"HVL",v:fK(d.hvl),c:C.gold,sub:d.spot>d.hvl?`+${((d.spot-d.hvl)/d.spot*100).toFixed(1)}%`:`-${((d.hvl-d.spot)/d.spot*100).toFixed(1)}%`},
                {l:"Front IV",v:pct(d.front_iv||0),c:d.front_iv>65?C.red:d.front_iv>45?C.gold:C.green},
                {l:"P/C OI",v:(d.pc_ratio||0).toFixed(2),c:d.pc_ratio>1.2?C.green:d.pc_ratio<0.7?C.red:C.text},
              ].map((s,i)=>(
                <div key={i} style={{padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                  <div style={{color:C.muted,fontSize:9,marginBottom:2}}>{s.l}</div>
                  <div style={{color:s.c,fontSize:16,fontWeight:900,fontFamily:"monospace",lineHeight:1}}>{s.v}</div>
                  {s.sub&&<div style={{color:C.muted,fontSize:8.5,marginTop:1}}>{s.sub}</div>}
                </div>
              ))}
            </div>

            {/* GEX Haritası + Kritik Seviyeler */}
            <div style={{display:"grid",gridTemplateColumns:"520px 1fr",gap:12}}>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:6}}>Net GEX Haritası</div>
                <GEXBar data={gexRows} spot={d.spot} hvl={d.hvl} callRes={d.call_resistance} putSup={d.put_support}/>
                <div style={{display:"flex",gap:12,fontSize:9,color:C.muted,marginTop:3}}>
                  <span><span style={{color:C.green}}>──</span> CR {fK(d.call_resistance||0)}</span>
                  <span><span style={{color:C.gold}}>──</span> HVL {fK(d.hvl||0)}</span>
                  <span><span style={{color:C.red}}>──</span> PS {fK(d.put_support||0)}</span>
                </div>
              </div>
              <div>
                <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",marginBottom:6}}>Kritik Seviyeler</div>
                {[
                  {l:"Call Resistance",v:fK(d.call_resistance||0),c:C.green},
                  {l:"Spot",v:fK(price||d.spot),c:C.blue,bold:true},
                  {l:"HVL / Flip",v:fK(d.hvl||0),c:C.gold},
                  {l:"Put Support",v:fK(d.put_support||0),c:C.red},
                  {l:"Max Pain",v:d.max_pain?fK(d.max_pain):"—",c:C.purple},
                ].map((s,i)=>(
                  <div key={i} style={{display:"flex",justifyContent:"space-between",padding:`${s.bold?"6":"4"}px 8px`,background:s.bold?`${C.blue}10`:C.card2,border:`1px solid ${s.bold?C.blue+"40":C.border}`,borderRadius:4,marginBottom:3}}>
                    <span style={{color:C.muted,fontSize:9.5}}>{s.l}</span>
                    <span style={{color:s.c,fontWeight:s.bold?900:700,fontFamily:"monospace",fontSize:11}}>{s.v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── BÖLÜM 2: Teknik Analiz ── */}
          <div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"14px 16px",borderLeft:`3px solid ${t4?.sc||C.muted}`}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
              <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em"}}>Teknik Analiz — Binance 4H + 1H</div>
              <span style={{color:t4?.sc||C.muted,fontSize:10,fontWeight:700}}>{t4?.sl||"Yükleniyor"}</span>
            </div>
            {t4&&(
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12}}>
                <div>
                  <div style={{color:C.muted,fontSize:9,marginBottom:6}}>4H Göstergeler</div>
                  {[
                    {l:"EMA 9/21",v:`${t4.ema9?.toFixed(0)} / ${t4.ema21?.toFixed(0)}`,c:t4.ema9>t4.ema21?C.green:C.red},
                    {l:"RSI 14",v:t4.rsi?.toFixed(1),c:t4.rsi>70?C.red:t4.rsi<30?C.green:t4.rsi>55?C.green:C.orange},
                    {l:"MACD Hist",v:`${t4.histV>=0?"+":""}${t4.histV?.toFixed(0)}`,c:t4.histV>0?C.green:C.red},
                    {l:"BB %B",v:t4.bb?((t4.price-t4.bb.lower)/(t4.bb.upper-t4.bb.lower)*100).toFixed(0)+"%":"—",c:C.blue},
                  ].map((s,i)=>(
                    <div key={i} style={{display:"flex",justifyContent:"space-between",padding:"4px 8px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:4,marginBottom:3}}>
                      <span style={{color:C.muted,fontSize:9.5}}>{s.l}</span>
                      <span style={{color:s.c,fontFamily:"monospace",fontSize:10.5,fontWeight:700}}>{s.v}</span>
                    </div>
                  ))}
                </div>
                <div>
                  <div style={{color:C.muted,fontSize:9,marginBottom:6}}>Sinyal Bileşenleri</div>
                  {t4.signals.map((s,i)=>(
                    <div key={i} style={{display:"flex",alignItems:"center",gap:6,padding:"3px 6px",borderRadius:3,background:s.bull===true?`${C.green}08`:s.bull===false?`${C.red}08`:C.dim+"20",marginBottom:2}}>
                      <span style={{color:s.bull===true?C.green:s.bull===false?C.red:C.muted,fontSize:9}}>{s.bull===true?"▲":s.bull===false?"▼":"●"}</span>
                      <span style={{color:C.muted,fontSize:9.5}}>{s.k}: {s.v}</span>
                    </div>
                  ))}
                  <div style={{marginTop:8,padding:"8px",background:`${t4.sc}10`,border:`1px solid ${t4.sc}30`,borderRadius:6,textAlign:"center"}}>
                    <div style={{color:t4.sc,fontWeight:900,fontSize:16}}>4H {t4.sl}</div>
                    {t1&&<div style={{color:t1.sc,fontSize:11,marginTop:2}}>1H {t1.sl}</div>}
                  </div>
                </div>
              </div>
            )}
            {bt&&(
              <div style={{marginTop:10,padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                <div style={{color:C.muted,fontSize:9,marginBottom:5}}>Backtest — 4H 500 Bar</div>
                <div style={{display:"flex",gap:14,flexWrap:"wrap",fontSize:9.5}}>
                  {[{l:"WR",v:`${bt.wr}%`,c:bt.wr>=50?C.green:C.orange},{l:"PF",v:`${bt.pf}×`,c:bt.pf>=1.5?C.green:bt.pf>=1?C.gold:C.red},{l:"MaxDD",v:`${bt.maxDD}%`,c:bt.maxDD<10?C.green:C.red},{l:"Beklenti",v:`${bt.exp>=0?"+":""}${bt.exp}`,c:bt.exp>=0?C.green:C.red}].map((s,i)=>(
                    <span key={i}>{s.l}: <span style={{color:s.c,fontWeight:700}}>{s.v}</span></span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── BÖLÜM 3: Opsiyon Notları ── */}
          <div style={{background:C.card,border:`1px solid ${C.purple}30`,borderRadius:12,padding:"14px 16px",borderLeft:`3px solid ${C.purple}`}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10}}>
              <span style={{color:C.purple,fontWeight:700,fontSize:11,textTransform:"uppercase",letterSpacing:"0.06em"}}>◆ Opsiyon Notu</span>
              {dec.layers[3]?.signal!==0&&<span style={{color:dec.layers[3]?.color,fontSize:10,fontWeight:700}}>{dec.layers[3]?.signal>0?"▲ Bullish +1 puan":"▼ Bearish -1 puan"}</span>}
            </div>
            <div style={{display:"flex",gap:8,marginBottom:8}}>
              <input value={newNote} onChange={e=>setNewNote(e.target.value)} onKeyDown={e=>e.key==="Enter"&&addNote()} placeholder="Bugünün thesis notu... (Enter ile kaydet)" style={{flex:1,background:C.card2,border:`1px solid ${C.border}`,borderRadius:5,padding:"7px 10px",color:C.text,fontFamily:"monospace",fontSize:11}}/>
              <button onClick={addNote} style={{background:`${C.purple}15`,border:`1px solid ${C.purple}30`,color:C.purple,padding:"7px 14px",borderRadius:5,cursor:"pointer",fontFamily:"monospace",fontSize:10,fontWeight:700}}>+ Ekle</button>
            </div>
            <div style={{display:"flex",flexDirection:"column",gap:4}}>
              {optNotes.slice(0,5).map((n,i)=>(
                <div key={i} style={{display:"flex",gap:10,padding:"6px 10px",background:i===0?`${C.purple}08`:C.card2,border:`1px solid ${i===0?C.purple+"30":C.border}`,borderRadius:5}}>
                  <span style={{color:C.muted,fontSize:9,flexShrink:0,marginTop:1}}>{n.date}</span>
                  <span style={{color:C.text,fontSize:10.5,lineHeight:1.5,flex:1}}>{n.text}</span>
                  {n.spot&&<span style={{color:C.muted,fontSize:9,flexShrink:0}}>@{fK(n.spot)}</span>}
                </div>
              ))}
              {optNotes.length===0&&<div style={{color:C.muted,fontSize:10,textAlign:"center",padding:10}}>Not yok — thesis yaz</div>}
            </div>
          </div>

          {/* ── BÖLÜM 4: MenthorQ ── */}
          {mq&&<div style={{background:C.card,border:`1px solid ${C.border}`,borderRadius:12,padding:"14px 16px"}}>
            <div style={{color:C.muted,fontSize:9,textTransform:"uppercase",letterSpacing:"0.08em",marginBottom:10}}>MenthorQ Kurumsal Akış</div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(5,1fr)",gap:8}}>
              {[
                {l:"Gamma Z",v:(mq.gamma_z||0).toFixed(3),c:mq.gamma_z>0.5?C.green:mq.gamma_z<-0.5?C.red:C.gold},
                {l:"Dealer Bias",v:(mq.dealer_bias||0).toFixed(3),c:mq.dealer_bias>0.2?C.green:mq.dealer_bias<-0.2?C.red:C.muted},
                {l:"Flow Score",v:(mq.flow_score||0).toFixed(3),c:mq.flow_score>0.2?C.green:mq.flow_score<-0.2?C.red:C.muted},
                {l:"MQ Score",v:(mq.score||0).toFixed(3),c:mq.score>0.2?C.green:mq.score<-0.2?C.red:C.gold},
                {l:"Scalar",v:`${(lb?.final_scalar||1).toFixed(3)}×`,c:lb?.final_scalar>=1.02?C.green:lb?.final_scalar<=0.97?C.red:C.gold},
              ].map((s,i)=>(
                <div key={i} style={{padding:"8px 10px",background:C.card2,border:`1px solid ${C.border}`,borderRadius:6}}>
                  <div style={{color:C.muted,fontSize:8.5,marginBottom:2}}>{s.l}</div>
                  <div style={{color:s.c,fontWeight:700,fontSize:14,fontFamily:"monospace"}}>{s.v}</div>
                </div>
              ))}
            </div>
          </div>}

        </div>
      </div>
    </div>
  );
}
