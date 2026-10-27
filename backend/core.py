"""Image-only embedding index with resumable writes and exact cosine retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from backend.billing import cost_cny
from backend.client import ModelCallError, call_embeddings
from try_embedding import BASE_URL, MODEL, image_input

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class ServiceError(Exception):
    """A diagnostic that is safe to show in the renderer."""


def normalize(vector: list[float]) -> list[float]:
    if not vector or any(not math.isfinite(value) for value in vector):
        raise ServiceError("模型返回了无效向量。")
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        raise ServiceError("模型返回了零向量。")
    return [value / norm for value in vector]


class SearchService:
    def __init__(self, data_dir: Path = DATA):
        load_dotenv(ROOT / ".env", override=False)
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = os.getenv("DASHSCOPE_BASE_HTTP_API_URL", BASE_URL).rstrip("/")
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.model = MODEL
        self.config = {"model": self.model, "base_url": self.base_url, "enable_fusion": False, "dimension": "default"}
        self.model_key = hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()
        self.db = sqlite3.connect(self.data_dir / "index.sqlite3")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS embeddings (
                image_id TEXT NOT NULL, model_key TEXT NOT NULL, sha256 TEXT NOT NULL,
                dimension INTEGER NOT NULL, vector TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(image_id, model_key)
            );
            CREATE TABLE IF NOT EXISTS queries (
                query_key TEXT PRIMARY KEY, vector TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_calls (
                id INTEGER PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
                input_tokens INTEGER, image_tokens INTEGER, total_tokens INTEGER
            );
        """)

    def close(self) -> None:
        self.db.close()

    def photos(self) -> list[dict]:
        try:
            return json.loads((self.data_dir / "manifest.json").read_text(encoding="utf-8"))["photos"]
        except FileNotFoundError:
            return []

    def image_path(self, photo: dict) -> Path:
        path = (self.data_dir / photo["path"]).resolve()
        if self.data_dir.resolve() not in path.parents:
            raise ServiceError("图片路径不在图库目录内。")
        return path

    def ready_vectors(self, photos: list[dict]) -> dict[str, list[float]]:
        hashes = {photo["id"]: photo["sha256"] for photo in photos}
        return {
            image_id: json.loads(vector)
            for image_id, digest, vector in self.db.execute(
                "SELECT image_id, sha256, vector FROM embeddings WHERE model_key = ?", (self.model_key,)
            )
            if hashes.get(image_id) == digest
        }

    def status(self) -> dict:
        photos = self.photos()
        vectors = self.ready_vectors(photos)
        totals = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(image_tokens),0), COALESCE(SUM(total_tokens),0) FROM api_calls"
        ).fetchone()
        usage = dict(zip(("calls", "input_tokens", "image_tokens", "total_tokens"), totals))
        usage["list_price_cost_cny"] = cost_cny(usage["input_tokens"], usage["image_tokens"])
        return {
            "total": len(photos), "indexed": len(vectors),
            "categories": len({photo["category"] for photo in photos}),
            "media_types": {kind: sum(photo.get("media_type", "photo") == kind for photo in photos) for kind in ("photo", "screenshot", "illustration")},
            "dimension": len(next(iter(vectors.values()))) if vectors else None,
            "has_key": bool(self.api_key), "model": self.model,
            "usage": usage,
        }

    def embed(self, inputs: list[dict], *, kind: str) -> list[list[float]]:
        try:
            response = call_embeddings(inputs, model=self.model, base_url=self.base_url,
                                       api_key=self.api_key, kind=kind)
        except ModelCallError as exc:
            raise ServiceError(str(exc)) from None
        items = sorted(response["output"]["embeddings"], key=lambda item: item["index"])
        if [item["index"] for item in items] != list(range(len(inputs))):
            raise ServiceError("模型返回的向量数量或索引与输入不一致。")
        vectors = [normalize(item["embedding"]) for item in items]
        if len({len(vector) for vector in vectors}) != 1:
            raise ServiceError("模型返回的向量维度不一致。")
        usage = response.get("usage") or {}
        self.db.execute(
            "INSERT INTO api_calls(kind, created_at, input_tokens, image_tokens, total_tokens) VALUES (?, ?, ?, ?, ?)",
            (kind, datetime.now(timezone.utc).isoformat(), usage.get("input_tokens", 0), usage.get("image_tokens", 0), usage.get("total_tokens", 0)),
        )
        self.db.commit()
        return vectors

    def index(self, progress: Callable[[dict], None] = lambda _: None, *, batch_size: int = 5) -> dict:
        photos = self.photos()
        if not photos:
            raise ServiceError("图库为空，请先运行 npm run download:demo 下载测试图片。")
        if not 1 <= batch_size <= 10:
            raise ServiceError("图片入库批量必须在 1 到 10 之间。")
        ready = self.ready_vectors(photos)
        pending = [photo for photo in photos if photo["id"] not in ready]
        done = len(ready)
        progress({"done": done, "total": len(photos)})
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            for photo in batch:
                if hashlib.sha256(self.image_path(photo).read_bytes()).hexdigest() != photo["sha256"]:
                    raise ServiceError(f"图片 {photo['id']} 与清单不符，请重新下载。")
            # No labels, captions, titles or filenames are sent to the model.
            vectors = self.embed([{"image": image_input(str(self.image_path(photo)))} for photo in batch], kind="index")
            for photo, vector in zip(batch, vectors):
                self.db.execute(
                    "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?, ?)",
                    (photo["id"], self.model_key, photo["sha256"], len(vector), json.dumps(vector), datetime.now(timezone.utc).isoformat()),
                )
            self.db.commit()
            done += len(batch)
            progress({"done": done, "total": len(photos)})
        return self.status()

    def query_vectors(self, queries: list[str]) -> list[list[float]]:
        keys = [hashlib.sha256(f"{self.model_key}\n{query}".encode()).hexdigest() for query in queries]
        cache = {}
        for key in set(keys):
            row = self.db.execute("SELECT vector FROM queries WHERE query_key = ?", (key,)).fetchone()
            if row:
                cache[key] = json.loads(row[0])
        missing = list(dict.fromkeys(key for key in keys if key not in cache))
        texts = dict(zip(keys, queries))
        for offset in range(0, len(missing), 20):
            batch = missing[offset:offset + 20]
            vectors = self.embed([{"text": texts[key]} for key in batch], kind="query")
            for key, vector in zip(batch, vectors):
                cache[key] = vector
                self.db.execute("INSERT OR REPLACE INTO queries VALUES (?, ?)", (key, json.dumps(vector)))
            self.db.commit()
        return [cache[key] for key in keys]

    def search(self, query: str, *, limit: int = 12, media_type: str = "all") -> dict:
        query = query.strip()
        if not query or len(query) > 1000:
            raise ServiceError("请输入 1 到 1000 个字符的图片描述。")
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ServiceError("返回数量必须在 1 到 100 之间。")
        if media_type not in ("all", "photo", "screenshot", "illustration"):
            raise ServiceError("无效的图片类型。")
        started = time.perf_counter()
        photos = [photo for photo in self.photos() if media_type == "all" or photo.get("media_type", "photo") == media_type]
        vectors = self.ready_vectors(photos)
        if not vectors:
            raise ServiceError("尚未建立图片索引，请先点击「建立索引」。")
        before = self.db.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
        query_vector = self.query_vectors([query])[0]
        after = self.db.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
        usage = None
        if after > before:
            row = self.db.execute("SELECT input_tokens, image_tokens, total_tokens FROM api_calls ORDER BY id DESC LIMIT 1").fetchone()
            usage = dict(zip(("input_tokens", "image_tokens", "total_tokens"), row))
        if any(len(vector) != len(query_vector) for vector in vectors.values()):
            raise ServiceError("查询和图片向量维度不一致，请检查模型配置并重新入库。")
        scored = [
            dict(photo, score=sum(x * y for x, y in zip(query_vector, vectors[photo["id"]])))
            for photo in photos if photo["id"] in vectors
        ]
        scored.sort(key=lambda photo: photo["score"], reverse=True)
        return {"query": query, "results": scored[:limit], "searched": len(vectors), "media_type": media_type, "api_called": after > before, "usage": usage, "elapsed_ms": round((time.perf_counter() - started) * 1000)}
