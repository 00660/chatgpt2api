from __future__ import annotations

import base64
import hashlib
import json
import random
import secrets
import string
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi import requests

from services.account_service import account_service
from services.proxy_service import ClearanceBundle, proxy_settings
from services.register import mail_provider
from services.register_mihomo_service import normalize_register_runtime_config, resolve_register_worker_proxy

base_dir = Path(__file__).resolve().parent
config = {
    "mail": {
        "request_timeout": 30,
        "wait_timeout": 30,
        "wait_interval": 2,
        "providers": [],
    },
    "scheduler": {
        "fetch_otp_url": "",
        "request_timeout": 8,
        "wait_timeout": 120,
        "wait_interval": 2,
    },
    "proxy": "",
    "proxy_mode": "direct",
    "mihomo": {},
    "total": 10,
    "threads": 3,
}
register_config_file = base_dir.parents[1] / "data" / "register.json"
try:
    saved_config = json.loads(register_config_file.read_text(encoding="utf-8"))
    config.update({key: saved_config[key] for key in ("mail", "scheduler", "proxy", "proxy_mode", "mihomo", "mimo", "total", "threads") if key in saved_config})
except Exception:
    pass
config = normalize_register_runtime_config(config)

auth_base = "https://auth.openai.com"
platform_base = "https://platform.openai.com"
login_oauth_client_id = "app_EMoamEEZ73f0CkXaXp7hrann"
login_oauth_redirect_uri = "http://localhost:1455/auth/callback"
platform_oauth_client_id = "app_2SKx67EdpoN0G6j64rFvigXD"
platform_oauth_redirect_uri = f"{platform_base}/auth/callback"
platform_oauth_audience = "https://api.openai.com/v1"
platform_auth0_client = "eyJuYW1lIjoiYXV0aDAtc3BhLWpzIiwidmVyc2lvbiI6IjEuMjEuMCJ9"
user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
sec_ch_ua = '"Google Chrome";v="145", "Not?A_Brand";v="8", "Chromium";v="145"'
sec_ch_ua_full_version_list = '"Chromium";v="145.0.0.0", "Not:A-Brand";v="99.0.0.0", "Google Chrome";v="145.0.0.0"'
default_timeout = 30
print_lock = threading.Lock()
stats_lock = threading.Lock()
stats = {"done": 0, "success": 0, "fail": 0, "start_time": 0.0}
register_log_sink = None

common_headers = {
    "accept": "application/json",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "content-type": "application/json",
    "dnt": "1",
    "origin": auth_base,
    "priority": "u=1, i",
    "sec-gpc": "1",
    "sec-ch-ua": sec_ch_ua,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": sec_ch_ua_full_version_list,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": user_agent,
}

navigate_headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "max-age=0",
    "connection": "keep-alive",
    "dnt": "1",
    "sec-gpc": "1",
    "sec-ch-ua": sec_ch_ua,
    "sec-ch-ua-arch": '"x86_64"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": sec_ch_ua_full_version_list,
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"10.0.0"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": user_agent,
}


def log(text: str, color: str = "") -> None:
    colors = {"red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m"}
    if register_log_sink:
        try:
            register_log_sink(text, color)
        except Exception:
            pass
    with print_lock:
        prefix = colors.get(color, "")
        suffix = "\033[0m" if prefix else ""
        print(f"{prefix}{datetime.now().strftime('%H:%M:%S')} {text}{suffix}")


def step(index: int, text: str, color: str = "") -> None:
    log(f"[任务{index}] {text}", color)


def _make_trace_headers() -> dict[str, str]:
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


from utils.pkce import generate_pkce as _generate_pkce  # noqa: F401


def _random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    value = list(
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(chars) for _ in range(max(0, length - 4)))
    )
    random.shuffle(value)
    return "".join(value)


def _random_name() -> tuple[str, str]:
    return random.choice(["James", "Robert", "John", "Michael", "David", "Mary", "Emma", "Olivia"]), random.choice(
        ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller"]
    )


def _random_birthdate() -> str:
    return f"{random.randint(1996, 2006):04d}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _response_json(resp) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _decode_jwt_payload(token: str) -> dict:
    try:
        payload = str(token or "").split(".")[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _response_debug_detail(resp, limit: int = 800) -> str:
    if resp is None:
        return ""
    data = _response_json(resp)
    parts = [
        f"url={str(getattr(resp, 'url', '') or '')[:300]}",
        f"content_type={str(getattr(resp, 'headers', {}).get('content-type') or '')}",
    ]
    for key in ("cf-ray", "x-request-id", "openai-processing-ms"):
        value = str(getattr(resp, "headers", {}).get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    if data:
        parts.append(f"json={json.dumps(data, ensure_ascii=False)[:limit]}")
    else:
        parts.append(f"body={str(getattr(resp, 'text', '') or '')[:limit]}")
    return ", ".join(parts)


def _is_cloudflare_challenge(resp) -> bool:
    if resp is None:
        return False
    try:
        status_code = int(getattr(resp, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status_code = 0
    if status_code not in (403, 503):
        return False
    text = str(getattr(resp, "text", "") or "").lower()
    return (
        "<title>just a moment" in text
        or "<title>attention required! | cloudflare" in text
        or "cf-chl-" in text
        or "__cf_chl_" in text
        or "cf-browser-verification" in text
    )


def _mail_config() -> dict:
    return {**config["mail"], "proxy": config["proxy"]}


def _authorize_landed_page(resp) -> str:
    """诊断用：粗判 authorize 之后落在哪个页面。返回 signup / login / "" 仅供日志。

    注意：email-verification / email_otp_verification 在注册和登录流程里都会出现，
    无法据此可靠区分，所以这里只用于打日志，绝不据此中断注册流程。
    """
    if resp is None:
        return ""
    final_url = str(getattr(resp, "url", "") or "").lower()
    data = _response_json(resp)
    page_type = ""
    page = data.get("page") if isinstance(data, dict) else None
    if isinstance(page, dict):
        page_type = str(page.get("type") or "").lower()
    if "create-account" in final_url or "signup" in final_url or "create_account" in page_type:
        return "signup"
    if "/log-in" in final_url or "/login" in final_url or page_type in {"login", "password_verification"}:
        return "login"
    return ""


def create_mailbox(username: str | None = None) -> dict:
    return mail_provider.create_mailbox(_mail_config(), username)


def _scheduler_config() -> dict:
    source = config.get("scheduler") if isinstance(config.get("scheduler"), dict) else {}
    return {
        "fetch_otp_url": "",
        "request_timeout": max(1, int(source.get("request_timeout") or config["mail"].get("request_timeout") or 8)),
        "wait_timeout": max(1, int(source.get("wait_timeout") or config["mail"].get("wait_timeout") or 120)),
        "wait_interval": max(1.0, float(source.get("wait_interval") or config["mail"].get("wait_interval") or 2)),
    }


def build_existing_mailbox(address: str, not_before: float | None = None) -> dict[str, Any]:
    email = str(address or "").strip().lower()
    if not email:
        raise RuntimeError("缺少邮箱地址")
    mailbox = mail_provider.get_existing_mailbox(_mail_config(), email)
    mailbox["not_before"] = float(not_before) if not_before is not None else time.time()
    return mailbox


def wait_for_code(mailbox: dict, label: str = "路由器注册取码") -> str | None:
    return mail_provider.wait_for_code(_mail_config(), mailbox)


from utils.sentinel import SentinelTokenGenerator, build_sentinel_token as _build_sentinel_token_tuple  # noqa: F401


def build_sentinel_token(session: requests.Session, device_id: str, flow: str) -> str:
    """请求 sentinel token，返回 sentinel header 字符串（兼容旧接口）。"""
    sentinel_val, _oai_sc_val = _build_sentinel_token_tuple(session, device_id, flow, user_agent=user_agent, sec_ch_ua=sec_ch_ua)
    return sentinel_val


def create_session(proxy: str = "") -> Any:
    kwargs = proxy_settings.build_session_kwargs(
        proxy=proxy,
        upstream=True,
        impersonate="chrome",
        verify=False,
    )
    return requests.Session(**kwargs)


def _apply_clearance_to_session(session: requests.Session, bundle: ClearanceBundle | None) -> None:
    if bundle is None:
        return
    if bundle.user_agent:
        session.headers["User-Agent"] = bundle.user_agent
        session.headers["user-agent"] = bundle.user_agent
    for name, value in bundle.cookies.items():
        try:
            session.cookies.set(name, value, domain=f".{bundle.target_host or 'openai.com'}")
            session.cookies.set(name, value, domain=bundle.target_host or "auth.openai.com")
        except Exception:
            continue


def _headers_with_clearance(
    headers: dict[str, str],
    target_url: str,
    proxy: str = "",
    user_agent_override: str = "",
) -> dict[str, str]:
    merged = proxy_settings.build_headers(
        headers=headers,
        target_url=target_url,
        proxy=proxy,
        upstream=True,
    )
    normalized = {str(key): str(value) for key, value in merged.items()}
    if user_agent_override:
        ua_key = next((key for key in normalized if key.lower() == "user-agent"), "user-agent")
        normalized[ua_key] = user_agent_override
    return normalized


def _cloudflare_block_message(resp, prefix: str = "被 Cloudflare 拦截", reason: str = "") -> str:
    status = getattr(resp, "status_code", "unknown")
    debug = _response_debug_detail(resp)
    reason = reason or "clearance 刷新失败或重试后仍失败，请更换 IP/代理重试"
    return f"{prefix}，{reason}: status={status}, {debug}"


def request_with_local_retry(session: requests.Session, method: str, url: str, retry_attempts: int = 3, **kwargs):
    last_error = ""
    for _ in range(max(1, retry_attempts)):
        try:
            return session.request(method.upper(), url, timeout=default_timeout, **kwargs), ""
        except Exception as error:
            last_error = str(error)
            time.sleep(1)
    return None, last_error


def validate_otp(session: requests.Session, device_id: str, code: str):
    headers = dict(common_headers)
    headers["referer"] = f"{auth_base}/email-verification"
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    resp, error = request_with_local_retry(session, "post", f"{auth_base}/api/accounts/email-otp/validate", json={"code": code}, headers=headers, verify=False)
    if resp is not None and resp.status_code == 200:
        return resp, ""
    headers["openai-sentinel-token"] = build_sentinel_token(session, device_id, "authorize_continue")
    resp, error = request_with_local_retry(session, "post", f"{auth_base}/api/accounts/email-otp/validate", json={"code": code}, headers=headers, verify=False)
    return resp, error


def extract_oauth_callback_params_from_url(url: str) -> dict[str, str] | None:
    if not url:
        return None
    try:
        params = parse_qs(urlparse(url).query)
    except Exception:
        return None
    code = str((params.get("code") or [""])[0]).strip()
    if not code:
        return None
    return {"code": code, "state": str((params.get("state") or [""])[0]).strip(), "scope": str((params.get("scope") or [""])[0]).strip()}


def request_platform_oauth_token(session: requests.Session, code: str, code_verifier: str) -> dict | None:
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "auth0-client": platform_auth0_client,
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": platform_base,
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": f"{platform_base}/",
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": user_agent,
    }
    resp = session.post(
        f"{auth_base}/api/accounts/oauth/token",
        headers=headers,
        json={
            "client_id": platform_oauth_client_id,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": platform_oauth_redirect_uri,
        },
        verify=False,
        timeout=60,
    )
    if resp.status_code != 200:
        print(resp.text)
        return None
    return _response_json(resp)


def exchange_platform_tokens_from_callback_url(session: requests.Session, code_verifier: str, callback_url: str) -> dict | None:
    callback_params = extract_oauth_callback_params_from_url(callback_url)
    if not callback_params:
        return None
    code = str(callback_params.get("code") or "").strip()
    if not code:
        return None
    tokens = request_platform_oauth_token(session, code, code_verifier)
    if not tokens:
        return None
    payload = _decode_jwt_payload(str(tokens.get("id_token") or "")) or _decode_jwt_payload(str(tokens.get("access_token") or ""))
    return {
        "email": str(payload.get("email") or "").strip(),
        "access_token": str(tokens.get("access_token") or "").strip(),
        "refresh_token": str(tokens.get("refresh_token") or "").strip(),
        "id_token": str(tokens.get("id_token") or "").strip(),
    }


def extract_oauth_callback_params_from_consent_session(session: requests.Session, consent_url: str, device_id: str) -> dict[str, str] | None:
    if consent_url.startswith("/"):
        consent_url = f"{auth_base}{consent_url}"
    current_url = consent_url
    for _ in range(10):
        response = session.get(current_url, headers=navigate_headers, verify=False, timeout=30, allow_redirects=False)
        callback_params = extract_oauth_callback_params_from_url(str(response.url)) or extract_oauth_callback_params_from_url(str(response.headers.get("Location") or "").strip())
        if callback_params:
            return callback_params
        location = str(response.headers.get("Location") or "").strip()
        if response.status_code not in (301, 302, 303, 307, 308) or not location:
            break
        current_url = f"{auth_base}{location}" if location.startswith("/") else location

    raw = session.cookies.get("oai-client-auth-session", domain=".auth.openai.com") or session.cookies.get("oai-client-auth-session")
    if not raw:
        return None
    try:
        first_part = raw.split(".")[0]
        padding = 4 - len(first_part) % 4
        if padding != 4:
            first_part += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(first_part))
        workspace_id = payload["workspaces"][0]["id"]
    except Exception:
        return None
    headers = dict(common_headers)
    headers["referer"] = consent_url
    headers["oai-device-id"] = device_id
    headers.update(_make_trace_headers())
    ws_resp = session.post(
        f"{auth_base}/api/accounts/workspace/select",
        json={"workspace_id": workspace_id},
        headers=headers,
        verify=False,
        timeout=30,
        allow_redirects=False,
    )
    callback_params = extract_oauth_callback_params_from_url(str(ws_resp.headers.get("Location") or "").strip())
    if callback_params:
        return callback_params
    ws_data = _response_json(ws_resp)
    orgs = ((ws_data.get("data") or {}).get("orgs") or []) if isinstance(ws_data, dict) else []
    if not orgs:
        return None
    org_id = str((orgs[0] or {}).get("id") or "").strip()
    project_id = str(((orgs[0] or {}).get("projects") or [{}])[0].get("id") or "").strip()
    if not org_id:
        return None
    org_headers = dict(common_headers)
    org_headers["referer"] = str(ws_data.get("continue_url") or consent_url)
    org_headers["oai-device-id"] = device_id
    org_headers.update(_make_trace_headers())
    body = {"org_id": org_id}
    if project_id:
        body["project_id"] = project_id
    org_resp = session.post(
        f"{auth_base}/api/accounts/organization/select",
        json=body,
        headers=org_headers,
        verify=False,
        timeout=30,
        allow_redirects=False,
    )
    return extract_oauth_callback_params_from_url(str(org_resp.headers.get("Location") or "").strip())


def exchange_platform_tokens(session: requests.Session, device_id: str, code_verifier: str, consent_url: str) -> dict | None:
    callback_params = extract_oauth_callback_params_from_consent_session(session, consent_url, device_id)
    if not callback_params:
        return None
    query = urlencode({key: value for key, value in callback_params.items() if value})
    callback_url = f"{platform_oauth_redirect_uri}?{query}" if query else ""
    return exchange_platform_tokens_from_callback_url(session, code_verifier, callback_url)


def _normalize_auth_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("/"):
        return f"{auth_base}{text}"
    return text


def _response_landed_on_error_page(resp: Any) -> bool:
    if resp is None:
        return False
    current_url = str(getattr(resp, "url", "") or "").strip().lower()
    if "/error" not in current_url:
        return False
    body = str(getattr(resp, "text", "") or "")[:2000].lower()
    return "invalid_auth_step" in body or "invalid authorization step" in body or True


class PlatformRegistrar:
    def __init__(self, proxy: str = "") -> None:
        self.proxy = str(proxy or "").strip()
        self.session = create_session(self.proxy)
        self.clearance_user_agent = ""
        self.clearance_failure_reason = ""
        self.device_id = str(uuid.uuid4())
        self.code_verifier = ""
        self.platform_auth_code = ""

    def close(self) -> None:
        self.session.close()

    def _reset_session(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
        self.session = create_session(self.proxy)
        self.clearance_user_agent = ""
        self.clearance_failure_reason = ""
        self.device_id = str(uuid.uuid4())
        self.code_verifier = ""
        self.platform_auth_code = ""

    def _navigate_headers(self, referer: str = "") -> dict[str, str]:
        headers = dict(navigate_headers)
        if referer:
            headers["referer"] = referer
        return headers

    def _flow_headers(self, referer: str, session: Any | None = None, device_id: str = "", flow: str = "") -> dict[str, str]:
        target_session = session or self.session
        target_device_id = str(device_id or self.device_id).strip() or self.device_id
        headers = dict(common_headers)
        headers["referer"] = referer
        headers["oai-device-id"] = target_device_id
        headers.update(_make_trace_headers())
        if flow:
            headers["openai-sentinel-token"] = build_sentinel_token(target_session, target_device_id, flow)
        return headers

    def _json_headers(self, referer: str) -> dict[str, str]:
        headers = dict(common_headers)
        headers["referer"] = referer
        headers["oai-device-id"] = self.device_id
        headers.update(_make_trace_headers())
        return headers

    def _refresh_cloudflare_clearance(self, target_url: str, index: int) -> ClearanceBundle | None:
        self.clearance_failure_reason = ""
        profile = proxy_settings.get_profile(proxy=self.proxy, upstream=True)
        if not profile.clearance_enabled:
            self.clearance_failure_reason = (
                "可尝试使用 FlareSolverr 清障方式，注意需要 Docker 部署 flaresolverr、privoxy、warp-proxy 等相关容器"
            )
            step(index, f"检测到 Cloudflare 拦截，{self.clearance_failure_reason}", "yellow")
            return None
        step(index, "检测到 Cloudflare 拦截，尝试刷新 clearance", "yellow")
        bundle = proxy_settings.refresh_clearance(
            target_url=target_url,
            proxy=self.proxy,
            force=True,
            upstream=True,
        )
        if bundle is not None:
            _apply_clearance_to_session(self.session, bundle)
            self.clearance_user_agent = bundle.user_agent or self.clearance_user_agent
            step(index, "Cloudflare clearance 刷新完成，重试当前请求", "yellow")
        else:
            self.clearance_failure_reason = "clearance 刷新未返回可用 Cookie，请检查 FlareSolverr URL、代理和出口 IP"
            step(index, f"Cloudflare clearance 刷新失败：{self.clearance_failure_reason}", "yellow")
        return bundle

    def _platform_authorize(self, email: str, index: int) -> None:
        step(index, "开始 platform authorize")
        self.session.cookies.set("oai-did", self.device_id, domain=".auth.openai.com")
        self.session.cookies.set("oai-did", self.device_id, domain="auth.openai.com")
        self.code_verifier, code_challenge = _generate_pkce()
        params = {
            "issuer": auth_base,
            "client_id": platform_oauth_client_id,
            "audience": platform_oauth_audience,
            "redirect_uri": platform_oauth_redirect_uri,
            "device_id": self.device_id,
            # 注册流程显式声明 signup：throwaway 域名 OpenAI 会自动当新账号走注册，
            # 但 @outlook.com/@hotmail.com 这类真实消费邮箱会被 login_or_signup 路由到登录分支，
            # 后续 user/register 落在错误的 auth step 上报 invalid_auth_step。
            "screen_hint": "signup",
            "max_age": "0",
            "login_hint": email,
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": platform_auth0_client,
        }
        target_url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"
        headers = self._navigate_headers(f"{platform_base}/")
        headers = _headers_with_clearance(headers, target_url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "get", target_url, headers=headers, allow_redirects=True, verify=False)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            retry_headers = _headers_with_clearance(self._navigate_headers(f"{platform_base}/"), target_url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "get", target_url, headers=retry_headers, allow_redirects=True, verify=False)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code != 200:
            err = _response_json(resp).get("error", {}) if resp is not None else {}
            detail = f": {err.get('code', '')} - {err.get('message', '')}".strip(" -") if err else ""
            debug = _response_debug_detail(resp)
            status = getattr(resp, "status_code", "unknown")
            raise RuntimeError(error or f"platform_authorize_http_{status}{detail}, {debug}")
        landed = _authorize_landed_page(resp)
        # 仅打日志，不据此中断：authorize 落地页无法可靠区分注册/登录，
        # 真正的判定交给 user/register（失败会 dump 完整响应）。
        step(index, f"platform authorize 完成[{landed or '?'}] url={str(getattr(resp, 'url', '') or '')[:160]}")

    def _register_user(self, email: str, password: str, index: int) -> None:
        step(index, "开始提交注册密码")
        url = f"{auth_base}/api/accounts/user/register"
        headers = self._json_headers(f"{auth_base}/create-account/password")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "username_password_create")
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "post", url, json={"username": email, "password": password}, headers=headers, verify=False)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = self._json_headers(f"{auth_base}/create-account/password")
            headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "username_password_create")
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "post", url, json={"username": email, "password": password}, headers=headers, verify=False)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code != 200:
            data = _response_json(resp) if resp is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                step(index, "注册失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "yellow")
            detail = f", detail={json.dumps(data, ensure_ascii=False)}" if data else ""
            raise RuntimeError(error or f"user_register_http_{getattr(resp, 'status_code', 'unknown')}{detail}")
        step(index, "提交注册密码完成")

    def _send_otp(self, index: int) -> None:
        step(index, "开始发送验证码")
        url = f"{auth_base}/api/accounts/email-otp/send"
        headers = _headers_with_clearance(self._navigate_headers(f"{auth_base}/create-account/password"), url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "get", url, headers=headers, allow_redirects=True, verify=False)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = _headers_with_clearance(self._navigate_headers(f"{auth_base}/create-account/password"), url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "get", url, headers=headers, allow_redirects=True, verify=False)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code not in (200, 302):
            raise RuntimeError(error or f"send_otp_http_{getattr(resp, 'status_code', 'unknown')}")
        step(index, "发送验证码完成")

    def _start_login_with_email_otp(self, email: str, index: int, session: Any, device_id: str) -> str:
        step(index, "开始进入邮箱验证码登录")
        url = f"{auth_base}/api/accounts/authorize/continue"
        headers = self._flow_headers(f"{auth_base}/log-in", session=session, device_id=device_id, flow="authorize_continue")
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(
            session,
            "post",
            url,
            json={"username": {"kind": "email", "value": email}, "screen_hint": "login"},
            headers=headers,
            allow_redirects=False,
            verify=False,
        )
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = self._flow_headers(f"{auth_base}/log-in", session=session, device_id=device_id, flow="authorize_continue")
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(
                session,
                "post",
                url,
                json={"username": {"kind": "email", "value": email}, "screen_hint": "login"},
                headers=headers,
                allow_redirects=False,
                verify=False,
            )
        if resp is None or resp.status_code != 200:
            detail = _response_json(resp) if resp is not None else {}
            suffix = f", detail={json.dumps(detail, ensure_ascii=False)}" if detail else ""
            raise RuntimeError(error or f"authorize_continue_http_{getattr(resp, 'status_code', 'unknown')}{suffix}")
        payload = _response_json(resp)
        continue_url = str(payload.get("continue_url") or "").strip()
        page_type = str(((payload.get("page") or {}).get("type")) or "").strip()
        step(index, f"登录入口完成: {page_type or 'unknown'}")
        return continue_url

    def _prepare_passwordless_login(self, session: Any, continue_url: str) -> tuple[str, Any]:
        candidates: list[str] = []
        remembered_url = _normalize_auth_url(continue_url)
        if remembered_url:
            candidates.append(remembered_url)
        candidates.extend((f"{auth_base}/log-in/password", f"{auth_base}/log-in", f"{auth_base}/log-in/passwordless"))
        last_resp = None
        seen: set[str] = set()
        for target in candidates:
            target = _normalize_auth_url(target)
            if not target or target in seen:
                continue
            seen.add(target)
            resp, _error = request_with_local_retry(
                session,
                "get",
                target,
                headers=self._navigate_headers(f"{auth_base}/log-in"),
                allow_redirects=True,
                verify=False,
            )
            last_resp = resp
            if resp is not None and getattr(resp, "status_code", 0) < 400 and not _response_landed_on_error_page(resp):
                return _normalize_auth_url(str(getattr(resp, "url", "") or "").strip()) or target, resp
        return remembered_url or f"{auth_base}/log-in/passwordless", last_resp

    def _send_login_otp(self, index: int, session: Any, device_id: str, continue_url: str) -> str:
        step(index, "开始发送登录验证码")
        login_referer, prepare_resp = self._prepare_passwordless_login(session, continue_url)
        url = f"{auth_base}/api/accounts/passwordless/send-otp"
        for include_flow in (True, False):
            headers = (
                self._flow_headers(login_referer, session=session, device_id=device_id, flow="passwordless_login_send_otp")
                if include_flow
                else self._flow_headers(login_referer, session=session, device_id=device_id)
            )
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(session, "post", url, headers=headers, allow_redirects=True, verify=False)
            if resp is not None and resp.status_code in (200, 204, 301, 302) and not _response_landed_on_error_page(resp):
                step(index, "登录验证码发送完成")
                return login_referer
            last_error = error or f"passwordless_send_otp_http_{getattr(resp, 'status_code', 'unknown')}"

        fallback_url = f"{auth_base}/api/accounts/email-otp/send"
        for referer in (login_referer, f"{auth_base}/log-in/passwordless", f"{auth_base}/log-in"):
            headers = _headers_with_clearance(self._navigate_headers(referer), fallback_url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(session, "get", fallback_url, headers=headers, allow_redirects=True, verify=False)
            if resp is not None and resp.status_code in (200, 204, 301, 302) and not _response_landed_on_error_page(resp):
                step(index, "登录验证码发送完成")
                return referer
            detail = _response_json(resp) if resp is not None else {}
            last_error = error or f"login_send_otp_http_{getattr(resp, 'status_code', 'unknown')}"
            if detail:
                last_error = f"{last_error}, detail={json.dumps(detail, ensure_ascii=False)}"
        if prepare_resp is not None and not last_error:
            last_error = f"passwordless_prepare_http_{getattr(prepare_resp, 'status_code', 'unknown')}"
        raise RuntimeError(last_error or "login_send_otp_failed")

    def _open_login_verify_page(self, referer: str, index: int, session: Any) -> None:
        step(index, "打开登录验证码页")
        resp, error = request_with_local_retry(
            session,
            "get",
            f"{auth_base}/email-verification",
            headers=self._navigate_headers(referer),
            allow_redirects=True,
            verify=False,
        )
        if resp is None or resp.status_code != 200:
            raise RuntimeError(error or f"open_login_verify_page_http_{getattr(resp, 'status_code', 'unknown')}")
        step(index, "登录验证码页已打开")

    def _establish_login_session_with_email_otp(self, email: str, index: int) -> Any:
        step(index, "开始建立邮箱验证码登录会话")
        last_error = ""
        for attempt in range(1, 4):
            login_session = create_session(self.proxy)
            try:
                _code_verifier, code_challenge = _generate_pkce()
                params = {
                    "response_type": "code",
                    "client_id": login_oauth_client_id,
                    "redirect_uri": login_oauth_redirect_uri,
                    "scope": "openid profile email offline_access",
                    "code_challenge": code_challenge,
                    "code_challenge_method": "S256",
                    "state": secrets.token_urlsafe(32),
                    "prompt": "login",
                }
                resp, error = request_with_local_retry(login_session, "get", f"{auth_base}/oauth/authorize?{urlencode(params)}", verify=False)
                if resp is None:
                    raise RuntimeError(error or "login_oauth_authorize_failed")
                login_device_id = str(login_session.cookies.get("oai-did") or self.device_id).strip() or self.device_id
                continue_url = self._start_login_with_email_otp(email, index, login_session, login_device_id)
                login_referer = self._send_login_otp(index, login_session, login_device_id, continue_url)
                self._open_login_verify_page(login_referer, index, login_session)
                step(index, "开始等待独立登录验证码")
                mailbox = build_existing_mailbox(email, time.time() - 2)
                code = wait_for_code(mailbox, "路由器补 login 取码")
                if not code:
                    raise RuntimeError("独立登录等待验证码超时")
                step(index, f"收到独立登录验证码: {code}")
                resp, reason = validate_otp(login_session, login_device_id, code)
                if resp is None or resp.status_code != 200:
                    data = _response_json(resp) if resp is not None else {}
                    message = str((data.get("error") or {}).get("message") or data.get("message") or "").strip()
                    raise RuntimeError(reason or f"独立登录验证码校验失败{': ' + message if message else ''}")
                step(index, "独立登录验证码校验完成")
                try:
                    self.session.close()
                except Exception:
                    pass
                self.session = login_session
                self.device_id = login_device_id
                return login_session
            except Exception as exc:
                last_error = str(exc).strip() or "独立登录失败"
                try:
                    login_session.close()
                except Exception:
                    pass
                if attempt < 3:
                    step(index, f"独立登录失败，第 {attempt}/3 次后重试: {last_error[:180]}", "yellow")
                    time.sleep(attempt)
        raise RuntimeError(last_error or "独立登录失败")

    def _login_and_exchange_tokens(self, email: str, index: int) -> dict:
        step(index, "开始独立登录换 token")
        self._establish_login_session_with_email_otp(email, index)
        current_device_id = str(self.session.cookies.get("oai-did") or self.device_id).strip() or self.device_id
        self.device_id = current_device_id
        code_verifier, code_challenge = _generate_pkce()
        params = {
            "issuer": auth_base,
            "client_id": platform_oauth_client_id,
            "audience": platform_oauth_audience,
            "redirect_uri": platform_oauth_redirect_uri,
            "device_id": current_device_id,
            "screen_hint": "login_or_signup",
            "max_age": "0",
            "login_hint": email,
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": platform_auth0_client,
        }
        url = f"{auth_base}/api/accounts/authorize?{urlencode(params)}"
        headers = _headers_with_clearance(self._navigate_headers(f"{platform_base}/"), url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "get", url, headers=headers, allow_redirects=False, verify=False)
        if resp is None:
            raise RuntimeError(error or "platform_login_authorize_failed")
        step(index, "平台 authorize 完成")
        continue_url = str(resp.headers.get("Location") or "").strip()
        if continue_url.startswith("/"):
            continue_url = f"{auth_base}{continue_url}"
        if not continue_url:
            response_url = str(getattr(resp, "url", "") or "").strip()
            if response_url and response_url != url:
                continue_url = response_url
        tokens = exchange_platform_tokens_from_callback_url(self.session, code_verifier, continue_url) if continue_url else None
        if not tokens:
            tokens = exchange_platform_tokens(self.session, current_device_id, code_verifier, continue_url or f"{auth_base}/sign-in-with-chatgpt/codex/consent")
        if not tokens:
            raise RuntimeError("token换取失败")
        step(index, "token 换取完成")
        return tokens

    def _validate_otp(self, code: str, index: int) -> None:
        step(index, f"开始校验验证码 {code}")
        resp, error = validate_otp(self.session, self.device_id, code)
        if resp is None or resp.status_code != 200:
            body = ""
            try:
                body = (resp.text or "")[:500] if resp is not None else ""
            except Exception:
                pass
            raise RuntimeError(error or f"validate_otp_http_{getattr(resp, 'status_code', 'unknown')}_body={body}")
        step(index, "验证码校验完成")

    def _create_account(self, name: str, birthdate: str, index: int) -> None:
        step(index, "开始创建账号资料")
        url = f"{auth_base}/api/accounts/create_account"
        headers = self._json_headers(f"{auth_base}/about-you")
        headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "oauth_create_account")
        headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
        resp, error = request_with_local_retry(self.session, "post", url, json={"name": name, "birthdate": birthdate}, headers=headers, verify=False)
        if _is_cloudflare_challenge(resp):
            bundle = self._refresh_cloudflare_clearance(auth_base, index)
            if bundle is None:
                raise RuntimeError(_cloudflare_block_message(resp, reason=self.clearance_failure_reason))
            headers = self._json_headers(f"{auth_base}/about-you")
            headers["openai-sentinel-token"] = build_sentinel_token(self.session, self.device_id, "oauth_create_account")
            headers = _headers_with_clearance(headers, url, self.proxy, self.clearance_user_agent)
            resp, error = request_with_local_retry(self.session, "post", url, json={"name": name, "birthdate": birthdate}, headers=headers, verify=False)
            if _is_cloudflare_challenge(resp):
                raise RuntimeError(_cloudflare_block_message(resp, "Cloudflare clearance 重试仍被拦截"))
        if resp is None or resp.status_code not in (200, 302):
            data = _response_json(resp) if resp is not None else {}
            if data.get("message") == "Failed to create account. Please try again.":
                step(index, "创建账号失败提示: 邮箱域名很可能因滥用被封禁，请更换邮箱域名", "yellow")
            detail = f", detail={json.dumps(data, ensure_ascii=False)}" if data else ""
            raise RuntimeError(error or f"create_account_http_{getattr(resp, 'status_code', 'unknown')}{detail}")
        data = _response_json(resp)
        callback_params = extract_oauth_callback_params_from_url(str(data.get("continue_url") or "").strip())
        self.platform_auth_code = str((callback_params or {}).get("code") or "").strip()
        step(index, "创建账号资料完成")

    def _exchange_registered_tokens(self, index: int) -> dict:
        step(index, "开始换 token")
        tokens = request_platform_oauth_token(self.session, self.platform_auth_code, self.code_verifier)
        if not tokens:
            raise RuntimeError("token换取失败")
        step(index, "token 换取完成")
        return tokens

    def register(self, index: int) -> dict:
        step(index, "开始创建邮箱")
        mailbox = create_mailbox()
        email = str(mailbox.get("address") or "").strip()
        if not email:
            mail_provider.release_mailbox(mailbox)
            raise RuntimeError("邮箱服务未返回 address")
        label = str(mailbox.get("label") or "")
        step(index, f"邮箱创建完成[{label}]: {email}")
        try:
            password = _random_password()
            first_name, last_name = _random_name()
            self._platform_authorize(email, index)
            self._register_user(email, password, index)
            self._send_otp(index)
            step(index, "开始等待注册验证码")
            code = wait_for_code(mailbox, "路由器注册取码")
            if not code:
                raise RuntimeError("等待注册验证码超时")
            step(index, f"收到注册验证码: {code}")
            self._validate_otp(code, index)
            self._create_account(f"{first_name} {last_name}", _random_birthdate(), index)
            tokens = self._exchange_registered_tokens(index)
        except Exception as error:
            mail_provider.mark_mailbox_result(mailbox, success=False, error=error)
            raise
        mail_provider.mark_mailbox_result(mailbox, success=True)
        return {
            "email": email,
            "password": password,
            "access_token": str(tokens.get("access_token") or "").strip(),
            "refresh_token": str(tokens.get("refresh_token") or "").strip(),
            "id_token": str(tokens.get("id_token") or "").strip(),
            "source_type": "web",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def register_queued(self, index: int, item: dict[str, Any]) -> dict:
        email = str(item.get("email") or item.get("address") or "").strip().lower()
        if not email:
            raise RuntimeError("队列邮箱缺少 email")
        password = str(item.get("password") or "").strip() or _random_password()
        mailbox = build_existing_mailbox(email, time.time() - 2)
        first_name, last_name = _random_name()
        step(index, f"开始注册队列邮箱: {email}")
        self._platform_authorize(email, index)
        self._register_user(email, password, index)
        mailbox["not_before"] = time.time() - 2
        self._send_otp(index)
        step(index, "开始等待队列邮箱注册验证码")
        code = wait_for_code(mailbox, "路由器注册取码")
        if not code:
            raise RuntimeError("等待队列邮箱注册验证码超时")
        step(index, f"收到队列邮箱注册验证码: {code}")
        self._validate_otp(code, index)
        self._create_account(f"{first_name} {last_name}", _random_birthdate(), index)
        tokens = self._exchange_registered_tokens(index)
        return {
            "email": email,
            "password": password,
            "access_token": str(tokens.get("access_token") or "").strip(),
            "refresh_token": str(tokens.get("refresh_token") or "").strip(),
            "id_token": str(tokens.get("id_token") or "").strip(),
            "source_type": "web",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def register_existing(self, index: int, email: str, password: str = "", mode: str = "auto") -> dict:
        target_email = str(email or "").strip().lower()
        if not target_email:
            raise RuntimeError("缺少待补跑邮箱地址")
        target_mode = str(mode or "auto").strip().lower()
        if target_mode not in {"auto", "register", "login"}:
            target_mode = "auto"
        target_password = str(password or "").strip() or _random_password()
        step(index, f"开始补跑邮箱: {target_email}")
        login_error = ""
        if target_mode in {"auto", "login"}:
            try:
                self._reset_session()
                tokens = self._login_and_exchange_tokens(target_email, index)
                return {
                    "email": target_email,
                    "password": target_password,
                    "access_token": str(tokens.get("access_token") or "").strip(),
                    "refresh_token": str(tokens.get("refresh_token") or "").strip(),
                    "id_token": str(tokens.get("id_token") or "").strip(),
                    "source_type": "web",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "login",
                }
            except Exception as exc:
                login_error = str(exc).strip() or "邮箱登录补登失败"
                if target_mode == "login":
                    raise
                step(index, f"邮箱登录补登失败，回退注册续跑: {login_error[:180]}", "yellow")

        self._reset_session()
        mailbox = build_existing_mailbox(target_email, time.time() - 2)
        first_name, last_name = _random_name()
        self._platform_authorize(target_email, index)
        self._register_user(target_email, target_password, index)
        mailbox["not_before"] = time.time() - 2
        self._send_otp(index)
        step(index, "开始等待补跑注册验证码")
        code = wait_for_code(mailbox, "路由器补注册取码")
        if not code:
            raise RuntimeError("等待补跑注册验证码超时")
        step(index, f"收到补跑注册验证码: {code}")
        self._validate_otp(code, index)
        self._create_account(f"{first_name} {last_name}", _random_birthdate(), index)
        tokens = self._exchange_registered_tokens(index)
        return {
            "email": target_email,
            "password": target_password,
            "access_token": str(tokens.get("access_token") or "").strip(),
            "refresh_token": str(tokens.get("refresh_token") or "").strip(),
            "id_token": str(tokens.get("id_token") or "").strip(),
            "source_type": "web",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "register",
            "login_error": login_error,
        }


def _format_proxy_binding_log(listener: dict[str, Any] | None) -> str:
    data = listener if isinstance(listener, dict) else {}
    selected_proxy = str(data.get("selected_proxy") or "").strip() or "DIRECT"
    public_ip = str(data.get("selected_proxy_public_ip") or "").strip()
    if public_ip:
        return f"{selected_proxy} @ {public_ip}"
    return f"{selected_proxy} @ 出口待探测"


def _resolve_worker_proxy(index: int, item: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(item, dict) and "proxy" in item:
        forced_proxy = str(item.get("proxy") or "").strip()
        return {"mode": "manual" if forced_proxy else "direct", "proxy": forced_proxy, "listener": None, "snapshot": None}
    return resolve_register_worker_proxy(config, index)


def worker(index: int, item: dict[str, Any] | None = None) -> dict:
    start = time.time()
    proxy_binding = _resolve_worker_proxy(index, item)
    registrar = PlatformRegistrar(str(proxy_binding.get("proxy") or ""))
    try:
        step(index, "任务启动")
        if proxy_binding.get("mode") == "mihomo":
            listener = proxy_binding.get("listener") if isinstance(proxy_binding.get("listener"), dict) else {}
            step(index, f"使用 Mihomo 代理：{_format_proxy_binding_log(listener)}", "yellow")
        elif proxy_binding.get("mode") == "manual" and proxy_binding.get("proxy"):
            step(index, f"使用手动代理：{proxy_binding.get('proxy')}", "yellow")
        result = registrar.register_queued(index, item) if isinstance(item, dict) else registrar.register(index)
        cost = time.time() - start
        access_token = str(result["access_token"])
        account_service.add_account_items([result])
        refresh_result = account_service.refresh_accounts([access_token])
        if refresh_result.get("errors"):
            step(index, f"账号已保存，刷新状态暂未成功，稍后可重试: {refresh_result['errors']}", "yellow")
        with stats_lock:
            stats["done"] += 1
            stats["success"] += 1
            avg = (time.time() - stats["start_time"]) / stats["success"]
        log(f'{result["email"]} 注册成功，本次耗时{cost:.1f}s，全局平均每个号注册耗时{avg:.1f}s', "green")
        return {"ok": True, "index": index, "result": result, "item": item or {}}
    except Exception as e:
        cost = time.time() - start
        with stats_lock:
            stats["done"] += 1
            stats["fail"] += 1
        log(f"任务{index} 注册失败，本次耗时{cost:.1f}s，原因: {e}", "red")
        return {"ok": False, "index": index, "error": str(e), "item": item or {}}
    finally:
        registrar.close()


def recover_existing_worker(index: int, item: dict[str, Any]) -> dict:
    start = time.time()
    proxy_binding = _resolve_worker_proxy(index, item)
    registrar = PlatformRegistrar(str(proxy_binding.get("proxy") or ""))
    email = str(item.get("email") or item.get("address") or "").strip().lower()
    password = str(item.get("password") or "").strip()
    mode = str(item.get("mode") or "auto").strip().lower() or "auto"
    try:
        step(index, f"补 login 任务启动: {email}")
        if proxy_binding.get("mode") == "mihomo":
            listener = proxy_binding.get("listener") if isinstance(proxy_binding.get("listener"), dict) else {}
            step(index, f"使用 Mihomo 代理：{_format_proxy_binding_log(listener)}", "yellow")
        elif proxy_binding.get("mode") == "manual" and proxy_binding.get("proxy"):
            step(index, f"使用手动代理：{proxy_binding.get('proxy')}", "yellow")
        result = registrar.register_existing(index, email, password=password, mode=mode)
        cost = time.time() - start
        access_token = str(result["access_token"])
        account_service.add_account_items([result])
        refresh_result = account_service.refresh_accounts([access_token])
        if refresh_result.get("errors"):
            step(index, f"账号已保存，刷新状态暂未成功，稍后可重试: {refresh_result['errors']}", "yellow")
        log(f'{result["email"]} 补 login 成功，本次耗时{cost:.1f}s', "green")
        return {"ok": True, "index": index, "result": result, "item": item}
    except Exception as e:
        cost = time.time() - start
        log(f"任务{index} 补 login 失败，本次耗时{cost:.1f}s，原因: {e}", "red")
        return {"ok": False, "index": index, "error": str(e), "item": item}
    finally:
        registrar.close()
