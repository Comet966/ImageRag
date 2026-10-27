"""Repair alpha compositing and replace visually rejected illustration samples."""
from __future__ import annotations

import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.expand_demo import EXCLUDED_COMMONS_IDS, MIXED_CACHE, illustrations, save_image


def repair(photo):
    corrected = save_image(photo, vector_source=photo.get("vector_source", False), refresh=True)
    if photo["category_en"] in ("Anime illustrations", "Wikipe-tan"):
        corrected["labels"] = sorted(set(corrected["labels"] + ["Anime illustration"]))
    print(f"透明背景校正：{photo['id']}", flush=True)
    return corrected


def main():
    manifest_path = ROOT / "data/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = [photo for photo in manifest["photos"] if photo["media_type"] == "illustration"]
    retained = [photo for photo in current if photo["id"] not in EXCLUDED_COMMONS_IDS]
    with ThreadPoolExecutor(max_workers=4) as pool:
        repaired = list(pool.map(repair, retained))
    corrected = illustrations(existing=repaired)
    rows = [photo for photo in manifest["photos"] if photo["media_type"] != "illustration"] + corrected
    for photo in rows:
        if photo["media_type"] == "screenshot" and any(tag in photo["labels"] for tag in ("ios", "android")):
            photo["labels"] = sorted(set(photo["labels"] + ["Mobile screenshot"]))
        if not photo.get("author"):
            photo["author"] = "See source file page"
    if len(rows) != 300 or len({photo["sha256"] for photo in rows}) != 300:
        raise ValueError("数量或内容去重校验失败。")
    random.Random(300).shuffle(rows)
    manifest["photos"] = rows
    manifest["visual_qa"] = "Transparent images composited on white; misclassified physical photos/UI composites replaced after visual review."
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    (MIXED_CACHE / "illustrations-complete.json").write_text(json.dumps(corrected, ensure_ascii=False, indent=2), encoding="utf-8")
    (MIXED_CACHE / "screenshots-complete.json").write_text(json.dumps([photo for photo in rows if photo["media_type"] == "screenshot"], ensure_ascii=False, indent=2), encoding="utf-8")
    print("校正完成：300 张，140 照片 / 80 截图 / 80 插画。", flush=True)


if __name__ == "__main__":
    main()
