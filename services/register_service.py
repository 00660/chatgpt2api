from __future__ import annotations

import json
import re
import secrets
import string
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.account_service import account_service
from services.config import DATA_DIR
from services.register import mail_provider, openai_register
from services.register_mihomo_service import (
    ensure_register_proxy_runtime_ready,
    get_register_proxy_status,
    normalize_register_runtime_config,
    refresh_register_proxy_runtime,
    stop_register_proxy_runtime,
)


REGISTER_FILE = DATA_DIR / "register.json"
REGISTER_QUEUE_FILE = DATA_DIR / "register_email_queue.json"
FAILED_REGISTER_FILE = DATA_DIR / "register_failed.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    value = list(
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(chars) for _ in range(max(0, length - 4)))
    )
    secrets.SystemRandom().shuffle(value)
    return "".join(value)


def _default_scheduler() -> dict:
    return {
        "fetch_otp_url": "",
        "request_timeout": 8,
        "wait_timeout": 120,
        "wait_interval": 2,
    }


def _default_config() -> dict:
    return {
        **openai_register.config,
        "mail": {
            "request_timeout": 30,
            "wait_timeout": 30,
            "wait_interval": 2,
            "providers": [],
        },
        "scheduler": _default_scheduler(),
        "proxy_mode": "direct",
        "mihomo": {},
        "mimo": {},
        "mode": "total",
        "target_quota": 100,
        "target_available": 10,
        "check_interval": 5,
        "enabled": False,
        "stats": {
            "success": 0,
            "fail": 0,
            "done": 0,
            "running": 0,
            "threads": int(openai_register.config.get("threads") or 3),
            "elapsed_seconds": 0,
            "avg_seconds": 0,
            "success_rate": 0,
            "current_quota": 0,
            "current_available": 0,
        },
    }


def _safe_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _normalize_scheduler(value: Any) -> dict:
    source = value if isinstance(value, dict) else {}
    default = _default_scheduler()
    return {
        "fetch_otp_url": "",
        "request_timeout": _safe_int(source.get("request_timeout"), default["request_timeout"], 1),
        "wait_timeout": _safe_int(source.get("wait_timeout"), default["wait_timeout"], 1),
        "wait_interval": _safe_int(source.get("wait_interval"), default["wait_interval"], 1),
    }


def _normalize(raw: dict) -> dict:
    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if k not in {"stats", "logs", "queue_items", "failed_items", "failed_retry", "proxy_status"}})
    if isinstance(cfg.get("mimo"), dict) and not isinstance(cfg.get("mihomo"), dict):
        cfg["mihomo"] = dict(cfg["mimo"])
    if isinstance(cfg.get("mihomo"), dict):
        cfg["mimo"] = dict(cfg["mihomo"])
    cfg = normalize_register_runtime_config(cfg)
    cfg["scheduler"] = _normalize_scheduler(cfg.get("scheduler"))
    cfg["total"] = _safe_int(cfg.get("total"), 1, 1)
    cfg["threads"] = _safe_int(cfg.get("threads"), 1, 1)
    cfg["mode"] = str(cfg.get("mode") or "total").strip() if str(cfg.get("mode") or "total").strip() in {"total", "quota", "available"} else "total"
    cfg["target_quota"] = _safe_int(cfg.get("target_quota"), 1, 1)
    cfg["target_available"] = _safe_int(cfg.get("target_available"), 1, 1)
    cfg["check_interval"] = _safe_int(cfg.get("check_interval"), 5, 1)
    cfg["proxy"] = str(cfg.get("proxy") or "").strip()
    cfg["enabled"] = bool(cfg.get("enabled"))
    stats = {
        **_default_config()["stats"],
        **(raw.get("stats") if isinstance(raw.get("stats"), dict) else {}),
        "threads": cfg["threads"],
    }
    cfg["stats"] = stats
    return cfg


def _default_failed_retry_state() -> dict:
    return {
        "running": False,
        "total": 0,
        "queued": 0,
        "success": 0,
        "fail": 0,
        "mode": "",
        "label": "",
        "message": "",
    }


def _read_json_list(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _split_email_line(line: str) -> tuple[str, str]:
    text = str(line or "").strip()
    if not text or text.startswith("#"):
        return "", ""
    if "----" in text:
        parts = [part.strip() for part in text.split("----")]
    elif "|" in text:
        parts = [part.strip() for part in text.split("|")]
    elif "," in text:
        parts = [part.strip() for part in text.split(",")]
    elif "\t" in text:
        parts = [part.strip() for part in text.split("\t")]
    elif text.count(":") == 1 and "@" in text.split(":", 1)[0]:
        parts = [part.strip() for part in text.split(":", 1)]
    else:
        parts = [part.strip() for part in re.split(r"\s+", text, maxsplit=1)]
    email = str(parts[0] if parts else "").strip().lower()
    password = str(parts[1] if len(parts) > 1 else "").strip()
    return email, password


def _parse_email_text(text: str, *, default_mode: str = "register") -> list[dict]:
    now = _now()
    items: list[dict] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        email, password = _split_email_line(line)
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        mode = default_mode if default_mode in {"auto", "register", "login"} else "register"
        items.append(
            {
                "id": uuid.uuid4().hex,
                "email": email,
                "password": password or _random_password(),
                "mode": mode,
                "status": "pending" if mode == "register" else "queued",
                "retry_count": 0,
                "last_error": "",
                "created_at": now,
                "updated_at": now,
            }
        )
    return items


class RegisterService:
    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock = threading.RLock()
        self._runner: threading.Thread | None = None
        self._retry_runner: threading.Thread | None = None
        self._logs: list[dict] = []
        self._queue_items = self._load_queue()
        self._failed_items = self._load_failed()
        self._failed_retry_state = _default_failed_retry_state()
        openai_register.register_log_sink = self._append_log
        self._config = self._load()
        self._sync_openai_config()
        if self._config["enabled"]:
            self.start()

    def _load(self) -> dict:
        try:
            return _normalize(json.loads(self._store_file.read_text(encoding="utf-8")))
        except Exception:
            return _normalize({})

    def _load_queue(self) -> list[dict]:
        return [self._normalize_queue_item(item) for item in _read_json_list(REGISTER_QUEUE_FILE)]

    def _load_failed(self) -> list[dict]:
        return [self._normalize_failed_item(item) for item in _read_json_list(FAILED_REGISTER_FILE)]

    def _save(self) -> None:
        _write_json(self._store_file, self._config)

    def _save_queue(self) -> None:
        _write_json(REGISTER_QUEUE_FILE, self._queue_items)

    def _save_failed(self) -> None:
        _write_json(FAILED_REGISTER_FILE, self._failed_items)

    def _sync_openai_config(self) -> None:
        keys = ("mail", "scheduler", "proxy", "proxy_mode", "mihomo", "mimo", "total", "threads")
        openai_register.config.update({k: self._config[k] for k in keys if k in self._config})
        openai_register.config.update(normalize_register_runtime_config(openai_register.config))

    def _normalize_queue_item(self, item: dict) -> dict:
        now = _now()
        email = str(item.get("email") or item.get("address") or "").strip().lower()
        status = str(item.get("status") or "pending").strip().lower()
        if status not in {"pending", "running", "success", "failed"}:
            status = "pending"
        return {
            "id": str(item.get("id") or uuid.uuid4().hex),
            "email": email,
            "password": str(item.get("password") or "").strip(),
            "status": status,
            "retry_count": _safe_int(item.get("retry_count"), 0, 0),
            "last_error": str(item.get("last_error") or item.get("error") or "").strip(),
            "created_at": str(item.get("created_at") or now),
            "updated_at": str(item.get("updated_at") or now),
        }

    def _normalize_failed_item(self, item: dict) -> dict:
        now = _now()
        email = str(item.get("email") or item.get("address") or "").strip().lower()
        mode = str(item.get("mode") or "auto").strip().lower()
        if mode not in {"auto", "register", "login"}:
            mode = "auto"
        status = str(item.get("status") or "failed").strip().lower()
        if status not in {"queued", "running", "success", "failed"}:
            status = "failed"
        return {
            "id": str(item.get("id") or uuid.uuid4().hex),
            "email": email,
            "password": str(item.get("password") or "").strip(),
            "mode": mode,
            "status": status,
            "retry_count": _safe_int(item.get("retry_count"), 0, 0),
            "last_error": str(item.get("last_error") or item.get("error") or "").strip(),
            "source": str(item.get("source") or "register").strip() or "register",
            "created_at": str(item.get("created_at") or now),
            "updated_at": str(item.get("updated_at") or now),
        }

    def get(self) -> dict:
        with self._lock:
            snapshot = json.loads(
                json.dumps(
                    {
                        **self._config,
                        "mimo": self._config.get("mihomo") or {},
                        "queue_items": self._queue_items,
                        "failed_items": self._failed_items,
                        "failed_retry": self._failed_retry_state,
                        "logs": self._logs[-300:],
                    },
                    ensure_ascii=False,
                )
            )
        snapshot["proxy_status"] = get_register_proxy_status(self._config)
        snapshot["imap_dispatch"] = mail_provider.imap_dispatch_snapshot(self._config.get("mail") or {})
        return snapshot

    def update(self, updates: dict) -> dict:
        with self._lock:
            normalized_updates = dict(updates or {})
            if isinstance(normalized_updates.get("mimo"), dict):
                normalized_updates["mihomo"] = normalized_updates["mimo"]
            self._config = _normalize({**self._config, **normalized_updates})
            self._sync_openai_config()
            self._save()
            return self.get()

    def import_queue(self, text: str) -> dict:
        imported = _parse_email_text(text, default_mode="register")
        if not imported:
            raise RuntimeError("没有解析到可导入邮箱")
        with self._lock:
            by_email = {str(item.get("email") or "").strip().lower(): item for item in self._queue_items}
            for item in imported:
                current = by_email.get(item["email"])
                if current:
                    current.update(
                        {
                            "password": item["password"] or current.get("password") or _random_password(),
                            "status": "pending",
                            "last_error": "",
                            "updated_at": _now(),
                        }
                    )
                else:
                    self._queue_items.append(item)
                    by_email[item["email"]] = item
            self._save_queue()
            self._append_log(f"已导入 {len(imported)} 个待注册邮箱", "yellow")
            return self.get()

    def remove_queue(self, ids: list[str]) -> dict:
        normalized_ids = {str(item).strip() for item in ids if str(item).strip()}
        if not normalized_ids:
            raise RuntimeError("缺少要删除的队列 ID")
        with self._lock:
            if self._config.get("enabled"):
                raise RuntimeError("注册任务运行中，暂不能删除队列")
            before = len(self._queue_items)
            self._queue_items = [item for item in self._queue_items if str(item.get("id") or "") not in normalized_ids]
            removed = before - len(self._queue_items)
            self._save_queue()
            self._append_log(f"已删除 {removed} 个待注册邮箱", "yellow")
            return self.get()

    def clear_queue(self, scope: str = "all") -> dict:
        scope = str(scope or "all").strip().lower()
        with self._lock:
            if self._config.get("enabled"):
                raise RuntimeError("注册任务运行中，暂不能清空队列")
            before = len(self._queue_items)
            if scope == "done":
                self._queue_items = [item for item in self._queue_items if item.get("status") not in {"success", "failed"}]
            else:
                self._queue_items = []
            self._save_queue()
            self._append_log(f"已清空 {before - len(self._queue_items)} 个队列邮箱", "yellow")
            return self.get()

    def start(self) -> dict:
        with self._lock:
            if self._runner and self._runner.is_alive():
                self._config["enabled"] = True
                self._save()
                return self.get()
            self._config["enabled"] = True
            self._logs = []
            metrics = self._pool_metrics()
            self._config["stats"] = {
                "job_id": uuid.uuid4().hex,
                "success": 0,
                "fail": 0,
                "done": 0,
                "running": 0,
                "threads": self._config["threads"],
                **metrics,
                "started_at": _now(),
                "updated_at": _now(),
            }
            self._sync_openai_config()
            with openai_register.stats_lock:
                openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": time.time()})
            self._save()
            self._runner = threading.Thread(target=self._run, daemon=True, name="openai-register")
            self._runner.start()
            self._append_log(f"注册任务启动，模式={self._config['mode']}，线程数={self._config['threads']}", "yellow")
            return self.get()

    def stop(self) -> dict:
        with self._lock:
            self._config["enabled"] = False
            self._config["stats"]["updated_at"] = _now()
            self._save()
            self._append_log("已请求停止注册任务，正在等待当前运行任务结束", "yellow")
            return self.get()

    def reset(self) -> dict:
        with self._lock:
            self._logs = []
            self._config["stats"] = {
                "success": 0,
                "fail": 0,
                "done": 0,
                "running": 0,
                "threads": self._config["threads"],
                "elapsed_seconds": 0,
                "avg_seconds": 0,
                "success_rate": 0,
                **self._pool_metrics(),
                "updated_at": _now(),
            }
            with openai_register.stats_lock:
                openai_register.stats.update({"done": 0, "success": 0, "fail": 0, "start_time": 0.0})
            self._save()
            return self.get()

    def reset_outlook_pool(self, scope: str = "all") -> dict:
        scope = "failed" if str(scope) == "failed" else "all"
        cleared = mail_provider.reset_outlook_token_pool_state(scope)
        with self._lock:
            self._append_log(f"已重置 Outlook 邮箱池状态，清除 {cleared} 条记录", "yellow")
        return self.get()

    def refresh_proxy(self) -> dict:
        with self._lock:
            self._sync_openai_config()
            snapshot = refresh_register_proxy_runtime(self._config)
            self._append_log(str(snapshot.get("message") or "mimo 代理已刷新"), "yellow")
            return self.get()

    def stop_proxy(self) -> dict:
        snapshot = stop_register_proxy_runtime()
        with self._lock:
            self._append_log(str(snapshot.get("message") or "mimo 代理已停止"), "yellow")
        return self.get()

    def retry_failed(self, ids: list[str] | None = None, mode: str = "") -> dict:
        normalized_ids = {str(item).strip() for item in (ids or []) if str(item).strip()}
        retry_mode = str(mode or "auto").strip().lower()
        if retry_mode not in {"auto", "register", "login"}:
            retry_mode = "auto"
        with self._lock:
            if self._retry_runner and self._retry_runner.is_alive():
                raise RuntimeError("恢复任务仍在运行")
            selected = [item for item in self._failed_items if not normalized_ids or str(item.get("id") or "") in normalized_ids]
            if not selected:
                raise RuntimeError("没有可补跑邮箱")
            selected_ids = [str(item.get("id") or "") for item in selected]
            for item in self._failed_items:
                if str(item.get("id") or "") in selected_ids:
                    item["status"] = "queued"
                    item["mode"] = retry_mode
                    item["updated_at"] = _now()
            self._save_failed()
            self._failed_retry_state = {
                **_default_failed_retry_state(),
                "running": True,
                "total": len(selected_ids),
                "queued": len(selected_ids),
                "mode": retry_mode,
                "label": "补 login" if retry_mode == "login" else "恢复补跑",
                "message": f"已加入 {len(selected_ids)} 个恢复任务",
                "started_at": _now(),
                "updated_at": _now(),
            }
            self._retry_runner = threading.Thread(target=self._run_failed_retry, args=(selected_ids, retry_mode), daemon=True, name="openai-register-recovery")
            self._retry_runner.start()
            self._append_log(f"恢复任务启动，共 {len(selected_ids)} 个邮箱，模式={retry_mode}", "yellow")
            return self.get()

    def queue_login_recovery(self, text: str) -> dict:
        imported = _parse_email_text(text, default_mode="login")
        if not imported:
            raise RuntimeError("没有解析到可补 login 邮箱")
        selected_ids: list[str] = []
        with self._lock:
            by_email = {str(item.get("email") or "").strip().lower(): item for item in self._failed_items}
            for item in imported:
                current = by_email.get(item["email"])
                if current:
                    current.update(
                        {
                            "password": item["password"] or current.get("password") or _random_password(),
                            "mode": "login",
                            "status": "queued",
                            "last_error": "",
                            "source": "manual_login",
                            "updated_at": _now(),
                        }
                    )
                    selected_ids.append(str(current.get("id") or ""))
                else:
                    failed = self._normalize_failed_item({**item, "status": "queued", "mode": "login", "source": "manual_login"})
                    self._failed_items.append(failed)
                    by_email[failed["email"]] = failed
                    selected_ids.append(str(failed.get("id") or ""))
            self._save_failed()
            self._append_log(f"已导入 {len(selected_ids)} 个补 login 邮箱", "yellow")
        return self.retry_failed(selected_ids, mode="login")

    def remove_failed(self, ids: list[str]) -> dict:
        normalized_ids = {str(item).strip() for item in ids if str(item).strip()}
        if not normalized_ids:
            raise RuntimeError("缺少要移除的恢复记录 ID")
        with self._lock:
            if self._retry_runner and self._retry_runner.is_alive():
                raise RuntimeError("恢复任务运行中，暂不能移除记录")
            before = len(self._failed_items)
            self._failed_items = [item for item in self._failed_items if str(item.get("id") or "") not in normalized_ids]
            removed = before - len(self._failed_items)
            self._save_failed()
            self._append_log(f"已移除 {removed} 条恢复记录", "yellow")
            return self.get()

    def clear_failed(self) -> dict:
        with self._lock:
            if self._retry_runner and self._retry_runner.is_alive():
                raise RuntimeError("恢复任务运行中，暂不能清空记录")
            count = len(self._failed_items)
            self._failed_items = []
            self._save_failed()
            self._append_log(f"已清空恢复记录，共 {count} 条", "yellow")
            return self.get()

    def _append_log(self, text: str, color: str = "") -> None:
        with self._lock:
            self._logs.append({"time": _now(), "text": str(text), "level": str(color or "info")})
            self._logs = self._logs[-300:]

    def _pool_metrics(self) -> dict:
        items = account_service.list_accounts()
        normal = [item for item in items if item.get("status") == "正常"]
        return {
            "current_quota": sum(int(item.get("quota") or 0) for item in normal if not item.get("image_quota_unknown")),
            "current_available": len(normal),
        }

    def _target_reached(self, cfg: dict, submitted: int) -> bool:
        mode = str(cfg.get("mode") or "total")
        metrics = self._pool_metrics()
        self._bump(**metrics)
        if mode == "quota":
            reached = metrics["current_quota"] >= int(cfg.get("target_quota") or 1)
            self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，当前剩余额度={metrics['current_quota']}，目标额度={cfg.get('target_quota')}，{'跳过注册' if reached else '继续注册'}", "yellow")
            return reached
        if mode == "available":
            reached = metrics["current_available"] >= int(cfg.get("target_available") or 1)
            self._append_log(f"检查号池：当前正常账号={metrics['current_available']}，目标账号={cfg.get('target_available')}，当前剩余额度={metrics['current_quota']}，{'跳过注册' if reached else '继续注册'}", "yellow")
            return reached
        return submitted >= int(cfg.get("total") or 1)

    def _bump(self, **updates: Any) -> None:
        with self._lock:
            self._config["stats"].update(updates)
            stats = self._config["stats"]
            started_at = str(stats.get("started_at") or "")
            if started_at:
                try:
                    elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())
                except Exception:
                    elapsed = 0.0
                success = int(stats.get("success") or 0)
                fail = int(stats.get("fail") or 0)
                stats["elapsed_seconds"] = round(elapsed, 1)
                stats["avg_seconds"] = round(elapsed / success, 1) if success else 0
                stats["success_rate"] = round(success * 100 / max(1, success + fail), 1)
            self._config["stats"]["updated_at"] = _now()
            self._save()

    def _pending_queue_count_locked(self) -> int:
        return sum(1 for item in self._queue_items if item.get("status") == "pending")

    def _reserve_queue_item_locked(self) -> dict | None:
        for item in self._queue_items:
            if item.get("status") == "pending":
                item["status"] = "running"
                item["updated_at"] = _now()
                self._save_queue()
                return dict(item)
        return None

    def _complete_queue_item(self, item_id: str, ok: bool, error: str = "") -> None:
        with self._lock:
            for item in self._queue_items:
                if str(item.get("id") or "") != str(item_id or ""):
                    continue
                item["status"] = "success" if ok else "failed"
                item["last_error"] = "" if ok else str(error or "").strip()
                item["retry_count"] = _safe_int(item.get("retry_count"), 0, 0) + (0 if ok else 1)
                item["updated_at"] = _now()
                if not ok:
                    self._upsert_failed_item_locked({**item, "mode": "auto", "source": "register_queue", "last_error": error})
                break
            self._save_queue()
            self._save_failed()

    def _upsert_failed_item_locked(self, item: dict) -> dict:
        normalized = self._normalize_failed_item(item)
        for current in self._failed_items:
            if current.get("email") == normalized.get("email"):
                current.update({**normalized, "id": current.get("id") or normalized["id"], "retry_count": _safe_int(current.get("retry_count"), 0, 0) + 1})
                return current
        self._failed_items.append(normalized)
        return normalized

    def _run(self) -> None:
        with self._lock:
            threads = int(self._config["threads"])
            cfg = dict(self._config)
        submitted, done, success, fail = 0, 0, 0, 0
        if cfg.get("proxy_mode") == "mihomo":
            self._append_log("正在后台启动 mimo 注册代理。", "yellow")
            snapshot = ensure_register_proxy_runtime_ready(cfg, force_restart=True)
            if not snapshot.get("running"):
                message = str(snapshot.get("message") or "mimo 代理启动失败").strip() or "mimo 代理启动失败"
                with self._lock:
                    self._config["enabled"] = False
                    self._save()
                self._bump(running=0, done=0, success=0, fail=0, finished_at=_now())
                self._append_log(f"mimo 代理启动失败，注册任务已停止: {message}", "red")
                return
            self._append_log(str(snapshot.get("message") or "mimo 注册代理已就绪。").strip() or "mimo 注册代理已就绪。", "green")

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = set()
            while True:
                with self._lock:
                    cfg = dict(self._config)
                    enabled = bool(self._config.get("enabled"))
                while enabled and not self._target_reached(cfg, submitted) and len(futures) < threads:
                    with self._lock:
                        item = self._reserve_queue_item_locked()
                    if not item:
                        if not futures:
                            self._append_log("待注册队列为空，注册任务结束", "yellow")
                        break
                    submitted += 1
                    futures.add(executor.submit(openai_register.worker, submitted, item))
                    with self._lock:
                        enabled = bool(self._config.get("enabled"))
                self._bump(running=len(futures), done=done, success=success, fail=fail)
                with self._lock:
                    no_pending = self._pending_queue_count_locked() <= 0
                    enabled = bool(self._config.get("enabled"))
                if not futures and (not enabled or no_pending or str(cfg.get("mode") or "total") == "total"):
                    break
                if not futures:
                    time.sleep(max(1, int(cfg.get("check_interval") or 5)))
                    continue
                finished, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    done += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc), "item": {}}
                    item = result.get("item") if isinstance(result.get("item"), dict) else {}
                    if result.get("ok"):
                        success += 1
                        self._complete_queue_item(str(item.get("id") or ""), True)
                    else:
                        fail += 1
                        self._complete_queue_item(str(item.get("id") or ""), False, str(result.get("error") or "注册失败"))
        self._bump(running=0, done=done, success=success, fail=fail, finished_at=_now())
        with self._lock:
            self._config["enabled"] = False
            self._save()
        self._append_log(f"注册任务结束，成功{success}，失败{fail}", "yellow")

    def _reserve_failed_item_locked(self, selected_ids: set[str], mode: str) -> dict | None:
        for item in self._failed_items:
            if str(item.get("id") or "") not in selected_ids or item.get("status") != "queued":
                continue
            item["status"] = "running"
            item["mode"] = mode
            item["updated_at"] = _now()
            self._save_failed()
            return dict(item)
        return None

    def _complete_failed_item(self, item_id: str, ok: bool, error: str = "") -> None:
        with self._lock:
            for item in self._failed_items:
                if str(item.get("id") or "") != str(item_id or ""):
                    continue
                item["status"] = "success" if ok else "failed"
                item["last_error"] = "" if ok else str(error or "").strip()
                item["retry_count"] = _safe_int(item.get("retry_count"), 0, 0) + (0 if ok else 1)
                item["updated_at"] = _now()
                break
            self._save_failed()

    def _run_failed_retry(self, selected_ids: list[str], mode: str) -> None:
        selected_id_set = {str(item) for item in selected_ids}
        with self._lock:
            threads = int(self._config["threads"])
            cfg = dict(self._config)
        if cfg.get("proxy_mode") == "mihomo":
            snapshot = ensure_register_proxy_runtime_ready(cfg, force_restart=False)
            if not snapshot.get("running"):
                message = str(snapshot.get("message") or "mimo 代理未就绪").strip() or "mimo 代理未就绪"
                with self._lock:
                    self._failed_retry_state.update({"running": False, "message": message, "updated_at": _now()})
                self._append_log(f"恢复任务停止: {message}", "red")
                return
        done, success, fail = 0, 0, 0
        submitted = 0
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = set()
            while True:
                while len(futures) < threads:
                    with self._lock:
                        item = self._reserve_failed_item_locked(selected_id_set, mode)
                    if not item:
                        break
                    submitted += 1
                    futures.add(executor.submit(openai_register.recover_existing_worker, submitted, item))
                with self._lock:
                    self._failed_retry_state.update({"queued": max(0, len(selected_ids) - submitted), "success": success, "fail": fail, "updated_at": _now()})
                if not futures:
                    break
                finished, futures = wait(futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    done += 1
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc), "item": {}}
                    item = result.get("item") if isinstance(result.get("item"), dict) else {}
                    if result.get("ok"):
                        success += 1
                        self._complete_failed_item(str(item.get("id") or ""), True)
                    else:
                        fail += 1
                        self._complete_failed_item(str(item.get("id") or ""), False, str(result.get("error") or "恢复失败"))
        with self._lock:
            self._failed_retry_state.update(
                {
                    "running": False,
                    "queued": 0,
                    "success": success,
                    "fail": fail,
                    "done": done,
                    "message": f"恢复任务结束，成功{success}，失败{fail}",
                    "finished_at": _now(),
                    "updated_at": _now(),
                }
            )
        self._append_log(f"恢复任务结束，成功{success}，失败{fail}", "yellow")


register_service = RegisterService(REGISTER_FILE)
