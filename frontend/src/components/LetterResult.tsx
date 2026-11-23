"use client";

import { useState } from "react";

import { AnswerCard } from "@/components/AnswerCard";
import { downloadIcs, type LetterResponse } from "@/lib/api";

function formatDate(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((new Date(iso).getTime() - today.getTime()) / 86_400_000);
}

const MASK_LABELS: Record<string, string> = {
  NAME: "name",
  ADDRESS: "address",
  IBAN: "IBAN",
  EMAIL: "e-mail",
  PHONE: "phone number",
  BIRTH_DATE: "date of birth",
  TAX_ID: "tax ID",
  CASE_ID: "reference number",
};

export function LetterResult({ data }: { data: LetterResponse }) {
  const { fields } = data;
  const [icsError, setIcsError] = useState<string | null>(null);
  const days = fields.deadline ? daysUntil(fields.deadline) : null;
  const masked = Object.entries(data.masked_items);

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-sm text-slate-500">{fields.sender ?? "Unknown sender"}</p>
        <h3 className="text-lg font-semibold text-slate-900">{fields.letter_type}</h3>
        <p className="mt-2 leading-relaxed text-slate-800">{fields.summary_plain_english}</p>

        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          <div
            className={`rounded-lg p-3 ${
              fields.deadline ? "bg-red-50 ring-1 ring-red-200" : "bg-slate-50"
            }`}
          >
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Deadline
            </dt>
            <dd className={`mt-1 font-semibold ${fields.deadline ? "text-red-700" : "text-slate-700"}`}>
              {formatDate(fields.deadline)}
              {days !== null && (
                <span className="block text-sm font-normal">
                  {days > 1 && `in ${days} days`}
                  {days === 1 && "tomorrow"}
                  {days === 0 && "today"}
                  {days < 0 && `${-days} days ago`}
                </span>
              )}
            </dd>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Amount</dt>
            <dd className="mt-1 font-semibold text-slate-800">
              {fields.amount_eur !== null
                ? fields.amount_eur.toLocaleString("de-DE", { style: "currency", currency: "EUR" })
                : "–"}
            </dd>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Letter date
            </dt>
            <dd className="mt-1 font-semibold text-slate-800">{formatDate(fields.letter_date)}</dd>
          </div>
        </dl>

        {fields.required_actions.length > 0 && (
          <div className="mt-4">
            <h4 className="mb-1 text-sm font-semibold text-slate-700">What the letter asks you to do</h4>
            <ul className="list-disc space-y-1 pl-5 text-slate-800">
              {fields.required_actions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}

        {data.ics_available && (
          <button
            type="button"
            onClick={() => downloadIcs(fields).catch((e: Error) => setIcsError(e.message))}
            className="mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <span aria-hidden>📅</span> Add deadline to calendar (.ics)
          </button>
        )}
        {icsError && <p className="mt-2 text-sm text-red-700">{icsError}</p>}

        {masked.length > 0 && (
          <p className="mt-4 text-xs text-slate-500">
            Before analysis we hid:{" "}
            {masked.map(([k, n]) => `${n} ${MASK_LABELS[k] ?? k.toLowerCase()}`).join(", ")}.
          </p>
        )}
      </section>

      <div>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          The rules behind this letter
        </h3>
        <AnswerCard data={data.explanation} idPrefix="letter" />
      </div>
    </div>
  );
}
