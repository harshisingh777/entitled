export type Text2 = { en: string };
export type Outcome = "eligible" | "not_eligible" | "near_miss" | "undecided";

export type TraceItem = { id: string; status: "pass" | "fail" | "unknown"; label: Text2; reason?: Text2 };
export type SchemeResult = {
  id: string; name: Text2; level: string; outcome: Outcome; trace: TraceItem[];
  gaps: (Text2 & { kind: string; doc?: string; years?: number })[];
  benefit: Text2; annual_inr: number; one_time_inr: number; cover_inr: number; beneficiary: Text2;
  source_url: string; last_verified: string; verification: { status: string; note: string };
  suppressed_by?: string; application_status?: string | null;
};
export type DocumentItem = {
  id: string; name: Text2; where: Text2; time: Text2; have: boolean | null;
  unlocks: { id: string; name: Text2 }[]; unlock_value_inr: number;
};
export type Application = {
  id: string; scheme_id: string; scheme_name: Text2; status: string; status_label: Text2; reference: string | null;
  frames: number; fill_accuracy: number | null; fields: { id: string; label: Text2; value: string }[];
  documents: { id: string; name: Text2 }[]; awaiting_confirmation: boolean; confirmed_by: string | null;
  next_action: Text2 | null; due_at: string | null; overdue: boolean; days_since_submission: number | null;
  events: { status: string; label: Text2; at: string }[];
};
export type Message = { id: number; role: "user" | "agent"; en: string; kind: string; at: string };
export type Notice = { id: number; kind: string; en: string; delivery: string; at: string };
export type Fact = { key: string; value: string | number | boolean; source: string; confidence: number; label: Text2 };
export type HouseholdState = {
  household: {
    id: string; name: string | null; village: string | null; operator: string | null; stage: string;
    questions_asked: number; session_no: number; expected: string | null; pending_field: string | null;
    pending_digit: boolean; active_scheme: string | null;
  };
  facts: Fact[];
  eligibility: {
    results: SchemeResult[]; counts: Record<Outcome, number>;
    conflicts: (Text2 & { group: string; schemes: string[]; recommended: string })[];
    totals: { annual_inr: number; one_time_inr: number; cover_inr: number };
  };
  documents: { items: DocumentItem[]; total: number; have: number; missing: string[]; unknown: string[]; requested_across_schemes: number };
  scheme_count: number;
  received_annual_inr: number;
  applications: Application[];
  messages: Message[];
  notifications: Notice[];
  now: string;
};
export type TurnResult = { reply: Text2; state: HouseholdState };
export type ClientConfig = { voice: { server: string[]; mode: "server" | "browser" }; llm: boolean; ocr: string; sms: string; schemes: number };
export type DashboardRow = {
  id: string; name: string; village: string | null; stage: string; eligible: number; near_miss: number;
  entitled_annual_inr: number; received_annual_inr: number; missing_documents: number; applications: number;
  action: Text2 & { kind: string; due_at: string | null; overdue: boolean };
};
export type Dashboard = {
  totals: { households: number; entitled_annual_inr: number; received_annual_inr: number; overdue: number; pending: number; submitted: number };
  households: DashboardRow[];
  now: string;
};
export type AuditEntry = {
  id: number; household_id: string | null; tool: string; inputs: Record<string, unknown>; output: Record<string, unknown>;
  actor: string; outcome: string; at: string;
};

/**
 * What went wrong, in terms the page can act on.
 * gone: the household or application no longer exists, usually because a free server restarted and lost its data.
 * waking: the host was starting the server and never passed the request on. busy: the server's heavy-work slot was full.
 */
export type ErrorKind = "offline" | "waking" | "busy" | "timeout" | "gone" | "rejected" | "server";

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, public kind: ErrorKind) {
    super(`Request failed: ${kind} (${status})`);
  }
}

const GET_TIMEOUT_MS = 30_000;
// Long enough for a document read or a form fill on a small server, plus a queue.
const POST_TIMEOUT_MS = 170_000;
// A sleeping free server takes about a minute to start, so retries cover a bit more than that.
const WAKE_DELAYS_MS = [2_000, 4_000, 8_000, 12_000, 15_000, 15_000, 15_000, 15_000];
const BUSY_RETRIES = 2;

type Waiting = { reason: "waking" | "busy"; attempt: number } | null;
const waitingListeners = new Set<(waiting: Waiting) => void>();
/** Lets a page say "waking the server" while requests are being retried. */
export function onWaiting(listener: (waiting: Waiting) => void): () => void {
  waitingListeners.add(listener);
  return () => waitingListeners.delete(listener);
}
const announce = (waiting: Waiting) => waitingListeners.forEach((listener) => listener(waiting));

function detail(body: unknown): string | null {
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.en === "string") return record.en;
    if (typeof record.detail === "string") return record.detail;
  }
  return null;
}

function classify(response: Response, body: unknown): ErrorKind {
  // Render answers for a sleeping or restarting service itself, before the app ever sees the request.
  const fromHost = response.headers.has("x-render-routing") || (response.status === 429 && !body);
  if (response.status === 429 || (fromHost && response.status >= 502)) return "waking";
  if (response.status === 503 && (body as { code?: string } | null)?.code === "busy") return "busy";
  if (response.status === 404) return "gone";
  if (response.status >= 500) return "server";
  return "rejected";
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  let wakes = 0, busies = 0;
  for (;;) {
    if (typeof navigator !== "undefined" && navigator.onLine === false) throw new ApiError(0, null, "offline");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), method === "GET" ? GET_TIMEOUT_MS : POST_TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(path, { ...init, signal: controller.signal });
    } catch {
      clearTimeout(timer);
      if (controller.signal.aborted) {
        announce(null);
        throw new ApiError(0, null, "timeout");
      }
      // A GET can safely go again. A POST may already have run, so it is never repeated blindly.
      if (method === "GET" && wakes < WAKE_DELAYS_MS.length) {
        announce({ reason: "waking", attempt: wakes + 1 });
        await sleep(WAKE_DELAYS_MS[wakes++]);
        continue;
      }
      announce(null);
      throw new ApiError(0, null, navigator.onLine === false ? "offline" : "waking");
    }
    clearTimeout(timer);
    const body = await response.json().catch(() => null);
    if (response.ok) {
      announce(null);
      return body as T;
    }
    const kind = classify(response, body);
    if (kind === "waking" && wakes < WAKE_DELAYS_MS.length) {
      announce({ reason: "waking", attempt: wakes + 1 });
      await sleep(WAKE_DELAYS_MS[wakes++]);
      continue;
    }
    if (kind === "busy" && busies < BUSY_RETRIES) {
      busies += 1;
      announce({ reason: "busy", attempt: busies });
      await sleep(Math.min(30, Number(response.headers.get("retry-after")) || 15) * 1000);
      continue;
    }
    announce(null);
    throw new ApiError(response.status, body, kind);
  }
}

/** Words for the person, never a status code. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.kind) {
    case "offline": return "You seem to be offline. Check your connection and try again.";
    case "waking": return "The server is still starting up. Please try again in a minute.";
    case "timeout": return "The server took too long to answer. Please try again.";
    case "gone": return "This household is no longer on the server. The free demo server clears its data when it restarts.";
    case "busy": return detail(error.body) ?? "The server is busy. Please try again in a minute.";
    case "rejected": return detail(error.body) ?? "That did not work. Please check and try again.";
    default: return detail(error.body) ?? "Something went wrong on the server. Please try again.";
  }
}

function post<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
}

const MAX_PHOTO_SIDE = 2000;
const LARGE_PHOTO_BYTES = 1_500_000;

/** Phone photos can exceed a host's upload limit, and reading them takes longer. This size still reads well. */
async function shrinkPhoto(file: Blob): Promise<Blob> {
  if (file.size <= LARGE_PHOTO_BYTES) return file;
  try {
    const image = await createImageBitmap(file);
    const scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    canvas.getContext("2d")!.drawImage(image, 0, 0, canvas.width, canvas.height);
    image.close();
    const smaller = await new Promise<Blob | null>((done) => canvas.toBlob(done, "image/jpeg", 0.85));
    return smaller && smaller.size < file.size ? smaller : file;
  } catch {
    return file; // Formats the browser cannot decode go up as they are.
  }
}

export const api = {
  config: () => request<ClientConfig>("/api/config"),
  createHousehold: (data: { village?: string; operator?: string; name?: string } = {}) => post<HouseholdState>("/api/households", data),
  household: (id: string) => request<HouseholdState>(`/api/households/${id}`),
  chat: (id: string, text: string) => post<TurnResult>(`/api/households/${id}/chat`, { text }),
  resume: (id: string) => post<TurnResult>(`/api/households/${id}/session`),
  setDocument: (id: string, doc: string, have: boolean) => post<HouseholdState>(`/api/households/${id}/documents/${doc}`, { have }),
  startForm: (id: string, schemeId: string) => post<TurnResult>(`/api/households/${id}/form`, { scheme_id: schemeId }),
  editFact: (id: string, key: string, value: string) => request<HouseholdState>(`/api/households/${id}/facts/${key}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }),
  }),
  ocr: async (id: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", await shrinkPhoto(file), filename);
    return request<TurnResult & { extracted: { doc_type: string | null; fields: Record<string, string>; engine: string } }>(
      `/api/households/${id}/ocr`, { method: "POST", body: form });
  },
  ocrText: (id: string, rows: string[]) => post<(TurnResult & { extracted: { doc_type: string | null; fields: Record<string, string>; engine: string } }) | { needs_image: true }>(
    `/api/households/${id}/ocr/text`, { rows }),
  health: () => request<{ status: string }>("/api/health"),
  confirm: (applicationId: string) => post<TurnResult>(`/api/applications/${applicationId}/confirm`),
  submitWithoutConfirmation: (applicationId: string) => post<unknown>(`/api/applications/${applicationId}/submit`),
  advance: (days: number) => post<{ offset_days: number }>("/api/demo/advance", { days }),
  dashboard: () => request<Dashboard>("/api/operator/dashboard"),
  audit: () => request<AuditEntry[]>("/api/audit?limit=200"),
};

export const inr = (value: number) => `₹${value.toLocaleString("en-IN")}`;
