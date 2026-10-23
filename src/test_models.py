"""텍스트/이미지 인식 모델 동작 테스트.

실행: python src/test_models.py
"""

import base64
import json
import sys
import time
from pathlib import Path

import requests

from openrouter_chat import API_URL, get_api_key

# 원래 계획: nvidia/nemotron-3-super-120b-a12b:free(404), google/gemma-4-26b-a4b-it:free(429) → 응답 불가로 교체
TEXT_MODEL = "cohere/north-mini-code:free"
VISION_MODEL = "nvidia/nemotron-3.5-super-vl:free"
IMAGE_PATH = Path(__file__).parent.parent / "test_assets" / "sample.png"


# 요청 자체가 잘못된 경우(키·결제·형식 오류)는 재시도해도 소용없으므로 제외
NO_RETRY_STATUS = {400, 401, 402, 403}
RETRY_WAITS = [10, 30, 60]  # 무료 모델은 공급자 쪽 일시 오류(429/404/5xx)가 잦음


def call(model: str, content) -> str | None:
    print(f"모델: {model}")
    for attempt, wait in enumerate([0, *RETRY_WAITS], start=1):
        if wait:
            print(f"  {wait}초 후 재시도 ({attempt}번째 시도)...")
            time.sleep(wait)
        started = time.time()
        try:
            response = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {get_api_key()}"},
                json={"model": model, "messages": [{"role": "user", "content": content}]},
                timeout=180,
            )
        except requests.Timeout:
            print("  응답 시간 초과(180초)")
            continue
        elapsed = time.time() - started
        data = response.json()
        # HTTP 200이어도 공급자 오류가 본문의 error로 오는 경우가 있음
        if response.ok and "choices" in data:
            break
        if response.status_code in NO_RETRY_STATUS:
            break
        print(f"  HTTP {response.status_code}: {data.get('error', {}).get('message')}")
    else:
        print(f"실패: 시도 {attempt}회 모두 응답을 받지 못함")
        return None

    print(f"HTTP {response.status_code} / {elapsed:.1f}초 / 시도 {attempt}회")
    if "choices" not in data:
        print(f"실패: {response.text}")
        return None

    usage = data.get("usage", {})
    print(f"토큰: 입력 {usage.get('prompt_tokens')} / 출력 {usage.get('completion_tokens')}")
    answer = data["choices"][0]["message"]["content"]
    print("응답:")
    print(answer)
    return answer


def test_text() -> None:
    print("=== 텍스트 인식 테스트 (JSON 형식 처리) ===")
    answer = call(TEXT_MODEL, "다음 문장에서 식재료와 수량을 뽑아 JSON 배열로만 답해줘. "
                              "형식: [{\"name\": \"재료명\", \"quantity\": \"수량\"}]. 값은 한국어로 쓰고, 다른 설명은 쓰지 마.\n"
                              "문장: 냉장고에 달걀 6개, 우유 1팩, 대파 2뿌리가 있어.")
    if answer is None:
        return
    # 모델이 ```json 코드 블록으로 감싸 답하는 경우가 있어 벗겨냄
    cleaned = answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        print(f"JSON 파싱: 성공 → {json.loads(cleaned)}")
    except json.JSONDecodeError as e:
        print(f"JSON 파싱: 실패 ({e})")


def test_image() -> None:
    print("=== 이미지 인식 테스트 ===")
    image_b64 = base64.b64encode(IMAGE_PATH.read_bytes()).decode()
    call(VISION_MODEL, [
        {"type": "text", "text": "이 이미지에 있는 도형들의 색깔과 모양, 그리고 적힌 글자를 한국어로 알려줘."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ])


if __name__ == "__main__":
    tests = {"text": test_text, "image": test_image}
    for name in sys.argv[1:] or tests:
        tests[name]()
        print()
