const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type QuestionKind = "text" | "single_select" | "multi_select";

export interface QuestionOption {
  label: string;
  description: string;
}

export interface Question {
  id: string;
  header: string;
  text: string;
  kind: QuestionKind;
  options: QuestionOption[];
  why_it_matters: string;
  targets: string[];
}

export interface LintFinding {
  code: string;
  severity: "error" | "warning";
  location: string;
  evidence: string;
  rectification: string;
}

export interface Snapshot {
  thread_id: string;
  status: "interviewing" | "ready" | "exhausted";
  round: number;
  questions: Question[];
  rationale: string;
  draft: Record<string, unknown>;
  missing_fields: string[];
  lint: { findings: LintFinding[] } | null;
  lint_summary: string | null;
  spec: Record<string, unknown> | null;
  notices: string[];
  transcript: { question: string; answer: string }[];
}

export interface ReviewFinding {
  location: string;
  issue: string;
  evidence: string;
  fix: string;
  blocking: boolean;
}

export interface Task {
  id: string;
  title: string;
  requirement_id: string | null;
  intent: string;
  scope_paths: string[];
  done_when: string[];
  depends_on: string[];
}

export interface Generation {
  accepted: boolean;
  attempts: number;
  review: { findings: ReviewFinding[]; verdict: string };
  review_summary: string;
  notes: string[];
  backlog: { tasks: Task[] };
  files: { path: string; bytes: number; executable: boolean }[];
  output_dir: string;
}

export class ApiError extends Error {
  detail: unknown;
  status: number;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(
      0,
      null,
      "Cannot reach the Ouroboros server. Start it with: uvicorn ouroboros.server.app:app --port 8000",
    );
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail ?? null;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.error as string) ?? `Request failed (${response.status}).`;
    throw new ApiError(response.status, detail, message);
  }

  return (await response.json()) as T;
}

export const api = {
  start: (brief: string) =>
    request<Snapshot>("/api/interview/start", {
      method: "POST",
      body: JSON.stringify({ brief }),
    }),

  answer: (threadId: string, answers: { question_id: string; value: string }[]) =>
    request<Snapshot>(`/api/interview/${threadId}/answer`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),

  generate: (threadId: string) =>
    request<Generation>(`/api/generate/${threadId}`, { method: "POST" }),

  readFile: (threadId: string, path: string) =>
    request<{ path: string; contents: string }>(
      `/api/generate/${threadId}/file?path=${encodeURIComponent(path)}`,
    ),

  publish: (
    threadId: string,
    token: string,
    repoName: string,
    isPrivate: boolean,
  ) =>
    request<{ repo_url: string; clone_url: string; branch: string; created: boolean }>(
      `/api/publish/${threadId}`,
      {
        method: "POST",
        body: JSON.stringify({ token, repo_name: repoName, private: isPrivate }),
      },
    ),

  downloadUrl: (threadId: string) =>
    `${API_BASE}/api/generate/${threadId}/download`,
};
