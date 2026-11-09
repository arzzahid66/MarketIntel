"use client";

/**
 * The AI analyst conversation.
 *
 * Two things this component must never soften:
 *
 *   1. **Citations are part of the answer, not a footnote.** Every answer shows
 *      the articles it was built from, each a link to the publisher. An answer
 *      with no citations says so plainly rather than looking authoritative.
 *   2. **A spent quota is not an error.** A 402 carries which window ran out and
 *      the counts, so the reader sees "5 of 5 used today" and an upgrade link,
 *      not a red failure.
 *
 * History is deliberately per-session and in memory. Persisting it would be a
 * second store of what the analyst said, and `ai_messages` is already the
 * record - two copies drift, and the audit trail is the one that matters.
 */

import { useCallback, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import type { AnalystAnswer, AnalystUsage } from "@/lib/types";

const UNLIMITED = -1;

interface Turn {
  id: number;
  question: string;
  answer: AnalystAnswer | null;
  error: string | null;
}

export function remaining(usage: AnalystUsage): string {
  const daily =
    usage.daily_limit === UNLIMITED
      ? "Fair use"
      : `${usage.used_today} of ${usage.daily_limit} used today`;
  const hourly =
    usage.hourly_limit === UNLIMITED
      ? ""
      : ` · ${usage.used_this_hour} of ${usage.hourly_limit} this hour`;
  return `${daily}${hourly}`;
}

/** The message for a spent quota, from the API's own 402 body. */
export function quotaMessage(detail: Record<string, unknown> | undefined): string {
  const window = detail?.window === "hour" ? "this hour" : "today";
  const limit = typeof detail?.limit === "number" ? detail.limit : null;
  return limit === null
    ? `You have used your allowance for ${window}.`
    : `You have used all ${limit} analyst questions for ${window}.`;
}

function Citations({ answer }: { answer: AnalystAnswer }) {
  if (answer.citations.length === 0) {
    return (
      <p className="mt-2 text-small text-muted">
        {answer.retrieved === 0
          ? "No articles in the feed matched this question."
          : "This answer did not cite a specific article."}
      </p>
    );
  }
  return (
    <ol className="mt-3 flex flex-col gap-1.5 border-t border-line pt-3">
      {answer.citations.map((citation) => (
        <li key={citation.feed_item_id} className="text-small text-muted">
          <span className="tnum">[{citation.number}]</span>{" "}
          <a
            href={citation.source_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="text-action hover:underline"
          >
            {citation.title}
          </a>{" "}
          — {citation.publisher}
        </li>
      ))}
    </ol>
  );
}

export function AnalystChat({ initialUsage }: { initialUsage: AnalystUsage }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [usage, setUsage] = useState(initialUsage);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(0);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const asked = question.trim();
      if (!asked || busy) return;

      const id = nextId.current++;
      setTurns((previous) => [...previous, { id, question: asked, answer: null, error: null }]);
      setQuestion("");
      setBusy(true);

      try {
        const response = await fetch("/api/ai/ask", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ question: asked }),
          cache: "no-store",
        });
        const body = await response.json();

        if (response.ok) {
          const answer = body as AnalystAnswer;
          setUsage(answer.usage);
          setTurns((previous) =>
            previous.map((turn) => (turn.id === id ? { ...turn, answer } : turn)),
          );
          return;
        }

        const error =
          response.status === 402
            ? quotaMessage(body?.detail as Record<string, unknown> | undefined)
            : response.status === 503
              ? "The analyst is unavailable right now. Please try again in a moment."
              : "Something went wrong asking that question.";
        setTurns((previous) =>
          previous.map((turn) => (turn.id === id ? { ...turn, error } : turn)),
        );
      } catch {
        setTurns((previous) =>
          previous.map((turn) =>
            turn.id === id ? { ...turn, error: "Could not reach the analyst." } : turn,
          ),
        );
      } finally {
        setBusy(false);
      }
    },
    [busy, question],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-xl font-semibold tracking-tight">AI analyst</h1>
        <span className="text-small text-muted tnum">{remaining(usage)}</span>
      </div>

      <p className="text-small text-muted">
        Ask about anything in the news feed. Answers come only from articles we have
        ingested, and every claim is cited so you can check it. The analyst reports what
        the news says — it cannot tell you what to buy or sell.
      </p>

      <form onSubmit={submit} className="flex gap-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What is happening with Nvidia?"
          aria-label="Ask the analyst a question"
          maxLength={2000}
          className="h-9 flex-1 rounded-[var(--radius-ui)] border border-line bg-surface px-3 text-body outline-none focus:border-action"
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 3}
          className="h-9 rounded-[var(--radius-ui)] bg-action px-4 text-small font-medium text-white disabled:opacity-50"
        >
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>

      {turns.length === 0 && (
        <p className="py-8 text-center text-small text-muted">
          Nothing asked yet. Try &ldquo;what is the latest on Nvidia?&rdquo;
        </p>
      )}

      {turns.map((turn) => (
        <section
          key={turn.id}
          className="rounded-[var(--radius-ui)] border border-line bg-surface p-4"
        >
          <p className="font-medium">{turn.question}</p>
          {turn.error ? (
            <div className="mt-3">
              <Alert>{turn.error}</Alert>
            </div>
          ) : turn.answer ? (
            <>
              <p className="mt-2 whitespace-pre-wrap text-body text-muted">
                {turn.answer.answer}
              </p>
              <Citations answer={turn.answer} />
            </>
          ) : (
            <p className="mt-2 text-small text-muted">Reading the feed…</p>
          )}
        </section>
      ))}
    </div>
  );
}
