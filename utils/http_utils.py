from __future__ import annotations

from typing import Any

from curl_cffi import requests


class HttpClient:
    """基于 curl_cffi 的简单 HTTP 封装。"""

    def __init__(self, url: str, options: dict[str, Any] | None = None) -> None:
        """初始化请求地址和可选请求参数。"""
        self.url = url
        self.options = options or {}

    def post_json(
        self,
        body: dict[str, Any],
        headers: dict[str, object],
    ):
        """发送 JSON POST 请求。"""
        kwargs: dict[str, Any] = {
            "json": body,
            "headers": headers,
            "timeout": self.options.get("timeout", 1200),
            "verify": self.options.get("verify", True),
            "impersonate": self.options.get("impersonate", "chrome"),
        }
        proxy = self.options.get("proxy")
        if proxy:
            kwargs["proxy"] = proxy
        return requests.post(self.url, **kwargs)
