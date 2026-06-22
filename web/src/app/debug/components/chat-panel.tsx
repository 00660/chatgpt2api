"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, ExternalLink, Globe2, LoaderCircle, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { fetchModels } from "@/lib/api";
import { httpRequest } from "@/lib/request";
import { cn } from "@/lib/utils";

import type { ChatCompletionResponse, ChatMessage, SearchResult } from "./types";

type Mode = "chat" | "search";
type ChatTurn = { mode: "chat"; role: "user" | "assistant"; content: string };
type SearchTurn = { mode: "search"; prompt: string; result?: SearchResult; error?: string; elapsedMs?: number };
type Turn = ChatTurn | SearchTurn;

const normalizeMarkdown = (text: string) =>
  text
    .replace(/\ue200url\ue202([^\ue202\ue201]*)\ue202([^\ue201]*)\ue201/g, "[$1]($2)")
    .replace(/\ue200cite\ue202[^\ue201]*\ue201/g, "")
    .replace(/\ue200[^\ue201]*\ue201/g, "")
    .replace(/\ue200[^\ue201]*$/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

const cleanUrl = (url: string) => url.replace(/[\ue200-\ue202].*$/g, "").trim();
const sourceKind = (url: string) => {
  try {
    return new URL(url).hostname.includes("github.com") ? "github" : "web";
  } catch {
    return "web";
  }
};

function MarkdownResult({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ className, ...props }) => <a className={cn("font-medium text-blue-700 underline decoration-blue-300 underline-offset-4 hover:text-blue-900 dark:text-blue-300 dark:decoration-blue-700", className)} target="_blank" rel="noreferrer" {...props} />,
        h1: ({ className, ...props }) => <h1 className={cn("mt-8 mb-4 text-2xl font-semibold tracking-tight text-stone-950 first:mt-0 dark:text-stone-50", className)} {...props} />,
        h2: ({ className, ...props }) => <h2 className={cn("mt-8 mb-4 border-b border-stone-200 pb-2 text-xl font-semibold tracking-tight text-stone-950 first:mt-0 dark:border-white/10 dark:text-stone-50", className)} {...props} />,
        h3: ({ className, ...props }) => <h3 className={cn("mt-6 mb-3 text-lg font-semibold text-stone-900 dark:text-stone-100", className)} {...props} />,
        p: ({ className, ...props }) => <p className={cn("my-4 leading-8 text-stone-800 dark:text-stone-200", className)} {...props} />,
        ul: ({ className, ...props }) => <ul className={cn("my-4 list-disc space-y-2 pl-6 leading-7 text-stone-800 dark:text-stone-200", className)} {...props} />,
        ol: ({ className, ...props }) => <ol className={cn("my-4 list-decimal space-y-2 pl-6 leading-7 text-stone-800 dark:text-stone-200", className)} {...props} />,
        blockquote: ({ className, ...props }) => <blockquote className={cn("my-5 border-l-4 border-stone-300 bg-white/70 py-3 pr-4 pl-5 text-stone-700 dark:border-white/20 dark:bg-white/[0.04] dark:text-stone-300", className)} {...props} />,
        code: ({ className, ...props }) => <code className={cn("rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[0.9em] text-stone-800 dark:bg-white/10 dark:text-stone-100", className)} {...props} />,
        pre: ({ className, ...props }) => <pre className={cn("my-5 overflow-x-auto rounded-xl border border-stone-200 bg-stone-950 p-4 text-sm text-stone-50 dark:border-white/10", className)} {...props} />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function SearchResultView({ turn }: { turn: SearchTurn }) {
  const result = turn.result;
  return (
    <div className="mx-auto w-full max-w-5xl space-y-5">
      <div className="flex justify-end">
        <div className="max-w-[86%] rounded-3xl bg-stone-950 px-5 py-3 text-[15px] leading-7 whitespace-pre-wrap text-white dark:bg-white dark:text-stone-950">{turn.prompt}</div>
      </div>
      {turn.error ? <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-300">{turn.error}</div> : null}
      {result ? (
        <article className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0">
            <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-stone-500 dark:text-stone-400">
              <span className="rounded-full border border-stone-200 bg-white px-3 py-1 dark:border-white/10 dark:bg-white/[0.03]">{result.status || "done"}</span>
              <span className="rounded-full border border-stone-200 bg-white px-3 py-1 dark:border-white/10 dark:bg-white/[0.03]">{((turn.elapsedMs || 0) / 1000).toFixed(2)}s</span>
              <span className="rounded-full border border-stone-200 bg-white px-3 py-1 dark:border-white/10 dark:bg-white/[0.03]">{result.sources?.length || 0} sources</span>
            </div>
            <div className="text-[15px]">
              <MarkdownResult content={normalizeMarkdown(result.answer || "")} />
            </div>
          </div>
          {result.sources?.length ? (
            <aside className="lg:sticky lg:top-24 lg:self-start">
              <div className="mb-3 text-sm font-semibold text-stone-900 dark:text-stone-100">来源</div>
              <div className="divide-y divide-stone-200 dark:divide-white/10">
                {result.sources.map((source, index) => {
                  const url = cleanUrl(source.url || "");
                  return (
                    <a key={`${url || index}`} href={url} target="_blank" rel="noreferrer" className="flex gap-3 py-3 text-xs transition hover:text-stone-950 dark:hover:text-stone-50">
                      <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center text-stone-600 dark:text-stone-300">
                        {sourceKind(url) === "github" ? <img src="/github.svg" alt="" aria-hidden="true" className="size-3.5 dark:invert" /> : <Globe2 className="size-3.5" />}
                      </span>
                      <span className="min-w-0">
                        <span className="line-clamp-2 font-medium leading-5 text-stone-800 dark:text-stone-200">{source.title || url || "source"}</span>
                        <span className="mt-1 flex items-center gap-1 truncate text-stone-500 dark:text-stone-400">
                          <ExternalLink className="size-3 shrink-0" />
                          {url}
                        </span>
                      </span>
                    </a>
                  );
                })}
              </div>
            </aside>
          ) : null}
        </article>
      ) : null}
    </div>
  );
}

export function ChatPanel() {
  const [mode, setMode] = useState<Mode>("chat");
  const [model, setModel] = useState("auto");
  const [models, setModels] = useState<string[]>(["auto"]);
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");
  const [error, setError] = useState("");
  const viewportRef = useRef<HTMLDivElement>(null);
  const chatMessages = useMemo<ChatMessage[]>(() => turns.flatMap((turn) => turn.mode === "chat" ? [{ role: turn.role, content: turn.content }] : []), [turns]);

  useEffect(() => {
    let active = true;
    void fetchModels().then((data) => {
      const ids = Array.from(new Set(["auto", ...(data.data || []).map((item) => item.id).filter(Boolean)]));
      if (active) {
        setModels(ids);
        setModel((current) => ids.includes(current) ? current : ids[0] || "auto");
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

  const submit = async () => {
    const content = input.trim();
    if (!content || loading) return;
    setInput("");
    setLoading(true);
    setError("");

    if (mode === "search") {
      const start = Date.now();
      setLoadingText("搜索中...");
      const index = turns.length;
      setTurns((current) => [...current, { mode: "search", prompt: content }]);
      try {
        const result = await httpRequest<SearchResult>("/v1/search", { method: "POST", body: { prompt: content } });
        setTurns((current) => current.map((turn, itemIndex) => itemIndex === index ? { mode: "search", prompt: content, result, elapsedMs: Date.now() - start } : turn));
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setTurns((current) => current.map((turn, itemIndex) => itemIndex === index ? { mode: "search", prompt: content, error: message, elapsedMs: Date.now() - start } : turn));
      } finally {
        setLoading(false);
        setLoadingText("");
      }
      return;
    }

    const nextMessages: ChatMessage[] = [...chatMessages, { role: "user", content }];
    setLoadingText("正在回复...");
    setTurns((current) => [...current, { mode: "chat", role: "user", content }]);
    try {
      const result = await httpRequest<ChatCompletionResponse>("/v1/chat/completions", { method: "POST", body: { model, messages: nextMessages } });
      setTurns((current) => [...current, { mode: "chat", role: "assistant", content: String(result.choices?.[0]?.message?.content || "") }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
      setLoadingText("");
    }
  };

  return (
    <section className="mx-auto flex h-[calc(100dvh-6.5rem)] min-h-0 w-full max-w-6xl flex-col overflow-hidden px-1 pb-3 sm:h-[calc(100dvh-5.25rem)] sm:px-4 sm:pb-5">
      <div ref={viewportRef} className="hide-scrollbar min-h-0 flex-1 overflow-y-auto px-1 py-6 sm:px-5">
        {turns.length ? (
          <div className="space-y-8">
            {turns.map((turn, index) => turn.mode === "search" ? (
              <SearchResultView key={`search-${index}`} turn={turn} />
            ) : (
              <div key={`chat-${index}`} className={cn("mx-auto flex max-w-3xl", turn.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cn(
                  "max-w-[86%] whitespace-pre-wrap text-[15px] leading-7",
                  turn.role === "user"
                    ? "rounded-3xl bg-stone-950 px-5 py-3 text-white dark:bg-white dark:text-stone-950"
                    : "text-stone-800 dark:text-stone-100",
                )}>
                  {turn.content}
                </div>
              </div>
            ))}
            {loading ? (
              <div className="mx-auto flex max-w-3xl items-center gap-2 text-sm text-stone-500">
                <LoaderCircle className="size-4 animate-spin" />
                {loadingText}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-center text-2xl font-semibold tracking-tight text-stone-900 dark:text-stone-50">
            {mode === "search" ? "想搜索什么？" : "有什么可以帮忙的？"}
          </div>
        )}
      </div>

      <div className="mx-auto w-full max-w-3xl">
        {error ? <div className="mb-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-300">{error}</div> : null}
        <div className="overflow-hidden rounded-[28px] border border-stone-200 bg-white shadow-[0_18px_70px_-45px_rgba(15,23,42,0.55)] dark:border-white/10 dark:bg-stone-950/90">
          <Textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={mode === "search" ? "输入要搜索的问题" : "给 ChatGPT2API 发送消息"}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            className="min-h-[88px] resize-none border-0 bg-transparent px-5 pt-5 text-[15px] leading-7 shadow-none focus-visible:ring-0 dark:text-stone-100"
          />
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-stone-100 px-4 py-3 dark:border-white/10">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger className="h-9 w-40 rounded-full border-stone-200 bg-stone-50 px-4 font-mono text-xs shadow-none dark:border-white/10 dark:bg-white/[0.04] sm:w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
                </SelectContent>
              </Select>
              <div className="flex rounded-full bg-stone-100 p-1 dark:bg-white/10">
                {(["chat", "search"] as const).map((item) => (
                  <button key={item} type="button" onClick={() => setMode(item)} className={cn("h-8 rounded-full px-3 text-sm font-medium transition", mode === item ? "bg-white text-stone-950 shadow-sm dark:bg-stone-900 dark:text-stone-50" : "text-stone-500 hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100")}>
                    {item === "chat" ? "对话" : "搜索"}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="button" variant="outline" size="icon" className="size-9 rounded-full border-stone-200 bg-white" onClick={() => { setTurns([]); setError(""); }} title="清空对话">
                <RotateCcw className="size-4" />
              </Button>
              <button type="button" onClick={() => void submit()} disabled={loading || !input.trim()} className="inline-flex size-9 items-center justify-center rounded-full bg-stone-950 text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-300 dark:bg-white dark:text-stone-950 dark:hover:bg-stone-200">
                {loading ? <LoaderCircle className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
