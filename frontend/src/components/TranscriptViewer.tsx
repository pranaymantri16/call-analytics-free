"use client";
type Segment = {start:number;end:number;text:string;speaker:string;role:string};
export default function TranscriptViewer({segments, transcript}:{segments?:Segment[];transcript?:string|null}) {
  if (segments?.length) return <div className="space-y-3">{segments.map((s,i)=>
    <div key={`${s.start}-${i}`} className={`rounded-xl border p-4 ${s.role === "Caller" ? "border-sky-900 bg-sky-950/40" : "border-violet-900 bg-violet-950/30"}`}>
      <div className="mb-1 flex items-center justify-between text-xs text-slate-400">
        <span className={s.role === "Caller" ? "text-sky-300" : "text-violet-300"}>{s.role} · {s.speaker}</span>
        <span>{Math.floor(s.start/60).toString().padStart(2,"0")}:{Math.floor(s.start%60).toString().padStart(2,"0")}</span>
      </div><p className="leading-7 text-slate-100">{s.text}</p>
    </div>)}</div>;
  return <pre className="whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950 p-4 leading-7">{transcript || "Transcript is not available yet."}</pre>;
}
