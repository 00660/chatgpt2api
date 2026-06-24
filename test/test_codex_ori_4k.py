#!/usr/bin/env python3
# 直接调用 ChatGPT Codex 原生接口生成 4K 图片。

import json
import time
import unittest

import httpx

from test.utils import save_image

ACCESS_TOKEN = ""


def parse_events(response: httpx.Response) -> list[dict]:
    if "application/json" in response.headers.get("content-type", ""):
        return [response.json()]
    events = []
    for line in response.text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                events.append(json.loads(data))
    return events


def find_images(value):
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call" and isinstance(value.get("result"), str):
            result = value["result"].strip()
            return [result.split(",", 1)[1] if result.startswith("data:image/") else result]
        return [image for item in value.values() for image in find_images(item)]
    if isinstance(value, list):
        return [image for item in value for image in find_images(item)]
    return []


class Codex4KTests(unittest.TestCase):
    def test_codex_v1_4k(self) -> None:
        if not ACCESS_TOKEN.strip():
            self.skipTest("ACCESS_TOKEN is required")

        start_time = time.time()
        body = {
            "model": "gpt-5.5",
            "instructions": "Use the image_generation tool to create exactly one image for the user's request. Return the generated image result.",
            "store": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "A highly detailed square 2K image of a quiet futuristic library at sunrise"}]}],
            "tools": [{"type": "image_generation", "model": "gpt-image-2", "action": "generate", "size": "3840x2160", "quality": "auto", "output_format": "png"}],
            "tool_choice": {"type": "image_generation"},
            "stream": True,
        }
        response = httpx.post(
            "https://chatgpt.com/backend-api/codex/responses",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
            json=body,
            timeout=1200,
        )
        if response.status_code >= 400:
            self.fail(f"HTTP {response.status_code}: {response.text[:1000]}")

        images = find_images(parse_events(response))
        self.assertTrue(images, "No image result found in response")
        print(f"saved {save_image(images[0], 'codex_ori_v1_4k')}")
        print(f"total time: {time.time() - start_time:.2f} seconds")

    def test_codex_v2_4k(self) -> None:
        if not ACCESS_TOKEN.strip():
            self.skipTest("ACCESS_TOKEN is required")

        start_time = time.time()
        response = httpx.post(
            "https://chatgpt.com/backend-api/codex/images/generations",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
            json={"prompt": "A highly detailed square 2K image of a quiet futuristic library at sunrise", "model": "gpt-image-2", "size": "3840x2160", "quality": "auto", "output_format": "png"},
            timeout=1200,
        )
        if response.status_code >= 400:
            self.fail(f"HTTP {response.status_code}: {response.text[:1000]}")

        data = response.json()
        item = (data.get("data") or [{}])[0]
        image = item.get("b64_json") or item.get("base64") or item.get("image") or data.get("result") or data.get("image") or ""
        if isinstance(image, str) and image.startswith("data:image/"):
            image = image.split(",", 1)[1]
        self.assertTrue(image, "No image result found in response")
        print(f"saved {save_image(image, 'codex_ori_v2_4k')}")
        print(f"total time: {time.time() - start_time:.2f} seconds")


if __name__ == "__main__":
    unittest.main()
