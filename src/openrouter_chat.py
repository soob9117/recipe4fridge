"""OpenRouter 채팅 API 호출 예제.

.env 파일의 OPENROUTER_API_KEY를 python-dotenv로 읽어서 사용합니다.
실행: python src/openrouter_chat.py "질문 내용"
"""

import os
import sys

import requests
from dotenv import load_dotenv

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# openrouter/free: 사용 가능한 무료 모델 중 하나로 자동 연결 (.env의 OPENROUTER_MODEL로 변경 가능)
DEFAULT_MODEL = "openrouter/free"


def get_api_key() -> str:
    load_dotenv()  # 현재 폴더의 .env를 환경변수로 불러옴 (이미 설정된 환경변수는 덮어쓰지 않음)
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        sys.exit("오류: OPENROUTER_API_KEY가 없습니다. .env.example을 참고해 .env를 만드세요.")
    return key


def chat(prompt: str, model: str | None = None) -> str:
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {get_api_key()}"},
        json={
            "model": model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL),
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    if not response.ok:
        # 응답 본문에는 키가 포함되지 않으므로 그대로 보여줘도 안전함
        sys.exit(f"API 오류 (HTTP {response.status_code}): {response.text}")

    data = response.json()
    print(f"[사용된 모델: {data.get('model')}]", file=sys.stderr)
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "안녕하세요! 한 문장으로 자기소개 해주세요."
    print(chat(question))
