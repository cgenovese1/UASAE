import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UASAE — Universal Autonomous Software Assurance Engine",
  description:
    "AI-native continuous verification intelligence. Discovers, verifies, and maintains software assurance autonomously.",
  openGraph: {
    title: "UASAE",
    description: "AI-native software assurance platform",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full bg-gray-950 text-gray-100 antialiased">
        <div className="flex h-full flex-col">
          <header className="border-b border-gray-800 px-6 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded bg-indigo-600 text-sm font-bold">
                U
              </div>
              <span className="text-lg font-semibold tracking-tight">UASAE</span>
              <span className="text-sm text-gray-500">Universal Autonomous Software Assurance Engine</span>
            </div>
          </header>

          <div className="flex flex-1 overflow-hidden">
            <nav className="w-56 flex-none border-r border-gray-800 py-4">
              <ul className="space-y-1 px-3">
                {[
                  { href: "/", label: "Dashboard" },
                  { href: "/cases", label: "Verification Cases" },
                  { href: "/verdicts", label: "Verdicts" },
                  { href: "/risk", label: "Risk Summary" },
                  { href: "/cycles", label: "Assurance Cycles" },
                ].map(({ href, label }) => (
                  <li key={href}>
                    <a
                      href={href}
                      className="block rounded px-3 py-2 text-sm text-gray-400 hover:bg-gray-800 hover:text-gray-100 transition-colors"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>

            <main className="flex-1 overflow-auto px-8 py-6">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
