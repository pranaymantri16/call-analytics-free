"use client";
import { useState } from "react";

export default function AuditAccess({ connected, ready, connect, forget }: {
  connected: boolean; ready: boolean; connect: (token: string) => Promise<void>; forget: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!ready) return <p className="mb-5 text-sm text-slate-400">Loading saved connection…</p>;
  if (connected && !editing) return <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4">
    <p className="text-sm text-emerald-300">Saved audit connection · remembered on this browser</p>
    <div className="flex gap-3"><button className="text-sm text-cyan-300" onClick={() => { setEditing(true); setError(""); }}>Change token</button>
      <button className="text-sm text-slate-400" onClick={() => { forget(); setDraft(""); }}>Forget saved token</button></div>
  </div>;
  return <form className="mb-5 rounded-xl border border-slate-800 bg-slate-900 p-4" onSubmit={async event => {
    event.preventDefault(); setBusy(true); setError("");
    try { await connect(draft); setDraft(""); setEditing(false); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Unable to save connection."); }
    finally { setBusy(false); }
  }}>
    <div className="flex flex-wrap items-end gap-3"><label className="min-w-64 flex-1 text-sm text-slate-300">Admin token
      <input type="password" autoComplete="off" required value={draft} onChange={event => setDraft(event.target.value)}
        placeholder="ERPNEXT_ADMIN_TOKEN" className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2" /></label>
      <button disabled={busy} className="rounded-lg border border-slate-700 px-4 py-2 text-sm disabled:opacity-40">{busy ? "Verifying…" : "Save connection"}</button>
      {connected && <button type="button" className="text-sm text-slate-400" onClick={() => { setEditing(false); setDraft(""); }}>Cancel</button>}
    </div>
    <p className="mt-3 text-xs text-slate-500">Saved on this browser until you change or forget it. Customer audit data remains protected by the backend token.</p>
    {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
  </form>;
}
