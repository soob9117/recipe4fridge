"""냉장고 사진에서 식재료 인식 (PRD_step1.md 3.1~3.2)."""

import base64
import io

from PIL import Image, ImageOps

from ai_client import AiResult, chat_with_fallback, extract_json

# 기본 모델이 실패하면 뒤 모델로 차례로 넘어감 (2026-10-23 연결 시험 기준)
VISION_MODELS = [
    "nvidia/nemotron-3.5-super-vl:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
]

CATEGORIES = ["채소", "과일", "육류", "해산물", "유제품·달걀", "소스·양념", "음료", "기타"]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE_PX = 1568

PROMPT = f"""이 냉장고 사진에 보이는 식재료를 모두 찾아줘.
아래 JSON 형식으로만 답하고, 다른 설명은 쓰지 마.
{{"ingredients": [{{"name": "재료명", "quantity": "수량", "category": "분류"}}]}}

규칙:
- name과 quantity는 한국어로 쓴다. (예: "달걀", "6개")
- quantity는 사진에서 보이는 개수를 직접 세어 숫자와 단위로 쓴다. (예: "4개", "1묶음", "2팩")
- 일부가 가려져 정확히 셀 수 없으면 보이는 만큼 세어 "약 4개"처럼 쓴다.
- "여러 개", "몇 개", "많이", "약간" 같은 막연한 표현은 쓰지 않는다.
- 개수를 전혀 짐작할 수 없으면 quantity는 빈 문자열 ""로 둔다.
- category는 다음 중 하나만 쓴다: {", ".join(CATEGORIES)}
- 포장 때문에 무엇인지 확실하지 않은 것은 넣지 않는다.
- 식재료가 하나도 없으면 {{"ingredients": []}}로 답한다."""


def prepare_image(raw: bytes) -> str:
    """사진의 긴 변을 MAX_SIDE_PX 이하로 줄이고 JPEG data URL로 바꾼다."""
    image = Image.open(io.BytesIO(raw))
    image = ImageOps.exif_transpose(image)  # 휴대폰 사진의 회전 정보 반영
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


VAGUE_WORDS = ("여러", "몇", "많", "약간", "조금", "일부", "다수", "적당", "소량", "다량")


def normalize_quantity(quantity: str) -> str:
    """막연한 수량("여러 개", "조금" 등)은 빈 값으로 바꿔 사용자가 직접 채우게 한다.

    숫자가 있으면("약 4개") 그대로 두고, "한 묶음"처럼 수를 글자로 쓴 것도 그대로 둔다.
    """
    quantity = quantity.strip()
    if any(ch.isdigit() for ch in quantity):
        return quantity
    return "" if any(word in quantity for word in VAGUE_WORDS) else quantity


def merge_duplicates(ingredients: list[dict]) -> list[dict]:
    """이름이 같은 식재료(공백 무시)를 하나로 합친다. 수량은 서로 다를 때만 이어 붙인다."""
    merged: dict[str, dict] = {}
    for item in ingredients:
        key = item["name"].replace(" ", "")
        if key not in merged:
            merged[key] = dict(item)
            continue
        existing = merged[key]
        quantities = [q for q in (existing["quantity"], item["quantity"]) if q]
        existing["quantity"] = " + ".join(dict.fromkeys(quantities))
    return list(merged.values())


def parse_ingredients(answer: str) -> list[dict]:
    data = extract_json(answer)
    items = data.get("ingredients") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("ingredients 목록이 없습니다")

    ingredients = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        category = str(item.get("category", "")).strip()
        ingredients.append({
            "name": str(item["name"]).strip(),
            "quantity": normalize_quantity(str(item.get("quantity") or "")),
            "category": category if category in CATEGORIES else "기타",
        })
    return merge_duplicates(ingredients)


def recognize_ingredients(raw_image: bytes, models: list[str] = VISION_MODELS) -> AiResult:
    """사진 바이트를 받아 식재료 목록을 인식한다. 결과의 data는 parse_ingredients 형식의 목록."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": prepare_image(raw_image)}},
        ],
    }]
    return chat_with_fallback(models, messages, parse_ingredients)
