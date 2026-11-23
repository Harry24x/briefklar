import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy – BriefKlar" };

// TODO(Harman): check this text and fill in the [placeholders] before going live.
export default function Privacy() {
  return (
    <article className="mx-auto max-w-3xl space-y-4 px-4 py-10 text-slate-800">
      <h1 className="text-2xl font-bold">Privacy</h1>
      <p>
        <strong>Responsible:</strong> [Full name, address, email] (see Impressum).
      </p>
      <h2 className="text-lg font-semibold">What happens with your text</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>Questions and letter text are processed only to create your answer.</li>
        <li>
          Before any AI model sees a letter, names, addresses, IBANs, e-mail addresses, phone
          numbers, dates of birth, tax IDs and reference numbers are replaced by placeholders.
        </li>
        <li>
          The masked text is sent to Groq (USA) to generate the answer. Raw letter text is never
          stored or logged by BriefKlar.
        </li>
        <li>We store nothing about you: no accounts, no cookies, no tracking.</li>
        <li>
          To prevent abuse, your IP address is used in memory to count requests per day (20
          questions, 5 letters). It is not written to disk.
        </li>
      </ul>
      <h2 className="text-lg font-semibold">Hosting</h2>
      <p>
        Frontend: Vercel. Backend: [hosting provider and region]. These providers process technical
        access data (e.g. IP address) to deliver the website.
      </p>
      <p className="text-sm text-slate-500">
        Your rights (access, deletion, objection) under the GDPR: contact [email address].
      </p>
    </article>
  );
}
