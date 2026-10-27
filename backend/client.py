"""Direct model requests with an offline-test guard and no automatic retries."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import requests



class ModelCallError(Exception):
    """A credential-free diagnostic safe for UI presentation."""


def call_embeddings(
    inputs: list[dict], *, model: str, base_url: str, api_key: str,
    kind: str,
) -> dict:
    if not api_key:
        raise ModelCallError("请先在项目 .env 中配置 DASHSCOPE_API_KEY，再重启程序。")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelCallError("模型服务地址必须是有效的 HTTPS 基础地址。")
    if os.getenv("IMAGERAG_NO_API") == "1":
        raise ModelCallError("当前为离线验收模式，禁止调用模型 API。")
    try:
        # requests' default adapter does not retry. Redirects are also disabled.
        response = requests.post(
            base_url.rstrip("/") + "/services/embeddings/multimodal-embedding/multimodal-embedding",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": {"contents": inputs}, "parameters": {"enable_fusion": False}},
            timeout=(15, 60), allow_redirects=False,
        )
    except requests.RequestException:
        raise ModelCallError("模型请求连接失败或超时，未自动重试。请检查网络后重试。") from None
    if response.status_code != 200:
        # Never echo response bodies: they may include credentials or input data.
        request_id = response.headers.get("x-request-id", "unknown")
        raise ModelCallError(f"模型调用失败：HTTP {response.status_code}，request_id={request_id}。未自动重试。")
    try:
        result = response.json()
    except ValueError:
        raise ModelCallError("模型已返回响应，但内容不是有效 JSON；未自动重试。") from None
    if not isinstance(result, dict):
        raise ModelCallError("模型已返回响应，但返回格式异常；未自动重试。")
    return result
