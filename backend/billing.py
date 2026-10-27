"""Reference prices used only to summarize recorded actual usage."""

TEXT_PRICE_PER_1000 = 0.0007
IMAGE_PRICE_PER_1000 = 0.0018


def cost_cny(text_tokens: int, image_tokens: int) -> float:
    return round((text_tokens * TEXT_PRICE_PER_1000 + image_tokens * IMAGE_PRICE_PER_1000) / 1000, 8)
