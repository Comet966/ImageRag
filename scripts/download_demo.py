"""Download a reproducible, attributed 100-photo Open Images validation subset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"
SOURCES = {
    "classes.csv": "https://storage.googleapis.com/openimages/v5/class-descriptions-boxable.csv",
    "labels.csv": "https://storage.googleapis.com/openimages/v5/validation-annotations-human-imagelabels-boxable.csv",
    "images.csv": "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv",
}
# 20 × 3 + 20 × 2 = 100. Labels are for sampling/evaluation, never for retrieval.
TARGETS = [
    ("Cat", "猫"), ("Dog", "狗"), ("Bird", "鸟"), ("Horse", "马"),
    ("Bicycle", "自行车"), ("Car", "汽车"), ("Bus", "公交车"), ("Motorcycle", "摩托车"),
    ("Airplane", "飞机"), ("Boat", "船"), ("Train", "火车"), ("Truck", "卡车"),
    ("Pizza", "披萨"), ("Cake", "蛋糕"), ("Bread", "面包"), ("Apple", "苹果"),
    ("Banana", "香蕉"), ("Flower", "花"), ("Tree", "树木"), ("House", "房屋"),
    ("Chair", "椅子"), ("Couch", "沙发"), ("Bed", "床"), ("Table", "桌子"),
    ("Laptop", "笔记本电脑"), ("Mobile phone", "手机"), ("Book", "书籍"), ("Clock", "钟表"),
    ("Backpack", "背包"), ("Guitar", "吉他"), ("Umbrella", "雨伞"), ("Bottle", "瓶子"),
    ("Coffee cup", "咖啡杯"), ("Sunglasses", "太阳镜"), ("Strawberry", "草莓"), ("Tomato", "番茄"),
    ("Butterfly", "蝴蝶"), ("Duck", "鸭子"), ("Fountain", "喷泉"), ("Swimming pool", "游泳池"),
]


def download_metadata() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for filename, url in SOURCES.items():
        target = CACHE / filename
        if target.exists():
            continue
        print(f"下载元数据：{filename}", flush=True)
        with requests.get(url, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            temporary = target.with_suffix(".part")
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
            temporary.replace(target)


def download_group(group: dict) -> list[dict]:
    results = []
    for metadata in group["candidates"]:
        image_id = metadata["ImageID"]
        url = f"https://open-images-dataset.s3.amazonaws.com/validation/{image_id}.jpg"
        try:
            target = DATA / "images" / f"{image_id}.jpg"
            cached = target.exists()
            if cached:
                content = target.read_bytes()
            else:
                response = requests.get(url, timeout=(15, 40))
                response.raise_for_status()
                content = response.content
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                width, height = image.size
                # Real web/photo resolution, no upscaling or tiny thumbnails.
                if max(width, height) < 1000 or min(width, height) < 480:
                    continue
                if not cached:
                    image.save(target, "JPEG", quality=94)
                thumb = image.copy()
                thumb.thumbnail((480, 480))
                thumb.save(DATA / "thumbnails" / f"{image_id}.jpg", "JPEG", quality=85)
            results.append({
                "id": image_id,
                "title": f"{group['zh']} · {len(results) + 1:02d}",
                "category": group["zh"],
                "category_en": group["en"],
                "labels": sorted(metadata["labels"]),
                "path": f"images/{image_id}.jpg",
                "thumbnail": f"thumbnails/{image_id}.jpg",
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "source_url": metadata["OriginalLandingURL"],
                "original_url": metadata["OriginalURL"],
                "download_url": url,
                "author": metadata["Author"],
                "license": metadata["License"],
                "dataset": "Open Images validation",
            })
            print(f"已准备 {group['zh']} {len(results)}/{group['count']} · {width}×{height}", flush=True)
            if len(results) == group["count"]:
                return results
        except (requests.RequestException, OSError, ValueError) as exc:
            print(f"跳过 {image_id}：{type(exc).__name__}", file=sys.stderr, flush=True)
    raise RuntimeError(f"{group['en']} 高分辨率候选不足：{len(results)}/{group['count']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    current = DATA / "manifest.json"
    if current.exists() and not args.metadata_only:
        manifest = json.loads(current.read_text(encoding="utf-8"))
        if manifest.get("version", 1) >= 2:
            print("现有图库已扩充，保留当前清单，不覆盖为 100 张基础图库。")
            return
    download_metadata()
    with (CACHE / "classes.csv").open(encoding="utf-8") as stream:
        classes = dict(csv.reader(stream))
    names = {name: code for code, name in classes.items()}
    missing = [name for name, _ in TARGETS if name not in names]
    if missing:
        raise ValueError(f"标签不存在：{missing}")
    if args.metadata_only:
        print("元数据准备完成，40 个目标类别均存在。")
        return

    by_label = {names[name]: set() for name, _ in TARGETS}
    all_labels = {}
    with (CACHE / "labels.csv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["Confidence"] != "1":
                continue
            image_id, label = row["ImageID"], row["LabelName"]
            all_labels.setdefault(image_id, set()).add(classes.get(label, label))
            if label in by_label:
                by_label[label].add(image_id)
    with (CACHE / "images.csv").open(encoding="utf-8") as stream:
        metadata = {row["ImageID"]: row for row in csv.DictReader(stream)}
    rng = random.Random(20261026)
    reserved = set()
    groups = []
    for position, (name, zh) in enumerate(TARGETS):
        candidates = sorted(by_label[names[name]] - reserved)
        rng.shuffle(candidates)
        candidates = [image_id for image_id in candidates if image_id in metadata][:80]
        reserved.update(candidates)
        rows = [dict(metadata[image_id], labels=all_labels[image_id]) for image_id in candidates]
        groups.append({"en": name, "zh": zh, "count": 3 if position < 20 else 2, "candidates": rows})
    for folder in ("images", "thumbnails"):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    collected = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(download_group, group): group for group in groups}
        for future in as_completed(futures):
            collected[futures[future]["en"]] = future.result()
    photos = [photo for name, _ in TARGETS for photo in collected[name]]
    assert len(photos) == len({photo["id"] for photo in photos}) == 100
    assert len({photo["sha256"] for photo in photos}) == 100
    manifest = {
        "version": 1,
        "seed": 20261026,
        "dataset": "Open Images validation",
        "dataset_url": "https://storage.googleapis.com/openimages/web/download_v7.html",
        "selection": "40 categories; long edge >=1000px, short edge >=480px; no upscaling",
        "photos": photos,
    }
    temporary = DATA / "manifest.tmp"
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(DATA / "manifest.json")
    print(f"完成：{len(photos)} 张 / {len(TARGETS)} 类，清单：{DATA / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
