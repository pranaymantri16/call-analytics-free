"use client";
type Segment = {start:number;end:number;text:string;speaker:string;role:string;role_source?:string;role_confidence?:string;role_evidence?:string};
export default function TranscriptViewer({segments, transcript}:{segments?:Segment[];transcript?:string|null}) {
  if (segments?.length) return <div className="space-y-3">{segments.map((s,i)=>
    <div key={`${s.start}-${i}`} className={`rounded-xl border p-4 ${s.role === "Caller" ? "border-sky-900 bg-sky-950/40" : s.role === "Customer" ? "border-violet-900 bg-violet-950/30" : "border-slate-700 bg-slate-950/40"}`}>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
        <span className={s.role === "Caller" ? "text-sky-300" : s.role === "Customer" ? "text-violet-300" : "text-slate-400"}>{s.role === "Caller" ? "Caller (agent)" : s.role === "Customer" ? "Customer" : "Unassigned"} · {s.speaker}</span>
        <span>{Math.floor(s.start/60).toString().padStart(2,"0")}:{Math.floor(s.start%60).toString().padStart(2,"0")}</span>
      </div><p className="leading-7 text-slate-100">{s.text}</p>
      {s.role_source && <p className="mt-2 text-xs text-slate-500">{s.role_source === "ollama_content_inference" ? "Role inferred from text; voice separation unavailable" : s.role_source === "ollama_speaker_mapping" ? "Role inferred for this acoustic speaker" : "Role could not be determined"}{s.role_confidence ? ` · ${s.role_confidence} confidence` : ""}</p>}
    </div>)}</div>;
  return <pre className="whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950 p-4 leading-7">{transcript || "Transcript is not available yet."}</pre>;
}
