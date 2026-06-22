"use client";

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Image as ImageIcon, KeyRound, LoaderCircle, MessageSquareText, ShieldCheck, Workflow } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { HeaderActions } from "@/components/header-actions";
import { login } from "@/lib/api";
import { useRedirectIfAuthenticated } from "@/lib/use-auth-guard";
import { getDefaultRouteForRole, setStoredAuthSession } from "@/store/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const [authKey, setAuthKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { isCheckingAuth } = useRedirectIfAuthenticated();

  const handleLogin = async () => {
    const normalizedAuthKey = authKey.trim();
    if (!normalizedAuthKey) {
      toast.error("请输入密钥");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await login(normalizedAuthKey);
      await setStoredAuthSession({
        key: normalizedAuthKey,
        role: data.role,
        subjectId: data.subject_id,
        name: data.name,
      });
      navigate(getDefaultRouteForRole(data.role), { replace: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : "登录失败";
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="grid h-dvh w-full place-items-center bg-stone-950">
        <LoaderCircle className="size-5 animate-spin text-white/70" />
      </div>
    );
  }

  return (
    <section className="relative h-dvh w-full overflow-hidden bg-[#f4f0e8] text-stone-950 dark:bg-[#090d11] dark:text-white">
      <div className="absolute inset-0 bg-[linear-gradient(126deg,_rgba(255,255,255,0.98)_0%,_rgba(239,235,227,0.92)_44%,_rgba(222,234,229,0.82)_100%)] dark:bg-[linear-gradient(126deg,_rgba(8,11,15,1)_0%,_rgba(18,18,17,0.98)_54%,_rgba(15,31,29,0.92)_100%)]" />
      <div className="absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(28,25,23,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(28,25,23,0.05)_1px,transparent_1px)] [background-size:56px_56px] dark:opacity-15 dark:[background-image:linear-gradient(rgba(255,255,255,0.1)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.1)_1px,transparent_1px)]" />
      <div className="absolute right-0 bottom-0 left-0 h-56 bg-[linear-gradient(0deg,_rgba(20,184,166,0.16),_transparent)] dark:bg-[linear-gradient(0deg,_rgba(20,184,166,0.12),_transparent)]" />
      <HeaderActions className="fixed top-4 right-4 z-20 rounded-lg border border-stone-950/10 bg-white/55 px-3 py-2 shadow-sm backdrop-blur-xl dark:border-white/10 dark:bg-white/10 sm:top-5 sm:right-5" />

      <div className="relative mx-auto grid h-full w-full max-w-6xl grid-cols-1 items-center gap-12 px-5 pt-16 sm:px-8 lg:grid-cols-[minmax(0,1fr)_410px] lg:px-10 lg:pt-0">
        <div className="hidden max-w-[570px] flex-col gap-10 lg:flex">
          <div className="space-y-5">
            <div className="inline-flex h-8 items-center gap-2 rounded-lg border border-stone-950/10 bg-white/45 px-3 text-xs font-medium text-stone-600 backdrop-blur dark:border-white/10 dark:bg-white/10 dark:text-stone-300">
              <span className="size-1.5 rounded-full bg-teal-500" />
              私有入口
            </div>
            <h1 className="text-[68px] font-semibold leading-[0.9] tracking-tight text-stone-950 dark:text-white">ChatGPT2API</h1>
            <p className="max-w-sm text-base leading-7 text-stone-600 dark:text-stone-300">对话、生图与接口转发的一体化管理后台。</p>
          </div>

          <div className="relative h-72 w-[520px]">
            <div className="absolute top-8 left-10 h-48 w-72 rotate-[-6deg] rounded-lg border border-stone-950/10 bg-white/52 shadow-[0_30px_90px_rgba(15,23,42,0.12)] backdrop-blur-xl dark:border-white/10 dark:bg-white/8" />
            <div className="absolute right-8 bottom-7 h-48 w-72 rotate-[5deg] rounded-lg border border-stone-950/10 bg-stone-950 shadow-[0_34px_100px_rgba(15,23,42,0.24)] dark:border-white/10" />
            <div className="absolute top-0 left-20 grid h-56 w-80 grid-cols-3 gap-3 rounded-lg border border-white/70 bg-white/78 p-4 shadow-[0_36px_110px_rgba(15,23,42,0.18)] backdrop-blur-2xl dark:border-white/10 dark:bg-stone-950/72">
              {[
                { Icon: MessageSquareText, active: true },
                { Icon: ImageIcon },
                { Icon: Workflow },
                { Icon: ShieldCheck },
                { Icon: KeyRound },
                { Icon: ArrowRight },
              ].map(({ Icon, active }, index) => (
                <div key={index} className={active ? "flex items-center justify-center rounded-lg bg-stone-950 text-white shadow-sm dark:bg-white dark:text-stone-950" : "flex items-center justify-center rounded-lg border border-stone-950/10 bg-stone-50/80 text-stone-500 dark:border-white/10 dark:bg-white/8 dark:text-stone-300"}>
                  <Icon className="size-5" />
                </div>
              ))}
              <div className="col-span-3 mt-1 grid grid-cols-[1fr_auto] items-end gap-3">
                <div className="space-y-2">
                  <div className="h-2 w-28 rounded bg-stone-900/80 dark:bg-white/80" />
                  <div className="h-2 w-40 rounded bg-stone-200 dark:bg-white/16" />
                </div>
                <div className="h-9 w-16 rounded-lg bg-teal-500" />
              </div>
            </div>
          </div>
        </div>

        <Card className="mx-auto w-full max-w-[410px] overflow-hidden rounded-lg border-white/70 bg-white/82 shadow-[0_34px_120px_rgba(15,23,42,0.16)] backdrop-blur-2xl dark:border-white/10 dark:bg-stone-950/76">
          <CardContent className="p-6 sm:p-8">
            <div className="mb-8 flex items-start justify-between gap-4">
              <div className="space-y-2">
                <div className="text-xs font-semibold text-teal-700 dark:text-teal-300">私有密钥</div>
                <h2 className="text-[28px] font-semibold tracking-tight text-stone-950 dark:text-white">登录</h2>
                <p className="text-sm leading-6 text-stone-500 dark:text-stone-400">解锁全部管理功能。</p>
              </div>
              <div className="flex size-11 items-center justify-center rounded-lg bg-stone-950 text-white dark:bg-white dark:text-stone-950">
                <ShieldCheck className="size-5" />
              </div>
            </div>

            <form
              className="space-y-5"
              onSubmit={(event) => {
                event.preventDefault();
                void handleLogin();
              }}
            >
              <div className="space-y-2">
                <label htmlFor="auth-key" className="block text-sm font-medium text-stone-700 dark:text-stone-200">
                  访问密钥
                </label>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-stone-400" />
                  <Input
                    id="auth-key"
                    type="password"
                    value={authKey}
                    onChange={(event) => setAuthKey(event.target.value)}
                    placeholder="粘贴管理员或用户密钥"
                    autoComplete="current-password"
                    className="h-12 rounded-lg border-stone-200/80 bg-white/80 pl-11 text-base shadow-none dark:border-white/10 dark:bg-white/10"
                  />
                </div>
              </div>

              <Button type="submit" className="h-12 w-full rounded-lg bg-stone-950 text-white hover:bg-stone-800 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200" disabled={isSubmitting}>
                {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : "进入控制台"}
                {!isSubmitting ? <ArrowRight className="size-4" /> : null}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
