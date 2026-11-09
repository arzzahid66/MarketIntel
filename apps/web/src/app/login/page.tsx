import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { Panel } from "@/components/ui/Panel";

export const metadata: Metadata = { title: "Log in" };

export default function LoginPage() {
  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4 py-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Log in</h1>
        <p className="mt-1 text-small text-muted">
          New here?{" "}
          <Link href="/signup">Create an account</Link> — the Big 7 dashboard and the
          full feed are free.
        </p>
      </div>
      <Panel className="p-4">
        <Suspense fallback={null}>
          <AuthForm mode="login" />
        </Suspense>
      </Panel>
    </div>
  );
}
