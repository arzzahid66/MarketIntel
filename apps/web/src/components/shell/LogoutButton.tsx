"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

export function LogoutButton() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    startTransition(() => {
      router.replace("/");
      router.refresh();
    });
  };

  return (
    <button
      type="button"
      onClick={logout}
      disabled={isPending}
      className="text-small text-muted hover:text-ink disabled:opacity-50"
    >
      Log out
    </button>
  );
}
