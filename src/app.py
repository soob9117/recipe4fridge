"""냉장고 사진으로 식재료를 인식하고 레시피를 추천하는 Streamlit 앱 (PRD 1~2단계).

실행: streamlit run src/app.py
"""

import pandas as pd
import streamlit as st

from ai_client import AllModelsFailedError, ApiKeyError
from recipe import CUISINES, DIFFICULTIES, SERVINGS, TIME_LIMITS, generate_recipes
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
state.setdefault("recipes", [])
state.setdefault("recipe_basis", None)  # 레시피를 만들 때 쓴 식재료와 조건. 바뀌었는지 비교용
state.setdefault("recipe_model", None)
state.setdefault("recipe_attempts", [])
state.setdefault("recipe_error", None)
state.setdefault("recipe_running", False)


def start_recognition() -> None:
    state.running = True


def start_recipe() -> None:
    state.recipe_running = True


def reset_recipes() -> None:
    state.recipes = []
    state.recipe_basis = None
    state.recipe_model = None
    state.recipe_attempts = []
    state.recipe_error = None


def reset_results() -> None:
    state.recognized = None
    state.ingredients = []
    state.model_used = None
    state.attempts = []
    state.error = None
    reset_recipes()


def show_failed_attempts(attempts: list[str]) -> None:
    if attempts:
        with st.expander(f"실패한 시도 {len(attempts)}건 보기"):
            for line in attempts:
                st.text(line)


def format_item(item: dict) -> str:
    return f"{item['name']} {item['amount']}".strip()


def render_recipe(recipe: dict) -> None:
    with st.container(border=True):
        st.subheader(recipe["title"])
        if recipe["summary"]:
            st.write(recipe["summary"])
        meta = [
            f"⏱ {recipe['time_minutes']}분" if recipe["time_minutes"] else "",
            f"난이도 {recipe['difficulty']}" if recipe["difficulty"] else "",
            f"{recipe['servings']}인분" if recipe["servings"] else "",
            recipe["cuisine"],
        ]
        st.caption(" · ".join(m for m in meta if m))

        have_col, need_col = st.columns(2)
        with have_col:
            st.markdown("**✅ 가진 재료**")
            st.markdown("\n".join(f"- {format_item(i)}" for i in recipe["used_ingredients"]))
        with need_col:
            st.markdown("**🛒 부족한 재료**")
            if recipe["missing_ingredients"]:
                st.markdown("\n".join(f"- :orange[{format_item(i)}]" for i in recipe["missing_ingredients"]))
            else:
                st.markdown("없음")

        with st.expander("조리 순서"):
            st.markdown("\n".join(f"{n}. {step}" for n, step in enumerate(recipe["steps"], start=1)))


st.title("🥕 냉장고 사진으로 레시피 찾기")
st.caption("냉장고 사진을 올리면 AI가 식재료를 찾고, 그 재료로 만들 수 있는 레시피를 추천해 줍니다.")

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

# ── 1단계: 식재료 인식 ─────────────────────────────────────────
photo_col, result_col = st.columns(2, gap="large")

with photo_col:
    st.subheader("사진")
    st.image(uploaded)

with result_col:
    st.subheader("인식된 식재료")
    st.button(
        "식재료 인식" if state.recognized is None else "다시 인식",
        type="primary",
        disabled=state.running or state.recipe_running,
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
    show_failed_attempts(state.attempts)

if state.recognized is None:
    st.stop()  # 레시피 추천은 식재료를 인식한 뒤에 보임

# ── 2단계: 레시피 추천 ─────────────────────────────────────────
st.divider()
st.header("🍳 레시피 추천")
condition_col, recipe_col = st.columns([1, 2], gap="large")

with condition_col:
    st.subheader("추천 조건")
    cuisine = st.selectbox("요리 종류", CUISINES, key="cuisine")
    time_limit = st.selectbox("조리 시간", list(TIME_LIMITS), key="time_limit")
    difficulty = st.selectbox("난이도", DIFFICULTIES, key="difficulty")
    servings = st.selectbox("인원", SERVINGS, index=1, format_func=lambda n: f"{n}인", key="servings")

    basis = (tuple((i["name"], i["quantity"]) for i in state.ingredients), cuisine, time_limit, difficulty, servings)
    st.button(
        "레시피 추천" if not state.recipes else "다시 추천",
        type="primary",
        disabled=state.recipe_running or state.running or not state.ingredients,
        on_click=start_recipe,
    )
    if not state.ingredients:
        st.info("식재료를 먼저 추가해 주세요.")

with recipe_col:
    if state.recipe_running:
        with st.spinner("레시피를 만드는 중입니다. 무료 모델은 1분 넘게 걸리기도 해요..."):
            reset_recipes()
            try:
                result = generate_recipes(state.ingredients, cuisine, time_limit, difficulty, servings)
                state.recipes = result.data
                state.recipe_model = result.model
                state.recipe_attempts = result.attempts
                state.recipe_basis = basis
            except ApiKeyError as e:
                state.recipe_error = str(e)
            except AllModelsFailedError as e:
                state.recipe_error = f"모든 모델이 레시피 생성에 실패했습니다. 마지막 원인: {e}"
                state.recipe_attempts = e.attempts
        state.recipe_running = False
        st.rerun()

    if state.recipe_error:
        st.error(state.recipe_error)

    if state.recipes:
        if state.recipe_basis != basis:
            st.info("식재료나 조건이 바뀌었어요. '다시 추천'을 누르면 반영됩니다.")
        for recipe in state.recipes:
            render_recipe(recipe)
    elif not state.recipe_error:
        st.caption("조건을 고른 뒤 '레시피 추천'을 눌러 주세요. 조건은 모두 선택 사항입니다.")

    if state.recipe_model:
        st.caption(f"레시피 모델: {state.recipe_model}")
    show_failed_attempts(state.recipe_attempts)
