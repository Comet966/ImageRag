"""Run real Chinese text→image retrieval, with labels used only for scoring."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core import SearchService

CASES = [
    ("一只猫", "Cat"), ("一只狗", "Dog"),
    ("一架飞机", "Airplane"), ("一辆自行车", "Bicycle"),
    ("一份披萨", "Pizza"), ("一杯咖啡", "Coffee cup"),
    ("盛开的花朵", "Flower"), ("桌上的笔记本电脑", "Laptop"),
    ("书架上的书", "Book"), ("一个背包", "Backpack"),
    ("一把吉他", "Guitar"), ("一串香蕉", "Banana"),
    ("一辆公交车", "Bus"), ("水里的鸭子", "Duck"),
    ("一只蝴蝶", "Butterfly"), ("一个喷泉", "Fountain"),
    ("有人在游泳池里游泳", "Swimming pool"), ("一张床", "Bed"),
    ("一个生日蛋糕", "Cake"), ("一把雨伞", "Umbrella"),
    ("手机上的应用界面截图", "Mobile screenshot"), ("Windows电脑软件的截图", "windows"),
    ("一个购物网站的截图", "shop"), ("代码托管网站的页面截图", "gitlab"),
    ("论坛网站的页面截图", "forum"), ("卡通漫画", "Illustration"),
    ("动漫人物插画", "Anime illustration"), ("黑白线条漫画", "Line art cartoons"),
    ("一只大象", "Elephant"), ("一只熊猫", "Panda"),
    ("一架钢琴", "Piano"), ("一座城堡", "Castle"),
]


def main():
    service = SearchService()
    try:
        status = service.status()
        calls_before = status["usage"]["calls"]
        if status["indexed"] != 300 or status["total"] != 300:
            raise RuntimeError("验收需要 300 张图片全部入库。")
        # Batch only the text queries; images have already been indexed independently.
        service.query_vectors([query for query, _ in CASES])
        results = []
        for query, label in CASES:
            result = service.search(query, limit=5)
            relevant = [label in photo["labels"] for photo in result["results"]]
            first_rank = next((i + 1 for i, value in enumerate(relevant) if value), None)
            row = {
                "query": query, "expected_label": label,
                "top1_hit": relevant[0], "top5_hit": any(relevant), "first_relevant_rank": first_rank,
                "results": [{key: photo[key] for key in ("id", "title", "category_en", "labels", "score", "source_url")} for photo in result["results"]],
            }
            results.append(row)
            print(f"{query} → {result['results'][0]['title']} · {result['results'][0]['score']:.4f} · first relevant: {first_rank}", flush=True)
        final_usage = service.status()["usage"]
        calls_made = final_usage["calls"] - calls_before
        report = {
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "model_config": service.config,
            "images": status["total"], "categories": status["categories"], "queries": len(CASES),
            "method": "Exact cosine search over image-only embeddings. Source labels and curated media types used only after retrieval to score category hits; this is a small smoke evaluation, not a general benchmark.",
            "top1_hits": sum(row["top1_hit"] for row in results),
            "top5_hits": sum(row["top5_hit"] for row in results),
            "mode": "online query encoding" if calls_made else "replay of real model-produced cached vectors",
            "model_calls_during_run": calls_made,
            "usage": final_usage,
            "results": results,
        }
        target = ROOT / "outputs" / "retrieval-evaluation.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Top-1: {report['top1_hits']}/{len(CASES)}, Top-5: {report['top5_hits']}/{len(CASES)}")
        print(f"报告：{target}")
    finally:
        service.close()


if __name__ == "__main__":
    main()
