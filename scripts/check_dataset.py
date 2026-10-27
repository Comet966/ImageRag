"""Verify the downloaded dataset and model index without any network access."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core import SearchService


def main():
    photos = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))["photos"]
    if len(photos) != 300 or len({photo["id"] for photo in photos}) != 300:
        raise ValueError("测试图片必须为 300 张，ID 不重复。")
    hashes = set()
    for photo in photos:
        path = ROOT / "data" / photo["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != photo["sha256"] or digest in hashes:
            raise ValueError(f"图片内容不匹配或重复：{photo['id']}")
        hashes.add(digest)
        with Image.open(path) as image:
            image.load()
            if image.size != (photo["width"], photo["height"]):
                raise ValueError(f"分辨率与清单不符：{photo['id']}")
            if max(image.size) < 960 or min(image.size) < 320:
                raise ValueError(f"分辨率不足：{photo['id']}")
        with Image.open(ROOT / "data" / photo["thumbnail"]) as image:
            image.load()
        if not all(photo.get(key) for key in ("source_url", "download_url", "original_url", "author", "license")):
            raise ValueError(f"图片缺少来源信息：{photo['id']}")
    service = SearchService()
    try:
        status = service.status()
    finally:
        service.close()
    if status["indexed"] != 300:
        raise ValueError("有图片尚未入库。")
    report = {
        "images": len(photos), "media_types": dict(Counter(photo.get("media_type", "photo") for photo in photos)), "unique_content_hashes": len(hashes),
        "categories": dict(Counter(photo["category"] for photo in photos)),
        "long_edge_range": [min(max(photo["width"], photo["height"]) for photo in photos), max(max(photo["width"], photo["height"]) for photo in photos)],
        "short_edge_range": [min(min(photo["width"], photo["height"]) for photo in photos), max(min(photo["width"], photo["height"]) for photo in photos)],
        "all_originals_and_thumbnails_decoded": True, "all_attributions_present": True,
        "indexed": status["indexed"], "dimension": status["dimension"],
        "network_requests": 0,
    }
    target = ROOT / "outputs/dataset-check.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
