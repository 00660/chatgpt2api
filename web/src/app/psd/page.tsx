"use client";

import { LoaderCircle } from "lucide-react";

import { PsdPanel } from "@/app/debug/components/psd-panel";
import { useAuthGuard } from "@/lib/use-auth-guard";

export default function PsdPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <PsdPanel />;
}
