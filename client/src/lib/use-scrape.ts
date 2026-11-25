"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, cancelScrape, createScrape, getScrape } from "./api";
import { isTerminal, type Run, type ScrapeInput } from "./types";

export type Phase = "idle" | "submitting" | "active" | "done" | "error";

export interface ScrapeState {
  phase: Phase;
  run: Run | null;
  error: string | null;
}

const POLL_MS = 1500;
const MAX_POLL_FAILURES = 5;

const IDLE: ScrapeState = { phase: "idle", run: null, error: null };

/** Submit a scrape, then poll until it finishes. Polling stops on unmount or reset. */
export function useScrape() {
  const [state, setState] = useState<ScrapeState>(IDLE);
  const abort = useRef<AbortController | null>(null);
  const runId = useRef<string | null>(null);

  const stop = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
  }, []);

  useEffect(() => stop, [stop]);

  const poll = useCallback(async (id: string, signal: AbortSignal) => {
    let failures = 0;
    while (!signal.aborted) {
      try {
        const run = await getScrape(id, signal);
        failures = 0;
        if (isTerminal(run.status)) {
          setState({ phase: "done", run, error: null });
          return;
        }
        setState({ phase: "active", run, error: null });
      } catch (err) {
        if (signal.aborted) return;
        // A 404 means the run is gone; anything else may be a blip, so retry a few times.
        const fatal = err instanceof ApiError && err.status === 404;
        failures += 1;
        if (fatal || failures >= MAX_POLL_FAILURES) {
          const message = err instanceof ApiError ? err.message : "Lost contact with the server.";
          setState((s) => ({ ...s, phase: "error", error: message }));
          return;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_MS * (failures + 1)));
    }
  }, []);

  const start = useCallback(
    async (input: ScrapeInput) => {
      stop();
      const controller = new AbortController();
      abort.current = controller;
      setState({ phase: "submitting", run: null, error: null });
      try {
        // A fresh key per click: a double click or a retried request cannot start two runs.
        const created = await createScrape(input, crypto.randomUUID(), controller.signal);
        runId.current = created.id;
        setState({ phase: "active", run: null, error: null });
        await poll(created.id, controller.signal);
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({
          phase: "error",
          run: null,
          error: err instanceof ApiError ? err.message : "Could not start the scrape.",
        });
      }
    },
    [poll, stop],
  );

  const cancel = useCallback(async () => {
    const id = runId.current;
    if (!id) return;
    try {
      const run = await cancelScrape(id);
      // A queued run is cancelled at once; a running one stops at its next check, so keep polling.
      if (isTerminal(run.status)) {
        stop();
        setState({ phase: "done", run, error: null });
      } else {
        setState((s) => ({ ...s, run }));
      }
    } catch (err) {
      setState((s) => ({
        ...s,
        error: err instanceof ApiError ? err.message : "Could not cancel.",
      }));
    }
  }, [stop]);

  const reset = useCallback(() => {
    stop();
    runId.current = null;
    setState(IDLE);
  }, [stop]);

  return { state, start, cancel, reset };
}
