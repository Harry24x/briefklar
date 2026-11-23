import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "BriefKlar – German official letters, explained",
  description:
    "Explains German official letters and bureaucracy rules to international students in simple English, with an official source for every answer.",
};

const GITHUB_URL = "https://github.com/Harry24x/briefklar";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col bg-slate-50 text-slate-900">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-semibold text-slate-900">
              {/* eslint-disable-next-line @next/next/no-img-element -- tiny static SVG */}
              <img src="/logo.svg" alt="" width={28} height={28} className="h-7 w-7" />
              <span>
                Brief<span className="text-blue-700">Klar</span>
              </span>
            </Link>
            <span className="text-sm text-slate-500">Official sources · simple English</span>
          </div>
        </header>

        <main className="flex-1">{children}</main>

        <footer className="border-t border-slate-200 bg-white">
          <div className="mx-auto flex max-w-3xl flex-col gap-2 px-4 py-5 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
            <p>General information from official sources, not legal advice.</p>
            <nav className="flex gap-4">
              <Link href="/impressum" className="hover:text-slate-800">
                Impressum
              </Link>
              <Link href="/privacy" className="hover:text-slate-800">
                Privacy
              </Link>
              <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="hover:text-slate-800">
                GitHub
              </a>
            </nav>
          </div>
        </footer>
      </body>
    </html>
  );
}
