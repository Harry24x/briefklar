import type { Metadata } from "next";

export const metadata: Metadata = { title: "Impressum – BriefKlar" };

// TODO(Harman): replace every [placeholder] with your real details before going live.
export default function Impressum() {
  return (
    <article className="mx-auto max-w-3xl space-y-4 px-4 py-10 text-slate-800">
      <h1 className="text-2xl font-bold">Impressum</h1>
      <p>Angaben gemäß § 5 DDG</p>
      <p>
        [Full name]
        <br />
        [Street and house number]
        <br />
        [Postcode and city]
      </p>
      <p>E-Mail: [email address]</p>
      <p className="text-sm text-slate-500">
        BriefKlar is a non-commercial student project. It gives general information from official
        sources and is not legal advice.
      </p>
    </article>
  );
}
