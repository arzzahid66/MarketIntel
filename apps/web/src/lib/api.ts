/**
 * Server-side HTTP client for the FastAPI service.
 *
 * Architecture rule: the browser never talks to a third-party data provider,
 * and it never holds an access token either - tokens live in httpOnly cookies
 * and only this module (running on the server) attaches them.
 */

import type { ApiErrorBody } from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, message: string, body: ApiErrorBody | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  /** 402 is the upgrade signal, not a failure. See require_feature in the API. */
  get isUpgradeRequired(): boolean {
    return this.status === 402;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  accessToken?: string;
  /** Seconds. Omit for no caching, which is the right default for market data. */
  revalidate?: number;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, accessToken, revalidate, headers, ...rest } = options;

  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(revalidate !== undefined ? { next: { revalidate } } : { cache: "no-store" }),
  });

  if (!response.ok) {
    let parsed: ApiErrorBody | null = null;
    try {
      parsed = (await response.json()) as ApiErrorBody;
    } catch {
      // Non-JSON error body (a proxy 502, say). The status is still meaningful.
    }
    throw new ApiError(
      response.status,
      typeof parsed?.error === "string" ? parsed.error : `Request failed (${response.status})`,
      parsed,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/**
 * For surfaces that must render even when the API is down.
 *
 * Phase 2 exit criteria require a provider outage to degrade to a visible
 * "data delayed" state instead of an error page. The same principle applies
 * from Phase 1: the shell renders, the data area says what is wrong.
 */
export async function apiFetchOrNull<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T | null> {
  try {
    return await apiFetch<T>(path, options);
  } catch {
    return null;
  }
}
