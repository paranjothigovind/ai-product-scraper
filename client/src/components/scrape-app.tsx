"use client";

import { useScrape } from "@/lib/use-scrape";
import { Results } from "./results";
import { RunStatusPanel } from "./run-status";
import { ScrapeForm } from "./scrape-form";

export function ScrapeApp() {
  const { state, start, cancel, reset } = useScrape();
  const busy = state.phase === "submitting" || state.phase === "active";
  const finished = state.phase === "done" && state.run;

  return (
    <div className="space-y-8">
      <ScrapeForm onSubmit={start} disabled={busy} />

      {state.phase === "error" && (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
        >
          <p>{state.error}</p>
          <button type="button" onClick={reset} className="mt-2 font-medium underline">
            Dismiss
          </button>
        </div>
      )}

      {(busy || finished) && (
        <RunStatusPanel
          run={state.run}
          waiting={state.phase === "submitting"}
          onCancel={cancel}
        />
      )}

      {state.error && state.phase !== "error" && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-300">
          {state.error}
        </p>
      )}

      {finished && state.run?.products && <Results products={state.run.products} />}
    </div>
  );
}
