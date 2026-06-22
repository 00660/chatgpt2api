"use client";

import { LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { useAuthGuard } from "@/lib/use-auth-guard";

const links = [
  { href: "/chat", title: "对话" },
  { href: "/search", title: "搜索" },
  { href: "/ppt", title: "PPT生成" },
  { href: "/psd", title: "PSD生成" },
  { href: "/api-docs", title: "接口文档" },
];

export default function DebugPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[60vh] max-w-xl flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">调试入口已拆分</h1>
      <div className="flex flex-wrap justify-center gap-2">
        {links.map((item) => (
          <Button key={item.href} variant="outline" asChild>
            <Link to={item.href}>{item.title}</Link>
          </Button>
        ))}
      </div>
    </div>
  );
}
