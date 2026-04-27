// src/api/index.js
// All API calls — replaces every MOCK_* constant in hotel-voice-app-enhanced.jsx

import client from "./client";

// ── Token ─────────────────────────────────────────────────────────────────────
export const api = {

  // GET /api/token?identity=x&room=y
  getToken: (identity, room = "personaplex-test") =>
    client.get("/api/token", { params: { identity, room } }),

  // ── Transcripts ─────────────────────────────────────────────────────────────
  // GET /api/transcripts
  getTranscripts: () => client.get("/api/transcripts"),

  // GET /api/transcripts/:sessionId
  getTranscript: (sessionId) => client.get(`/api/transcripts/${sessionId}`),

  // ── CRM Records ─────────────────────────────────────────────────────────────
  // GET /api/crm
  getCrmRecords: () => client.get("/api/crm"),

  // GET /api/crm/:sessionId
  getCrmRecord: (sessionId) => client.get(`/api/crm/${sessionId}`),

  // ── Bills ────────────────────────────────────────────────────────────────────
  // GET /api/bills
  getBills: () => client.get("/api/bills"),

  // GET /api/bills/:orderId
  getBill: (orderId) => client.get(`/api/bills/${orderId}`),

  // ── Health ────────────────────────────────────────────────────────────────────
  health: () => client.get("/health"),
};

export default api;
