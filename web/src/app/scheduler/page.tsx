"use client";

import { useEffect, useRef } from "react";
import { LoaderCircle } from "lucide-react";

import webConfig from "@/constants/common-env";
import type { RegisterConfig } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { getStoredAuthKey } from "@/store/auth";

import { useSettingsStore } from "../settings/store";
import { RegisterCard } from "../register/components/register-card";

function SchedulerDataController() {
  const didLoadRef = useRef(false);
  const loadRegister = useSettingsStore((state) => state.loadRegister);
  const setRegisterConfig = useSettingsStore((state) => state.setRegisterConfig);

  useEffect(() => {
    if (didLoadRef.current) return;
    didLoadRef.current = true;
    void loadRegister();
  }, [loadRegister]);

  useEffect(() => {
    let source: EventSource | null = null;
    let closed = false;
    void getStoredAuthKey().then((token) => {
      if (closed || !token) return;
      const baseUrl = webConfig.apiUrl.replace(/\/$/, "");
      source = new EventSource(`${baseUrl}/api/register/events?token=${encodeURIComponent(token)}`);
      source.onmessage = (event) => {
        setRegisterConfig(JSON.parse(event.data) as RegisterConfig);
      };
    });
    return () => {
      closed = true;
      source?.close();
    };
  }, [setRegisterConfig]);

  return null;
}

function SchedulerPageContent() {
  return (
    <>
      <SchedulerDataController />
      <section className="mb-2 flex flex-col gap-1 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">Scheduler</div>
          <h1 className="text-2xl font-semibold tracking-tight">IMAP调度台</h1>
        </div>
      </section>
      <section>
        <RegisterCard initialTab="scheduler" />
      </section>
    </>
  );
}

export default function SchedulerPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <SchedulerPageContent />;
}
