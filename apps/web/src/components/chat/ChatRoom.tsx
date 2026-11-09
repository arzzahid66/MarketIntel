"use client";

/**
 * One chatroom: the conversation and the composer.
 *
 * The composer is the interesting part. There are three reasons a post can be
 * refused, and they are not the same message:
 *
 *   - **402** the plan does not include posting. An upgrade link, and the input
 *     is not shown at all - offering a box that always fails is worse than
 *     saying so.
 *   - **429** posting too fast. A wait, not a sale.
 *   - **400** empty, too long, or a repeat of something already said.
 *
 * A post the spam screen hid on arrival is shown to its author, labelled. The
 * alternative is a shadow-ban, which teaches people the product is broken
 * rather than teaching them the rule.
 */

import { useCallback, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { formatExchangeTime } from "@/lib/market";
import type { ChatHistory, ChatMessage } from "@/lib/types";

const MAX_LENGTH = 2000;

/** The message for a refused post, from the API's own error body. */
export function refusalMessage(status: number, detail: unknown): string {
  const body = detail as { message?: string; error?: string } | undefined;
  if (status === 429) {
    return body?.message ?? "You are posting too quickly. Try again shortly.";
  }
  if (status === 402) {
    return "Posting is included from the Plus plan.";
  }
  if (status === 400 && body?.error === "duplicate") {
    return "You have already posted that message.";
  }
  return body?.message ?? "That message could not be posted.";
}

function Message({ message }: { message: ChatMessage }) {
  return (
    <li className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex items-baseline gap-2 text-small text-muted">
        <span className="font-medium text-ink">{message.author}</span>
        <time dateTime={message.created_at}>
          {formatExchangeTime(message.created_at, false)}
        </time>
        {message.flags > 0 && (
          <span className="tnum">
            · {message.flags} report{message.flags === 1 ? "" : "s"}
          </span>
        )}
        {message.spam_label && <span>· screened {message.spam_label}</span>}
      </div>
      <p className="mt-1 whitespace-pre-wrap text-body">{message.body}</p>
      {message.is_hidden && (
        <p className="mt-1 text-small text-muted">
          Hidden from the room{message.hidden_reason ? ` — ${message.hidden_reason}` : ""}.
        </p>
      )}
    </li>
  );
}

export function ChatRoomView({ initial }: { initial: ChatHistory }) {
  const [history, setHistory] = useState(initial);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async (slug: string) => {
    try {
      const response = await fetch(`/api/chat/${slug}`, { cache: "no-store" });
      if (response.ok) setHistory((await response.json()) as ChatHistory);
    } catch {
      // Keep what is on screen; the next post or reload will catch up.
    }
  }, []);

  const send = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const body = draft.trim();
      if (!body || busy) return;
      setBusy(true);
      setNotice(null);

      try {
        const response = await fetch(`/api/chat/${history.room.slug}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ body }),
          cache: "no-store",
        });
        const payload = await response.json().catch(() => null);

        if (response.ok) {
          setDraft("");
          if (payload?.auto_hidden) {
            setNotice(
              "Your message was held by the spam filter and is not visible to the room. " +
                "A moderator will review it.",
            );
          }
          await refresh(history.room.slug);
          return;
        }
        setNotice(refusalMessage(response.status, payload?.detail ?? payload));
      } catch {
        setNotice("Could not reach the chatroom.");
      } finally {
        setBusy(false);
      }
    },
    [busy, draft, history.room.slug, refresh],
  );

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{history.room.name}</h2>
        <p className="text-small text-muted">{history.room.description}</p>
      </div>

      <div className="rounded-[var(--radius-ui)] border border-line bg-surface">
        {history.messages.length === 0 ? (
          <p className="px-4 py-10 text-center text-small text-muted">
            Nothing posted here yet.
          </p>
        ) : (
          <ul>
            {history.messages.map((message) => (
              <Message key={message.id} message={message} />
            ))}
          </ul>
        )}
      </div>

      {notice && <Alert>{notice}</Alert>}

      {history.can_post ? (
        <form onSubmit={send} className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={`Message ${history.room.name}`}
            aria-label={`Message ${history.room.name}`}
            maxLength={MAX_LENGTH}
            className="h-9 flex-1 rounded-[var(--radius-ui)] border border-line bg-surface px-3 text-body outline-none focus:border-action"
          />
          <button
            type="submit"
            disabled={busy || draft.trim().length === 0}
            className="h-9 rounded-[var(--radius-ui)] bg-action px-4 text-small font-medium text-white disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send"}
          </button>
        </form>
      ) : (
        <Alert>
          Reading is free. Posting is included from the Plus plan —{" "}
          <a href="/pricing" className="text-action hover:underline">
            see what each plan includes
          </a>
          .
        </Alert>
      )}

      <p className="text-small text-muted">
        Messages are screened automatically and reviewed by a moderator. Nothing here is
        financial advice.
      </p>
    </div>
  );
}
