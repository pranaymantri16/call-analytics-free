"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API } from "@/lib/api";
import { useAuditAuth } from "@/lib/audit-auth";
import AuditAccess from "@/components/AuditAccess";

type CallGroup = { call_id: number; status: string; summary: string | null; crm_status: string | null;
  device_id: string | null; recording_id: string | null; event_count: number; failure_count: number;
  last_event_at: string; last_event: string; last_outcome: string };
const fieldClass = "mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm";

export default function RecordingAuditPage() {
  const auth = useAuditAuth();
  const router = useRouter();
  const [items, setItems] = useState<CallGroup[]>([]);
  const [filters, setFilters] = useState({ call_id: "", device_id: "", recording_id: "", stage: "", outcome: "" });
  const [next, setNext] = useState<number | null>(null);
  const [unassigned, setUnassigned] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    const legacyCall = new URLSearchParams(window.location.search).get("call_id");
    if (legacyCall && /^\d+$/.test(legacyCall)) router.replace(`/audit/calls/${legacyCall}`);
  }, [router]);
  const load = useCallback(async (before?: number) => {
    const current = ++generation.current;
    if (!auth.credential) { setItems([]); setNext(null); setUnassigned(0); setError(""); setBusy(false); return; }
    setBusy(true);
    try {
      const query = new URLSearchParams({ limit: "30" });
      Object.entries(filters).forEach(([name, value]) => { if (value.trim()) query.set(name, value.trim()); });
      if (before) query.set("before_call_id", String(before));
      const response = await fetch(`${API}/api/v1/recording-audit/groups?${query}`, {
        headers: { Authorization: `Bearer ${auth.credential}` }, cache: "no-store",
      });
      if (!response.ok) throw new Error(response.status === 401 ? "Saved token was rejected. Use Change token to update it."
        : response.status === 422 ? "Check the filters. Call ID must be a positive number." : "Audit API unavailable. Check the backend connection.");
      const data = await response.json();
      if (current !== generation.current) return;
      setItems(data.items); setNext(data.next_before_call_id); setUnassigned(data.unassigned_count); setError("");
    } catch (failure) {
      if (current !== generation.current) return;
      setItems([]); setNext(null); setUnassigned(0);
      setError(failure instanceof Error ? failure.message : "Unable to load call groups.");
    } finally { if (current === generation.current) setBusy(false); }
  }, [auth.credential, filters]);
  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [load]);
  useEffect(() => {
    if (!refresh || !auth.credential) return;
    const timer = setInterval(() => void load(), 10000);
    return () => clearInterval(timer);
  }, [refresh, auth.credential, load]);
  return <main className="mx-auto max-w-7xl px-5 py-8 md:px-8">
    <Link href="/" className="text-sm text-cyan-300">← Dashboard</Link>
    <header className="my-6"><h1 className="text-3xl font-bold">Recording audit trail</h1>
      <p className="mt-2 text-slate-400">One card per call. Open a call to inspect its APK data, analysis, CRM requests and responses.</p></header>
    <AuditAccess connected={!!auth.credential} ready={auth.ready} connect={auth.connect} forget={auth.forget} />
    {auth.credential && <>
      <section className="mb-5 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(["call_id", "device_id", "recording_id"] as const).map(name => <label key={name} className="text-sm text-slate-300">
            {{ call_id: "Call ID", device_id: "Device ID", recording_id: "APK recording ID" }[name]}
            <input type={name === "call_id" ? "number" : "text"} min={1} className={fieldClass} value={filters[name]}
              onChange={event => setFilters({ ...filters, [name]: event.target.value })} /></label>)}
          <label className="text-sm text-slate-300">Stage<select className={fieldClass} value={filters.stage} onChange={event => setFilters({ ...filters, stage: event.target.value })}>
            <option value="">All stages</option>{["mobile", "dispatch", "analysis", "crm"].map(value => <option key={value}>{value}</option>)}
          </select></label>
          <label className="text-sm text-slate-300">Outcome<select className={fieldClass} value={filters.outcome} onChange={event => setFilters({ ...filters, outcome: event.target.value })}>
            <option value="">All outcomes</option>{["received", "processing", "success", "retry", "failed", "ignored"].map(value => <option key={value}>{value}</option>)}
          </select></label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
          <button disabled={busy} onClick={() => void load()} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-40">Refresh latest</button>
          <label className="flex items-center gap-2 text-slate-400"><input type="checkbox" checked={refresh} onChange={event => setRefresh(event.target.checked)} />Refresh every 10 seconds</label>
          <Link href="/audit/unassigned" className="text-cyan-300 hover:underline">Uploads without a call ID ({unassigned})</Link>
        </div>
      </section>
      <section className="space-y-3" aria-label="Call audit groups">
        {items.map(call => <Link key={call.call_id} href={`/audit/calls/${call.call_id}`} className="block rounded-xl border border-slate-800 bg-slate-900 p-5 transition hover:border-cyan-700 hover:bg-slate-800/60">
          <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap items-center gap-3">
            <h2 className="font-semibold text-cyan-300">Call #{call.call_id}</h2>
            <span className={`rounded-full px-2 py-1 text-xs ${call.status === "completed" ? "bg-emerald-950 text-emerald-300" : call.status === "failed" ? "bg-rose-950 text-rose-300" : "bg-amber-950 text-amber-300"}`}>{call.status}</span>
            <span className="text-xs text-slate-400">CRM: {call.crm_status || "not queued"}</span>
          </div><span className="text-xs text-slate-500">{new Date(call.last_event_at).toLocaleString()}</span></div>
          <p className="mt-3 line-clamp-2 whitespace-pre-line text-sm leading-6 text-slate-300">{call.summary || "Analysis summary will appear when processing completes."}</p>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500">
            <span>{call.event_count} matching events</span><span className={call.failure_count ? "text-rose-300" : ""}>{call.failure_count} failed events</span>
            <span>Latest: {call.last_event}</span>{call.device_id && <span>Device: {call.device_id}</span>}
            <span className="ml-auto text-cyan-300">Open full audit trail →</span>
          </div>
        </Link>)}
        {!items.length && <p className="rounded-xl border border-slate-800 p-8 text-center text-slate-400">{busy ? "Loading calls…" : "No matching call history yet."}</p>}
      </section>
      <div className="mt-5 flex items-center justify-between gap-3 text-sm"><span className="text-slate-500">Newest call IDs first · {items.length} calls</span>
        <button disabled={!next || busy || refresh} onClick={() => next && void load(next)} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-40">Older calls</button></div>
    </>}
    {error && <p role="alert" className="mt-4 rounded-xl border border-rose-900 bg-rose-950/40 p-4 text-rose-200">{error}</p>}
  </main>;
}
