from __future__ import annotations

from typing import Any

from curl_cffi import requests as curl_requests


DEFAULT_TIMEOUT = 30.0

FINGERPRINT_HEADERS: dict[str, dict[str, str]] = {
    "chrome": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
        "sec-ch-ua": '"Chromium";v="145", "Google Chrome";v="145", "Not/A)Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    "edge": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
        "sec-ch-ua": '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
}


class HttpResponse:
    def __init__(self, raw: Any):
        self.raw = raw

    @property
    def is_success(self) -> bool:
        return 200 <= int(getattr(self.raw, "status_code", 0) or 0) < 400

    @property
    def status(self) -> int:
        return int(getattr(self.raw, "status_code", 0) or 0)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


class HttpClient:
    def __init__(
        self,
        *,
        proxy: str = "",
        verify: bool = True,
        fingerprint: str = "",
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        follow_redirects: bool = True,
    ) -> None:
        self.fingerprint = str(fingerprint or "").strip()
        self.follow_redirects = follow_redirects
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self.proxy = str(proxy or "").strip()
        self.verify = verify
        self.client = self._build_curl_client(headers or {})
        self.headers = self.client.headers
        self.cookies = self.client.cookies

    def request(
        self,
        method: str,
        url: str,
        *,
        follow_redirects: bool | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> HttpResponse:
        follow = self.follow_redirects if follow_redirects is None else follow_redirects
        request_kwargs = self._request_kwargs(kwargs)
        request_timeout = timeout or request_kwargs.pop("client_timeout", None) or self.timeout
        raw = self.client.request(
            method,
            url,
            allow_redirects=follow,
            timeout=float(request_timeout),
            **request_kwargs,
            **kwargs,
        )
        return HttpResponse(raw)

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        self.client.close()

    def _build_curl_client(self, headers: dict[str, str]):
        kwargs: dict[str, Any] = {"verify": self.verify}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        if self.fingerprint:
            kwargs["impersonate"] = self.fingerprint
        session = curl_requests.Session(**kwargs)
        session.headers.update(browser_headers(self.fingerprint))
        session.headers.update(headers)
        return session

    def _request_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {}
        proxy = str(kwargs.pop("proxy", "") or "")
        fingerprint = str(kwargs.pop("fingerprint", "") or "")
        verify = kwargs.pop("verify", None)
        headers = kwargs.pop("base_headers", None)
        request_headers = kwargs.pop("headers", None)
        client_timeout = kwargs.pop("client_timeout", None)

        if proxy:
            request_kwargs["proxy"] = proxy
        if verify is not None:
            request_kwargs["verify"] = bool(verify)
        if fingerprint:
            request_kwargs["impersonate"] = fingerprint
        if client_timeout:
            request_kwargs["client_timeout"] = float(client_timeout)

        merged_headers = browser_headers(fingerprint)
        merged_headers.update(headers or {})
        merged_headers.update(request_headers or {})
        if merged_headers:
            request_kwargs["headers"] = merged_headers
        return request_kwargs

def browser_headers(fingerprint: str = "") -> dict[str, str]:
    value = str(fingerprint or "").strip().lower()
    if value.startswith("edge"):
        return dict(FINGERPRINT_HEADERS["edge"])
    if value.startswith("chrome"):
        return dict(FINGERPRINT_HEADERS["chrome"])
    return {}


http_client = HttpClient()
