"use client";

import { useState } from "react";

import { AnswerCard } from "@/components/AnswerCard";
import { LetterResult } from "@/components/LetterResult";
import {
  askQuestion,
  explainLetter,
  type AskResponse,
  type Lang,
  type LetterResponse,
} from "@/lib/api";

type Tab = "ask" | "letter";

const EXAMPLES = [
  "How many days per year can I work as a non-EU student?",
  "Do I have to pay the Rundfunkbeitrag in a shared flat?",
  "Wie viel darf ich in einem Minijob verdienen?",
];

const MAX_QUESTION = 500;
const MAX_LETTER = 8000;

function Spinner() {
  return (
    <span
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
      aria-hidden
    />
  );
}

function AskTab() {
  const [question, setQuestion] = useState("");
  const [lang, setLang] = useState<Lang | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(q: string) {
    if (q.trim().length < 3 || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await askQuestion(q.trim(), lang));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit(question);
        }}
        className="space-y-3"
      >
        <label htmlFor="question" className="block text-sm font-medium text-slate-700">
          Your question about studying, working or the Rundfunkbeitrag
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value.slice(0, MAX_QUESTION))}
          rows={3}
          placeholder="e.g. How many hours can I work as a Werkstudent?"
          className="w-full resize-y rounded-lg border border-slate-300 bg-white p-3 text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={loading || question.trim().length < 3}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading && <Spinner />} {loading ? "Searching official sources…" : "Ask"}
          </button>
          <select
            value={lang ?? "auto"}
            onChange={(e) => setLang(e.target.value === "auto" ? null : (e.target.value as Lang))}
            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700"
            aria-label="Answer language"
          >
            <option value="auto">Answer language: auto</option>
            <option value="en">English</option>
            <option value="de">Deutsch</option>
          </select>
          <span className="ml-auto text-xs text-slate-400">
            {question.length}/{MAX_QUESTION}
          </span>
        </div>
      </form>

      {!result && !loading && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => {
                setQuestion(ex);
                void submit(ex);
              }}
              className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-600 hover:border-blue-300 hover:text-blue-700"
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {result && <AnswerCard data={result} />}
    </div>
  );
}

function LetterTab() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<LetterResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    if (text.trim().length < 20 || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await explainLetter(text));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
        <strong>Privacy:</strong> remove your name and address if you can. We hide personal data
        (names, addresses, IBAN, IDs) before any AI sees the text, and we don&apos;t store anything.
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="space-y-3"
      >
        <label htmlFor="letter" className="block text-sm font-medium text-slate-700">
          Paste the text of your German letter
        </label>
        <textarea
          id="letter"
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_LETTER))}
          rows={10}
          placeholder="Sehr geehrte …"
          className="w-full resize-y rounded-lg border border-slate-300 bg-white p-3 font-mono text-sm text-slate-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={loading || text.trim().length < 20}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading && <Spinner />} {loading ? "Reading your letter…" : "Explain my letter"}
          </button>
          <span className="ml-auto text-xs text-slate-400">
            {text.length}/{MAX_LETTER}
          </span>
        </div>
      </form>

      {error && (
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
          {error}
        </p>
      )}
      {result && <LetterResult data={result} />}
    </div>
  );
}

export default function Home() {
  const [tab, setTab] = useState<Tab>("ask");
  const tabs: { id: Tab; label: string }[] = [
    { id: "ask", label: "Ask" },
    { id: "letter", label: "Explain my letter" },
  ];

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:py-12">
      <section className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          German bureaucracy, explained simply.
        </h1>
        <p className="mt-3 text-lg text-slate-600">
          Ask about student jobs, visas, health insurance or the Rundfunkbeitrag, or paste an
          official letter. Every answer links to the official source.
        </p>
      </section>

      <div role="tablist" className="mb-6 inline-flex rounded-lg bg-slate-100 p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-md px-4 py-2 text-sm font-medium transition ${
              tab === t.id
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-600 hover:text-slate-900"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel">{tab === "ask" ? <AskTab /> : <LetterTab />}</div>
    </div>
  );
}
