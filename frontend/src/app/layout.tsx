import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CEXvsCEX Terminal",
  description: "Institutional-grade crypto basis trading terminal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="h-screen overflow-hidden bg-zinc-950 text-zinc-100 font-mono">
        {children}
      </body>
    </html>
  );
}
