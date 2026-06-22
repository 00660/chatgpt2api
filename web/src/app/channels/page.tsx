"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import { useAuthGuard } from "@/lib/use-auth-guard";

import { CodexChannelsCard } from "./components/codex-channels-card";
import { useSettingsStore } from "../settings/store";

function ChannelsDataController() {
  const didLoadRef = useRef(false);
  const loadConfig = useSettingsStore((state) => state.loadConfig);

  useEffect(() => {
    if (didLoadRef.current) return;
    didLoadRef.current = true;
    void loadConfig();
  }, [loadConfig]);

  return null;
}

function ChannelsPageContent() {
  return (
    <>
      <ChannelsDataController />
      <section className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Channels</div>
          <h1 className="text-2xl font-semibold tracking-tight">渠道设置</h1>
        </div>
      </section>
      <CodexChannelsCard />
    </>
  );
}

export default function ChannelsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <ChannelsPageContent />;
}
