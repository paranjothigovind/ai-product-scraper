import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "AI Product Scraper",
  description: "Find and rank the products on a shop page.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased dark:bg-neutral-950 dark:text-neutral-100">{children}</body>
    </html>
  );
}
