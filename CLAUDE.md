# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

냉장고 사진에서 식재료를 인식(이미지 모델)하고 레시피를 추천(텍스트 모델)하는 Streamlit 웹 앱. AI 모델은 OpenRouter 무료 모델을 쓴다. 사용자에게 보이는 답변과 보고는 한국어로 작성한다.

앱 요구사항은 `docs/PRD_step1.md`(사진에서 식재료 인식) → `docs/PRD_step2.md`(레시피 생성) → `docs/PRD_step3.md`(프로필과 레시피 저장) 순서로 구현한다. 1단계까지 구현했다. 화면은 Streamlit, 배포처는 Streamlit Community Cloud로 정했다.

## 명령어

```bash
pip install -r requirements.txt          # python-dotenv, requests, streamlit, Pillow
streamlit run src/app.py                 # 앱 실행 (http://localhost:8501)
python src/openrouter_chat.py "질문"      # 단일 채팅 호출 (기본 모델 openrouter/free)
python src/test_models.py                # 텍스트 + 이미지 모델 연결 시험
python src/test_models.py text           # 텍스트 시험만
python src/test_models.py image          # 이미지 시험만
```

Windows 콘솔/Git Bash에서 한글이 깨지면 `PYTHONUTF8=1`을 붙여 실행한다. 별도의 빌드, 린트, 테스트 프레임워크는 없다. `load_dotenv()`는 호출한 파일 위치에서 위로 올라가며 `.env`를 찾으므로 프로젝트 루트의 `.env`를 어느 폴더에서 실행해도 읽는다.

## 구조

앱 코드 (`src/`, 앱 파일끼리는 같은 폴더 기준으로 import):
- `ai_client.py`: 모든 AI 호출이 거치는 공용 모듈. `chat_with_fallback(models, messages, parse)`가 모델 목록을 차례로 시도하고, `parse`가 성공한 첫 결과를 `AiResult(data, model, attempts)`로 돌려준다. `parse`는 쓸 수 없는 답이면 `ValueError`를 내야 한다(그러면 같은 모델로 한 번 더, 이후 다음 모델). 모델당 2회 시도, 401은 `ApiKeyError`로 즉시 중단, 400/402/403은 바로 다음 모델, 전부 실패하면 `AllModelsFailedError(attempts)`. `extract_json()`은 코드 블록이나 앞뒤 설명이 붙은 답에서 JSON을 꺼낸다. 2단계(레시피)도 이 모듈을 쓴다.
- `vision.py`: 1단계. `VISION_MODELS`(우선순위 목록), 사진 축소(긴 변 1568px, EXIF 회전 반영, JPEG data URL), 프롬프트, 응답 검증(`CATEGORIES` 밖의 분류는 "기타"), 같은 이름(공백 무시) 식재료 합치기.
- `app.py`: Streamlit 화면. 사진과 인식 결과를 같은 화면 두 칸에 보여 주고, 결과는 `st.data_editor`로 수정, 추가, 삭제한다. 상태는 `st.session_state`에 둔다: `recognized`(모델 결과, 편집표의 처음 값)와 `ingredients`(사용자가 확정한 목록, 2단계의 입력)를 구분한다. 다시 인식할 때마다 `run_count`로 편집표 key를 바꿔 이전 편집 상태를 버린다.

연결 시험 스크립트 (`src/`, 앱과 독립):
- `src/openrouter_chat.py`: 공통 기반. `get_api_key()`가 `load_dotenv()`로 `.env`를 읽어 `OPENROUTER_API_KEY`를 반환하고, `API_URL`(chat/completions)을 정의한다. 다른 스크립트는 여기서 이 둘을 import해 쓴다.
- `src/test_models.py`: 모델 연결 시험. `TEXT_MODEL`/`VISION_MODEL` 상수로 모델을 지정한다.
  - 텍스트 시험: 문장에서 식재료와 수량을 JSON 배열로 뽑게 하고 `json.loads`로 파싱 성공 여부를 확인한다(```json 코드 블록 감싸기 제거 포함).
  - 이미지 시험: `test_assets/sample.png`(빨간 원, 파란 사각형, 초록 삼각형, 글자 "HELLO 42")를 base64 data URL로 보내 인식 결과를 확인한다.

`test_assets/fridge_demo.png`는 앱 시험용 냉장고 그림(달걀 6, 우유, 사과 2, 토마토 3, 바나나, 당근 3, 대파 2)이다. 모델은 그림 속 대파를 오이로, 바나나를 놓치는 경우가 있다.

설정: `.streamlit/config.toml`(업로드 10MB 제한), `.claude/launch.json`(미리보기 실행 설정). Streamlit Community Cloud에서는 Secrets의 최상위 키가 환경변수로 들어오므로 `OPENROUTER_API_KEY="키"` 형식으로 넣으면 코드 변경 없이 읽힌다.

브라우저로 앱을 시험할 때: `st.data_editor`는 canvas 표라 텍스트로 읽으려면 `[role=row]`/`[role=gridcell]` 요소를 쓴다. 파일 업로드는 `input[type=file]`에 `DataTransfer`로 File을 넣고 `change` 이벤트를 보낸다.

## 사용 모델

| 용도 | 현재 모델 | 비고 |
|---|---|---|
| 텍스트 | `cohere/north-mini-code:free` | 원래 계획한 `nvidia/nemotron-3-super-120b-a12b:free`는 공급자 404로 응답 불가 (2026-10-23) |
| 이미지 | `nvidia/nemotron-3.5-super-vl:free` | 원래 계획한 `google/gemma-4-26b-a4b-it:free`는 공급자 429 지속 (2026-10-23). 앱은 이 둘 다음에 `google/gemma-4-31b-it:free`를 예비로 둔다 |

무료 모델 목록과 가용성은 수시로 바뀐다. 모델을 고를 때는 `https://openrouter.ai/api/v1/models`(입력 형식 `architecture.input_modalities`)와 `/api/v1/models/{id}/endpoints`(공급자 상태, 가동률)로 확인한다. 이미지 모델은 입력에 `image`가 있어야 한다.

## OpenRouter 무료 모델 주의점

- 키는 무료 티어이며 하루 호출 한도(50회)가 있다. 불필요한 반복 호출을 피하고, 남은 사용량은 `GET /api/v1/key`로 확인한다.
- 공급자 쪽 일시 오류(429, 404, 5xx)가 잦다. 앱은 `ai_client.py`가 처리하고, 시험 스크립트 `test_models.py`의 `call()`은 10/30/60초 간격으로 따로 재시도한다.
- **HTTP 200이어도 본문에 `choices` 없이 `error`만 오는 경우가 있다.** 상태 코드만 보지 말고 `choices` 존재 여부로 성공을 판단한다.
- 응답이 2분 가까이 걸리는 경우가 있어 요청 timeout은 180초로 둔다.
- 텍스트 모델은 지시가 없으면 영어로 답하기 쉬우므로, 프롬프트에 "한국어로"를 명시한다.

## 비밀 정보

- `.env`(`OPENROUTER_API_KEY`, 선택적으로 `OPENROUTER_MODEL`)는 `.gitignore`로 제외되어 있고, `.env.example`이 공유용 틀이다.
- `.env` 내용을 출력하거나 읽어서 보여주지 않는다. 확인이 필요하면 변수 이름만 보거나 길이와 앞 몇 글자만 출력한다.
