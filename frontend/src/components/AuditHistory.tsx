"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { API } from "@/lib/api";
import { useAuditAuth } from "@/lib/audit-auth";
import AuditAccess from "@/components/AuditAccess";

type AuditEvent = {
  id: number; call_id: number | null; device_id: string | null; recording_id: string | null;
  correlation_id: string; stage: string; event: string; outcome: string;
  attempt: number | null; created_at: string; details?: Record<string, unknown>;
};
type Filters = { call_id: string; device_id: string; recording_id: string; stage: string; outcome: string };
const emptyFilters: Filters = { call_id: "", device_id: "", recording_id: "", stage: "", outcome: "" };
const inputStyle = "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm";
const buttonStyle = "rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800 disabled:opacity-40";

export default function AuditHistory({ callId, unassigned = false }: { callId?: string; unassigned?: boolean }) {
  const auth = useAuditAuth();
  const { credential } = auth;
  const [filters, setFilters] = useState<Filters>({ ...emptyFilters, call_id: callId || "" });
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const listGeneration = useRef(0);

  const request = useCallback(async (path: string) => {
    const response = await fetch(`${API}/api/v1/recording-audit${path}`, {
      headers: { Authorization: `Bearer ${credential}` }, cache: "no-store",
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error("Invalid admin token. Check the value in your private .env.");
      if (response.status === 503) throw new Error("Admin access is not configured. Set ERPNEXT_ADMIN_TOKEN on the backend.");
      if (response.status === 404) throw new Error("This call or event was not found.");
      if (response.status === 422) throw new Error("Check the filters. Call ID must be a positive number.");
      throw new Error("Audit API unavailable. Check the backend and database.");
    }
    return response.json();
  }, [credential]);

  const load = useCallback(async (before?: number) => {
    if (!credential) return;
    const current = generation.current;
    const listVersion = ++listGeneration.current;
    setBusy(true);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (unassigned) params.set("unassigned", "true");
      Object.entries(filters).forEach(([key, value]) => { if (value.trim()) params.set(key, value.trim()); });
      if (before) params.set("before_id", String(before));
      const data = await request(`?${params}`);
      if (current !== generation.current || listVersion !== listGeneration.current) return;
      setItems(data.items); setNext(data.next_before_id); setError("");
    } catch (failure) {
      if (current !== generation.current || listVersion !== listGeneration.current) return;
      setItems([]); setNext(null); setSelected(null); setSnapshot(null);
      setError(failure instanceof Error ? failure.message : "Unable to load audit history.");
    } finally { if (current === generation.current && listVersion === listGeneration.current) setBusy(false); }
  }, [credential, filters, request, unassigned]);

  useEffect(() => {
    generation.current += 1;
    detailGeneration.current += 1;
    setSelected(null); setSnapshot(null);
    if (credential) void load();
    else { setItems([]); setNext(null); setBusy(false); }
    return () => { generation.current += 1; };
  }, [credential, load]);
  useEffect(() => {
    if (!autoRefresh || !credential) return;
    const timer = setInterval(() => { void load(); }, 10000);
    return () => clearInterval(timer);
  }, [autoRefresh, credential, load]);

  async function inspect(row: AuditEvent) {
    const current = generation.current;
    const selectionVersion = ++detailGeneration.current;
    setSelected(null); setSnapshot(null); setError("");
    try {
      const detail = await request(`/events/${row.id}`);
      if (current === generation.current && selectionVersion === detailGeneration.current) setSelected(detail);
    } catch (failure) {
      if (current === generation.current && selectionVersion === detailGeneration.current) setError(failure instanceof Error ? failure.message : "Unable to load event.");
    }
  }

  async function currentSnapshot() {
    if (!filters.call_id) { setError("Enter a Call ID to inspect its current saved data."); return; }
    const current = generation.current;
    const selectionVersion = ++detailGeneration.current;
    setSelected(null); setSnapshot(null);
    try {
      const data = await request(`/calls/${encodeURIComponent(filters.call_id)}`);
      if (current === generation.current && selectionVersion === detailGeneration.current) { setSnapshot(data); setError(""); }
    } catch (failure) {
      if (current === generation.current && selectionVersion === detailGeneration.current) setError(failure instanceof Error ? failure.message : "Unable to load call.");
    }
  }

  function download() {
    if (!selected) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(selected, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `recording-audit-${selected.id}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <main className="mx-auto max-w-7xl px-5 py-8 md:px-8">
    <Link href="/audit" className="text-sm text-cyan-300">← Call audit groups</Link>
    <header className="my-6"><h1 className="text-3xl font-bold">{callId ? `Call #${callId} audit trail` : "Uploads without a call ID"}</h1>
      <p className="mt-2 text-slate-400">Inspect what the APK sent, what analysis produced, and what was delivered to CRM.</p>
    </header>

    <AuditAccess connected={!!credential} ready={auth.ready} connect={auth.connect} forget={auth.forget} />

    {credential && <>
      <section className="mb-5 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {(["call_id", "device_id", "recording_id"] as const).map(key => <label key={key} className="text-sm text-slate-300">
            {{ call_id: "Call ID", device_id: "Device ID", recording_id: "APK recording ID" }[key]}
            <input className={`${inputStyle} mt-2`} type={key === "call_id" ? "number" : "text"} min={key === "call_id" ? 1 : undefined}
              disabled={key === "call_id" && (!!callId || unassigned)} value={filters[key]} onChange={event => { setSelected(null); setSnapshot(null); setFilters({ ...filters, [key]: event.target.value }); }} />
          </label>)}
          <label className="text-sm text-slate-300">Stage<select className={`${inputStyle} mt-2`} value={filters.stage}
            onChange={event => setFilters({ ...filters, stage: event.target.value })}>
            <option value="">All stages</option>{["mobile", "dispatch", "analysis", "crm"].map(stage => <option key={stage}>{stage}</option>)}
          </select></label>
          <label className="text-sm text-slate-300">Outcome<select className={`${inputStyle} mt-2`} value={filters.outcome}
            onChange={event => setFilters({ ...filters, outcome: event.target.value })}>
            <option value="">All outcomes</option>{["received", "processing", "success", "retry", "failed", "ignored"].map(outcome => <option key={outcome}>{outcome}</option>)}
          </select></label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button className={buttonStyle} onClick={() => void load()} disabled={busy}>Refresh latest</button>
          <button className={buttonStyle} onClick={() => void currentSnapshot()}>Current call snapshot</button>
          <button className={buttonStyle} onClick={() => { setFilters({ ...emptyFilters, call_id: callId || "" }); setSelected(null); setSnapshot(null); }}>Clear filters</button>
          <label className="flex items-center gap-2 text-sm text-slate-400"><input type="checkbox" checked={autoRefresh}
            onChange={event => setAutoRefresh(event.target.checked)} /> Refresh latest every 10 seconds</label>
        </div>
      </section>

      <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="bg-slate-800 text-slate-300"><tr>{["Time", "Call", "APK recording / device", "Event", "Outcome", "Attempt", ""].map(title => <th key={title} className="px-4 py-3">{title}</th>)}</tr></thead>
          <tbody>{items.map(row => <tr key={row.id} className={`border-t border-slate-800 ${selected?.id === row.id ? "bg-slate-800" : ""}`}>
            <td className="whitespace-nowrap px-4 py-3 text-slate-400">{new Date(row.created_at).toLocaleString()}</td>
            <td className="px-4 py-3">{row.call_id ? <Link href={`/calls/${row.call_id}`} className="text-cyan-300">#{row.call_id}</Link> : "—"}</td>
            <td className="max-w-60 break-all px-4 py-3 text-slate-400">{row.recording_id || "—"}<br />{row.device_id || "—"}</td>
            <td className="px-4 py-3">{row.event}</td>
            <td className={`px-4 py-3 ${row.outcome === "failed" ? "text-rose-300" : row.outcome === "success" ? "text-emerald-300" : "text-amber-200"}`}>{row.outcome}</td>
            <td className="px-4 py-3">{row.attempt ?? "—"}</td>
            <td className="px-4 py-3"><button onClick={() => void inspect(row)} className="text-cyan-300 underline">Inspect</button></td>
          </tr>)}</tbody>
        </table></div>
        {!items.length && <p className="p-6 text-slate-400">{busy ? "Loading history…" : "No matching events. New uploads and CRM attempts will appear here."}</p>}
        <div className="flex items-center justify-between gap-3 border-t border-slate-800 p-4">
          <span className="text-xs text-slate-500">Newest first · {items.length} events on this page · full details load when inspected</span>
          <button className={buttonStyle} disabled={!next || busy || autoRefresh} onClick={() => next && void load(next)}>Older events</button>
        </div>
      </section>
    </>}

    {error && <p role="alert" className="my-4 rounded-lg border border-rose-900 bg-rose-950/40 p-4 text-rose-200">{error}</p>}
    {(selected || snapshot) && <section className="mt-5 rounded-xl border border-slate-700 bg-slate-900 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">{selected ? selected.event : "Current saved call data"}</h2>
        {selected && <button className={buttonStyle} onClick={download}>Download event JSON</button>}</div>
      {selected && <p className="mb-4 break-all text-xs text-slate-400">Event #{selected.id} · Correlation: {selected.correlation_id}</p>}
      <pre className="max-h-[40rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-300">{JSON.stringify(selected?.details ?? snapshot, null, 2)}</pre>
    </section>}
    <p className="mt-5 text-xs text-slate-500">History starts after this update is installed. Current call snapshots also work for earlier recordings. Audio binaries and credentials are excluded.</p>
  </main>;
}
