"use client";
import { useEffect,useState } from "react";
import Link from "next/link";
import { ArrowLeft, Clock3, UserRound, ListChecks, Tag } from "lucide-react";
import TranscriptViewer from "@/components/TranscriptViewer";
import { API, CallRecord } from "@/lib/api";
export default function CallDetail({params}:{params:{id:string}}) {
  const [call,setCall]=useState<CallRecord|null>(null); const [error,setError]=useState("");
  useEffect(()=>{let alive=true; async function load(){try{const r=await fetch(`${API}/api/v1/calls/${params.id}`,{cache:"no-store"});if(!r.ok)throw new Error("Call not found or API unavailable.");const d=await r.json();if(alive)setCall(d);}catch(e){if(alive)setError(e instanceof Error?e.message:"Failed to load call.");}}load();const t=setInterval(load,5000);return()=>{alive=false;clearInterval(t)};},[params.id]);
  if(error)return <main className="mx-auto max-w-5xl p-8"><Link href="/" className="text-cyan-300">← Dashboard</Link><p className="mt-6">{error}</p></main>;
  if(!call)return <main className="mx-auto max-w-5xl p-8 text-slate-400">Loading call…</main>;
  return <main className="mx-auto max-w-6xl px-5 py-8 md:px-8">
    <Link href="/" className="mb-6 inline-flex items-center gap-2 text-sm text-cyan-300 hover:text-cyan-200"><ArrowLeft size={16}/> Back to dashboard</Link>
    <header className="mb-7"><div className="mb-2 text-sm text-slate-500">CALL #{call.id} · {call.status.toUpperCase()}</div><h1 className="text-3xl font-bold">Call details</h1><div className="mt-3 flex flex-wrap gap-4 text-sm text-slate-400"><span className="flex items-center gap-2"><UserRound size={15}/>{call.caller_name} → {call.customer_name}</span><span className="flex items-center gap-2"><Clock3 size={15}/>{call.duration_seconds?`${Math.round(call.duration_seconds)} seconds`:"Duration pending"}</span></div></header>
    {call.error_message&&<div className="mb-5 rounded-xl border border-rose-900 bg-rose-950/40 p-4 text-rose-200">Processing error: {call.error_message}</div>}
    <section className="mb-5 grid gap-4 md:grid-cols-3">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 md:col-span-2"><h2 className="mb-3 text-lg font-semibold">AI call summary</h2><p className="leading-7 text-slate-300">{call.call_summary||"Summary will appear after transcription and local LLM processing finish."}</p></div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5"><h2 className="text-sm text-slate-400">Customer interest</h2><div className="my-2 text-2xl font-semibold">{call.customer_interest_level||"Pending"}</div><h2 className="mt-4 text-sm text-slate-400">Agent score</h2><div className="my-2 text-2xl font-semibold">{call.agent_performance_score??"—"}<span className="text-sm text-slate-500"> / 10</span></div></div>
    </section>
    <section className="mb-5 grid gap-4 md:grid-cols-2">
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-3 flex items-center gap-2 font-semibold"><Tag size={17}/> Key topics</h2>{call.key_topics?.length?<div className="flex flex-wrap gap-2">{call.key_topics.map((t,i)=><span key={i} className="rounded-full bg-slate-800 px-3 py-1 text-sm text-slate-300">{t}</span>)}</div>:<p className="text-sm text-slate-500">No topics yet.</p>}</div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5"><h2 className="mb-3 flex items-center gap-2 font-semibold"><ListChecks size={17}/> Action items</h2>{call.action_items?.length?<ul className="list-inside list-disc space-y-2 text-sm text-slate-300">{call.action_items.map((a,i)=><li key={i}>{a}</li>)}</ul>:<p className="text-sm text-slate-500">No action items yet.</p>}</div>
    </section>
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5"><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">Transcript</h2><span className="text-xs text-slate-500">Caller: blue · Customer: violet</span></div><TranscriptViewer segments={call.segments} transcript={call.transcript}/><p className="mt-4 text-xs text-slate-500">Speaker roles are heuristically assigned by first speaker heard. Verify role mapping before relying on it.</p></section>
  </main>;
}
