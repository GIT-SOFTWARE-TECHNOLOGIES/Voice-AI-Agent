import { useState, useEffect, useRef, useCallback } from "react";
import { useTranscripts, useBills } from "./hooks/useApi";
import api from "./api";

// ============================================================
// DESIGN TOKENS
// ============================================================
const T = {
  bg: "#F9F5EF", bgDeep: "#F2EBE0", surface: "#FFFDF9",
  surfaceAlt: "#F5EFE6", border: "#E8DDD0", borderLight: "#EFE8DE",
  gold: "#C9973A", goldLight: "#E8C47A", goldSoft: "rgba(201,151,58,0.10)",
  maroon: "#7C2D3E", maroonSoft: "rgba(124,45,62,0.09)",
  forest: "#2D5C3E", forestSoft: "rgba(45,92,62,0.10)",
  navy: "#1F2D4A", navySoft: "rgba(31,45,74,0.09)",
  textPrimary: "#1A1208", textSecondary: "#6B5B48",
  textMuted: "#A89880", textLight: "#C4B09A",
  green: "#2D6B4A", greenSoft: "rgba(45,107,74,0.10)",
  red: "#8B2020", redSoft: "rgba(139,32,32,0.10)",
  amber: "#B8760A", amberSoft: "rgba(184,118,10,0.10)",
};

// ============================================================
// GLOBAL STYLES
// ============================================================
const GlobalStyle = () => {
  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = `
      @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&family=Jost:wght@300;400;500;600&display=swap');
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { background: #F9F5EF; color: #1A1208; font-family: 'Jost', sans-serif; }
      ::-webkit-scrollbar { width: 5px; }
      ::-webkit-scrollbar-track { background: #F2EBE0; }
      ::-webkit-scrollbar-thumb { background: #D4C4B0; border-radius: 4px; }
      @keyframes fadeUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
      @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
      @keyframes chatIn { from { opacity:0; transform:translateY(8px) scale(0.97); } to { opacity:1; transform:translateY(0) scale(1); } }
      @keyframes pulseDot { 0%,100%{opacity:1;transform:scale(1);} 50%{opacity:0.4;transform:scale(0.75);} }
      @keyframes pulseRing {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(201,151,58,0.5); }
        70% { transform: scale(1); box-shadow: 0 0 0 18px rgba(201,151,58,0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(201,151,58,0); }
      }
      @keyframes pulseRingRed {
        0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(124,45,62,0.6); }
        70% { transform: scale(1.04); box-shadow: 0 0 0 22px rgba(124,45,62,0); }
        100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(124,45,62,0); }
      }
      @keyframes waveBar { 0%,100% { transform: scaleY(0.3); } 50% { transform: scaleY(1); } }
      @keyframes spin { from{transform:rotate(0deg);} to{transform:rotate(360deg);} }
      @keyframes slideIn { from{opacity:0;transform:translateX(20px);} to{opacity:1;transform:translateX(0);} }
      .fade-up { animation: fadeUp 0.32s cubic-bezier(0.22,1,0.36,1) forwards; }
      .fade-in { animation: fadeIn 0.25s ease forwards; }
      .chat-in { animation: chatIn 0.22s ease forwards; }
      .slide-in { animation: slideIn 0.28s ease forwards; }
      .nav-item { transition: all 0.18s ease; cursor: pointer; }
      .nav-item:hover { background: rgba(201,151,58,0.08) !important; }
      .nav-item.active { background: rgba(201,151,58,0.14) !important; border-left: 3px solid #C9973A !important; }
      .card-h { transition: all 0.2s ease; }
      .card-h:hover { box-shadow: 0 6px 28px rgba(124,45,62,0.08), 0 2px 8px rgba(0,0,0,0.04); transform: translateY(-1px); border-color: #D4C4B0 !important; }
      .btn-gold { background: linear-gradient(135deg,#C9973A,#B8800C); color:#FFF8EE; border:none; cursor:pointer; font-family:'Jost'; font-weight:500; letter-spacing:0.04em; transition:all 0.18s ease; }
      .btn-gold:hover { background:linear-gradient(135deg,#D9A84A,#C8901C); box-shadow:0 4px 18px rgba(201,151,58,0.38); transform:translateY(-1px); }
      .btn-outline { background:transparent; border:1.5px solid #D4C4B0; color:#6B5B48; cursor:pointer; font-family:'Jost'; transition:all 0.18s ease; }
      .btn-outline:hover { border-color:#C9973A; color:#C9973A; background:rgba(201,151,58,0.06); }
      .btn-maroon { background:linear-gradient(135deg,#7C2D3E,#6A2234); color:#FFE8D6; border:none; cursor:pointer; font-family:'Jost'; font-weight:500; letter-spacing:0.04em; transition:all 0.18s ease; }
      .btn-forest { background:linear-gradient(135deg,#2D5C3E,#1e4028); color:#D4F0E0; border:none; cursor:pointer; font-family:'Jost'; font-weight:500; letter-spacing:0.04em; transition:all 0.18s ease; }
      .tab-item { cursor:pointer; transition:all 0.15s ease; }
      .tab-item:hover { color:#1A1208 !important; }
      .tab-item.active { color:#C9973A !important; border-bottom:2px solid #C9973A !important; }
      input:focus, textarea:focus { outline:none; border-color:#C9973A !important; box-shadow:0 0 0 3px rgba(201,151,58,0.12); }
      .voice-btn-idle { animation: pulseRing 2.5s infinite; }
      .voice-btn-listening { animation: pulseRingRed 1.2s infinite; }
      .wave-bar { display:inline-block; width:4px; border-radius:4px; background:currentColor; animation: waveBar 0.6s ease-in-out infinite; }
      .panel-tab { cursor:pointer; padding:8px 14px; font-size:12px; font-weight:500; color:#A89880; border-bottom:2px solid transparent; transition:all 0.15s; font-family:'Jost'; letter-spacing:0.02em; }
      .panel-tab:hover { color:#6B5B48; }
      .panel-tab.active { color:#C9973A; border-bottom:2px solid #C9973A; }
      .transcript-agent { background:linear-gradient(135deg,#1F2D4A,#16233a); color:#C9D8F0; }
      .transcript-user { background:linear-gradient(135deg,#7C2D3E,#6A2234); color:#FFE8D6; }
      .pay-link { color:#2D5C3E; text-decoration:none; font-weight:500; border-bottom:1px dashed #2D5C3E; transition:all 0.15s; }
      .pay-link:hover { color:#C9973A; border-bottom-color:#C9973A; }
    `;
    document.head.appendChild(style);
    return () => document.head.removeChild(style);
  }, []);
  return null;
};

// ============================================================
// LOADING / ERROR STATES
// ============================================================
const LoadingSpinner = ({ size = 20 }) => (
  <div style={{ display:"flex", alignItems:"center", justifyContent:"center", padding:20 }}>
    <div style={{ width:size, height:size, border:`2px solid ${T.border}`, borderTopColor:T.gold, borderRadius:"50%", animation:"spin 0.8s linear infinite" }} />
  </div>
);

const ErrorBanner = ({ message, onRetry }) => (
  <div style={{ margin:12, padding:"10px 14px", background:T.redSoft, borderRadius:9, border:`1px solid ${T.red}30`, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
    <span style={{ fontSize:12, color:T.red }}>⚠️ {message}</span>
    {onRetry && <button className="btn-outline" onClick={onRetry} style={{ padding:"3px 10px", fontSize:11, borderRadius:7 }}>Retry</button>}
  </div>
);

// ============================================================
// MICRO COMPONENTS
// ============================================================
const Divider = () => (
  <div style={{ display:"flex", alignItems:"center", gap:10, margin:"4px 0" }}>
    <div style={{ flex:1, height:1, background:`linear-gradient(to right, transparent, ${T.border})` }} />
    <span style={{ color:T.gold, fontSize:8, opacity:0.7 }}>✦</span>
    <div style={{ flex:1, height:1, background:`linear-gradient(to left, transparent, ${T.border})` }} />
  </div>
);

const StatusDot = ({ color=T.green, pulse=true }) => (
  <span style={{ display:"inline-block", width:7, height:7, borderRadius:"50%", background:color, animation: pulse ? "pulseDot 2s infinite" : "none", boxShadow:`0 0 6px ${color}60`, flexShrink:0 }} />
);

const Tag = ({ children, color=T.gold }) => (
  <span style={{ padding:"3px 10px", borderRadius:20, fontSize:10.5, fontWeight:600, letterSpacing:"0.04em", background:`${color}12`, color, border:`1px solid ${color}28`, fontFamily:"Jost", textTransform:"uppercase" }}>{children}</span>
);

const Card = ({ children, style={}, className="" }) => (
  <div className={`card-h ${className}`} style={{ background:T.surface, border:`1px solid ${T.border}`, borderRadius:14, padding:22, boxShadow:"0 2px 12px rgba(0,0,0,0.04)", transition:"all 0.2s ease", ...style }}>{children}</div>
);

const SoundWave = ({ active, color="#C9973A", bars=12 }) => (
  <div style={{ display:"flex", gap:3, alignItems:"center", height:28 }}>
    {Array.from({length:bars}).map((_,i) => (
      <div key={i} className="wave-bar" style={{ height: active ? `${Math.random()*100}%` : "30%", minHeight:4, maxHeight:28, background: color, opacity: active ? 0.9 : 0.3, animationDelay: `${i*0.06}s`, animationDuration: active ? `${0.4+Math.random()*0.4}s` : "none", color }} />
    ))}
  </div>
);

const VoiceOrb = ({ status, onClick, size=80 }) => {
  const colors = {
    idle: { bg:`linear-gradient(135deg, ${T.gold}, #8B5C1A)`, shadow:`0 8px 32px ${T.gold}50` },
    listening: { bg:`linear-gradient(135deg, ${T.maroon}, #5A1228)`, shadow:`0 8px 32px ${T.maroon}60` },
    speaking: { bg:`linear-gradient(135deg, ${T.navy}, #142238)`, shadow:`0 8px 32px ${T.navy}60` },
    processing: { bg:`linear-gradient(135deg, ${T.forest}, #1A3826)`, shadow:`0 8px 32px ${T.forest}60` },
  };
  const c = colors[status] || colors.idle;
  const cls = status === "idle" ? "voice-btn-idle" : status === "listening" ? "voice-btn-listening" : "";
  return (
    <div onClick={onClick} className={cls} style={{ width:size, height:size, borderRadius:"50%", cursor:"pointer", background:c.bg, boxShadow:c.shadow, display:"flex", alignItems:"center", justifyContent:"center", transition:"all 0.3s ease", userSelect:"none", position:"relative" }}>
      {status === "listening" && <div style={{ position:"absolute", inset:-8, borderRadius:"50%", border:`2px solid ${T.maroon}40`, animation:"pulseRingRed 1.2s infinite" }} />}
      <div style={{ fontSize: size*0.35, filter:"drop-shadow(0 2px 4px rgba(0,0,0,0.3))" }}>
        {status === "listening" ? "🎙️" : status === "speaking" ? "🔊" : status === "processing" ? "⏳" : "🎙️"}
      </div>
    </div>
  );
};

// ============================================================
// TRANSCRIPT PANEL — Real API data
// ============================================================
const TranscriptPanel = ({ liveSession }) => {
  const { data: transcripts, loading, error, refetch } = useTranscripts();
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState("live");

  const statusColor = (s) => s === "processed" ? T.green : s === "unprocessed" ? T.amber : T.red;
  const session = selected ? transcripts?.find(t => t.id === selected || t.session_id === selected) : null;
  const [sessionDetail, setSessionDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadSession = async (id) => {
    setSelected(id);
    setLoadingDetail(true);
    try {
      const detail = await api.getTranscript(id);
      setSessionDetail(detail);
    } catch (e) {
      setSessionDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100%", overflow:"hidden" }}>
      <div style={{ display:"flex", borderBottom:`1px solid ${T.border}`, background:T.surface, flexShrink:0 }}>
        {[["live","🔴 Live Session"],["history","📋 History"]].map(([k,l]) => (
          <div key={k} className={`panel-tab ${view===k?"active":""}`} onClick={() => { setView(k); setSelected(null); setSessionDetail(null); }}>{l}</div>
        ))}
        {view === "history" && (
          <button className="btn-outline" onClick={refetch} style={{ marginLeft:"auto", padding:"4px 10px", fontSize:10, borderRadius:6, margin:"6px 8px" }}>↻</button>
        )}
      </div>

      {view === "live" && (
        <div style={{ flex:1, overflowY:"auto", padding:14, display:"flex", flexDirection:"column", gap:10 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 12px", background:T.redSoft, borderRadius:9, border:`1px solid ${T.red}25`, marginBottom:4 }}>
            <StatusDot color={T.red} />
            <span style={{ fontSize:11, fontWeight:600, color:T.red, letterSpacing:"0.04em" }}>LIVE SESSION</span>
          </div>
          {liveSession.map((turn, i) => (
            <div key={i} className="slide-in" style={{ display:"flex", flexDirection:"column", gap:3 }}>
              <div style={{ fontSize:10, fontWeight:600, letterSpacing:"0.08em", color: turn.role === "agent" ? T.navy : T.maroon, textTransform:"uppercase" }}>
                {turn.role === "agent" ? "🏨 Vista Agent" : "👤 Guest"}
              </div>
              <div className={turn.role === "agent" ? "transcript-agent" : "transcript-user"} style={{ padding:"10px 14px", borderRadius:10, fontSize:12.5, lineHeight:1.65, fontFamily:"Jost" }}>
                {turn.text}
              </div>
            </div>
          ))}
          {liveSession.length === 0 && (
            <div style={{ textAlign:"center", padding:"40px 0", color:T.textMuted }}>
              <div style={{ fontSize:28, marginBottom:8 }}>🎙️</div>
              <div style={{ fontSize:12, fontStyle:"italic", fontFamily:"Cormorant Garamond" }}>Waiting for voice interaction…</div>
              <div style={{ fontSize:11, marginTop:4 }}>Say "Hey Vista" to start</div>
            </div>
          )}
        </div>
      )}

      {view === "history" && !selected && (
        <div style={{ flex:1, overflowY:"auto", padding:14, display:"flex", flexDirection:"column", gap:8 }}>
          {loading && <LoadingSpinner />}
          {error && <ErrorBanner message={error} onRetry={refetch} />}
          {!loading && !error && transcripts?.length === 0 && (
            <div style={{ textAlign:"center", padding:"32px 0", color:T.textMuted, fontSize:12 }}>No transcripts yet</div>
          )}
          {transcripts?.map((t, i) => (
            <div key={i} onClick={() => loadSession(t.id || t.session_id)} style={{ padding:"12px 14px", background:T.surface, borderRadius:11, border:`1px solid ${T.border}`, cursor:"pointer", transition:"all 0.18s" }}
              onMouseEnter={e => { e.currentTarget.style.borderColor=T.gold; e.currentTarget.style.background=T.goldSoft; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor=T.border; e.currentTarget.style.background=T.surface; }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:4 }}>
                <div style={{ fontFamily:"Playfair Display", fontSize:13, fontWeight:500, color:T.textPrimary }}>{t.room || t.session_id || t.id}</div>
                <Tag color={statusColor(t.status)}>{t.status}</Tag>
              </div>
              <div style={{ display:"flex", justifyContent:"space-between" }}>
                <span style={{ fontSize:11, color:T.textMuted }}>{t.id || t.session_id} · {t.turn_count} turns</span>
                <span style={{ fontSize:10, color:T.textMuted }}>{t.modified_at ? new Date(t.modified_at).toLocaleTimeString() : ""}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {view === "history" && selected && (
        <div style={{ flex:1, overflowY:"auto", padding:14 }}>
          <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:14 }}>
            <button className="btn-outline" onClick={() => { setSelected(null); setSessionDetail(null); }} style={{ padding:"5px 12px", borderRadius:8, fontSize:11 }}>← Back</button>
            <div style={{ fontSize:11, color:T.textMuted }}>{selected}</div>
          </div>
          {loadingDetail && <LoadingSpinner />}
          {!loadingDetail && sessionDetail && (
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              {sessionDetail.turns?.map((turn, i) => (
                <div key={i} style={{ display:"flex", flexDirection:"column", gap:3 }}>
                  <div style={{ fontSize:10, fontWeight:600, letterSpacing:"0.08em", color: turn.role === "agent" ? T.navy : T.maroon, textTransform:"uppercase" }}>
                    {turn.role === "agent" ? "🏨 Agent" : "👤 Guest"}
                  </div>
                  <div className={turn.role === "agent" ? "transcript-agent" : "transcript-user"} style={{ padding:"10px 14px", borderRadius:10, fontSize:12.5, lineHeight:1.65 }}>
                    {turn.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ============================================================
// PAYMENT / BILL PANEL — Real API data
// ============================================================
const PaymentPanel = ({ localBills = [] }) => {
  const { data: apiBills, loading, error, refetch } = useBills();
  const [selected, setSelected] = useState(null);

  // Merge local (voice-generated) bills with API bills, dedup by order_id
  const allBills = (() => {
    const map = new Map();
    (apiBills || []).forEach(b => map.set(b.order_id, b));
    localBills.forEach(b => map.set(b.order_id, b));   // local overrides
    return Array.from(map.values());
  })();

  const statusColor = (s) => s === "success" ? T.green : s === "pending" ? T.amber : T.red;
  const serviceLabel = (s) => s?.replace(/_/g," ").replace(/\b\w/g, c => c.toUpperCase()) || "Service";
  const bill = selected ? allBills.find(b => b.order_id === selected) : null;
  const total_pending = allBills.filter(b => b.status === "pending").reduce((s, b) => s + (b.total || 0), 0);

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100%", overflow:"hidden" }}>
      <div style={{ padding:"10px 14px", background:T.goldSoft, borderBottom:`1px solid ${T.gold}20`, flexShrink:0, display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <div>
          <div style={{ fontSize:10, color:T.textMuted, marginBottom:1 }}>Pending Bills</div>
          <div style={{ fontFamily:"Playfair Display", fontWeight:700, fontSize:18, color:T.gold }}>₹{total_pending.toLocaleString("en-IN")}</div>
        </div>
        <div style={{ display:"flex", gap:10, alignItems:"center" }}>
          <div style={{ textAlign:"right" }}>
            <div style={{ fontSize:10, color:T.textMuted, marginBottom:1 }}>Total</div>
            <div style={{ fontFamily:"Playfair Display", fontWeight:600, fontSize:15, color:T.textSecondary }}>{allBills.length}</div>
          </div>
          <button className="btn-outline" onClick={refetch} style={{ padding:"4px 9px", fontSize:10, borderRadius:6 }}>↻</button>
        </div>
      </div>

      {!selected && (
        <div style={{ flex:1, overflowY:"auto", padding:14, display:"flex", flexDirection:"column", gap:8 }}>
          {loading && <LoadingSpinner />}
          {error && <ErrorBanner message={error} onRetry={refetch} />}
          {!loading && allBills.length === 0 && (
            <div style={{ textAlign:"center", padding:"32px 0", color:T.textMuted, fontSize:12 }}>No bills yet</div>
          )}
          {allBills.map((b, i) => (
            <div key={i} onClick={() => setSelected(b.order_id)} style={{ padding:"12px 14px", background:T.surface, borderRadius:11, border:`1px solid ${T.border}`, cursor:"pointer", transition:"all 0.18s" }}
              onMouseEnter={e => { e.currentTarget.style.borderColor=T.gold; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor=T.border; }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:5 }}>
                <div>
                  <div style={{ fontFamily:"Playfair Display", fontSize:12.5, fontWeight:500, color:T.textPrimary }}>{b.guest_name} · Rm {b.room_number}</div>
                  <div style={{ fontSize:10.5, color:T.textMuted, marginTop:1 }}>{serviceLabel(b.service_type)}</div>
                </div>
                <Tag color={statusColor(b.status)}>{b.status}</Tag>
              </div>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                <span style={{ fontSize:10, color:T.textMuted }}>{b.bill_id}</span>
                <span style={{ fontFamily:"Playfair Display", fontWeight:700, fontSize:14, color:T.gold }}>₹{(b.total||0).toLocaleString("en-IN")}</span>
              </div>
              {b.status === "pending" && b.payment_link && (
                <a href={b.payment_link} target="_blank" rel="noreferrer" className="pay-link" style={{ display:"block", marginTop:8, fontSize:10.5, padding:"5px 10px", background:T.forestSoft, borderRadius:7, border:`1px solid ${T.forest}25`, textAlign:"center" }}>
                  💳 Pay Now
                </a>
              )}
            </div>
          ))}
        </div>
      )}

      {selected && bill && (
        <div style={{ flex:1, overflowY:"auto", padding:14 }}>
          <button className="btn-outline" onClick={() => setSelected(null)} style={{ padding:"5px 12px", borderRadius:8, fontSize:11, marginBottom:14 }}>← All Bills</button>
          <div style={{ background:T.surface, borderRadius:13, border:`1px solid ${T.border}`, overflow:"hidden" }}>
            <div style={{ padding:"14px 16px", background:`linear-gradient(135deg, ${T.navy}, #2A3D5C)`, color:"#F5E8D0" }}>
              <div style={{ fontFamily:"Playfair Display", fontWeight:700, fontSize:17, marginBottom:2 }}>Grand Vista Hotel</div>
              <div style={{ fontSize:10, opacity:0.6, letterSpacing:"0.08em", textTransform:"uppercase" }}>Tax Invoice</div>
            </div>
            <div style={{ padding:"14px 16px" }}>
              {[["Bill ID", bill.bill_id], ["Order ID", bill.order_id], ["Guest", bill.guest_name], ["Room", bill.room_number], ["Service", serviceLabel(bill.service_type)], ["Date", bill.created_at]].map(([k,v]) => (
                <div key={k} style={{ display:"flex", justifyContent:"space-between", padding:"5px 0", borderBottom:`1px solid ${T.borderLight}`, fontSize:12 }}>
                  <span style={{ color:T.textMuted }}>{k}</span>
                  <span style={{ color:T.textPrimary, fontWeight:500 }}>{v}</span>
                </div>
              ))}
              <div style={{ marginTop:12, marginBottom:8 }}>
                <div style={{ fontSize:10, fontWeight:600, color:T.textMuted, textTransform:"uppercase", letterSpacing:"0.06em", marginBottom:6 }}>Items</div>
                {(bill.items || []).map((item, j) => (
                  <div key={j} style={{ display:"flex", justifyContent:"space-between", padding:"5px 0", fontSize:12, borderBottom:`1px solid ${T.borderLight}` }}>
                    <span style={{ color:T.textSecondary }}>{item.name} ×{item.quantity}</span>
                    <span style={{ color:T.textPrimary }}>₹{(item.total||0).toLocaleString("en-IN")}</span>
                  </div>
                ))}
              </div>
              <div style={{ display:"flex", justifyContent:"space-between", padding:"10px 0 6px", borderTop:`2px solid ${T.border}`, marginTop:4 }}>
                <span style={{ fontFamily:"Playfair Display", fontWeight:700, fontSize:15 }}>Total</span>
                <span style={{ fontFamily:"Playfair Display", fontWeight:700, fontSize:18, color:T.gold }}>₹{(bill.total||0).toLocaleString("en-IN")}</span>
              </div>
              <div style={{ display:"flex", justifyContent:"center", margin:"10px 0 6px" }}>
                <Tag color={statusColor(bill.status)}>{bill.status === "success" ? "✓ Paid" : bill.status === "pending" ? "⏳ Awaiting Payment" : "✗ Failed"}</Tag>
              </div>
              {bill.status === "pending" && bill.payment_link && (
                <div style={{ marginTop:10, padding:"12px 14px", background:T.forestSoft, borderRadius:10, border:`1px solid ${T.forest}25` }}>
                  <div style={{ fontSize:10.5, color:T.forest, fontWeight:600, marginBottom:6, textTransform:"uppercase", letterSpacing:"0.04em" }}>💳 Payment Link</div>
                  <a href={bill.payment_link} target="_blank" rel="noreferrer" style={{ fontSize:11, color:T.forest, wordBreak:"break-all", textDecoration:"underline" }}>{bill.payment_link}</a>
                  <button className="btn-forest" style={{ width:"100%", marginTop:10, padding:"9px", borderRadius:9, fontSize:12 }} onClick={() => window.open(bill.payment_link, "_blank")}>Open Payment Page →</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ============================================================
// RIGHT PANEL
// ============================================================
const RightPanel = ({ liveSession, localBills }) => {
  const [tab, setTab] = useState("transcript");
  return (
    <div style={{ width:340, display:"flex", flexDirection:"column", background:T.bg, borderLeft:`1px solid ${T.border}`, overflow:"hidden" }}>
      <div style={{ display:"flex", background:T.surface, borderBottom:`1px solid ${T.border}`, flexShrink:0, overflowX:"auto" }}>
        {[{ id:"transcript", label:"📝 Transcript" }, { id:"payment", label:"💳 Bills" }].map(t => (
          <div key={t.id} className={`panel-tab ${tab===t.id?"active":""}`} onClick={() => setTab(t.id)} style={{ whiteSpace:"nowrap" }}>{t.label}</div>
        ))}
      </div>
      <div style={{ flex:1, overflow:"hidden", display:"flex", flexDirection:"column" }}>
        {tab === "transcript" && <TranscriptPanel liveSession={liveSession} />}
        {tab === "payment" && <PaymentPanel localBills={localBills} />}
      </div>
    </div>
  );
};

// ============================================================
// VOICE ENGINE (unchanged — browser APIs)
// ============================================================
const useSpeechSynthesis = () => {
  const speak = useCallback((text, onEnd) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.0; u.pitch = 1.05; u.volume = 1;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => v.name.includes("Google") && v.lang.startsWith("en")) || voices.find(v => v.lang.startsWith("en-IN")) || voices.find(v => v.lang.startsWith("en"));
    if (preferred) u.voice = preferred;
    u.onend = onEnd || null;
    window.speechSynthesis.speak(u);
  }, []);
  const stop = useCallback(() => window.speechSynthesis?.cancel(), []);
  return { speak, stop };
};

const useSpeechRecognition = ({ onResult, onEnd, onError }) => {
  const recRef = useRef(null);
  const start = useCallback(() => {
    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
      onError?.("Speech recognition not supported. Try Chrome.");
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new SR();
    r.lang = "en-IN"; r.interimResults = true; r.maxAlternatives = 1; r.continuous = false;
    r.onresult = (e) => {
      const t = Array.from(e.results).map(r => r[0].transcript).join("");
      onResult?.(t, e.results[e.results.length - 1].isFinal);
    };
    r.onend = () => onEnd?.();
    r.onerror = (e) => onError?.(e.error);
    recRef.current = r;
    r.start();
  }, [onResult, onEnd, onError]);
  const stop = useCallback(() => { recRef.current?.stop(); }, []);
  return { start, stop };
};

// ============================================================
// VOICE AGENT PAGE
// ============================================================
const VoiceAgentPage = ({ liveSession, setLiveSession, localBills, setLocalBills }) => {
  const [status, setStatus] = useState("idle");
  const [interimText, setInterimText] = useState("");
  const [messages, setMessages] = useState([
    { from:"ai", text:"Hello! I'm Vista, your AI voice concierge at Grand Vista Hotel.\n\nSay \"Hey Vista\" followed by your request. I can:\n• Order food 🍔 (\"Hey Vista, order a cheese burger\")\n• Book a cab 🚕 (\"Hey Vista, book me a cab to airport\")\n• Room service 🛎️ (\"Vista, I need extra towels\")\n• View bills 💳 (check the Bills tab →)\n\nTranscripts appear live in the Transcript tab →", time:"now" }
  ]);
  const [error, setError] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [textInput, setTextInput] = useState("");
  const bottomRef = useRef(null);
  const { speak, stop: stopSpeaking } = useSpeechSynthesis();

  const addMessage = useCallback((from, text) => {
    setMessages(prev => [...prev, { from, text, time: new Date().toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}) }]);
  }, []);

  const addTranscriptTurn = useCallback((role, text) => {
    setLiveSession(prev => [...prev, { role, text }]);
  }, [setLiveSession]);

  const addBill = useCallback((bill) => setLocalBills(prev => [bill, ...prev]), [setLocalBills]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior:"smooth" }); }, [messages]);

  // ── Token fetch from real API ─────────────────────────────────────────────
  const getToken = async () => {
    try {
      const data = await api.getToken();
      return data;
    } catch (e) {
      console.warn("Token fetch failed:", e.message);
      return null;
    }
  };

  const processUtterance = async (text) => {
    if (!text.trim()) return;
    const t = text.toLowerCase();
    addMessage("user", text);
    addTranscriptTurn("user", text);
    setStatus("processing");

    await new Promise(r => setTimeout(r, 400));

    // Simple local intent detection (keeps voice working offline)
    let aiMsg = "";

    if (t.includes("burger") || t.includes("pizza") || t.includes("food") || t.includes("order")) {
      const qty = t.includes("two") || t.includes("2") ? 2 : 1;
      const item = t.includes("pizza") ? "Margherita Pizza" : "Cheese Burger";
      const price = item === "Margherita Pizza" ? 380 : 280;
      const total_item = price * qty;
      const tax = Math.round(total_item * 0.05);
      const total = total_item + tax;
      const order_id = "ORD-" + Date.now().toString().slice(-8);
      const bill = {
        bill_id: "BILL-" + Date.now().toString().slice(-6), order_id,
        service_type: "food_order", room_number: "304", guest_name: "Mr. Arora",
        guest_email: "guest@email.com",
        items: [{ name: item, quantity: qty, unit_price: price, total: total_item }],
        subtotal: total_item, tax_rate: 0.05, tax_amount: tax, total,
        currency: "INR", status: "pending",
        payment_link: `${import.meta.env.VITE_API_URL || "http://localhost:8080"}/pay/${order_id}`,
        created_at: new Date().toLocaleString("en-IN"),
      };
      addBill(bill);
      aiMsg = `Perfect! Ordering ${qty} × ${item} for ₹${total}. Your order has been placed and will arrive in approximately 25 minutes.\n\n💳 Pay here: ${bill.payment_link}`;
    } else if (t.includes("cab") || t.includes("taxi")) {
      const dest = text.match(/to\s+([^.!?]+)/i)?.[1] || "your destination";
      aiMsg = `Booking a cab to ${dest} now. A driver will arrive in 5 minutes. Check the Bills tab for your invoice.`;
    } else if (t.includes("towel") || t.includes("pillow") || t.includes("housekeeping") || t.includes("laundry")) {
      aiMsg = `Got it! I've arranged the room service request. Our team will arrive within 15 minutes.`;
    } else if (t.includes("wifi") || t.includes("password")) {
      aiMsg = `Wi-Fi Network: GrandVista_Guest\nPassword: GV@2024\nSpeed: 100 Mbps. Enjoy!`;
    } else if (t.includes("hello") || t.includes("hi") || t.includes("hey vista")) {
      aiMsg = `Hello! I'm Vista, your AI concierge. I can help with food orders, cab bookings, room service, or billing. How may I assist?`;
    } else {
      aiMsg = `I'm here to help. You can ask me to order food, book a cab, arrange room service, or get Wi-Fi details.`;
    }

    addMessage("ai", aiMsg);
    addTranscriptTurn("agent", aiMsg);
    setStatus("speaking");
    if (voiceEnabled) {
      speak(aiMsg.replace(/https?:\/\/\S+/g, ""), () => setStatus("idle"));
    } else {
      setStatus("idle");
    }
  };

  const { start: startRecognition, stop: stopRecognition } = useSpeechRecognition({
    onResult: (text, isFinal) => {
      setInterimText(text);
      if (isFinal) { setInterimText(""); processUtterance(text); }
    },
    onEnd: () => { if (status === "listening") setStatus("idle"); },
    onError: (e) => { setError(e); setStatus("idle"); },
  });

  const toggleListen = () => {
    if (status === "listening") { stopRecognition(); setStatus("idle"); }
    else if (status === "idle") { setError(""); setStatus("listening"); startRecognition(); }
  };

  const sendText = () => {
    if (!textInput.trim()) return;
    processUtterance(textInput);
    setTextInput("");
  };

  const statusColors = { idle: T.textMuted, listening: T.maroon, speaking: T.navy, processing: T.forest };
  const quickCommands = [
    { icon:"🍔", label:"Order Food", cmd:"Hey Vista, order a cheese burger" },
    { icon:"🚕", label:"Book Cab", cmd:"Hey Vista, book me a cab to the airport" },
    { icon:"🛎️", label:"Room Service", cmd:"Vista, I need extra towels" },
    { icon:"📶", label:"WiFi", cmd:"What's the WiFi password?" },
    { icon:"💳", label:"My Bill", cmd:"Show my bill" },
  ];

  return (
    <div style={{ display:"flex", flex:1, overflow:"hidden" }}>
      <div style={{ flex:1, display:"flex", flexDirection:"column", overflow:"hidden" }}>
        {/* Header */}
        <div style={{ padding:"10px 18px", background:T.surface, borderBottom:`1px solid ${T.border}`, display:"flex", alignItems:"center", justifyContent:"space-between", flexShrink:0 }}>
          <div>
            <div style={{ fontFamily:"Playfair Display", fontWeight:600, fontSize:15, color:T.textPrimary }}>Vista AI Concierge</div>
            <div style={{ fontSize:10, color:T.textMuted }}>Room 304 · Mr. Arora</div>
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            {status === "listening" && <SoundWave active={true} color={T.maroon} bars={8} />}
            {status === "speaking" && <SoundWave active={true} color={T.navy} bars={8} />}
            <div onClick={() => setVoiceEnabled(v => !v)} style={{ display:"flex", alignItems:"center", gap:5, padding:"4px 10px", borderRadius:20, background: voiceEnabled ? T.goldSoft : T.surfaceAlt, border:`1px solid ${voiceEnabled ? T.gold : T.border}`, cursor:"pointer", fontSize:11, color: voiceEnabled ? T.gold : T.textMuted, fontWeight:500 }}>
              {voiceEnabled ? "🔊 Audio On" : "🔇 Audio Off"}
            </div>
          </div>
        </div>

        {/* Messages */}
        <div style={{ flex:1, overflowY:"auto", padding:"16px 18px", display:"flex", flexDirection:"column", gap:12, background:T.bg }}>
          {messages.map((msg, i) => (
            <div key={i} className="chat-in" style={{ display:"flex", justifyContent: msg.from === "user" ? "flex-end" : "flex-start" }}>
              {msg.from === "ai" && <div style={{ width:32, height:32, borderRadius:9, flexShrink:0, marginRight:9, marginTop:2, background:`linear-gradient(135deg, ${T.gold}25, ${T.maroon}15)`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:14, border:`1px solid ${T.gold}25` }}>🏨</div>}
              <div style={{ maxWidth:"72%", padding:"11px 14px", borderRadius:14, background: msg.from === "user" ? `linear-gradient(135deg, ${T.maroon}, #6A2234)` : T.surface, border: msg.from === "user" ? "none" : `1px solid ${T.border}`, fontSize:13, color: msg.from === "user" ? "#FFE8D6" : T.textPrimary, lineHeight:1.65, borderBottomRightRadius: msg.from === "user" ? 4 : 14, borderBottomLeftRadius: msg.from === "ai" ? 4 : 14, whiteSpace:"pre-wrap", wordBreak:"break-word" }}>
                {msg.from === "ai" && msg.text.includes("https://") ? (
                  msg.text.split("\n").map((line, li) => (
                    <div key={li}>{line.includes("https://") ? line.split(/(https:\/\/\S+)/g).map((p, pi) => p.startsWith("https://") ? <a key={pi} href={p} target="_blank" rel="noreferrer" className="pay-link">{p}</a> : <span key={pi}>{p}</span>) : line}{li < msg.text.split("\n").length - 1 && <br />}</div>
                  ))
                ) : msg.text}
                {msg.time && <div style={{ fontSize:10, opacity:0.5, marginTop:5, textAlign:"right" }}>{msg.time}</div>}
              </div>
              {msg.from === "user" && <div style={{ width:32, height:32, borderRadius:9, flexShrink:0, marginLeft:9, marginTop:2, background:`${T.maroon}18`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, border:`1px solid ${T.maroon}25` }}>👤</div>}
            </div>
          ))}
          {status === "listening" && interimText && (
            <div className="chat-in" style={{ display:"flex", justifyContent:"flex-end" }}>
              <div style={{ maxWidth:"72%", padding:"9px 13px", borderRadius:14, borderBottomRightRadius:4, background:`${T.maroon}20`, border:`1.5px dashed ${T.maroon}50`, fontSize:12.5, color:T.maroon, fontStyle:"italic" }}>{interimText || "…"}</div>
            </div>
          )}
          {status === "processing" && (
            <div className="chat-in" style={{ display:"flex", alignItems:"center", gap:9 }}>
              <div style={{ width:32, height:32, borderRadius:9, background:`${T.gold}18`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:14 }}>🏨</div>
              <div style={{ padding:"9px 13px", background:T.surface, borderRadius:14, border:`1px solid ${T.border}`, display:"flex", gap:5, alignItems:"center" }}>
                {[0,0.2,0.4].map((d,i) => <div key={i} style={{ width:7, height:7, borderRadius:"50%", background:T.gold, animation:`pulseDot 1.2s ${d}s infinite` }} />)}
                <span style={{ marginLeft:4, fontSize:11, color:T.textMuted }}>Vista is thinking…</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Quick Commands */}
        <div style={{ padding:"10px 14px 0", background:T.surface, borderTop:`1px solid ${T.border}`, flexShrink:0 }}>
          <div style={{ display:"flex", gap:6, overflowX:"auto", paddingBottom:8 }}>
            {quickCommands.map((qc, i) => (
              <button key={i} onClick={() => processUtterance(qc.cmd)} className="btn-outline" style={{ padding:"6px 10px", borderRadius:9, fontSize:10.5, whiteSpace:"nowrap", display:"flex", alignItems:"center", gap:5, background:T.surface, fontFamily:"Jost" }}>
                <span style={{ fontSize:14 }}>{qc.icon}</span><span style={{ fontWeight:500, color:T.textSecondary }}>{qc.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Input */}
        <div style={{ background:T.surface, flexShrink:0 }}>
          <div style={{ padding:"10px 18px 8px", display:"flex", flexDirection:"column", alignItems:"center", gap:7 }}>
            {error && <div style={{ width:"100%", padding:"7px 12px", background:T.redSoft, borderRadius:9, border:`1px solid ${T.red}30`, fontSize:12, color:T.red }}>⚠️ {error}</div>}
            <VoiceOrb status={status} onClick={toggleListen} size={62} />
            <div style={{ fontSize:10.5, color:statusColors[status], fontWeight:500, letterSpacing:"0.04em", textTransform:"uppercase" }}>
              {status === "listening" ? "● Recording" : status === "processing" ? "◌ Processing" : status === "speaking" ? "◉ Speaking" : "Tap to talk"}
            </div>
          </div>
          <div style={{ padding:"0 18px 14px", display:"flex", gap:8 }}>
            <input value={textInput} onChange={e => setTextInput(e.target.value)} onKeyDown={e => e.key === "Enter" && sendText()}
              placeholder="Or type your request here…"
              style={{ flex:1, padding:"9px 13px", borderRadius:10, background:T.bg, border:`1.5px solid ${T.border}`, color:T.textPrimary, fontSize:13, fontFamily:"Jost" }}
            />
            <button className="btn-gold" onClick={sendText} style={{ padding:"0 16px", borderRadius:10, fontSize:13 }}>Send</button>
          </div>
        </div>
      </div>

      <RightPanel liveSession={liveSession} localBills={localBills} />
    </div>
  );
};

// ============================================================
// ROOT APP
// ============================================================
export default function App() {
  const [role, setRole] = useState(null);
  const [liveSession, setLiveSession] = useState([]);
  const [localBills, setLocalBills] = useState([]);

  if (!role) return (
    <>
      <GlobalStyle />
      <div style={{ minHeight:"100vh", background:T.bg, display:"flex", alignItems:"center", justifyContent:"center", position:"relative", overflow:"hidden" }}>
        <div style={{ position:"absolute", inset:0, overflow:"hidden", pointerEvents:"none" }}>
          <div style={{ position:"absolute", top:"-10%", right:"-5%", width:500, height:500, borderRadius:"50%", background:`radial-gradient(circle,${T.gold}08 0%,transparent 70%)` }} />
          <div style={{ position:"absolute", bottom:"-10%", left:"-5%", width:400, height:400, borderRadius:"50%", background:`radial-gradient(circle,${T.maroon}06 0%,transparent 70%)` }} />
          <div style={{ position:"absolute", inset:0, backgroundImage:`linear-gradient(${T.border}40 1px,transparent 1px),linear-gradient(90deg,${T.border}40 1px,transparent 1px)`, backgroundSize:"48px 48px", opacity:0.4 }} />
        </div>
        <div className="fade-up" style={{ textAlign:"center", maxWidth:600, padding:"0 24px", position:"relative" }}>
          <div style={{ display:"flex", justifyContent:"center", marginBottom:22 }}>
            <div style={{ width:68, height:68, borderRadius:17, background:`linear-gradient(135deg,${T.gold},#8B5C1A)`, display:"flex", alignItems:"center", justifyContent:"center", fontFamily:"Playfair Display", fontWeight:700, color:"#FFF8EE", fontSize:32, boxShadow:`0 8px 32px ${T.gold}40` }}>G</div>
          </div>
          <div style={{ fontFamily:"Cormorant Garamond", fontSize:12, color:T.textMuted, letterSpacing:"0.18em", textTransform:"uppercase", marginBottom:7 }}>Welcome to</div>
          <h1 style={{ fontFamily:"Playfair Display", fontSize:40, fontWeight:700, color:T.textPrimary, letterSpacing:"-0.02em", lineHeight:1.1, marginBottom:8 }}>Hotel Grand Vista</h1>
          <div style={{ fontFamily:"Cormorant Garamond", fontStyle:"italic", fontSize:18, color:T.gold, marginBottom:20 }}>Powered by PersonaPlex Voice AI</div>
          <Divider />
          <div style={{ marginTop:20, display:"flex", gap:14, justifyContent:"center" }}>
            {[
              { role:"Guest", icon:"🎙️", bg:T.maroon, text:"#FFE8D6", sub:"Voice AI · Transcript · Bills", action:"Enter Guest Portal" },
            ].map(opt => (
              <div key={opt.role} onClick={() => setRole(opt.role)} style={{ flex:1, maxWidth:220, padding:24, borderRadius:16, cursor:"pointer", background:opt.bg, border:"1px solid rgba(255,255,255,0.08)", boxShadow:`0 8px 32px ${opt.bg}30`, transition:"all 0.22s ease", textAlign:"center" }}
                onMouseEnter={e => { e.currentTarget.style.transform="translateY(-4px)"; }}
                onMouseLeave={e => { e.currentTarget.style.transform="translateY(0)"; }}>
                <div style={{ fontSize:32, marginBottom:12 }}>{opt.icon}</div>
                <div style={{ fontFamily:"Playfair Display", fontSize:18, fontWeight:700, color:opt.text, marginBottom:7 }}>{opt.role}</div>
                <div style={{ fontSize:11.5, color:`${opt.text}70`, lineHeight:1.6, marginBottom:14, fontFamily:"Jost", fontWeight:300 }}>{opt.sub}</div>
                <div style={{ padding:"9px 0", background:`${T.gold}20`, borderRadius:9, border:`1px solid ${T.gold}30`, color:T.goldLight, fontSize:11.5, fontWeight:500, letterSpacing:"0.04em" }}>{opt.action} →</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop:24, fontSize:11, color:T.textLight, letterSpacing:"0.06em" }}>HOTEL GRAND VISTA · VOICE AI CONCIERGE · NEW DELHI</div>
        </div>
      </div>
    </>
  );

  return (
    <>
      <GlobalStyle />
      <div style={{ display:"flex", height:"100vh", background:T.bg, overflow:"hidden", flexDirection:"column" }}>
        <div style={{ height:54, background:T.surface, borderBottom:`1px solid ${T.border}`, display:"flex", alignItems:"center", justifyContent:"space-between", padding:"0 24px", flexShrink:0 }}>
          <div style={{ fontFamily:"Playfair Display", fontWeight:600, fontSize:16, color:T.textPrimary }}>Voice Concierge</div>
          <div style={{ display:"flex", alignItems:"center", gap:9 }}>
            <div style={{ padding:"4px 12px", background:T.goldSoft, borderRadius:20, border:`1px solid ${T.gold}30` }}>
              <span style={{ color:T.gold, fontSize:11, fontWeight:500 }}>🎙️ Vista Voice AI Active</span>
            </div>
            <button className="btn-outline" onClick={() => setRole(null)} style={{ padding:"5px 12px", borderRadius:20, fontSize:12 }}>← Switch</button>
          </div>
        </div>
        <div style={{ flex:1, display:"flex", overflow:"hidden" }}>
          <VoiceAgentPage
            liveSession={liveSession}
            setLiveSession={setLiveSession}
            localBills={localBills}
            setLocalBills={setLocalBills}
          />
        </div>
      </div>
    </>
  );
}
