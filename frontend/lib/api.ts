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

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`Request failed with status ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}

function post<T>(path: string, data?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
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
  ocr: (id: string, file: Blob, filename: string) => {
    const form = new FormData();
    form.append("file", file, filename);
    return request<TurnResult & { extracted: { doc_type: string | null; fields: Record<string, string>; engine: string } }>(
      `/api/households/${id}/ocr`, { method: "POST", body: form });
  },
  confirm: (applicationId: string) => post<TurnResult>(`/api/applications/${applicationId}/confirm`),
  submitWithoutConfirmation: (applicationId: string) => post<unknown>(`/api/applications/${applicationId}/submit`),
  advance: (days: number) => post<{ offset_days: number }>("/api/demo/advance", { days }),
  dashboard: () => request<Dashboard>("/api/operator/dashboard"),
  audit: () => request<AuditEntry[]>("/api/audit?limit=200"),
};

export const inr = (value: number) => `₹${value.toLocaleString("en-IN")}`;
