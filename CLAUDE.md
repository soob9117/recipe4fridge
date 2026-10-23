# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

OpenRouter API로 무료 AI 모델을 호출하는 학습용 프로젝트. 이후 냉장고 사진에서 식재료를 인식(이미지 모델)하고 레시피를 추천(텍스트 모델)하는 웹 앱으로 확장할 예정. 사용자에게 보이는 답변과 보고는 한국어로 작성한다.

앱 요구사항은 `docs/PRD_step1.md`(사진에서 식재료 인식) → `docs/PRD_step2.md`(레시피 생성) → `docs/PRD_step3.md`(프로필과 레시피 저장) 순서로 구현한다. 앞 단계가 끝나야 다음 단계가 동작한다. 화면 기술과 배포처는 아직 정하지 않았다.

## 명령어

```bash
pip install -r requirements.txt          # python-dotenv, requests
python src/openrouter_chat.py "질문"      # 단일 채팅 호출 (기본 모델 openrouter/free)
python src/test_models.py                # 텍스트 + 이미지 모델 연결 시험
python src/test_models.py text           # 텍스트 시험만
python src/test_models.py image          # 이미지 시험만
```

Windows 콘솔/Git Bash에서 한글이 깨지면 `PYTHONUTF8=1`을 붙여 실행한다. 별도의 빌드, 린트, 테스트 프레임워크는 없다. `load_dotenv()`는 호출한 파일 위치에서 위로 올라가며 `.env`를 찾으므로 프로젝트 루트의 `.env`를 어느 폴더에서 실행해도 읽는다.

## 구조

- `src/openrouter_chat.py`: 공통 기반. `get_api_key()`가 `load_dotenv()`로 `.env`를 읽어 `OPENROUTER_API_KEY`를 반환하고, `API_URL`(chat/completions)을 정의한다. 다른 스크립트는 여기서 이 둘을 import해 쓴다.
- `src/test_models.py`: 모델 연결 시험. `TEXT_MODEL`/`VISION_MODEL` 상수로 모델을 지정한다.
  - 텍스트 시험: 문장에서 식재료와 수량을 JSON 배열로 뽑게 하고 `json.loads`로 파싱 성공 여부를 확인한다(```json 코드 블록 감싸기 제거 포함).
  - 이미지 시험: `test_assets/sample.png`(빨간 원, 파란 사각형, 초록 삼각형, 글자 "HELLO 42")를 base64 data URL로 보내 인식 결과를 확인한다.

## 사용 모델

| 용도 | 현재 모델 | 비고 |
|---|---|---|
| 텍스트 | `cohere/north-mini-code:free` | 원래 계획한 `nvidia/nemotron-3-super-120b-a12b:free`는 공급자 404로 응답 불가 (2026-10-23) |
| 이미지 | `nvidia/nemotron-3.5-super-vl:free` | 원래 계획한 `google/gemma-4-26b-a4b-it:free`는 공급자 429 지속 (2026-10-23) |

무료 모델 목록과 가용성은 수시로 바뀐다. 모델을 고를 때는 `https://openrouter.ai/api/v1/models`(입력 형식 `architecture.input_modalities`)와 `/api/v1/models/{id}/endpoints`(공급자 상태, 가동률)로 확인한다. 이미지 모델은 입력에 `image`가 있어야 한다.

## OpenRouter 무료 모델 주의점

- 키는 무료 티어이며 하루 호출 한도(50회)가 있다. 불필요한 반복 호출을 피하고, 남은 사용량은 `GET /api/v1/key`로 확인한다.
- 공급자 쪽 일시 오류(429, 404, 5xx)가 잦다. `test_models.py`의 `call()`은 10/30/60초 간격으로 재시도하고, 400/401/402/403은 재시도하지 않는다.
- **HTTP 200이어도 본문에 `choices` 없이 `error`만 오는 경우가 있다.** 상태 코드만 보지 말고 `choices` 존재 여부로 성공을 판단한다.
- 응답이 2분 가까이 걸리는 경우가 있어 요청 timeout은 180초로 둔다.
- 텍스트 모델은 지시가 없으면 영어로 답하기 쉬우므로, 프롬프트에 "한국어로"를 명시한다.

## 비밀 정보

- `.env`(`OPENROUTER_API_KEY`, 선택적으로 `OPENROUTER_MODEL`)는 `.gitignore`로 제외되어 있고, `.env.example`이 공유용 틀이다.
- `.env` 내용을 출력하거나 읽어서 보여주지 않는다. 확인이 필요하면 변수 이름만 보거나 길이와 앞 몇 글자만 출력한다.
