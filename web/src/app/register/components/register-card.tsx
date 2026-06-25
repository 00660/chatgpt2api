"use client";

import { useState } from "react";
import { LoaderCircle, Play, RotateCcw, Save, Square, Trash2, UserPlus, RefreshCcw, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

import { useSettingsStore } from "../../settings/store";

function statusClass(status: string) {
  if (status === "success") return "bg-emerald-50 text-emerald-700";
  if (status === "running" || status === "queued") return "bg-sky-50 text-sky-700";
  if (status === "failed") return "bg-rose-50 text-rose-600";
  return "bg-stone-100 text-stone-600";
}

export function RegisterCard() {
  const [queueText, setQueueText] = useState("");
  const [recoveryText, setRecoveryText] = useState("");
  const config = useSettingsStore((state) => state.registerConfig);
  const isLoading = useSettingsStore((state) => state.isLoadingRegister);
  const isSaving = useSettingsStore((state) => state.isSavingRegister);
  const setProxy = useSettingsStore((state) => state.setRegisterProxy);
  const setTotal = useSettingsStore((state) => state.setRegisterTotal);
  const setThreads = useSettingsStore((state) => state.setRegisterThreads);
  const setMode = useSettingsStore((state) => state.setRegisterMode);
  const setTargetQuota = useSettingsStore((state) => state.setRegisterTargetQuota);
  const setTargetAvailable = useSettingsStore((state) => state.setRegisterTargetAvailable);
  const setCheckInterval = useSettingsStore((state) => state.setRegisterCheckInterval);
  const setSchedulerField = useSettingsStore((state) => state.setRegisterSchedulerField);
  const setProxyMode = useSettingsStore((state) => state.setRegisterProxyMode);
  const setMimoField = useSettingsStore((state) => state.setRegisterMimoField);
  const importQueue = useSettingsStore((state) => state.importRegisterQueueText);
  const removeQueueItem = useSettingsStore((state) => state.removeRegisterQueueItem);
  const clearQueue = useSettingsStore((state) => state.clearRegisterQueueItems);
  const queueLoginRecovery = useSettingsStore((state) => state.queueLoginRecoveryText);
  const retryFailed = useSettingsStore((state) => state.retryFailedRegisterItems);
  const removeFailed = useSettingsStore((state) => state.removeFailedRegisterItem);
  const clearFailed = useSettingsStore((state) => state.clearFailedRegisterItems);
  const refreshProxy = useSettingsStore((state) => state.refreshRegisterProxyRuntime);
  const save = useSettingsStore((state) => state.saveRegister);
  const toggle = useSettingsStore((state) => state.toggleRegister);
  const reset = useSettingsStore((state) => state.resetRegister);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-stone-200 bg-white/80 p-10">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  if (!config) return null;

  const stats = config.stats || { success: 0, fail: 0, done: 0, running: 0, threads: config.threads };
  const logs = config.logs || [];
  const queueItems = config.queue_items || [];
  const failedItems = config.failed_items || [];
  const scheduler = config.scheduler || { fetch_otp_url: "", request_timeout: 8, wait_timeout: 120, wait_interval: 2 };
  const mimo = (config.mimo || config.mihomo || {}) as Record<string, unknown>;
  const proxyStatus = (config.proxy_status || {}) as Record<string, unknown>;
  const listenerLines = Array.isArray(proxyStatus.selected_proxy_speed_lines) ? proxyStatus.selected_proxy_speed_lines.map(String) : [];
  const selectedFailedIds = failedItems.filter((item) => item.status !== "running" && item.status !== "success").map((item) => item.id);

  return (
    <div className="grid h-[calc(100vh-132px)] min-h-[640px] items-stretch gap-0 overflow-hidden rounded-xl border border-stone-200 bg-white/70 xl:grid-cols-2">
      <section className="space-y-4 overflow-y-auto border-b border-stone-200 p-4 xl:border-r xl:border-b-0">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md bg-stone-100">
              <UserPlus className="size-5 text-stone-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">注册</h2>
            </div>
          </div>
          <Button className="h-9 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800" onClick={() => void save()} disabled={isSaving || config.enabled}>
            {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存配置
          </Button>
        </div>

        <Tabs defaultValue="queue" className="min-h-0">
          <TabsList className="grid h-auto w-full grid-cols-4 rounded-xl bg-stone-100 p-1">
            <TabsTrigger value="queue" className="h-9 rounded-lg">注册队列</TabsTrigger>
            <TabsTrigger value="scheduler" className="h-9 rounded-lg">调度台</TabsTrigger>
            <TabsTrigger value="recovery" className="h-9 rounded-lg">恢复登录</TabsTrigger>
            <TabsTrigger value="mimo" className="h-9 rounded-lg">mimo代理</TabsTrigger>
          </TabsList>

          <TabsContent value="queue" className="mt-4 space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm text-stone-700">注册模式</label>
                <Select value={config.mode || "total"} onValueChange={(value) => setMode(value as "total" | "quota" | "available")} disabled={config.enabled}>
                  <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="total">注册总数</SelectItem>
                    <SelectItem value="quota">号池剩余额度</SelectItem>
                    <SelectItem value="available">可用账号数量</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">注册总数</label>
                <Input value={String(config.total)} onChange={(event) => setTotal(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.mode !== "total"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">线程数</label>
                <Input value={String(config.threads)} onChange={(event) => setThreads(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">目标剩余额度</label>
                <Input value={String(config.target_quota || "")} onChange={(event) => setTargetQuota(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.mode !== "quota"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">目标可用账号</label>
                <Input value={String(config.target_available || "")} onChange={(event) => setTargetAvailable(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.mode !== "available"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">检查间隔（秒）</label>
                <Input value={String(config.check_interval || "")} onChange={(event) => setCheckInterval(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.mode === "total"} />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm text-stone-700">导入待注册邮箱</label>
              <Textarea value={queueText} onChange={(event) => setQueueText(event.target.value)} placeholder={"每行一个邮箱，格式：\nemail@example.com\nemail@example.com----password"} className="min-h-32 rounded-xl border-stone-200 bg-white font-mono text-xs" disabled={config.enabled} />
              <div className="flex flex-wrap gap-2">
                <Button className="h-9 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800" onClick={async () => { await importQueue(queueText); setQueueText(""); }} disabled={isSaving || config.enabled || !queueText.trim()}>
                  <Upload className="size-4" />
                  导入队列
                </Button>
                <Button variant="outline" className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700" onClick={() => void clearQueue("done")} disabled={isSaving || config.enabled}>
                  清理完成项
                </Button>
                <Button variant="outline" className="h-9 rounded-xl border-rose-200 bg-white px-3 text-rose-600 hover:bg-rose-50" onClick={() => void clearQueue("all")} disabled={isSaving || config.enabled}>
                  清空队列
                </Button>
              </div>
            </div>

            <div className="max-h-72 overflow-y-auto border border-stone-200 bg-white/70">
              {queueItems.length === 0 ? (
                <div className="p-4 text-sm text-stone-500">待注册队列为空</div>
              ) : (
                queueItems.map((item) => (
                  <div key={item.id} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-stone-100 px-3 py-2 last:border-b-0">
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs text-stone-800">{item.email}</div>
                      {item.last_error ? <div className="mt-1 truncate text-xs text-rose-600">{item.last_error}</div> : null}
                    </div>
                    <span className={`rounded-md px-2 py-1 text-xs ${statusClass(item.status)}`}>{item.status}</span>
                    <button type="button" className="rounded-lg p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500 disabled:opacity-50" onClick={() => void removeQueueItem(item.id)} disabled={config.enabled || item.status === "running"} title="删除">
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </TabsContent>

          <TabsContent value="scheduler" className="mt-4 space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm text-stone-700">取码接口</label>
                <Input value={scheduler.fetch_otp_url} onChange={(event) => setSchedulerField("fetch_otp_url", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">请求超时</label>
                <Input value={String(scheduler.request_timeout || "")} onChange={(event) => setSchedulerField("request_timeout", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">等待验证码超时</label>
                <Input value={String(scheduler.wait_timeout || "")} onChange={(event) => setSchedulerField("wait_timeout", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">轮询间隔</label>
                <Input value={String(scheduler.wait_interval || "")} onChange={(event) => setSchedulerField("wait_interval", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="recovery" className="mt-4 space-y-4">
            <div className="space-y-2">
              <label className="text-sm text-stone-700">补 login 邮箱</label>
              <Textarea value={recoveryText} onChange={(event) => setRecoveryText(event.target.value)} placeholder={"每行一个邮箱，格式：\nemail@example.com\nemail@example.com----password"} className="min-h-28 rounded-xl border-stone-200 bg-white font-mono text-xs" disabled={Boolean(config.failed_retry?.running)} />
              <div className="flex flex-wrap gap-2">
                <Button className="h-9 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800" onClick={async () => { await queueLoginRecovery(recoveryText); setRecoveryText(""); }} disabled={isSaving || Boolean(config.failed_retry?.running) || !recoveryText.trim()}>
                  <Play className="size-4" />
                  导入并补 login
                </Button>
                <Button variant="outline" className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700" onClick={() => void retryFailed(selectedFailedIds, "login")} disabled={isSaving || Boolean(config.failed_retry?.running) || selectedFailedIds.length === 0}>
                  补 login
                </Button>
                <Button variant="outline" className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700" onClick={() => void retryFailed(selectedFailedIds, "auto")} disabled={isSaving || Boolean(config.failed_retry?.running) || selectedFailedIds.length === 0}>
                  自动恢复
                </Button>
                <Button variant="outline" className="h-9 rounded-xl border-rose-200 bg-white px-3 text-rose-600 hover:bg-rose-50" onClick={() => void clearFailed()} disabled={isSaving || Boolean(config.failed_retry?.running)}>
                  清空记录
                </Button>
              </div>
            </div>

            <div className="max-h-80 overflow-y-auto border border-stone-200 bg-white/70">
              {failedItems.length === 0 ? (
                <div className="p-4 text-sm text-stone-500">恢复池为空</div>
              ) : (
                failedItems.map((item) => (
                  <div key={item.id} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 border-b border-stone-100 px-3 py-2 last:border-b-0">
                    <div className="min-w-0">
                      <div className="truncate font-mono text-xs text-stone-800">{item.email}</div>
                      {item.last_error ? <div className="mt-1 truncate text-xs text-rose-600">{item.last_error}</div> : null}
                    </div>
                    <span className="rounded-md bg-stone-100 px-2 py-1 text-xs text-stone-600">{item.mode}</span>
                    <span className={`rounded-md px-2 py-1 text-xs ${statusClass(item.status)}`}>{item.status}</span>
                    <button type="button" className="rounded-lg p-2 text-stone-400 transition hover:bg-rose-50 hover:text-rose-500 disabled:opacity-50" onClick={() => void removeFailed(item.id)} disabled={Boolean(config.failed_retry?.running) || item.status === "running"} title="删除">
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </TabsContent>

          <TabsContent value="mimo" className="mt-4 space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm text-stone-700">代理模式</label>
                <Select value={config.proxy_mode || "direct"} onValueChange={(value) => setProxyMode(value as "direct" | "manual" | "mihomo")} disabled={config.enabled}>
                  <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="direct">直连</SelectItem>
                    <SelectItem value="manual">手动代理</SelectItem>
                    <SelectItem value="mihomo">mimo</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm text-stone-700">手动代理</label>
                <Input value={config.proxy} onChange={(event) => setProxy(event.target.value)} placeholder="http://127.0.0.1:7890" className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "manual"} />
              </div>
              <div className="space-y-2 md:col-span-3">
                <label className="text-sm text-stone-700">订阅地址</label>
                <Input value={String(mimo.subscription_url || "")} onChange={(event) => setMimoField("subscription_url", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">API 端口</label>
                <Input value={String(mimo.api_port || 19080)} onChange={(event) => setMimoField("api_port", Number(event.target.value) || 19080)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">监听起始端口</label>
                <Input value={String(mimo.listener_port_base || 19081)} onChange={(event) => setMimoField("listener_port_base", Number(event.target.value) || 19081)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">订阅刷新秒数</label>
                <Input value={String(mimo.provider_interval || 3600)} onChange={(event) => setMimoField("provider_interval", Number(event.target.value) || 3600)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">包含节点</label>
                <Input value={String(mimo.include_pattern || "")} onChange={(event) => setMimoField("include_pattern", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">排除节点</label>
                <Input value={String(mimo.exclude_pattern || "")} onChange={(event) => setMimoField("exclude_pattern", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">健康检查 URL</label>
                <Input value={String(mimo.healthcheck_url || "https://cp.cloudflare.com/generate_204")} onChange={(event) => setMimoField("healthcheck_url", event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" disabled={config.enabled || config.proxy_mode !== "mihomo"} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={proxyStatus.running ? "success" : "secondary"} className="rounded-md">
                {String(proxyStatus.status_label || proxyStatus.status || "未启动")}
              </Badge>
              <span className="text-xs text-stone-500">{String(proxyStatus.message || "")}</span>
              <Button variant="outline" className="h-8 rounded-lg border-stone-200 bg-white px-3 text-xs text-stone-700" onClick={() => void refreshProxy()} disabled={isSaving || config.proxy_mode !== "mihomo"}>
                <RefreshCcw className="size-3.5" />
                刷新
              </Button>
            </div>
            <div className="space-y-1 border border-stone-200 bg-white/70 p-3 font-mono text-xs text-stone-700">
              <div>监听端口：{String(proxyStatus.listener_ports_text || "-")}</div>
              <div>出口 IP：{String(proxyStatus.selected_proxy_public_ip_text || "-")}</div>
              {listenerLines.map((line) => <div key={line}>{line}</div>)}
            </div>
          </TabsContent>
        </Tabs>
      </section>

      <section className="flex min-h-0 flex-col p-4">
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">运行结果</h2>
            </div>
            <Badge variant={config.enabled ? "success" : "secondary"} className="rounded-md">
              {config.enabled ? "运行中" : "已停止"}
            </Badge>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {[
              ["成功 / 成功率", `${stats.success} / ${stats.success_rate || 0}%`],
              ["失败", stats.fail],
              ["完成", stats.done],
              ["运行 / 线程", `${stats.running} / ${stats.threads}`],
              ["运行时间", `${stats.elapsed_seconds || 0}s`],
              ["平均注册单个", `${stats.avg_seconds || 0}s`],
              ["当前额度", stats.current_quota || 0],
              ["正常账号", stats.current_available || 0],
            ].map(([label, value]) => (
              <div key={label} className="border border-stone-200 bg-white/70 px-3 py-2">
                <div className="text-xs text-stone-400">{label}</div>
                <div className="mt-1 text-base font-semibold text-stone-800">{value}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Button className="h-10 rounded-xl bg-stone-950 px-3 text-white hover:bg-stone-800" onClick={() => void toggle()} disabled={isSaving}>
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : config.enabled ? <Square className="size-4" /> : <Play className="size-4" />}
              {config.enabled ? "停止" : "启动"}
            </Button>
            <Button variant="outline" className="h-10 rounded-xl border-stone-200 bg-white px-3 text-stone-700" onClick={() => void reset()} disabled={isSaving || config.enabled}>
              <RotateCcw className="size-4" />
              重置
            </Button>
            <Button variant="outline" className="h-10 rounded-xl border-stone-200 bg-white px-3 text-stone-700" onClick={() => void save()} disabled={isSaving || config.enabled}>
              <Save className="size-4" />
              保存
            </Button>
          </div>
        </div>

        <div className="mt-4 flex min-h-0 flex-1 flex-col space-y-3 overflow-hidden border-t border-stone-200 pt-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-stone-900">实时日志</h3>
            </div>
            <Badge variant="secondary" className="rounded-md">
              {logs.length}
            </Badge>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto border border-stone-200 bg-white/70 p-3 font-mono text-xs leading-6">
            {logs.length === 0 ? (
              <div className="text-stone-500">暂无日志</div>
            ) : (
              logs.slice().reverse().map((item, index) => (
                <div key={`${item.time}-${index}`} className={item.level === "red" ? "text-rose-600" : item.level === "green" ? "text-emerald-700" : item.level === "yellow" ? "text-amber-700" : "text-stone-700"}>
                  <span className="text-stone-400">{new Date(item.time).toLocaleTimeString()}</span>
                  <span className="pl-2">{item.text}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
