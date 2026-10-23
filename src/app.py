"""냉장고 사진으로 식재료를 인식하는 Streamlit 앱 (PRD 1단계).

실행: streamlit run src/app.py
"""

import pandas as pd
import streamlit as st

from ai_client import AllModelsFailedError, ApiKeyError
from vision import CATEGORIES, MAX_UPLOAD_BYTES, recognize_ingredients

COLUMNS = ["name", "quantity", "category"]

st.set_page_config(page_title="냉장고 레시피", page_icon="🥕", layout="wide")

state = st.session_state
state.setdefault("photo_id", None)
state.setdefault("recognized", None)  # 모델이 인식한 목록. 편집표의 처음 값
state.setdefault("ingredients", [])  # 사용자가 확인·편집한 목록. 2단계의 입력
state.setdefault("model_used", None)
state.setdefault("attempts", [])  # 실패한 시도 기록
state.setdefault("error", None)
state.setdefault("running", False)
state.setdefault("run_count", 0)  # 다시 인식할 때마다 편집표를 새로 만들기 위한 번호


def start_recognition() -> None:
    state.running = True


def reset_results() -> None:
    state.recognized = None
    state.ingredients = []
    state.model_used = None
    state.attempts = []
    state.error = None


st.title("🥕 냉장고 사진으로 식재료 찾기")
st.caption("냉장고 사진을 올리면 AI가 식재료를 찾아 줍니다. 결과는 직접 고칠 수 있어요.")

uploaded = st.file_uploader("냉장고 사진 (JPG, PNG, WEBP · 10MB 이하)", type=["jpg", "jpeg", "png", "webp"])
if uploaded is None:
    reset_results()
    state.photo_id = None
    st.info("먼저 냉장고 사진을 올려 주세요.")
    st.stop()

if uploaded.size > MAX_UPLOAD_BYTES:
    st.error(f"사진이 너무 큽니다({uploaded.size / 1024 / 1024:.1f}MB). 10MB 이하의 사진을 올려 주세요.")
    st.stop()

if uploaded.file_id != state.photo_id:  # 새 사진이면 이전 결과를 지움
    state.photo_id = uploaded.file_id
    reset_results()

photo_col, result_col = st.columns(2, gap="large")

with photo_col:
    st.subheader("사진")
    st.image(uploaded)

with result_col:
    st.subheader("인식된 식재료")
    st.button(
        "식재료 인식" if state.recognized is None else "다시 인식",
        type="primary",
        disabled=state.running,
        on_click=start_recognition,
    )

    if state.running:
        with st.spinner("식재료를 인식하는 중입니다. 무료 모델은 1분 넘게 걸리기도 해요..."):
            reset_results()
            try:
                result = recognize_ingredients(uploaded.getvalue())
                state.recognized = result.data
                state.model_used = result.model
                state.attempts = result.attempts
            except ApiKeyError as e:
                state.error = str(e)
            except AllModelsFailedError as e:
                state.error = f"모든 모델이 식재료 인식에 실패했습니다. 마지막 원인: {e}"
                state.attempts = e.attempts
            except Exception as e:  # 사진 파일 손상 등
                state.error = f"사진을 처리하지 못했습니다: {e}"
        state.running = False
        state.run_count += 1
        st.rerun()

    if state.error:
        st.error(state.error)

    if state.recognized is not None:
        if not state.recognized:
            st.warning("식재료를 찾지 못했습니다. 다른 사진을 올리거나 아래 표에 직접 추가해 주세요.")

        edited = st.data_editor(
            pd.DataFrame(state.recognized, columns=COLUMNS),
            key=f"editor_{state.run_count}",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "name": st.column_config.TextColumn("이름", required=True),
                "quantity": st.column_config.TextColumn("수량"),
                "category": st.column_config.SelectboxColumn("분류", options=CATEGORIES, default="기타"),
            },
        )
        st.caption("칸을 두 번 눌러 고치고, 맨 아래 빈 행을 눌러 추가하고, "
                   "행 맨 왼쪽을 눌러 선택한 뒤 Delete 키나 표 위의 휴지통 아이콘으로 지웁니다.")

        state.ingredients = [
            {"name": str(row["name"]).strip(), "quantity": str(row["quantity"] or "").strip(),
             "category": row["category"] or "기타"}
            for row in edited.fillna("").to_dict("records")
            if str(row["name"]).strip()
        ]
        st.success(f"확정된 식재료 {len(state.ingredients)}개")

    if state.model_used:
        st.caption(f"인식 모델: {state.model_used}")
    if state.attempts:
        with st.expander(f"실패한 시도 {len(state.attempts)}건 보기"):
            for line in state.attempts:
                st.text(line)
