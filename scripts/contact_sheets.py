"""Create local visual QA sheets and ID maps for each media type."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    photos = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))["photos"]
    output = ROOT / "outputs"
    output.mkdir(exist_ok=True)
    for kind in ("photo", "screenshot", "illustration"):
        selected = sorted((photo for photo in photos if photo.get("media_type", "photo") == kind), key=lambda photo: (photo["category_en"], photo["title"]))
        columns = 8
        sheet = Image.new("RGB", (columns * 200, ((len(selected) + columns - 1) // columns) * 190), "#eee")
        draw = ImageDraw.Draw(sheet)
        for index, photo in enumerate(selected):
            x, y = index % columns * 200, index // columns * 190
            with Image.open(ROOT / "data" / photo["thumbnail"]) as image:
                image.thumbnail((192, 160))
                sheet.paste(image, (x + (192 - image.width) // 2, y))
            draw.text((x + 4, y + 162), f"{index + 1:03d} {photo['id'][:8]}", fill="black")
        sheet.save(output / f"{kind}-contact.jpg", quality=90)
        (output / f"{kind}-contact-map.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{kind}: {len(selected)}")


if __name__ == "__main__":
    main()
