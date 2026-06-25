from __future__ import annotations

import gzip
import ipaddress
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REGISTER_PROXY_MODES = {"direct", "manual", "mihomo"}
DEFAULT_MIHOMO_SETTINGS = {
    "subscription_url": "",
    "api_port": 19080,
    "listener_port_base": 19081,
    "include_pattern": "",
    "exclude_pattern": "",
    "provider_interval": 3600,
    "healthcheck_url": "https://cp.cloudflare.com/generate_204",
}

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
MIHOMO_RUNTIME_DIR = DATA_DIR / "mihomo"
MIHOMO_BIN_FILE = MIHOMO_RUNTIME_DIR / "mihomo"
MIHOMO_CONFIG_FILE = MIHOMO_RUNTIME_DIR / "config.yaml"
MIHOMO_STATE_FILE = MIHOMO_RUNTIME_DIR / "runtime_state.json"
MIHOMO_LOG_FILE = MIHOMO_RUNTIME_DIR / "mihomo.log"
MIHOMO_PROVIDER_DIR = MIHOMO_RUNTIME_DIR / "providers"
MIHOMO_PROVIDER_FILE = MIHOMO_PROVIDER_DIR / "panel_provider.yaml"
MIHOMO_PROVIDER_NAME = "panel_provider"
MIHOMO_GITHUB_RELEASE_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
MIHOMO_API_TIMEOUT_SECONDS = 6.0
MIHOMO_DOWNLOAD_TIMEOUT_SECONDS = 45.0
MIHOMO_START_TIMEOUT_SECONDS = 18.0
MIHOMO_READY_POLL_INTERVAL_SECONDS = 0.4
MIHOMO_PROVIDER_MAX_BYTES = 5 * 1024 * 1024
MIHOMO_PUBLIC_IP_CACHE_SECONDS = 300.0
MIHOMO_SOURCE_GROUP_CANDIDATES = ("Default Proxy", "Default Proxy Selector")
MIHOMO_GROUP_TYPES = {"select", "selector", "urltest", "fallback", "loadbalance", "relay"}
MIHOMO_PUBLIC_IP_CHECK_URLS = (
    "https://api.ipify.org?format=json",
    "http://api.ipify.org?format=json",
    "https://api.ipify.org",
    "http://api.ipify.org",
    "https://4.ident.me",
    "http://4.ident.me",
    "https://ipv4.icanhazip.com",
    "http://ipv4.icanhazip.com",
    "https://ifconfig.me/ip",
    "http://ifconfig.me/ip",
    "https://www.cloudflare.com/cdn-cgi/trace",
)
_PUBLIC_IP_CACHE: dict[str, tuple[float, str]] = {}
_PUBLIC_IP_CACHE_LOCK = threading.RLock()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _safe_int(value: Any, default: int, minimum: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, normalized)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _extract_global_ipv4(text: str) -> str:
    for candidate in re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", str(text or "")):
        try:
            addr = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if isinstance(addr, ipaddress.IPv4Address) and addr.is_global:
            return candidate
    return ""


def _resolve_proxy_public_ip(proxy_url: str, cache_key: str = "") -> str:
    normalized_proxy = str(proxy_url or "").strip()
    if not normalized_proxy:
        return ""
    normalized_cache_key = str(cache_key or "").strip()
    cache_token = f"{normalized_proxy}|{normalized_cache_key}" if normalized_cache_key else normalized_proxy
    now = time.time()
    with _PUBLIC_IP_CACHE_LOCK:
        cached = _PUBLIC_IP_CACHE.get(cache_token)
        if cached and now - float(cached[0] or 0.0) < MIHOMO_PUBLIC_IP_CACHE_SECONDS:
            return str(cached[1] or "").strip()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": normalized_proxy, "https": normalized_proxy}))
    opener.addheaders = [("User-Agent", "chatgpt2api-router-mihomo")]
    resolved = ""
    for url in MIHOMO_PUBLIC_IP_CHECK_URLS:
        try:
            with opener.open(url, timeout=MIHOMO_API_TIMEOUT_SECONDS) as response:
                payload = response.read(256).decode("utf-8", errors="replace")
            resolved = _extract_global_ipv4(payload)
            if resolved:
                break
        except Exception:
            continue
    with _PUBLIC_IP_CACHE_LOCK:
        _PUBLIC_IP_CACHE[cache_token] = (now, resolved)
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _match_pattern(text: str, pattern: str) -> bool:
    source = str(text or "")
    candidate = str(pattern or "").strip()
    if not candidate:
        return True
    try:
        return bool(re.search(candidate, source, re.IGNORECASE))
    except re.error:
        return candidate.lower() in source.lower()


def filter_mihomo_node_names(names: list[str], include_pattern: str, exclude_pattern: str) -> list[str]:
    result: list[str] = []
    for item in names:
        value = str(item or "").strip()
        if not value or value.upper() == "DIRECT":
            continue
        if include_pattern and not _match_pattern(value, include_pattern):
            continue
        if exclude_pattern and _match_pattern(value, exclude_pattern):
            continue
        if value not in result:
            result.append(value)
    return result


def normalize_register_runtime_config(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    manual_proxy = str(source.get("proxy") or "").strip()
    suggested_mode = "manual" if manual_proxy else "direct"
    proxy_mode = str(source.get("proxy_mode") or suggested_mode).strip().lower()
    if proxy_mode not in REGISTER_PROXY_MODES:
        proxy_mode = suggested_mode

    threads = _safe_int(source.get("threads"), 3, 1)
    raw_mihomo = source.get("mihomo") if isinstance(source.get("mihomo"), dict) else {}
    if not raw_mihomo and isinstance(source.get("mimo"), dict):
        raw_mihomo = source.get("mimo") or {}
    mihomo = {
        "subscription_url": str(raw_mihomo.get("subscription_url") or "").strip(),
        "api_port": _safe_int(raw_mihomo.get("api_port"), DEFAULT_MIHOMO_SETTINGS["api_port"], 1024),
        "listener_port_base": _safe_int(raw_mihomo.get("listener_port_base"), DEFAULT_MIHOMO_SETTINGS["listener_port_base"], 1024),
        "include_pattern": str(raw_mihomo.get("include_pattern") or "").strip(),
        "exclude_pattern": str(raw_mihomo.get("exclude_pattern") or "").strip(),
        "provider_interval": _safe_int(raw_mihomo.get("provider_interval"), DEFAULT_MIHOMO_SETTINGS["provider_interval"], 300),
        "healthcheck_url": str(raw_mihomo.get("healthcheck_url") or DEFAULT_MIHOMO_SETTINGS["healthcheck_url"]).strip() or DEFAULT_MIHOMO_SETTINGS["healthcheck_url"],
        "listener_count": threads,
    }

    source["proxy"] = manual_proxy
    source["proxy_mode"] = proxy_mode
    source["mihomo"] = mihomo
    source["mimo"] = mihomo
    return source


def _build_mihomo_settings(register_config: dict[str, Any] | None) -> dict[str, Any]:
    resolved = normalize_register_runtime_config(register_config)
    mihomo = resolved.get("mihomo") if isinstance(resolved.get("mihomo"), dict) else {}
    has_cached_provider = MIHOMO_PROVIDER_FILE.exists() and MIHOMO_PROVIDER_FILE.stat().st_size > 0
    listener_count = _safe_int(mihomo.get("listener_count"), _safe_int(resolved.get("threads"), 3, 1), 1)
    listener_port_base = _safe_int(mihomo.get("listener_port_base"), DEFAULT_MIHOMO_SETTINGS["listener_port_base"], 1024)
    listeners: list[dict[str, Any]] = []
    for index in range(listener_count):
        port = listener_port_base + index
        listeners.append(
            {
                "slot": index,
                "name": f"listener-{index + 1}",
                "group_name": f"thread-{index + 1}",
                "port": port,
                "proxy_url": f"http://127.0.0.1:{port}",
            }
        )
    return {
        "enabled": resolved.get("proxy_mode") == "mihomo",
        "configured": bool(str(mihomo.get("subscription_url") or "").strip() or has_cached_provider),
        "subscription_url": str(mihomo.get("subscription_url") or "").strip(),
        "has_cached_provider": has_cached_provider,
        "api_port": _safe_int(mihomo.get("api_port"), DEFAULT_MIHOMO_SETTINGS["api_port"], 1024),
        "api_url": f"http://127.0.0.1:{_safe_int(mihomo.get('api_port'), DEFAULT_MIHOMO_SETTINGS['api_port'], 1024)}",
        "listener_port_base": listener_port_base,
        "listener_count": listener_count,
        "listeners": listeners,
        "include_pattern": str(mihomo.get("include_pattern") or "").strip(),
        "exclude_pattern": str(mihomo.get("exclude_pattern") or "").strip(),
        "provider_interval": _safe_int(mihomo.get("provider_interval"), DEFAULT_MIHOMO_SETTINGS["provider_interval"], 300),
        "healthcheck_url": str(mihomo.get("healthcheck_url") or DEFAULT_MIHOMO_SETTINGS["healthcheck_url"]).strip() or DEFAULT_MIHOMO_SETTINGS["healthcheck_url"],
    }


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    return json.dumps(str(value), ensure_ascii=False)


def render_mihomo_config_yaml(settings: dict[str, Any]) -> str:
    lines = [
        "mixed-port: 0",
        "allow-lan: false",
        'bind-address: "127.0.0.1"',
        "mode: rule",
        "log-level: info",
        f'external-controller: "127.0.0.1:{int(settings["api_port"])}"',
        'secret: ""',
        "profile:",
        "  store-selected: true",
        "  store-fake-ip: false",
        "proxy-providers:",
        f"  {MIHOMO_PROVIDER_NAME}:",
        "    type: file",
        f'    path: {_yaml_scalar("./providers/panel_provider.yaml")}',
        "    health-check:",
        "      enable: true",
        f'      url: {_yaml_scalar(settings["healthcheck_url"])}',
        "      interval: 300",
        "proxy-groups:",
    ]
    for listener in settings["listeners"]:
        lines.extend(
            [
                f"  - name: {_yaml_scalar(listener['group_name'])}",
                '    type: "select"',
                "    proxies:",
                '      - "DIRECT"',
                "    use:",
                f"      - {_yaml_scalar(MIHOMO_PROVIDER_NAME)}",
            ]
        )
    lines.extend(
        [
            "rules:",
            '  - "MATCH,DIRECT"',
            "listeners:",
        ]
    )
    for listener in settings["listeners"]:
        lines.extend(
            [
                f"  - name: {_yaml_scalar(listener['name'])}",
                '    type: "mixed"',
                '    listen: "127.0.0.1"',
                f"    port: {int(listener['port'])}",
                f"    proxy: {_yaml_scalar(listener['group_name'])}",
            ]
        )
    return "\n".join(lines) + "\n"


def _append_unique_proxy_name(target: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if not text or text.upper() == "DIRECT" or text in target:
        return
    target.append(text)


def _extract_proxy_names(payload: Any) -> list[str]:
    result: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _append_unique_proxy_name(result, item.get("name") or item.get("title") or item.get("id"))
            else:
                _append_unique_proxy_name(result, item)
        return result
    if isinstance(payload, dict):
        if isinstance(payload.get("proxies"), list):
            result.extend(_extract_proxy_names(payload.get("proxies")))
        if isinstance(payload.get("proxies"), dict):
            for key in payload.get("proxies", {}).keys():
                _append_unique_proxy_name(result, key)
        if isinstance(payload.get("all"), list):
            for item in payload.get("all", []):
                _append_unique_proxy_name(result, item)
        _append_unique_proxy_name(result, payload.get("now"))
    return result


def _normalized_proxy_type(payload: dict[str, Any]) -> str:
    raw_type = str(payload.get("type") or "").strip().lower()
    return raw_type.replace("-", "").replace("_", "")


def _pick_source_group_name(group_names: list[str]) -> str:
    if not group_names:
        return ""
    normalized_names = [str(name or "").strip() for name in group_names if str(name or "").strip()]
    if not normalized_names:
        return ""
    available = {name: name for name in normalized_names}
    for candidate in MIHOMO_SOURCE_GROUP_CANDIDATES:
        if candidate in available:
            return available[candidate]
    lowered = {name.lower(): name for name in normalized_names}
    for candidate in MIHOMO_SOURCE_GROUP_CANDIDATES:
        matched_name = lowered.get(candidate.lower())
        if matched_name:
            return matched_name
    for name in normalized_names:
        normalized = name.lower()
        if "default proxy" in normalized:
            return name
    for name in normalized_names:
        normalized = name.lower()
        if "proxy" in normalized and "selector" in normalized:
            return name
    return ""


def _pick_source_group_payload_from_proxies(proxies: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for name, payload in proxies.items():
        normalized_name = str(name or "").strip()
        if not normalized_name or not isinstance(payload, dict):
            continue
        if _normalized_proxy_type(payload) in MIHOMO_GROUP_TYPES:
            groups[normalized_name] = payload
    if not groups:
        return "", {}
    source_group_name = _pick_source_group_name(list(groups.keys()))
    if source_group_name:
        return source_group_name, groups[source_group_name]
    return "", {}


def _resolve_source_group_direct_nodes_from_proxies(proxies: dict[str, Any]) -> tuple[str, list[str], int]:
    group_name, group_payload = _pick_source_group_payload_from_proxies(proxies)
    if not group_name or not isinstance(group_payload, dict):
        return "", [], 0
    group_members = [
        str(item or "").strip()
        for item in (group_payload.get("all") or [])
        if str(item or "").strip() and str(item or "").strip().upper() != "DIRECT"
    ]
    direct_nodes: list[str] = []
    for item in group_members:
        member_payload = proxies.get(item) if isinstance(proxies, dict) else None
        if isinstance(member_payload, dict) and _normalized_proxy_type(member_payload) in MIHOMO_GROUP_TYPES:
            continue
        if item not in direct_nodes:
            direct_nodes.append(item)
    return group_name, direct_nodes, len(group_members)


def _unquote_yaml_scalar(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _resolve_source_group_direct_nodes_from_provider_file() -> tuple[str, list[str], int]:
    try:
        lines = MIHOMO_PROVIDER_FILE.read_text(encoding="utf-8-sig").splitlines()
    except Exception:
        return "", [], 0
    section = ""
    raw_proxy_names: list[str] = []
    group_members: dict[str, list[str]] = {}
    current_group = ""
    collecting_group_members = False
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        top_level_match = re.match(r"^([A-Za-z0-9_-]+):\s*$", raw_line)
        if top_level_match:
            section = top_level_match.group(1)
            current_group = ""
            collecting_group_members = False
            continue
        if section == "proxies":
            proxy_match = re.match(r"^\s{2}-\s+name:\s*(.+?)\s*$", raw_line)
            if proxy_match:
                raw_proxy_names.append(_unquote_yaml_scalar(proxy_match.group(1)))
            continue
        if section != "proxy-groups":
            continue
        group_match = re.match(r"^\s{2}-\s+name:\s*(.+?)\s*$", raw_line)
        if group_match:
            current_group = _unquote_yaml_scalar(group_match.group(1))
            group_members.setdefault(current_group, [])
            collecting_group_members = False
            continue
        if not current_group:
            continue
        if re.match(r"^\s{4}proxies:\s*$", raw_line):
            collecting_group_members = True
            continue
        if collecting_group_members:
            member_match = re.match(r"^\s{6}-\s+(.+?)\s*$", raw_line)
            if member_match:
                member_name = _unquote_yaml_scalar(member_match.group(1))
                if member_name and member_name.upper() != "DIRECT":
                    group_members[current_group].append(member_name)
                continue
            if re.match(r"^\s{4}\S", raw_line):
                collecting_group_members = False
    source_group_name = _pick_source_group_name(list(group_members.keys()))
    if not source_group_name:
        return "", [], 0
    raw_proxy_name_set = set(raw_proxy_names)
    members = group_members.get(source_group_name) or []
    direct_nodes: list[str] = []
    for item in members:
        if item in raw_proxy_name_set and item not in direct_nodes:
            direct_nodes.append(item)
    return source_group_name, direct_nodes, len(members)


def _resolve_source_group_direct_nodes(proxies: dict[str, Any] | None = None) -> tuple[str, list[str], int]:
    if isinstance(proxies, dict) and proxies:
        group_name, direct_nodes, option_count = _resolve_source_group_direct_nodes_from_proxies(proxies)
        if group_name:
            return group_name, direct_nodes, option_count
    return _resolve_source_group_direct_nodes_from_provider_file()


def _parse_provider_file_proxy_metadata() -> dict[str, dict[str, Any]]:
    try:
        lines = MIHOMO_PROVIDER_FILE.read_text(encoding="utf-8-sig").splitlines()
    except Exception:
        return {}
    section = ""
    current_name = ""
    metadata: dict[str, dict[str, Any]] = {}
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        top_level_match = re.match(r"^([A-Za-z0-9_-]+):\s*$", raw_line)
        if top_level_match:
            section = top_level_match.group(1)
            current_name = ""
            continue
        if section != "proxies":
            continue
        name_match = re.match(r"^\s{2}-\s+name:\s*(.+?)\s*$", raw_line)
        if name_match:
            current_name = _unquote_yaml_scalar(name_match.group(1))
            metadata[current_name] = {"name": current_name}
            continue
        if not current_name:
            continue
        field_match = re.match(r"^\s{4}([A-Za-z0-9_-]+):\s*(.+?)\s*$", raw_line)
        if not field_match:
            continue
        key = field_match.group(1)
        value = _unquote_yaml_scalar(field_match.group(2))
        if key in {"server", "port", "type"}:
            metadata[current_name][key] = value
    return metadata


def _extract_proxy_delay_ms(proxy_payload: dict[str, Any]) -> int | None:
    history = proxy_payload.get("history") if isinstance(proxy_payload, dict) else None
    if not isinstance(history, list):
        return None
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        delay = item.get("delay")
        try:
            normalized = int(delay)
        except (TypeError, ValueError):
            continue
        if normalized > 0:
            return normalized
    return None


def _sort_proxy_candidates_by_speed(candidates: list[str], proxies: dict[str, Any]) -> list[str]:
    ranked: list[tuple[int, int, int, str]] = []
    for index, name in enumerate(candidates):
        payload = proxies.get(name) if isinstance(proxies, dict) else {}
        delay = _extract_proxy_delay_ms(payload if isinstance(payload, dict) else {})
        ranked.append((0 if delay is not None else 1, delay if delay is not None else 10**9, index, name))
    ranked.sort()
    return [name for _missing, _delay, _index, name in ranked]


def _build_listener_state(
    listener: dict[str, Any],
    selected_proxy: str,
    candidate_names: list[str],
    proxies: dict[str, Any],
    proxy_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resolved_proxy = str(selected_proxy or "").strip() or "DIRECT"
    proxy_payload = proxies.get(resolved_proxy) if isinstance(proxies, dict) else {}
    if not isinstance(proxy_payload, dict):
        proxy_payload = {}
    metadata = proxy_metadata.get(resolved_proxy) if isinstance(proxy_metadata, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    server = str(metadata.get("server") or "").strip()
    port = str(metadata.get("port") or "").strip()
    endpoint = ""
    if server and port:
        endpoint = f"{server}:{port}"
    elif server:
        endpoint = server
    proxy_url = str(listener.get("proxy_url") or "").strip()
    public_ip = _resolve_proxy_public_ip(proxy_url, resolved_proxy) if proxy_url and resolved_proxy != "DIRECT" else ""
    return {
        **listener,
        "selected_proxy": resolved_proxy,
        "selected_proxy_delay_ms": _extract_proxy_delay_ms(proxy_payload),
        "selected_proxy_type": str(metadata.get("type") or proxy_payload.get("type") or "").strip(),
        "selected_proxy_server": server,
        "selected_proxy_port": port,
        "selected_proxy_endpoint": endpoint,
        "selected_proxy_public_ip": public_ip,
        "candidate_count": len(candidate_names),
        "candidate_preview": candidate_names[:6],
    }


def _looks_like_local_placeholder_subscription(payload: bytes) -> bool:
    try:
        text = payload.decode("utf-8", errors="replace")
    except Exception:
        return False
    lowered = text.lower()
    if "server: 127.0.0.1" not in lowered and "server: localhost" not in lowered:
        return False
    if "type: socks5" not in lowered and "type: ss" not in lowered and "type: shadowsocks" not in lowered:
        return False
    name_count = len(re.findall(r"(?im)^\s*-\s*name\s*:", text))
    proxy_block_count = len(re.findall(r"(?im)^\s*proxies\s*:", text))
    return proxy_block_count >= 1 and name_count <= 1


class RegisterMihomoManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._log_handle = None

    def _read_state_locked(self) -> dict[str, Any]:
        return _read_json(MIHOMO_STATE_FILE)

    def _write_state_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["updated_at"] = _now_iso()
        return _write_json(MIHOMO_STATE_FILE, normalized)

    def _cleanup_if_finished_locked(self) -> None:
        if self._process is None or self._process.poll() is None:
            return
        self._process = None
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def _is_running_locked(self) -> bool:
        return bool(self._process and self._process.poll() is None)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_locked()
            self._write_state_locked({"status": "stopped", "running": False, "message": "线程代理已停止。"})
        return self.snapshot({})

    def _stop_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._cleanup_if_finished_locked()

    def _resolve_existing_binary_locked(self) -> Path | None:
        env_path = str(os.getenv("MIHOMO_BIN") or "").strip()
        candidates: list[Path] = []
        if env_path:
            candidates.append(Path(env_path))
        candidates.extend([MIHOMO_BIN_FILE, Path("/usr/local/bin/mihomo")])
        for candidate in candidates:
            try:
                if candidate.exists() and os.access(candidate, os.X_OK):
                    return candidate
            except Exception:
                continue
        return None

    def _github_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": "chatgpt2api-router-mihomo",
        }

    def _select_release_asset(self, release_payload: dict[str, Any]) -> tuple[str, str]:
        assets = release_payload.get("assets") if isinstance(release_payload, dict) else []
        if not isinstance(assets, list):
            raise RuntimeError("GitHub release 资产列表为空")

        machine = platform.machine().strip().lower()
        patterns: list[str]
        if machine in {"x86_64", "amd64"}:
            patterns = [r"mihomo-linux-amd64-compatible-.*\.gz$", r"mihomo-linux-amd64-.*\.gz$"]
        elif machine in {"aarch64", "arm64"}:
            patterns = [r"mihomo-linux-arm64-.*\.gz$"]
        elif machine in {"armv7l", "armv7", "armhf"}:
            patterns = [r"mihomo-linux-armv7-.*\.gz$", r"mihomo-linux-armv7l-.*\.gz$"]
        else:
            raise RuntimeError(f"暂不支持当前架构下载 mihomo: {machine or 'unknown'}")

        for pattern in patterns:
            matcher = re.compile(pattern, re.IGNORECASE)
            for item in assets:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                url = str(item.get("browser_download_url") or "").strip()
                if name and url and matcher.search(name):
                    return name, url
        asset_names = [str(item.get("name") or "").strip() for item in assets if isinstance(item, dict)]
        raise RuntimeError(f"没找到匹配当前架构的 mihomo 资产，可用资产: {', '.join(asset_names[:8])}")

    def _download_binary_locked(self) -> Path:
        request = urllib.request.Request(MIHOMO_GITHUB_RELEASE_API, headers=self._github_headers())
        with urllib.request.urlopen(request, timeout=MIHOMO_DOWNLOAD_TIMEOUT_SECONDS) as response:
            release_payload = json.loads(response.read().decode("utf-8", "replace"))
        asset_name, download_url = self._select_release_asset(release_payload)

        MIHOMO_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        gz_path = MIHOMO_RUNTIME_DIR / f"{asset_name}.download"
        tmp_bin_path = MIHOMO_RUNTIME_DIR / "mihomo.tmp"
        download_request = urllib.request.Request(download_url, headers=self._github_headers())
        with urllib.request.urlopen(download_request, timeout=MIHOMO_DOWNLOAD_TIMEOUT_SECONDS) as response:
            with gz_path.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        with gzip.open(gz_path, "rb") as source:
            with tmp_bin_path.open("wb") as target:
                shutil.copyfileobj(source, target)
        tmp_bin_path.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )
        tmp_bin_path.replace(MIHOMO_BIN_FILE)
        try:
            gz_path.unlink()
        except OSError:
            pass
        return MIHOMO_BIN_FILE

    def _ensure_binary_locked(self) -> Path:
        current = self._resolve_existing_binary_locked()
        if current is not None:
            return current
        return self._download_binary_locked()

    def _sync_provider_cache_locked(self, settings: dict[str, Any]) -> tuple[bool, str]:
        subscription_url = str(settings.get("subscription_url") or "").strip()
        MIHOMO_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        MIHOMO_PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
        if not subscription_url:
            if MIHOMO_PROVIDER_FILE.exists() and MIHOMO_PROVIDER_FILE.stat().st_size > 0:
                return True, "未填写订阅地址，已继续使用本地缓存节点。"
            return False, "已切到 Mihomo，但还没填写订阅地址。"
        request = urllib.request.Request(
            subscription_url,
            headers={
                "Accept": "text/plain, application/yaml, application/x-yaml, */*",
                "User-Agent": "chatgpt2api-router-mihomo",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=MIHOMO_DOWNLOAD_TIMEOUT_SECONDS) as response:
                payload = response.read(MIHOMO_PROVIDER_MAX_BYTES + 1)
            if len(payload) > MIHOMO_PROVIDER_MAX_BYTES:
                raise RuntimeError("订阅文件过大")
            if not bytes(payload or b"").strip():
                raise RuntimeError("订阅返回为空")
            if _looks_like_local_placeholder_subscription(payload):
                if MIHOMO_PROVIDER_FILE.exists() and MIHOMO_PROVIDER_FILE.stat().st_size > 0:
                    cached_payload = MIHOMO_PROVIDER_FILE.read_bytes()
                    if not _looks_like_local_placeholder_subscription(cached_payload):
                        return True, "订阅地址返回的是本地占位配置（127.0.0.1 / Shadowsocks），已继续使用本地缓存的有效节点。"
                return False, "订阅地址返回的是本地占位配置（127.0.0.1 / Shadowsocks），不是实际节点订阅。"
            MIHOMO_PROVIDER_FILE.write_bytes(payload)
            return True, ""
        except Exception as exc:
            if MIHOMO_PROVIDER_FILE.exists() and MIHOMO_PROVIDER_FILE.stat().st_size > 0:
                return True, f"订阅刷新失败，已回退到本地缓存节点: {exc}"
            return False, f"订阅拉取失败: {exc}"

    def _api_json(self, api_port: int, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{int(api_port)}{path}",
            data=body,
            method=str(method or "GET").upper(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=MIHOMO_API_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}

    def _wait_until_ready_locked(self, api_port: int) -> bool:
        deadline = time.time() + MIHOMO_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            self._cleanup_if_finished_locked()
            if not self._is_running_locked():
                return False
            try:
                payload = self._api_json(api_port, "GET", "/proxies")
                if isinstance(payload, dict) and isinstance(payload.get("proxies"), dict):
                    return True
            except Exception:
                pass
            time.sleep(MIHOMO_READY_POLL_INTERVAL_SECONDS)
        return False

    def _collect_provider_summary_locked(self, settings: dict[str, Any]) -> dict[str, Any]:
        raw_names: list[str] = []
        provider_error = ""
        source_group_name = ""
        source_group_option_count = 0
        proxies: dict[str, Any] = {}
        try:
            payload = self._api_json(settings["api_port"], "GET", "/providers/proxies")
            providers = payload.get("providers") if isinstance(payload, dict) and isinstance(payload.get("providers"), dict) else {}
            raw_names.extend(_extract_proxy_names(providers.get(MIHOMO_PROVIDER_NAME, {})))
        except Exception as exc:
            provider_error = str(exc)
        try:
            payload = self._api_json(settings["api_port"], "GET", "/proxies")
            proxies = payload.get("proxies") if isinstance(payload, dict) and isinstance(payload.get("proxies"), dict) else {}
        except Exception as exc:
            if not provider_error:
                provider_error = str(exc)
        scoped_names = raw_names
        try:
            source_group_name, direct_names, source_group_option_count = _resolve_source_group_direct_nodes(proxies)
            if direct_names:
                scoped_names = direct_names
        except Exception:
            source_group_name = ""
            source_group_option_count = 0
            scoped_names = raw_names
        filtered_names = filter_mihomo_node_names(scoped_names, settings["include_pattern"], settings["exclude_pattern"])
        preview_names = filtered_names or scoped_names
        return {
            "provider_total_node_count": len(scoped_names),
            "provider_filtered_node_count": len(filtered_names),
            "provider_node_preview": preview_names[:8],
            "provider_preview_text": " / ".join(preview_names[:4]) if preview_names else "-",
            "provider_error": provider_error,
            "provider_source_group_name": source_group_name,
            "provider_source_group_option_count": source_group_option_count,
        }

    def _bind_listener_groups_locked(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        deadline = time.time() + 12.0
        proxies: dict[str, Any] = {}
        allowed_node_set: set[str] = set()
        while time.time() < deadline:
            payload = self._api_json(settings["api_port"], "GET", "/proxies")
            proxies = payload.get("proxies") if isinstance(payload, dict) and isinstance(payload.get("proxies"), dict) else {}
            _source_group_name, direct_names, _source_group_option_count = _resolve_source_group_direct_nodes(proxies)
            allowed_node_set = set(direct_names)
            ready_listener_count = 0
            for listener in settings["listeners"]:
                group_payload = proxies.get(listener["group_name"], {}) if isinstance(proxies, dict) else {}
                raw_candidates = [str(item or "").strip() for item in (group_payload.get("all") or []) if str(item or "").strip()]
                if allowed_node_set:
                    scoped_candidates = [item for item in raw_candidates if item in allowed_node_set]
                    if scoped_candidates:
                        raw_candidates = scoped_candidates
                candidates = filter_mihomo_node_names(raw_candidates, settings["include_pattern"], settings["exclude_pattern"])
                if not candidates:
                    candidates = filter_mihomo_node_names(raw_candidates, "", settings["exclude_pattern"])
                if candidates:
                    ready_listener_count += 1
            if ready_listener_count >= len(settings["listeners"]):
                break
            time.sleep(0.8)
        proxy_metadata = _parse_provider_file_proxy_metadata()
        used: set[str] = set()
        used_public_ips: set[str] = set()
        listener_states: list[dict[str, Any]] = []
        for listener in settings["listeners"]:
            group_payload = proxies.get(listener["group_name"], {}) if isinstance(proxies, dict) else {}
            raw_candidates = [str(item or "").strip() for item in (group_payload.get("all") or []) if str(item or "").strip()]
            if allowed_node_set:
                scoped_candidates = [item for item in raw_candidates if item in allowed_node_set]
                if scoped_candidates:
                    raw_candidates = scoped_candidates
            candidates = filter_mihomo_node_names(raw_candidates, settings["include_pattern"], settings["exclude_pattern"])
            if not candidates:
                candidates = filter_mihomo_node_names(raw_candidates, "", settings["exclude_pattern"])
            ordered_candidates = _sort_proxy_candidates_by_speed(candidates, proxies)
            selected_proxy = ""
            last_bound_proxy = ""
            fallback_state: dict[str, Any] | None = None
            selected_state: dict[str, Any] | None = None
            for candidate in ordered_candidates:
                if candidate not in used:
                    self._api_json(settings["api_port"], "PUT", f"/proxies/{listener['group_name']}", {"name": candidate})
                    last_bound_proxy = candidate
                    candidate_state = _build_listener_state(listener, candidate, ordered_candidates, proxies, proxy_metadata)
                    if fallback_state is None:
                        fallback_state = candidate_state
                    public_ip = str(candidate_state.get("selected_proxy_public_ip") or "").strip()
                    if public_ip and public_ip not in used_public_ips:
                        selected_state = candidate_state
                        break
            if selected_state is None:
                selected_state = fallback_state
            if selected_state is not None:
                selected_proxy = str(selected_state.get("selected_proxy") or "").strip() or "DIRECT"
            if not selected_proxy:
                selected_proxy = "DIRECT"
                selected_state = _build_listener_state(listener, selected_proxy, ordered_candidates, proxies, proxy_metadata)
            if selected_proxy != "DIRECT":
                if not last_bound_proxy or last_bound_proxy != selected_proxy:
                    self._api_json(settings["api_port"], "PUT", f"/proxies/{listener['group_name']}", {"name": selected_proxy})
                used.add(selected_proxy)
                public_ip = str(selected_state.get("selected_proxy_public_ip") or "").strip() if isinstance(selected_state, dict) else ""
                if public_ip:
                    used_public_ips.add(public_ip)
            listener_states.append(selected_state if isinstance(selected_state, dict) else _build_listener_state(listener, selected_proxy, ordered_candidates, proxies, proxy_metadata))
        return listener_states

    def _refresh_listener_runtime_details_locked(self, settings: dict[str, Any], listeners: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = self._api_json(settings["api_port"], "GET", "/proxies")
        proxies = payload.get("proxies") if isinstance(payload, dict) and isinstance(payload.get("proxies"), dict) else {}
        _source_group_name, direct_names, _source_group_option_count = _resolve_source_group_direct_nodes(proxies)
        allowed_node_set = set(direct_names)
        proxy_metadata = _parse_provider_file_proxy_metadata()
        refreshed: list[dict[str, Any]] = []
        for listener in listeners:
            group_payload = proxies.get(listener.get("group_name"), {}) if isinstance(proxies, dict) else {}
            raw_candidates = [str(item or "").strip() for item in (group_payload.get("all") or []) if str(item or "").strip()]
            if allowed_node_set:
                scoped_candidates = [item for item in raw_candidates if item in allowed_node_set]
                if scoped_candidates:
                    raw_candidates = scoped_candidates
            candidates = filter_mihomo_node_names(raw_candidates, settings["include_pattern"], settings["exclude_pattern"])
            if not candidates:
                candidates = filter_mihomo_node_names(raw_candidates, "", settings["exclude_pattern"])
            ordered_candidates = _sort_proxy_candidates_by_speed(candidates, proxies)
            selected_proxy = str(group_payload.get("now") or listener.get("selected_proxy") or "").strip() or "DIRECT"
            refreshed.append(_build_listener_state(listener, selected_proxy, ordered_candidates, proxies, proxy_metadata))
        return refreshed

    def ensure_running(self, register_config: dict[str, Any] | None, *, force_restart: bool = False) -> dict[str, Any]:
        settings = _build_mihomo_settings(register_config)
        with self._lock:
            self._cleanup_if_finished_locked()
            if not settings["enabled"]:
                self._stop_locked()
                self._write_state_locked({"status": "off", "running": False, "message": "注册代理当前未使用 Mihomo。"})
                return self.snapshot(register_config)

            provider_ok, provider_message = self._sync_provider_cache_locked(settings)
            if not provider_ok:
                self._stop_locked()
                self._write_state_locked({"status": "provider_error", "running": False, "message": provider_message})
                return self.snapshot(register_config)

            try:
                binary_path = self._ensure_binary_locked()
            except Exception as exc:
                self._write_state_locked({"status": "binary_error", "running": False, "message": f"下载 Mihomo 核心失败: {exc}"})
                return self.snapshot(register_config)

            config_text = render_mihomo_config_yaml(settings)
            existing_text = MIHOMO_CONFIG_FILE.read_text(encoding="utf-8") if MIHOMO_CONFIG_FILE.exists() else ""
            should_restart = force_restart or not self._is_running_locked() or existing_text != config_text
            if should_restart:
                MIHOMO_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
                MIHOMO_PROVIDER_DIR.mkdir(parents=True, exist_ok=True)
                self._stop_locked()
                MIHOMO_CONFIG_FILE.write_text(config_text, encoding="utf-8")
                self._log_handle = MIHOMO_LOG_FILE.open("a", encoding="utf-8")
                self._process = subprocess.Popen(
                    [str(binary_path), "-d", str(MIHOMO_RUNTIME_DIR), "-f", str(MIHOMO_CONFIG_FILE)],
                    cwd=str(MIHOMO_RUNTIME_DIR),
                    stdout=self._log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                if not self._wait_until_ready_locked(settings["api_port"]):
                    self._stop_locked()
                    self._write_state_locked({"status": "start_failed", "running": False, "message": "Mihomo 启动失败，请查看运行日志。"})
                    return self.snapshot(register_config)

            try:
                listeners = self._bind_listener_groups_locked(settings)
                provider_summary = self._collect_provider_summary_locked(settings)
            except Exception as exc:
                self._write_state_locked({"status": "bind_failed", "running": True, "message": f"Mihomo 已启动，但节点绑定失败: {exc}"})
                return self.snapshot(register_config)

            self._write_state_locked(
                {
                    "status": "running",
                    "running": True,
                    "message": provider_message or f"Mihomo 已启动，当前拉起 {len(listeners)} 路本地代理。",
                    "listeners": listeners,
                    "binary_path": str(binary_path),
                    **provider_summary,
                }
            )
        return self.snapshot(register_config)

    def refresh(self, register_config: dict[str, Any] | None) -> dict[str, Any]:
        return self.ensure_running(register_config, force_restart=True)

    def snapshot(self, register_config: dict[str, Any] | None) -> dict[str, Any]:
        settings = _build_mihomo_settings(register_config)
        with self._lock:
            self._cleanup_if_finished_locked()
            saved = self._read_state_locked()
            binary_path = self._resolve_existing_binary_locked()
            running = self._is_running_locked()
            listeners = saved.get("listeners") if isinstance(saved.get("listeners"), list) else settings["listeners"]
            provider_preview = saved.get("provider_node_preview") if isinstance(saved.get("provider_node_preview"), list) else []
            provider_total = _safe_int(saved.get("provider_total_node_count"), 0, 0)
            provider_filtered = _safe_int(saved.get("provider_filtered_node_count"), 0, 0)
            provider_error = str(saved.get("provider_error") or "").strip()
            provider_source_group_name = str(saved.get("provider_source_group_name") or "").strip()
            provider_source_group_option_count = _safe_int(saved.get("provider_source_group_option_count"), 0, 0)
            deep_status = str(os.environ.get("CHATGPT2API_MIHOMO_DEEP_STATUS") or "").strip().lower() in {"1", "true", "yes", "on"}
            if running and deep_status:
                try:
                    listeners = self._refresh_listener_runtime_details_locked(settings, listeners)
                    provider_summary = self._collect_provider_summary_locked(settings)
                    provider_preview = provider_summary["provider_node_preview"]
                    provider_total = provider_summary["provider_total_node_count"]
                    provider_filtered = provider_summary["provider_filtered_node_count"]
                    provider_error = provider_summary["provider_error"]
                    provider_source_group_name = str(provider_summary.get("provider_source_group_name") or "").strip()
                    provider_source_group_option_count = _safe_int(provider_summary.get("provider_source_group_option_count"), 0, 0)
                except Exception:
                    pass

            if not settings["enabled"]:
                status = "off"
                status_label = "未启用"
                badge_kind = "off"
                message = "注册代理当前未使用 Mihomo。"
            elif not settings["configured"]:
                status = "need_config"
                status_label = "待配置"
                badge_kind = "off"
                message = "已切到 Mihomo，但还没填写订阅地址。"
            elif saved.get("status") == "binary_error":
                status = "binary_error"
                status_label = "下载失败"
                badge_kind = "danger"
                message = str(saved.get("message") or "Mihomo 核心下载失败。").strip()
            elif running:
                status = "running"
                status_label = "运行中"
                badge_kind = "ok"
                message = str(saved.get("message") or f"Mihomo 已启动，当前拉起 {len(listeners)} 路本地代理。").strip()
            else:
                status = str(saved.get("status") or "stopped").strip() or "stopped"
                status_label = "未运行"
                badge_kind = "danger" if status not in {"off", "need_config"} else "off"
                message = str(saved.get("message") or "Mihomo 当前未运行。").strip()

            listener_ports = [int(item.get("port") or 0) for item in listeners if int(item.get("port") or 0) > 0]
            proxy_names = []
            proxy_routes = []
            proxy_public_ips = []
            for item in listeners:
                proxy = str(item.get("selected_proxy") or "").strip()
                endpoint = str(item.get("selected_proxy_endpoint") or "").strip()
                public_ip = str(item.get("selected_proxy_public_ip") or "").strip()
                if proxy:
                    proxy_names.append(f"{proxy} @ {public_ip}" if public_ip else proxy)
                if public_ip:
                    proxy_public_ips.append(public_ip)
                    proxy_routes.append(f"{public_ip} via {endpoint}" if endpoint and endpoint != public_ip else public_ip)
                elif endpoint:
                    proxy_routes.append(endpoint)
            proxy_speed_lines = []
            for item in listeners:
                name = str(item.get("name") or "").strip() or str(item.get("group_name") or "").strip()
                proxy = str(item.get("selected_proxy") or "").strip() or "DIRECT"
                endpoint = str(item.get("selected_proxy_endpoint") or "").strip() or "-"
                public_ip = str(item.get("selected_proxy_public_ip") or "").strip()
                delay = item.get("selected_proxy_delay_ms")
                delay_text = f"{int(delay)}ms" if isinstance(delay, int) and delay > 0 else "-"
                route_text = f"{public_ip} via {endpoint}" if public_ip and endpoint != "-" and endpoint != public_ip else (public_ip or endpoint)
                proxy_speed_lines.append(f"{name}:{proxy}@{route_text} {delay_text}")
            return {
                "enabled": bool(settings["enabled"]),
                "configured": bool(settings["configured"]),
                "running": running,
                "status": status,
                "status_label": status_label,
                "badge_kind": badge_kind,
                "message": message,
                "api_port": int(settings["api_port"]),
                "api_url": settings["api_url"],
                "listener_count": int(settings["listener_count"]),
                "listener_ports": listener_ports,
                "listener_ports_text": " / ".join(str(item) for item in listener_ports) if listener_ports else "-",
                "selected_proxy_names": proxy_names,
                "selected_proxy_text": " / ".join(proxy_names) if proxy_names else "-",
                "selected_proxy_public_ips": proxy_public_ips,
                "selected_proxy_public_ip_text": " / ".join(proxy_public_ips) if proxy_public_ips else "-",
                "selected_proxy_routes": proxy_routes,
                "selected_proxy_route_text": " / ".join(proxy_routes) if proxy_routes else "-",
                "selected_proxy_speed_lines": proxy_speed_lines,
                "binary_ready": binary_path is not None,
                "binary_path": str(binary_path or ""),
                "listeners": listeners,
                "provider_total_node_count": provider_total,
                "provider_filtered_node_count": provider_filtered,
                "provider_node_preview": provider_preview,
                "provider_preview_text": " / ".join(provider_preview[:4]) if provider_preview else "-",
                "provider_error": provider_error,
                "provider_source_group_name": provider_source_group_name,
                "provider_source_group_option_count": provider_source_group_option_count,
                "healthcheck_url": str(settings.get("healthcheck_url") or "").strip(),
                "state_updated_at": str(saved.get("updated_at") or "").strip() if isinstance(saved, dict) else "",
            }


REGISTER_MIHOMO_MANAGER = RegisterMihomoManager()


def get_register_proxy_status(register_config: dict[str, Any] | None) -> dict[str, Any]:
    return REGISTER_MIHOMO_MANAGER.snapshot(register_config)


def ensure_register_proxy_runtime_ready(register_config: dict[str, Any] | None, *, force_restart: bool = False) -> dict[str, Any]:
    return REGISTER_MIHOMO_MANAGER.ensure_running(register_config, force_restart=force_restart)


def refresh_register_proxy_runtime(register_config: dict[str, Any] | None) -> dict[str, Any]:
    return REGISTER_MIHOMO_MANAGER.refresh(register_config)


def stop_register_proxy_runtime() -> dict[str, Any]:
    return REGISTER_MIHOMO_MANAGER.stop()


def resolve_register_worker_proxy(register_config: dict[str, Any] | None, worker_index: int) -> dict[str, Any]:
    resolved = normalize_register_runtime_config(register_config)
    mode = str(resolved.get("proxy_mode") or "direct").strip().lower()
    if mode == "direct":
        return {"mode": "direct", "proxy": "", "listener": None, "snapshot": None}
    manual_proxy = str(resolved.get("proxy") or "").strip()
    if mode == "manual":
        return {"mode": "manual", "proxy": manual_proxy, "listener": None, "snapshot": None}

    snapshot = ensure_register_proxy_runtime_ready(resolved)
    if not snapshot.get("running"):
        raise RuntimeError(str(snapshot.get("message") or "Mihomo 代理未就绪").strip() or "Mihomo 代理未就绪")
    listeners = snapshot.get("listeners") if isinstance(snapshot.get("listeners"), list) else []
    if not listeners:
        raise RuntimeError("Mihomo 已启动，但没有可用监听端口")
    slot = max(0, (max(1, int(worker_index or 1)) - 1) % len(listeners))
    listener = listeners[slot]
    proxy_url = str(listener.get("proxy_url") or "").strip()
    if not proxy_url:
        raise RuntimeError("Mihomo 监听端口缺少代理地址")
    return {"mode": "mihomo", "proxy": proxy_url, "listener": listener, "snapshot": snapshot}
