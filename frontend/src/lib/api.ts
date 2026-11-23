// Typed client for the BriefKlar FastAPI backend.
// The base URL comes from NEXT_PUBLIC_API_URL (e.g. https://api.example.com).

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

export type Lang = "en" | "de";

export interface SourceRef {
  n: number;
  url: string;
  title: string;
  heading: string;
  fetched_at: string | null;
}

export interface AskResponse {
  answer: string;
  citations: number[];
  sources: SourceRef[];
  next_steps: string[];
  confidence: "low" | "medium" | "high";
  refused: boolean;
  disclaimer: string;
}

export interface LetterFields {
  sender: string | null;
  letter_type: string;
  letter_date: string | null;
  deadline: string | null;
  amount_eur: number | null;
  required_actions: string[];
  summary_plain_english: string;
}

export interface LetterResponse {
  fields: LetterFields;
  explanation: AskResponse;
  ics_available: boolean;
  masked_items: Record<string, number>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function post(path: string, body: unknown): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("The server cannot be reached right now. Please try again later.", 0);
  }
  if (!res.ok) {
    let detail = "Something went wrong. Please try again.";
    if (res.status === 429) detail = "You reached today's limit. Please come back tomorrow.";
    else if (res.status === 422) detail = "Please check your input (length and format).";
    else {
      try {
        const data = (await res.json()) as { detail?: unknown };
        if (typeof data.detail === "string") detail = data.detail;
      } catch {
        /* keep the generic message */
      }
    }
    throw new ApiError(detail, res.status);
  }
  return res;
}

export async function askQuestion(question: string, lang: Lang | null): Promise<AskResponse> {
  const res = await post("/ask", { question, lang });
  return (await res.json()) as AskResponse;
}

export async function explainLetter(text: string): Promise<LetterResponse> {
  const res = await post("/letter", { text });
  return (await res.json()) as LetterResponse;
}

export async function downloadIcs(fields: LetterFields): Promise<void> {
  const res = await post("/letter/ics", fields);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "briefklar-deadline.ics";
  link.click();
  URL.revokeObjectURL(url);
}
