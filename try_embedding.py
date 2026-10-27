"""Probe Qwen's hosted multimodal embeddings without printing credentials."""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from backend.client import ModelCallError, call_embeddings

ROOT = Path(__file__).resolve().parent
MODEL = "qwen3-vl-embedding"
BASE_URL = "https://cn-beijing.maas.qianwenaiapi.com/api/v1"


def image_input(source: str) -> str:
    if source.startswith(("https://", "http://")):
        return source
    path = Path(source).expanduser().resolve()
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("图片不能超过 10 MB。")
    mime = mimetypes.guess_type(path.name)[0]
    if not mime or not mime.startswith("image/"):
        raise ValueError("无法识别图片类型，请使用 JPG、PNG、WEBP 等图片。")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("返回的向量维度不一致。")
    denominator = math.sqrt(sum(x * x for x in left) * sum(y * y for y in right))
    if not denominator:
        raise ValueError("API 返回了零向量。")
    return sum(x * y for x, y in zip(left, right)) / denominator


def main() -> int:
    parser = argparse.ArgumentParser(description="测试阿里云中文/图片向量 API")
    parser.add_argument("--text", action="append", help="中文查询，可重复传入")
    parser.add_argument("--image", action="append", help="本地图片路径或公网图片 URL，可重复传入")
    parser.add_argument("--output", type=Path, help="可选：保存完整向量和模型配置到 JSON")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        print("尚未配置密钥：请在项目 .env 中填写 DASHSCOPE_API_KEY，或设置同名环境变量。", file=sys.stderr)
        return 2

    texts = args.text or ([] if args.image else ["通用多模态表征模型示例"])
    if any(not text.strip() for text in texts):
        parser.error("文字输入不能为空。")
    images = args.image or []
    if len(texts) + len(images) > 20 or len(images) > 10:
        parser.error("每次最多 20 条输入，其中图片最多 10 张。")

    try:
        inputs = [{"text": text} for text in texts]
        inputs.extend({"image": image_input(source)} for source in images)
        base_url = os.getenv("DASHSCOPE_BASE_HTTP_API_URL", BASE_URL).rstrip("/")
        # Independent vectors: each query and image must remain separately searchable.
        response = call_embeddings(inputs, model=MODEL, base_url=base_url, api_key=api_key, kind="probe")
        items = sorted(response["output"]["embeddings"], key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(len(inputs))):
            raise ValueError("API 返回的向量数量或索引与输入不匹配。")
        vectors = [item["embedding"] for item in items]
        if any(not vector or any(not math.isfinite(x) for x in vector) for vector in vectors):
            raise ValueError("API 返回了空向量或非有限数值。")
        labels = [f"文字 {i + 1}" for i in range(len(texts))]
        labels.extend(f"图片 {i + 1}" for i in range(len(images)))
        print(f"调用成功：{MODEL}")
        for label, vector in zip(labels, vectors):
            print(f"{label}：{len(vector)} 维，前 5 个数值 {vector[:5]}")
        print("用量：", json.dumps(response.get("usage"), ensure_ascii=False))
        if len(vectors) > 1:
            print("余弦相似度（不是匹配概率）：")
            for i, left in enumerate(vectors):
                for j in range(i + 1, len(vectors)):
                    print(f"  {labels[i]} ↔ {labels[j]}：{cosine(left, vectors[j]):.4f}")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({
                "model": MODEL,
                "base_url": base_url,
                "enable_fusion": False,
                "inputs": [{"text": text} for text in texts] + [{"image_source": source} for source in images],
                "embeddings": items,
                "usage": response.get("usage"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"结果已保存：{args.output.resolve()}")
    except ModelCallError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"处理失败（{type(exc).__name__}）；请检查文件、网络及返回格式。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
