"use client";

/**
 * Login and signup share one form because they differ only in the endpoint and
 * one extra field. Both post to a Next route handler, never to FastAPI directly,
 * so the returned tokens land in httpOnly cookies instead of JS.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";

const MIN_PASSWORD_LENGTH = 10;

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isSignup = mode === "signup";

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (isSignup && password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          isSignup ? { email, password, display_name: displayName } : { email, password },
        ),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { message?: string } | null;
        setError(body?.message ?? "Something went wrong. Try again.");
        return;
      }

      // Replace, not push: the back button should not return to a form that
      // now redirects away.
      router.replace(next);
      router.refresh();
    } catch {
      setError("Could not reach the service. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}

      <Field
        label="Email"
        name="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="you@example.com"
      />

      {isSignup && (
        <Field
          label="Display name"
          name="display_name"
          type="text"
          autoComplete="name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="Optional"
        />
      )}

      <Field
        label="Password"
        name="password"
        type="password"
        autoComplete={isSignup ? "new-password" : "current-password"}
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        {...(isSignup ? { hint: `At least ${MIN_PASSWORD_LENGTH} characters.` } : {})}
      />

      <Button type="submit" disabled={submitting}>
        {submitting ? "Working…" : isSignup ? "Create account" : "Log in"}
      </Button>
    </form>
  );
}
