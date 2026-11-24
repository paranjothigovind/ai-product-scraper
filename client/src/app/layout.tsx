import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "AI Product Scraper" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900">{children}</body>
    </html>
  );
}
