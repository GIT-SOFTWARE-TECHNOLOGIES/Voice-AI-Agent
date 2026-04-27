// src/hooks/useApi.js
// Generic hooks that wrap every API call with loading + error states

import { useState, useEffect, useCallback } from "react";
import api from "../api";

// ── Generic fetch hook ────────────────────────────────────────────────────────
function useFetch(fetcher, deps = []) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcher();
      setData(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  return { data, loading, error, refetch: load };
}

// ── Transcripts ───────────────────────────────────────────────────────────────
export function useTranscripts() {
  return useFetch(() => api.getTranscripts());
}

export function useTranscript(sessionId) {
  return useFetch(() => api.getTranscript(sessionId), [sessionId]);
}

// ── CRM Records ───────────────────────────────────────────────────────────────
export function useCrmRecords() {
  return useFetch(() => api.getCrmRecords());
}

export function useCrmRecord(sessionId) {
  return useFetch(() => api.getCrmRecord(sessionId), [sessionId]);
}

// ── Bills ─────────────────────────────────────────────────────────────────────
export function useBills() {
  return useFetch(() => api.getBills());
}

export function useBill(orderId) {
  return useFetch(() => api.getBill(orderId), [orderId]);
}

// ── LiveKit Token ─────────────────────────────────────────────────────────────
export function useToken(identity, room) {
  return useFetch(() => api.getToken(identity, room), [identity, room]);
}
