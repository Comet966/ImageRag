"""Expand the existing library to 300 attributed photos, screenshots and illustrations."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_demo import CACHE, DATA, download_group, download_metadata

MIXED_CACHE = CACHE / "mixed"
HEADERS = {"User-Agent": "ImageRag-local-demo/0.2 (public image retrieval evaluation)"}
PHOTO_CLASSES = [
    ("Elephant", "大象"), ("Rabbit", "兔子"), ("Panda", "熊猫"), ("Sheep", "绵羊"),
    ("Giraffe", "长颈鹿"), ("Sea turtle", "海龟"), ("Penguin", "企鹅"), ("Camera", "相机"),
    ("Television", "电视"), ("Refrigerator", "冰箱"), ("Washing machine", "洗衣机"),
    ("Piano", "钢琴"), ("Violin", "小提琴"), ("Skateboard", "滑板"), ("Surfboard", "冲浪板"),
    ("Tent", "帐篷"), ("Castle", "城堡"), ("Skyscraper", "摩天大楼"), ("Watermelon", "西瓜"), ("Sushi", "寿司"),
]
COMMONS_GROUPS = [
    ("Anime illustrations", "动漫插画", 12),
    ("Wikipe-tan", "动漫角色", 8),
    ("SVG cartoons", "卡通绘画", 12),
    ("Line art cartoons", "线描卡通", 12),
    ("Cartoon characters", "卡通角色", 12),
    ("Comic strips", "条漫", 12),
    ("Comics", "漫画", 12),
]
# Excluded after visual inspection: photographs of merchandise/cosplay or UI captures.
EXCLUDED_COMMONS_IDS = {
    "d962b1426c7a8dc8", "6f3f253fd30d38e6", "d13f9bdfd4e9ff2b", "19ef037a961ccc57",
    "4bc7f5e5a7397258", "bac2aaed26ae00b4", "e20b8495a3584e44", "56f481515137712a",
    "9ca08d41b2ee1d72",
}


def get(url: str, **kwargs) -> requests.Response:
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=(20, 75), **kwargs)
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Download failed")


def cached_json(name: str, url: str, params: dict, *, max_age: int = 3600) -> dict:
    target = MIXED_CACHE / f"{name}.json"
    if target.exists() and time.time() - target.stat().st_mtime < max_age:
        return json.loads(target.read_text(encoding="utf-8"))
    result = get(url, params=params).json()
    target.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def save_image(record: dict, *, vector_source: bool = False, refresh: bool = False) -> dict:
    image_id = record["id"]
    path = DATA / "images" / f"{image_id}.jpg"
    cached = path.exists() and not refresh
    raw_path = MIXED_CACHE / "raw" / f"{image_id}.bin"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if cached:
        content = path.read_bytes()
    elif raw_path.exists():
        content = raw_path.read_bytes()
    else:
        content = get(record["download_url"]).content
        raw_path.write_bytes(content)
    with Image.open(io.BytesIO(content)) as source:
        source_size = source.size
        oriented = ImageOps.exif_transpose(source)
        if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
            rgba = oriented.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = oriented.convert("RGB")
        if max(image.size) < 960 or min(image.size) < 320 or max(image.size) / min(image.size) > 4.5:
            raise ValueError("Image too small or unusually narrow")
        if not cached:
            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
            image.save(path, "JPEG", quality=94)
        width, height = image.size
        thumb = image.copy()
        thumb.thumbnail((480, 480), Image.Resampling.LANCZOS)
        thumb.save(DATA / "thumbnails" / f"{image_id}.jpg", "JPEG", quality=85)
    return dict(record,
        path=f"images/{image_id}.jpg", thumbnail=f"thumbnails/{image_id}.jpg",
        width=width, height=height, source_width=record.get("source_width", source_size[0]),
        source_height=record.get("source_height", source_size[1]),
        vector_source=vector_source, normalization_version=2, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def additional_photos(existing: list[dict]) -> list[dict]:
    download_metadata()
    with (CACHE / "classes.csv").open(encoding="utf-8") as stream:
        classes = dict(csv.reader(stream))
    names = {name: code for code, name in classes.items()}
    needed = {names[name]: name for name, _ in PHOTO_CLASSES}
    by_label = defaultdict(set)
    all_labels = defaultdict(set)
    with (CACHE / "labels.csv").open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["Confidence"] == "1":
                all_labels[row["ImageID"]].add(classes.get(row["LabelName"], row["LabelName"]))
                if row["LabelName"] in needed:
                    by_label[row["LabelName"]].add(row["ImageID"])
    with (CACHE / "images.csv").open(encoding="utf-8") as stream:
        metadata = {row["ImageID"]: row for row in csv.DictReader(stream)}
    rng = random.Random(300)
    used = {photo["id"] for photo in existing}
    groups = []
    for name, zh in PHOTO_CLASSES:
        candidates = sorted(by_label[names[name]] - used)
        rng.shuffle(candidates)
        candidates = candidates[:50]
        used.update(candidates)
        groups.append({"en": name, "zh": zh, "count": 2,
                       "candidates": [dict(metadata[key], labels=all_labels[key]) for key in candidates]})
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(download_group, group): group["en"] for group in groups}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [dict(photo, media_type="photo") for name, _ in PHOTO_CLASSES for photo in results[name]]


def screenshot_rows(offset: int) -> list[dict]:
    result = cached_json(f"screenspot-{offset}", "https://datasets-server.huggingface.co/rows", {
        "dataset": "bevaya/ScreenSpot", "config": "default", "split": "test", "offset": offset, "length": 100,
    })
    return result.get("rows", [])


def screenshots() -> list[dict]:
    rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(screenshot_rows, range(0, 1272, 100)):
            rows.extend(batch)
    buckets = defaultdict(list)
    seen = set()
    for wrapper in rows:
        row = wrapper["row"]
        if row["file_name"] in seen:
            continue
        seen.add(row["file_name"])
        image = row["image"]
        if image.get("width", 0) < 320 or max(image.get("width", 0), image.get("height", 0)) < 960:
            continue
        buckets[row["data_source"]].append((wrapper["row_idx"], row))
    print("截图来源候选：", {key: len(value) for key, value in buckets.items()}, flush=True)
    translations = {"windows": "Windows 软件截图", "macos": "macOS 软件截图", "ios": "iOS 应用截图", "android": "Android 应用截图",
                    "web": "网页截图", "chrome": "浏览器截图", "safari": "网页截图", "linux": "Linux 软件截图"}
    rng = random.Random(301)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    results = []
    counts = Counter()
    failed = 0
    # Round-robin across actual dataset environments, rather than 80 adjacent rows.
    while len(results) < 80 and any(buckets.values()):
        for source in sorted(buckets):
            if len(results) == 80 or not buckets[source]:
                continue
            row_idx, row = buckets[source].pop()
            category = translations.get(source, f"{source} 网页截图")
            image_id = hashlib.sha256(f"screenspot:{row['file_name']}".encode()).hexdigest()[:16]
            record = {
                "id": image_id, "title": f"{category} · {counts[source] + 1:02d}",
                "category": category, "category_en": f"Screenshot {source}",
                "media_type": "screenshot", "labels": ["Screenshot", source] + (["Mobile screenshot"] if source in ("ios", "android") else []),
                "dataset": "ScreenSpot", "dataset_row": row_idx, "source_filename": row["file_name"],
                "source_url": f"https://huggingface.co/datasets/bevaya/ScreenSpot/viewer/default/test?row={row_idx}",
                "original_url": "https://huggingface.co/datasets/bevaya/ScreenSpot",
                "download_url": row["image"]["src"],
                "author": "ScreenSpot contributors",
                "license": "Apache-2.0 (dataset); underlying application/interface rights remain with their owners",
                "source_instruction": row["instruction"],
            }
            try:
                photo = save_image(record)
                if photo["sha256"] in {item["sha256"] for item in results}:
                    continue
                results.append(photo)
                counts[source] += 1
                print(f"截图 {len(results)}/80：{source} {photo['width']}×{photo['height']}", flush=True)
            except (requests.RequestException, OSError, ValueError) as exc:
                failed += 1
                print(f"跳过截图：{type(exc).__name__}", flush=True)
    if len(results) != 80:
        raise RuntimeError(f"截图不足：{len(results)}/80；失败 {failed}")
    return results


def clean_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()[:400]


def illustrations(existing: list[dict] | None = None) -> list[dict]:
    results = []
    seen = set()
    retained = [photo for photo in (existing or []) if photo["id"] not in EXCLUDED_COMMONS_IDS]
    retained_ids = {photo["id"] for photo in retained}
    excluded = re.compile(r"lolicon|nude|naked|bikini|underwear|sexual|hentai|bondage|fetish|topless|adult|pin.?up", re.I)
    for category, zh, count in COMMONS_GROUPS:
        complete_group = [photo for photo in retained if photo["category_en"] == category]
        if len(complete_group) == count:
            for index, photo in enumerate(complete_group):
                photo["title"] = f"{zh} · {index + 1:02d}"
            results.extend(complete_group)
            continue
        metadata = cached_json("commons-full-" + hashlib.sha256(category.encode()).hexdigest()[:12],
            "https://commons.wikimedia.org/w/api.php", {
                "action": "query", "generator": "categorymembers", "gcmtitle": f"Category:{category}",
                "gcmtype": "file", "gcmlimit": 500, "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json",
            }, max_age=86400)
        # Commons can return all category members but only 50 imageinfo records.
        # Hydrate missing records explicitly instead of treating them as unusable files.
        missing_ids = [str(page["pageid"]) for page in metadata.get("query", {}).get("pages", {}).values() if "imageinfo" not in page]
        for offset in range(0, len(missing_ids), 50):
            batch = missing_ids[offset:offset + 50]
            key = hashlib.sha256("|".join(batch).encode()).hexdigest()[:16]
            extra = cached_json(f"commons-info-{key}", "https://commons.wikimedia.org/w/api.php", {
                "action": "query", "pageids": "|".join(batch), "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1280, "format": "json",
            }, max_age=86400)
            for page_id, page in extra.get("query", {}).get("pages", {}).items():
                metadata["query"]["pages"][page_id].update(page)
        pages = sorted(metadata.get("query", {}).get("pages", {}).values(), key=lambda page: page["title"])
        rng = random.Random(category)
        rng.shuffle(pages)
        group = [photo for photo in retained if photo["category_en"] == category]
        for page in pages:
            if len(group) == count:
                break
            if page["pageid"] in seen or excluded.search(page["title"]):
                continue
            info = page.get("imageinfo", [{}])[0]
            mime = info.get("mime", "")
            if mime not in ("image/jpeg", "image/png", "image/webp", "image/svg+xml"):
                continue
            is_vector = mime == "image/svg+xml"
            if not is_vector and (max(info.get("width", 0), info.get("height", 0)) < 960 or min(info.get("width", 0), info.get("height", 0)) < 320):
                continue
            ext = info.get("extmetadata", {})
            description = clean_html(ext.get("ImageDescription", {}).get("value", ""))
            if excluded.search(description):
                continue
            image_id = hashlib.sha256(f"commons:{page['pageid']}".encode()).hexdigest()[:16]
            if image_id in EXCLUDED_COMMONS_IDS or image_id in retained_ids:
                continue
            record = {
                "id": image_id, "title": f"{zh} · {len(group) + 1:02d}",
                "category": zh, "category_en": category, "media_type": "illustration",
                "labels": ["Illustration", category] + (["Anime illustration"] if category in ("Anime illustrations", "Wikipe-tan") else []), "dataset": "Wikimedia Commons",
                "source_title": page["title"], "source_description": description,
                "source_width": info["width"], "source_height": info["height"],
                "source_url": info["descriptionurl"], "original_url": info["url"],
                "download_url": info.get("thumburl", info["url"]),
                "author": clean_html(ext.get("Artist", {}).get("value", "Wikimedia Commons contributor")),
                "license": clean_html(ext.get("LicenseShortName", {}).get("value", "See source file page")),
                "license_url": ext.get("LicenseUrl", {}).get("value", info["descriptionurl"]),
            }
            try:
                photo = save_image(record, vector_source=is_vector, refresh=True)
                if photo["sha256"] in {item["sha256"] for item in results + group}:
                    continue
                group.append(photo)
                seen.add(page["pageid"])
                print(f"插画 {len(results) + len(group)}/80：{zh} {photo['width']}×{photo['height']}", flush=True)
            except (requests.RequestException, OSError, ValueError) as exc:
                print(f"跳过插画：{page['title']} / {type(exc).__name__}", flush=True)
        if len(group) != count:
            raise RuntimeError(f"{category} 插画不足：{len(group)}/{count}")
        for index, photo in enumerate(group):
            photo["title"] = f"{zh} · {index + 1:02d}"
        results.extend(group)
    return results


def main():
    MIXED_CACHE.mkdir(parents=True, exist_ok=True)
    manifest_path = DATA / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(previous["photos"]) == 300:
        print("现有图库已经是 300 张，不重复导入。")
        return
    if len(previous["photos"]) != 100:
        raise ValueError("需要现有 100 张基础图库，或已完成的 300 张图库。")
    backup = DATA / "manifest-100.json"
    if not backup.exists():
        backup.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
    existing = [dict(photo, media_type="photo") for photo in previous["photos"]]
    # Group checkpoints allow a failed source to resume without redownloading others.
    additions = {}
    for name, loader in [("photos", lambda: additional_photos(existing)), ("screenshots", screenshots), ("illustrations", illustrations)]:
        checkpoint = MIXED_CACHE / f"{name}-complete.json"
        if checkpoint.exists():
            additions[name] = json.loads(checkpoint.read_text(encoding="utf-8"))
        else:
            additions[name] = loader()
            checkpoint.write_text(json.dumps(additions[name], ensure_ascii=False, indent=2), encoding="utf-8")
    photos = existing + additions["photos"] + additions["screenshots"] + additions["illustrations"]
    if len(photos) != 300 or len({photo["id"] for photo in photos}) != 300 or len({photo["sha256"] for photo in photos}) != 300:
        raise ValueError("图片数量、唯一 ID 或内容去重校验失败。")
    random.Random(300).shuffle(photos)
    manifest = {
        "version": 2, "target_count": 300, "seed": 300,
        "dataset": "Mixed public image test library",
        "selection": "140 real photos, 80 genuine UI screenshots, 80 cartoons/illustrations; no raster upscaling; long edge 960–1920px; short edge >=320px",
        "media_types": dict(Counter(photo["media_type"] for photo in photos)), "photos": photos,
    }
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    print("完成：", manifest["media_types"], flush=True)


if __name__ == "__main__":
    main()
