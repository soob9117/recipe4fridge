"""확정한 식재료로 레시피 생성 (PRD_step2.md 3.1~3.2)."""

import json

from ai_client import AiResult, chat_with_fallback, extract_json

# 기본 모델이 실패하면 뒤 모델로 차례로 넘어감 (2026-10-23 연결 시험 기준)
RECIPE_MODELS = [
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]
RECIPE_COUNT = 3

ANY = "상관없음"
CUISINES = [ANY, "한식", "양식", "중식", "일식", "간식·디저트"]
TIME_LIMITS = {ANY: None, "15분 이내": 15, "30분 이내": 30, "1시간 이내": 60}
DIFFICULTIES = [ANY, "쉬움", "보통", "어려움"]
SERVINGS = list(range(1, 7))


def build_prompt(ingredients: list[dict], cuisine: str, time_limit: str, difficulty: str, servings: int) -> str:
    owned = "\n".join(f"- {i['name']}" + (f" ({i['quantity']})" if i["quantity"] else "") for i in ingredients)
    conditions = [f"- 인원: {servings}인분"]
    if cuisine != ANY:
        conditions.append(f"- 요리 종류: {cuisine}")
    if TIME_LIMITS[time_limit]:
        conditions.append(f"- 조리 시간: {TIME_LIMITS[time_limit]}분 이하 (준비 시간 포함)")
    if difficulty != ANY:
        conditions.append(f"- 난이도: {difficulty}")

    example = {"recipes": [{
        "title": "대파 달걀볶음밥",
        "summary": "남은 밥과 달걀로 간단히 만드는 고소한 볶음밥",
        "cuisine": "한식",
        "time_minutes": 15,
        "difficulty": "쉬움",
        "servings": servings,
        "used_ingredients": [{"name": "달걀", "amount": "2개"}],
        "missing_ingredients": [{"name": "밥", "amount": "2공기"}],
        "steps": ["대파를 송송 썬다.", "팬에 기름을 두르고 대파를 볶는다.", "달걀을 넣고 스크램블한다.",
                  "밥을 넣고 고루 볶는다.", "간장과 소금으로 간한다."],
    }]}
    return f"""냉장고에 있는 식재료로 만들 수 있는 레시피 {RECIPE_COUNT}개를 추천해줘.

가지고 있는 식재료:
{owned}

조건:
{chr(10).join(conditions)}

규칙:
- 모든 값은 반드시 한국어(한글)로 쓴다. 영어, 한자, 중국어를 섞지 않는다.
- 가지고 있는 식재료를 최대한 많이 쓴다.
- 가지고 있지 않은 재료는 소금, 간장, 식용유 같은 기본 양념 외에는 최소로 한다.
- used_ingredients에는 가지고 있는 식재료 중 쓰는 것만, missing_ingredients에는 새로 필요한 재료(기본 양념 포함)를 넣는다.
- difficulty는 쉬움, 보통, 어려움 중 하나, time_minutes는 숫자로 쓴다.
- steps는 4~8단계로 나누고, 한 단계에는 한 가지 동작만 한 문장으로 쓴다.
- summary에는 조리 시간을 쓰지 않는다. (시간은 time_minutes에만 쓴다)
- 서로 다른 요리 {RECIPE_COUNT}개를 추천한다.
- 아래 JSON 형식으로만 답하고, 다른 설명은 쓰지 않는다.

{json.dumps(example, ensure_ascii=False, indent=2)}"""


def _same_name(a: str, b: str) -> bool:
    a, b = a.replace(" ", ""), b.replace(" ", "")
    return bool(a and b) and (a in b or b in a)


def _clean_items(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        if isinstance(item, str):  # "달걀 2개"처럼 문자열만 온 경우
            item = {"name": item, "amount": ""}
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            cleaned.append({"name": str(item["name"]).strip(), "amount": str(item.get("amount") or "").strip()})
    return cleaned


def _clean_steps(steps) -> list[str]:
    """조리 순서를 문자열 목록으로 맞춘다. 모델이 {"name": "..."}처럼 객체로 보내는 경우가 있다."""
    if not isinstance(steps, list):
        return []
    cleaned = []
    for step in steps:
        if isinstance(step, dict):
            texts = [v for v in step.values() if isinstance(v, str) and v.strip()]
            step = max(texts, key=len) if texts else ""  # 가장 긴 문자열 값을 설명으로 봄
        step = str(step).strip()
        if step:
            cleaned.append(step)
    return cleaned


def reconcile(recipe: dict, owned_names: list[str]) -> dict:
    """모델이 '가진 재료'로 적었지만 실제 목록에 없는 재료는 '부족한 재료'로 옮긴다."""
    used, missing = [], list(recipe["missing_ingredients"])
    for item in recipe["used_ingredients"]:
        (used if any(_same_name(item["name"], name) for name in owned_names) else missing).append(item)
    return {**recipe, "used_ingredients": used, "missing_ingredients": missing}


def parse_recipes(answer: str, owned_names: list[str], max_minutes: int | None) -> list[dict]:
    data = extract_json(answer)
    items = data.get("recipes") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("recipes 목록이 없습니다")

    recipes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        steps = _clean_steps(item.get("steps"))
        recipe = {
            "title": str(item.get("title", "")).strip(),
            "summary": str(item.get("summary", "")).strip(),
            "cuisine": str(item.get("cuisine", "")).strip(),
            "time_minutes": item.get("time_minutes"),
            "difficulty": str(item.get("difficulty", "")).strip(),
            "servings": item.get("servings"),
            "used_ingredients": _clean_items(item.get("used_ingredients")),
            "missing_ingredients": _clean_items(item.get("missing_ingredients")),
            "steps": steps,
        }
        # 필수 항목(PRD 3.2): title, used_ingredients, steps
        if not (recipe["title"] and recipe["used_ingredients"] and recipe["steps"]):
            continue
        try:
            recipe["time_minutes"] = int(recipe["time_minutes"])
        except (TypeError, ValueError):
            recipe["time_minutes"] = None
        # 시간 조건을 어긴 레시피는 버림. 조건을 지킨 레시피가 하나도 없으면 다시 요청하게 됨
        if max_minutes and recipe["time_minutes"] and recipe["time_minutes"] > max_minutes:
            continue
        recipes.append(reconcile(recipe, owned_names))

    if not recipes:
        raise ValueError("조건에 맞는 레시피가 없습니다")
    return recipes[:RECIPE_COUNT]


def generate_recipes(
    ingredients: list[dict],
    cuisine: str = ANY,
    time_limit: str = ANY,
    difficulty: str = ANY,
    servings: int = 2,
    models: list[str] = RECIPE_MODELS,
) -> AiResult:
    """확정한 식재료와 조건으로 레시피를 생성한다. 결과의 data는 parse_recipes 형식의 목록."""
    prompt = build_prompt(ingredients, cuisine, time_limit, difficulty, servings)
    owned_names = [i["name"] for i in ingredients]
    max_minutes = TIME_LIMITS[time_limit]
    return chat_with_fallback(
        models,
        [{"role": "user", "content": prompt}],
        lambda answer: parse_recipes(answer, owned_names, max_minutes),
    )
