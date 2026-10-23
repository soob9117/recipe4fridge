"""OpenRouter 호출 공용 모듈: 재시도, 예비 모델 전환, 응답 검증.

PRD_step1.md 3.4의 오류 처리 규칙을 구현하며, 2단계(레시피 생성)도 이 모듈을 함께 쓴다.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests
from dotenv import load_dotenv

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECONDS = 180
ATTEMPTS_PER_MODEL = 2  # 같은 모델로 최대 2번 시도한 뒤 예비 모델로 넘어감
RETRY_WAIT_SECONDS = 5
# 401은 키 문제라 어떤 모델로도 해결되지 않음. 나머지 4xx는 이 모델만의 문제일 수 있어 다음 모델로 넘어감
NO_RETRY_STATUS = {400, 402, 403}


class ApiKeyError(Exception):
    """API 키가 없거나 잘못됨."""


class AllModelsFailedError(Exception):
    """모든 모델이 실패함. attempts에 시도별 실패 원인이 남는다."""

    def __init__(self, attempts: list[str]):
        self.attempts = attempts
        super().__init__(attempts[-1] if attempts else "시도한 모델이 없습니다.")


@dataclass
class AiResult:
    data: Any  # parse 함수가 돌려준 값
    model: str  # 실제로 응답한 모델
    attempts: list[str] = field(default_factory=list)  # 성공 전까지의 실패 기록


def get_api_key() -> str:
    # 로컬에서는 .env, Streamlit Community Cloud에서는 Secrets의 최상위 키가 환경변수로 들어옴
    load_dotenv()
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ApiKeyError("OPENROUTER_API_KEY가 설정되지 않았습니다. .env 또는 배포 환경의 Secrets를 확인해 주세요.")
    return key


def extract_json(text: str) -> Any:
    """모델 응답에서 JSON을 꺼낸다. ```json 코드 블록이나 앞뒤 설명이 붙은 경우도 처리한다."""
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 설명 문장 사이에 JSON이 끼어 있는 경우: 첫 { 또는 [ 부터 마지막 } 또는 ] 까지
        starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if not starts or end == -1:
            raise
        return json.loads(cleaned[min(starts):end + 1])


def _describe_error(status: int, body: dict) -> str:
    message = body.get("error", {}).get("message") or "알 수 없는 오류"
    if status == 429:
        return "무료 모델이 혼잡합니다(429). 잠시 뒤 다시 시도해 주세요."
    if status == 404:
        return "모델 공급자가 응답하지 않습니다(404)."
    return f"HTTP {status}: {message}"


def chat_with_fallback(
    models: list[str],
    messages: list[dict],
    parse: Callable[[str], Any],
) -> AiResult:
    """models를 차례로 시도해 parse에 성공한 첫 결과를 돌려준다.

    parse는 모델의 답 문자열을 받아 결과를 돌려주고, 쓸 수 없는 답이면 ValueError를 낸다
    (json.JSONDecodeError도 ValueError의 하위 클래스).
    """
    headers = {"Authorization": f"Bearer {get_api_key()}"}
    attempts: list[str] = []

    for model in models:
        for attempt in range(1, ATTEMPTS_PER_MODEL + 1):
            if attempt > 1:
                time.sleep(RETRY_WAIT_SECONDS)
            label = f"{model} ({attempt}번째)"
            try:
                response = requests.post(
                    API_URL,
                    headers=headers,
                    json={"model": model, "messages": messages},
                    timeout=TIMEOUT_SECONDS,
                )
            except requests.Timeout:
                attempts.append(f"{label}: 응답 시간 초과({TIMEOUT_SECONDS}초)")
                continue
            except requests.RequestException as e:
                attempts.append(f"{label}: 네트워크 오류 ({type(e).__name__})")
                continue

            try:
                body = response.json()
            except ValueError:
                body = {}

            if response.status_code == 401:
                raise ApiKeyError("API 키를 확인해 주세요. OpenRouter가 키를 거부했습니다(401).")
            if not response.ok:
                attempts.append(f"{label}: {_describe_error(response.status_code, body)}")
                if response.status_code in NO_RETRY_STATUS:
                    break  # 같은 모델로 다시 해도 소용없음 → 다음 모델
                continue
            # HTTP 200이어도 공급자 오류가 본문의 error로만 오는 경우가 있음
            if not body.get("choices"):
                attempts.append(f"{label}: 응답에 답변이 없습니다({_describe_error(200, body)})")
                continue

            answer = body["choices"][0]["message"].get("content") or ""
            try:
                return AiResult(data=parse(answer), model=body.get("model", model), attempts=attempts)
            except ValueError as e:
                attempts.append(f"{label}: 답을 해석하지 못했습니다 ({e})")

    raise AllModelsFailedError(attempts)
