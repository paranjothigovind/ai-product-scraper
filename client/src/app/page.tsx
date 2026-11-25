import { ScrapeApp } from "@/components/scrape-app";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">AI Product Scraper</h1>
        <p className="mt-2 text-neutral-600 dark:text-neutral-400">
          Give it a shop page and it returns the products it finds, ranked. It uses the page&apos;s
          own product data when there is any, and AI reading when there is not. It respects
          robots.txt and stops if a site refuses access.
        </p>
      </header>
      <ScrapeApp />
    </main>
  );
}
