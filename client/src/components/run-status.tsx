import { isTerminal, type Run, type RunStatus } from "@/lib/types";

const LABEL: Record<RunStatus, string> = {
  queued: "Waiting for a worker",
  running: "Scraping",
  succeeded: "Done",
  low_confidence: "Done, but check the results",
  failed: "Failed",
  cancelled: "Cancelled",
};

const TONE: Record<RunStatus, string> = {
  queued: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200",
  succeeded: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  low_confidence: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
  cancelled: "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
};

const ERROR_TEXT: Record<string, string> = {
  invalid_input: "The request was not valid.",
  blocked: "The site refused access, so the scrape stopped. We do not try to get around that.",
  robots_disallowed: "The site's robots.txt does not allow scraping this page.",
  timeout: "The scrape ran out of time.",
  fetch_failed: "The page could not be fetched.",
  render_failed: "The page could not be rendered.",
  no_products_found: "No products were found on the page.",
  llm_failed: "The AI extraction step failed.",
  budget_exceeded: "The scrape used up its token budget before finishing.",
  internal: "Something went wrong on our side.",
};

export function RunStatusPanel({
  run,
  waiting,
  onCancel,
}: {
  run: Run | null;
  /** Submitted, but the first status has not come back yet. */
  waiting: boolean;
  onCancel: () => void;
}) {
  const status: RunStatus = run?.status ?? "queued";
  const active = !isTerminal(status);
  const cancelling = Boolean(run?.cancel_requested) && active;

  return (
    <section
      aria-live="polite"
      className="rounded-xl border border-neutral-200 p-5 dark:border-neutral-800"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={`rounded-full px-3 py-1 text-sm font-medium ${TONE[status]}`}>
            {cancelling ? "Cancelling…" : waiting ? "Submitting…" : LABEL[status]}
          </span>
          {active && (
            <span
              aria-hidden
              className="h-4 w-4 animate-spin rounded-full border-2 border-neutral-300 border-t-blue-600"
            />
          )}
        </div>
        {active && !waiting && (
          <button
            type="button"
            onClick={onCancel}
            disabled={cancelling}
            className="rounded-lg border border-neutral-300 px-3 py-1.5 text-sm font-medium hover:bg-neutral-100 disabled:opacity-60 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Cancel
          </button>
        )}
      </div>

      {run && (
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <Stat label="Pages fetched" value={run.pages_fetched} />
          <Stat label="Requested" value={run.requested} />
          <Stat label="Tokens" value={(run.tokens_in + run.tokens_out).toLocaleString()} />
          <Stat
            label="Quality"
            value={run.score === null ? "—" : `${Math.round(run.score * 100)}%`}
          />
        </dl>
      )}

      {run && isTerminal(run.status) && (
        <div className="mt-4 space-y-2 text-sm">
          {run.confidence && (
            <p>
              Confidence: <strong>{run.confidence}</strong>
            </p>
          )}
          {run.incomplete_reason && !run.error_code && (
            <p className="text-amber-800 dark:text-amber-300">
              Fewer products than requested: {run.incomplete_reason}.
            </p>
          )}
          {run.error_code && (
            <p className="text-red-700 dark:text-red-300">
              {ERROR_TEXT[run.error_code] ?? "The scrape ended with an error."}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-neutral-500 dark:text-neutral-400">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}
