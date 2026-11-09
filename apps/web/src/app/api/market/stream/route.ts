/**
 * Server-sent events pass-through.
 *
 * EventSource cannot set an Authorization header, and the access token lives
 * in an httpOnly cookie the browser's JS cannot read. So the browser opens the
 * stream here, same-origin, and this route opens the upstream FastAPI stream
 * with the token attached. Bytes are piped through untouched.
 *
 * `request.signal` aborts the upstream fetch when the browser disconnects, so a
 * closed tab does not leave a stream open against the API.
 */

import { API_URL } from "@/lib/api";
import { getAccessToken } from "@/lib/session";

export async function GET(request: Request) {
  const token = await getAccessToken();

  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/market/stream`, {
      cache: "no-store",
      signal: request.signal,
      headers: {
        Accept: "text/event-stream",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch {
    return new Response("upstream unavailable", { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    return new Response("upstream unavailable", { status: 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      // Stops reverse proxies (nginx and friends) buffering the stream.
      "X-Accel-Buffering": "no",
    },
  });
}
