import type { AskResponse, SourceRef } from "@/lib/api";

function formatDate(iso: string | null): string {
  if (!iso) return "unknown";
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Turns "text [1][2] more" into text with small citation links that jump to the source. */
function WithCitations({ text, idPrefix }: { text: string; idPrefix: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <span key={i}>{part}</span>;
        return (
          <a
            key={i}
            href={`#${idPrefix}-source-${match[1]}`}
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-blue-50 px-1 align-text-top text-xs font-semibold text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100"
            aria-label={`Source ${match[1]}`}
          >
            {match[1]}
          </a>
        );
      })}
    </>
  );
}

function SourceList({ sources, idPrefix }: { sources: SourceRef[]; idPrefix: string }) {
  return (
    <ol className="space-y-2">
      {sources.map((s) => (
        <li
          key={s.n}
          id={`${idPrefix}-source-${s.n}`}
          className="flex gap-3 rounded-lg border border-slate-200 bg-white p-3 text-sm target:ring-2 target:ring-blue-300"
        >
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-100 text-xs font-semibold text-slate-600">
            {s.n}
          </span>
          <div className="min-w-0">
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-blue-700 hover:underline"
            >
              {s.title || new URL(s.url).hostname}
            </a>
            {s.heading && <p className="truncate text-slate-500">{s.heading}</p>}
            <p className="text-xs text-slate-400">
              {new URL(s.url).hostname} · source checked on {formatDate(s.fetched_at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function AnswerCard({ data, idPrefix = "ask" }: { data: AskResponse; idPrefix?: string }) {
  if (data.refused) {
    const link = data.sources[0];
    return (
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h3 className="font-semibold text-amber-900">No answer in the official sources</h3>
        <p className="mt-1 text-amber-900">{data.answer}</p>
        {link && (
          <p className="mt-3 text-sm text-amber-900">
            Closest official page:{" "}
            <a href={link.url} target="_blank" rel="noopener noreferrer" className="font-medium underline">
              {link.title || link.url}
            </a>
          </p>
        )}
        <p className="mt-4 text-xs text-amber-800">{data.disclaimer}</p>
      </section>
    );
  }

  return (
    <section className="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Answer</h3>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
            confidence: {data.confidence}
          </span>
        </div>
        <p className="leading-relaxed text-slate-800">
          <WithCitations text={data.answer} idPrefix={idPrefix} />
        </p>
      </div>

      {data.next_steps.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Next steps
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-slate-800">
            {data.next_steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Official sources
        </h3>
        <SourceList sources={data.sources} idPrefix={idPrefix} />
      </div>

      <p className="border-t border-slate-100 pt-3 text-xs text-slate-500">{data.disclaimer}</p>
    </section>
  );
}
