"use client";

import { LoaderCircle } from "lucide-react";

import { ChatPanel } from "@/app/debug/components/chat-panel";
import { useAuthGuard } from "@/lib/use-auth-guard";

export default function ChatPage() {
  const { isCheckingAuth, session } = useAuthGuard();

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <ChatPanel />;
}
