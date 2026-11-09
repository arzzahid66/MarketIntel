import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/AuthForm";
import { Panel } from "@/components/ui/Panel";

export const metadata: Metadata = { title: "Sign up" };

export default function SignupPage() {
  return (
    <div className="mx-auto flex max-w-sm flex-col gap-4 py-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Create an account</h1>
        <p className="mt-1 text-small text-muted">
          Already have one? <Link href="/login">Log in</Link>
        </p>
      </div>
      <Panel className="p-4">
        <Suspense fallback={null}>
          <AuthForm mode="signup" />
        </Suspense>
      </Panel>
      <p className="text-small text-muted">
        By signing up you agree to the <Link href="/legal/terms">Terms</Link> and{" "}
        <Link href="/legal/privacy">Privacy Policy</Link>.
      </p>
    </div>
  );
}
