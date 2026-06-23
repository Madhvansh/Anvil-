// Minimal typed API client. Same-origin in prod; Vite proxies to :8000 in dev.

export type Mode = "simple" | "trader" | "expert";

export interface Me {
  id: number;
  email: string;
  role: string;
  display_name?: string | null;
  profile: { explain_mode: Mode; onboarded: boolean; benchmark: string; prefs: any; feature_flags: any };
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const api = {
  status: () => req<{ needs_setup: boolean }>("GET", "/auth/status"),
  me: () => req<Me>("GET", "/auth/me"),
  register: (email: string, password: string) => req<Me>("POST", "/auth/register", { email, password }),
  login: (email: string, password: string) => req<any>("POST", "/auth/login", { email, password }),
  logout: () => req<any>("POST", "/auth/logout"),
  patchProfile: (p: Partial<{ explain_mode: Mode; benchmark: string; onboarded: boolean; prefs: any }>) =>
    req<any>("PATCH", "/api/profile", p),

  analyze: (u: string) => req<any>("GET", `/api/analyze/${u}`),
  brief: (u: string) => req<any>("GET", `/api/daily-brief/${u}`),
  whatChanged: (u: string) => req<any>("GET", `/api/what-changed/${u}`),
  calibration: () => req<any>("GET", "/api/calibration"),
  eventRisk: (u: string) => req<any>("GET", `/api/event-risk/${u}`),
  ivCrush: (u: string) => req<any>("GET", `/api/iv-crush/${u}`),
  unusual: (u: string) => req<any>("GET", `/api/unusual/${u}`),
  portfolio: () => req<any>("GET", "/api/portfolio-risk"),
  scenario: (u: string) => req<any>("GET", `/api/scenario/${u}`),
  montecarlo: (u: string, n = 8000) => req<any>("POST", `/api/montecarlo/${u}`, { n_paths: n, seed: 7 }),
  copilotNarrate: (u: string, mode: Mode) => req<any>("GET", `/api/copilot/narrate/${u}?mode=${mode}`),
  copilotAsk: (u: string, question: string, mode: Mode) =>
    req<any>("POST", `/api/copilot/ask/${u}`, { question, mode }),

  alerts: () => req<any[]>("GET", "/api/alerts"),
  createAlert: (r: any) => req<any>("POST", "/api/alerts", r),
  deleteAlert: (id: number) => req<any>("DELETE", `/api/alerts/${id}`),
  alertEvents: () => req<any[]>("GET", "/api/alerts/events"),
  evaluateAlerts: (u: string) => req<any>("POST", `/api/alerts/evaluate/${u}`),

  journal: () => req<any[]>("GET", "/api/journal"),
  addJournal: (e: any) => req<any>("POST", "/api/journal", e),

  listWatchlists: () => req<any[]>("GET", "/api/watchlists"),
  createWatchlist: (name: string, symbols: string[]) =>
    req<any>("POST", "/api/watchlists", { name, symbols, is_default: false }),
  deleteWatchlist: (id: number) => req<any>("DELETE", `/api/watchlists/${id}`),

  // Paper-trading simulator (gated, personal money-making mock loop).
  paperAccount: () => req<any>("GET", "/api/paper/account"),
  paperRecommendations: (u: string) => req<any>("GET", `/api/paper/recommendations/${u}`),
  paperRun: (body: any) => req<any>("POST", "/api/paper/runs", body),
  paperStop: (id: number) => req<any>("POST", `/api/paper/runs/${id}/stop`),
  paperRuns: () => req<any[]>("GET", "/api/paper/runs"),
  paperEquityCurve: (id: number) => req<any[]>("GET", `/api/paper/runs/${id}/equity-curve`),
  paperPositions: (status?: string) =>
    req<any[]>("GET", `/api/paper/positions${status ? `?status=${status}` : ""}`),
  paperTrades: (positionId?: number) =>
    req<any[]>("GET", `/api/paper/trades${positionId ? `?position_id=${positionId}` : ""}`),

  // Buyer Decision Brief (Wave 2): environment-gate → strike-action P(touch). Analytics, not advice.
  decisionBrief: (u: string, horizon = 5) => req<any>("GET", `/api/decision-brief/${u}?horizon_days=${horizon}`),

  // Short-term tips engine (gated; flat-free). Headline = edge-proven (measured), watchlist = developing.
  tips: (u: string) => req<any>("GET", `/api/tips/${u}`),
  tipsEquities: () => req<any>("GET", "/api/tips/equities"),
  tipsTrackRecord: () => req<any>("GET", "/api/tips/track-record"),
  trustDial: () => req<any>("GET", "/api/tips/trust-dial"),

  // Multi-timeframe + options-flow momentum surface (Wave 2). Public analytics: consensus read,
  // flow velocity, fired momentum factors, and the honestly-gated prediction.
  momentum: (u: string) => req<any>("GET", `/api/momentum/${u}`),
  // Wave 0 live cockpit heartbeat: build stamp + supervisor status + gate/personal chip + freshness.
  cockpitStatus: () => req<any>("GET", "/api/cockpit/status"),
  tipsFeed: (u?: string, tier?: string, limit = 50) => {
    const q = new URLSearchParams();
    if (u) q.set("underlying", u);
    if (tier) q.set("tier", tier);
    q.set("limit", String(limit));
    return req<any>("GET", `/api/tips/feed?${q.toString()}`);
  },

  sourceStatus: () =>
    req<{
      mode: string;
      source: string;
      requested_source: string | null;
      fallback_reason: string | null;
      connected_brokers: string[];
      as_of: string | null;
    }>("GET", "/api/source/status"),

  brokerConnections: () => req<any[]>("GET", "/api/broker/connections"),
  brokerAuthUrl: () => req<any>("GET", "/api/broker/upstox/auth-url"),
  brokerConnect: (broker: string, access_token: string) =>
    req<any>("POST", `/api/broker/${broker}/connect`, { access_token }),
  upstoxExchange: (code: string) => req<any>("POST", "/api/broker/upstox/exchange", { code }),
  changePassword: (current_password: string, new_password: string) =>
    req<any>("POST", "/auth/change-password", { current_password, new_password }),
  health: () => req<any>("GET", "/health"),
};

export const INDEXES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"];

export function fmt(n: number | null | undefined, d = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
}
export function pct(n: number | null | undefined, d = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return (n * 100).toFixed(d) + "%";
}
