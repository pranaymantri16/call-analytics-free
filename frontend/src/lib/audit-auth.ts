"use client";
import { useCallback, useEffect, useState } from "react";
import { API } from "@/lib/api";

export const AUDIT_TOKEN_KEY = `call-analytics.audit-token:${API}`;

export function useAuditAuth() {
  const [credential, setCredential] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try { setCredential(localStorage.getItem(AUDIT_TOKEN_KEY) || ""); } catch { /* Form remains usable. */ }
    setReady(true);
    const synchronize = (event: StorageEvent) => {
      if (event.key === AUDIT_TOKEN_KEY || event.key === null) setCredential(event.newValue || "");
    };
    window.addEventListener("storage", synchronize);
    return () => window.removeEventListener("storage", synchronize);
  }, []);
  const connect = useCallback(async (token: string) => {
    const value = token.trim();
    if (!value) throw new Error("Enter your admin token.");
    const response = await fetch(`${API}/api/v1/recording-audit?limit=1`, {
      headers: { Authorization: `Bearer ${value}` }, cache: "no-store",
    });
    if (!response.ok) throw new Error(response.status === 401 ? "Invalid admin token. The saved connection has not changed."
      : response.status === 503 ? "Set ERPNEXT_ADMIN_TOKEN on the backend first." : "Unable to verify the token. Check the API connection.");
    try { localStorage.setItem(AUDIT_TOKEN_KEY, value); }
    catch { throw new Error("Browser storage is unavailable. Allow storage for this site to remember the token."); }
    setCredential(value);
  }, []);
  const forget = useCallback(() => {
    try { localStorage.removeItem(AUDIT_TOKEN_KEY); } catch { /* Always clear current page too. */ }
    setCredential("");
  }, []);
  return { credential, ready, connect, forget };
}
