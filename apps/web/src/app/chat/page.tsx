/**
 * The chatrooms page.
 *
 * Reading is free, so the only gate here is being signed in. Posting is gated
 * per-plan by the API, and `can_post` on the history payload is what decides
 * whether the composer or an upgrade prompt is shown.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { ChatRoomView } from "@/components/chat/ChatRoom";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { ApiError, apiFetch } from "@/lib/api";
import { getAccessToken } from "@/lib/session";
import type { ChatHistory, ChatRoom } from "@/lib/types";

export const metadata: Metadata = { title: "Chatrooms" };

const DEFAULT_ROOM = "general";

export default async function ChatPage({
  searchParams,
}: {
  searchParams: Promise<{ room?: string }>;
}) {
  const token = await getAccessToken();
  if (!token) {
    return (
      <Panel title="Chatrooms">
        <EmptyState
          title="Sign in to join the conversation"
          description="Reading the rooms is free on every plan. Posting is included from Plus."
          action={
            <Link href="/login" className="text-small">
              Log in or create an account
            </Link>
          }
        />
      </Panel>
    );
  }

  const { room: requested } = await searchParams;
  const slug = requested || DEFAULT_ROOM;

  let rooms: ChatRoom[] = [];
  let history: ChatHistory | null = null;
  try {
    [rooms, history] = await Promise.all([
      apiFetch<ChatRoom[]>("/chat/rooms", { accessToken: token }),
      apiFetch<ChatHistory>(`/chat/rooms/${encodeURIComponent(slug)}`, { accessToken: token }),
    ]);
  } catch (error) {
    const upgrade = error instanceof ApiError && error.isUpgradeRequired;
    return (
      <Panel title="Chatrooms">
        <EmptyState
          title={upgrade ? "Chatrooms are not included on your plan" : "Chatrooms are unavailable"}
          description={
            upgrade
              ? "Upgrade to read and post in the community rooms."
              : "This is a problem on our side. The rooms will return as soon as the service does."
          }
          action={
            upgrade ? (
              <Link href="/pricing" className="text-small">
                See what each plan includes
              </Link>
            ) : undefined
          }
        />
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Chatrooms</h1>
        <p className="mt-1 text-small text-muted">
          Community discussion. Reading is free; posting is included from Plus.
        </p>
      </div>

      <nav className="flex flex-wrap gap-1" aria-label="Rooms">
        {rooms.map((room) => (
          <Link
            key={room.slug}
            href={`/chat?room=${room.slug}`}
            aria-current={room.slug === slug ? "page" : undefined}
            className={`h-7 rounded-[var(--radius-ui)] border px-2 text-small leading-7 transition-colors ${
              room.slug === slug
                ? "border-line bg-bg font-medium text-ink"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {room.name}
          </Link>
        ))}
      </nav>

      {history && <ChatRoomView key={slug} initial={history} />}
    </div>
  );
}
