"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Activity, AudioLines, CheckCircle2, Clock3, Search, Upload, Users, AlertCircle, RefreshCw } from "lucide-react";
import { API, CallRecord } from "@/lib/api";

type Analytics = {total_calls:number;completed_calls:number;processing_calls:number;failed_calls:number;average_agent_score:number|null;interest_breakdown:Record<string,number>;caller_performance:{caller_name:string;calls:number;average_score:number|null}[]};
const panel = "rounded-2xl border border-slate-800 bg-slate-900/70 p-5";
export default function Dashboard() {
  const [calls,setCalls] = useState<CallRecord[]>([]);
  const [analytics,setAnalytics] = useState<Analytics|null>(null);
  const [search,setSearch] = useState("");
  const [status,setStatus] = useState("");
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  async function refresh() {
    setBusy(true);
    try {
      const [a,c] = await Promise.all([
        fetch(`${API}/api/v1/analytics/summary`,{cache:"no-store"}), 
        fetch(`${API}/api/v1/calls?limit=100&search=${encodeURIComponent(search)}&status=${encodeURIComponent(status)}`,{cache:"no-store"})
      ]);
      if(!a.ok || !c.ok) throw new Error("API is not ready. Check that the backend and database are running.");
      setAnalytics(await a.json()); setCalls(await c.json()); setMessage("");
    } catch(e) { setMessage(e instanceof Error ? e.message : "Could not connect to API."); }
    finally { setBusy(false); }
  }
  useEffect(()=>{refresh(); const timer=setInterval(refresh,10000); return ()=>clearInterval(timer);},[search,status]);
  async function upload(e:React.ChangeEvent<HTMLInputElement>) {
    const file=e.target.files?.[0]; if(!file) return;
    const data=new FormData(); data.append("file",file); data.append("caller_name","Caller"); data.append("customer_name","Customer");
    setMessage("Uploading audio…");
    try { const r=await fetch(`${API}/api/v1/calls/upload`,{method:"POST",body:data}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||"Upload failed"); setMessage(`Call #${j.id} queued for processing.`); refresh(); }
    catch(err){setMessage(err instanceof Error?err.message:"Upload failed.");}
    e.target.value="";
  }
  const interests=analytics?.interest_breakdown||{};
  const totalInterest=useMemo(()=>Object.values(interests).reduce((a,b)=>a+b,0),[interests]);
  return <main className="mx-auto max-w-7xl px-5 py-8 md:px-8">
    <header className="mb-8 flex flex-col justify-between gap-5 md:flex-row md:items-center">
      <div><div className="mb-2 flex items-center gap-2 text-sm text-cyan-300"><AudioLines size={17}/> LOCAL CALL INTELLIGENCE</div><h1 className="text-3xl font-bold tracking-tight md:text-4xl">Call analytics</h1><p className="mt-2 text-slate-400">Your recordings, summaries and insights — processed locally.</p></div>
      <div className="flex flex-wrap gap-3"><label className="flex cursor-pointer items-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 hover:bg-cyan-300"><Upload size={18}/> Upload recording<input type="file" accept="audio/*,.wav,.mp3,.m4a,.mp4,.aac,.ogg,.opus,.flac,.wma,.aiff,.aif,.amr,.webm,.mka,.mkv,.mov,.3gp,.ac3,.ape,.caf,.mp2,.mpga,.mpeg,.wv" className="hidden" onChange={upload}/></label><button onClick={refresh} className="rounded-xl border border-slate-700 px-4 py-3 hover:bg-slate-800"><RefreshCw size={18}/></button></div>
    </header>
    {message&&<div className="mb-5 rounded-xl border border-slate-700 bg-slate-900 p-3 text-sm text-slate-300">{message}</div>}
    <section className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {[
        {label:"Total calls",value:analytics?.total_calls??"—",icon:Activity},
        {label:"Completed",value:analytics?.completed_calls??"—",icon:CheckCircle2},
        {label:"In progress",value:analytics?.processing_calls??"—",icon:Clock3},
        {label:"Average agent score",value:analytics?.average_agent_score!=null?`${analytics.average_agent_score}/10`:"—",icon:Users}
      ].map(x=><div key={x.label} className={panel}><div className="flex items-center justify-between text-sm text-slate-400">{x.label}<x.icon size={18}/></div><div className="mt-4 text-3xl font-semibold">{x.value}</div></div>)}
    </section>
    <section className="mb-6 grid gap-4 lg:grid-cols-3">
      <div className={`${panel} lg:col-span-2`}><h2 className="mb-4 text-lg font-semibold">Caller performance</h2>
        {analytics?.caller_performance?.length?<div className="space-y-4">{analytics.caller_performance.map((p)=><div key={p.caller_name}><div className="mb-2 flex justify-between gap-3 text-sm"><span>{p.caller_name}</span><span className="text-slate-400">{p.calls} calls · {p.average_score??"—"}/10</span></div><div className="h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan-400" style={{width:`${Math.min(100,Math.max(0,(p.average_score||0)*10))}%`}}/></div></div>)}</div>:<p className="text-sm text-slate-500">Scores appear after calls finish processing.</p>}
      </div>
      <div className={panel}><h2 className="mb-4 text-lg font-semibold">Customer interest</h2>
        {["High","Medium","Low"].map((level,i)=>{const n=interests[level]||0; const pct=totalInterest?Math.round(n/totalInterest*100):0; const color=["bg-emerald-400","bg-amber-300","bg-rose-400"][i];return <div className="mb-4" key={level}><div className="mb-2 flex justify-between text-sm"><span>{level}</span><span>{n} · {pct}%</span></div><div className="h-2 rounded-full bg-slate-800"><div className={`h-2 rounded-full ${color}`} style={{width:`${pct}%`}}/></div></div>})}
      </div>
    </section>
    <section className={panel}>
      <div className="mb-5 flex flex-col justify-between gap-3 md:flex-row md:items-center"><h2 className="text-lg font-semibold">Recent calls</h2><div className="flex flex-col gap-2 sm:flex-row"><div className="flex items-center gap-2 rounded-lg border border-slate-700 px-3"><Search size={16} className="text-slate-500"/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search calls…" className="w-full bg-transparent py-2 text-sm outline-none sm:w-48"/></div><select value={status} onChange={e=>setStatus(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"><option value="">All statuses</option><option value="queued">Queued</option><option value="processing">Processing</option><option value="completed">Completed</option><option value="failed">Failed</option></select></div></div>
      {busy&&!calls.length?<p className="py-8 text-center text-slate-500">Loading calls…</p>:calls.length?<div className="space-y-3">{calls.map(c=><Link key={c.id} href={`/calls/${c.id}`} className="block rounded-xl border border-slate-800 p-4 transition hover:border-slate-600 hover:bg-slate-800/50"><div className="flex flex-col justify-between gap-3 md:flex-row md:items-center"><div className="min-w-0"><div className="flex items-center gap-2 font-medium">Call #{c.id}<span className={`rounded-full px-2 py-0.5 text-xs ${c.status==="completed"?"bg-emerald-950 text-emerald-300":c.status==="failed"?"bg-rose-950 text-rose-300":"bg-amber-950 text-amber-300"}`}>{c.status}</span></div><p className="mt-1 text-sm text-slate-400">{c.caller_name} → {c.customer_name}</p><p className="mt-2 line-clamp-2 text-sm text-slate-300">{c.call_summary||c.error_message||(c.status==="failed"?"Processing failed":"Summary will appear when processing completes.")}</p></div><div className="flex shrink-0 gap-4 text-sm text-slate-400"><span>{c.customer_interest_level||"—"} interest</span><span>{c.agent_performance_score??"—"}/10</span></div></div></Link>)}</div>:<div className="py-12 text-center text-slate-500"><AlertCircle className="mx-auto mb-3" size={24}/><p>No calls found. Upload an audio recording to get started.</p></div>}
      <p className="mt-4 text-xs text-slate-500">Auto-refreshes every 10 seconds. {analytics?.failed_calls?`${analytics.failed_calls} call(s) failed; open a call to inspect its error.`:""}</p>
    </section>
    <footer className="mt-8 text-center text-xs text-slate-600">Local-first processing · No paid AI APIs · Human review recommended for performance scores</footer>
  </main>;
}
