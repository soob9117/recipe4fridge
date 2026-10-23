"""냉장고 사진으로 식재료를 인식하고 레시피를 추천·저장하는 Streamlit 앱 (PRD 1~3단계).

실행: streamlit run src/app.py
"""

from datetime import datetime

import pandas as pd
import streamlit as st

import auth
import db
from ai_client import AllModelsFailedError, ApiKeyError
from recipe import CUISINES, DIFFICULTIES, SERVINGS, TIME_LIMITS, generate_recipes
from vision import CATEGORIES, MAX_UPLOAD_BYTES, recognize_ingredients

COLUMNS = ["name", "quantity", "category"]
CONDITION_KEYS = {"cuisine": "default_cuisine", "time_limit": "default_time_limit",
                  "difficulty": "default_difficulty", "servings": "default_servings"}
CONDITION_OPTIONS = {"cuisine": CUISINES, "time_limit": list(TIME_LIMITS),
                     "difficulty": DIFFICULTIES, "servings": SERVINGS}

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
state.setdefault("user", None)  # 로그인한 회원 (비밀번호 해시 제외)
state.setdefault("auth_error", None)
state.setdefault("save_message", None)  # (종류, 문구): 레시피 저장 결과
state.setdefault("profile_message", None)
state.setdefault("confirm_delete", None)  # 삭제 확인 중인 저장 레시피 id
for _key, _default in auth.DEFAULT_CONDITIONS.items():  # 추천 조건 선택 상자의 값
    state.setdefault(_key, _default)


# ── 상태 변경 (버튼 콜백) ─────────────────────────────────────

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
    state.save_message = None


def reset_results() -> None:
    state.recognized = None
    state.ingredients = []
    state.model_used = None
    state.attempts = []
    state.error = None
    reset_recipes()


def apply_profile(user: dict) -> None:
    """프로필의 기본 조건을 추천 조건 선택 상자에 채운다."""
    for key, column in CONDITION_KEYS.items():
        if user[column] in CONDITION_OPTIONS[key]:
            state[key] = user[column]


def sign_in(user: dict) -> None:
    state.user = user
    state.auth_error = None
    state.save_message = None  # 로그인 전에 보여 준 "로그인하면 저장할 수 있어요" 안내를 지움
    apply_profile(user)


def do_login() -> None:
    try:
        sign_in(auth.log_in(state.login_email, state.login_password))
    except (auth.AuthError, db.DatabaseError) as e:
        state.auth_error = str(e)


def do_signup() -> None:
    try:
        sign_in(auth.sign_up(state.signup_email, state.signup_password,
                             state.signup_password_confirm, state.signup_nickname))
    except (auth.AuthError, db.DatabaseError) as e:
        state.auth_error = str(e)


def do_logout() -> None:
    # 회원 정보와 화면에 남은 결과(사진, 식재료, 레시피)를 모두 지움.
    # 업로드 위젯은 브라우저 쪽에 파일을 들고 있으므로 key를 바꿔 새 위젯으로 만든다
    uploader_version = state.get("uploader_version", 0) + 1
    for key in list(state.keys()):
        del state[key]
    state.uploader_version = uploader_version


def save_recipe(recipe: dict) -> None:
    if not state.user:
        state.save_message = ("warning", "로그인하면 레시피를 저장할 수 있어요. 왼쪽에서 로그인하거나 가입해 주세요.")
        return
    try:
        db.save_recipe(state.user["id"], recipe, state.ingredients, state.recipe_model or "")
        state.save_message = ("success", f"'{recipe['title']}'을(를) 내 레시피에 저장했습니다.")
    except db.DuplicateError:
        state.save_message = ("info", "이미 저장한 레시피입니다.")
    except db.DatabaseError as e:
        state.save_message = ("error", f"저장하지 못했습니다. {e}")


def ask_delete(recipe_id: int) -> None:
    state.confirm_delete = recipe_id


def cancel_delete() -> None:
    state.confirm_delete = None


def delete_saved(recipe_id: int) -> None:
    state.confirm_delete = None
    state.save_message = None  # 지운 레시피의 "저장했습니다" 안내가 남지 않게 함
    try:
        db.delete_recipe(state.user["id"], recipe_id)
    except db.DatabaseError as e:
        state.save_message = ("error", f"삭제하지 못했습니다. {e}")


def save_profile() -> None:
    try:
        db.update_profile(state.user["id"], state.profile_nickname.strip() or state.user["nickname"],
                          state.profile_cuisine, state.profile_time_limit,
                          state.profile_difficulty, state.profile_servings)
        state.user = db.get_user(state.user["id"])
        apply_profile(state.user)
        state.profile_message = ("success", "저장했습니다. 레시피 추천 조건에 바로 반영됩니다.")
    except db.DatabaseError as e:
        state.profile_message = ("error", f"저장하지 못했습니다. {e}")


# ── 화면 조각 ─────────────────────────────────────────────────

def show_message(message) -> None:
    if message:
        kind, text = message
        getattr(st, kind)(text)


def show_failed_attempts(attempts: list[str]) -> None:
    if attempts:
        with st.expander(f"실패한 시도 {len(attempts)}건 보기"):
            for line in attempts:
                st.text(line)


def format_item(item: dict) -> str:
    return f"{item['name']} {item['amount']}".strip()


def recipe_meta(recipe: dict) -> str:
    meta = [
        f"⏱ {recipe['time_minutes']}분" if recipe["time_minutes"] else "",
        f"난이도 {recipe['difficulty']}" if recipe["difficulty"] else "",
        f"{recipe['servings']}인분" if recipe["servings"] else "",
        recipe["cuisine"],
    ]
    return " · ".join(m for m in meta if m)


def render_recipe_body(recipe: dict) -> None:
    if recipe["summary"]:
        st.write(recipe["summary"])
    st.caption(recipe_meta(recipe))

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


def render_sidebar() -> None:
    with st.sidebar:
        if state.user:
            st.subheader(f"👋 {state.user['nickname']}님")
            st.caption(state.user["email"])
            st.button("로그아웃", on_click=do_logout, use_container_width=True)
        else:
            st.subheader("로그인")
            st.caption("로그인하지 않아도 식재료 인식과 레시피 추천은 쓸 수 있어요. 레시피를 저장하려면 로그인해 주세요.")
            login_tab, signup_tab = st.tabs(["로그인", "회원 가입"])
            with login_tab:
                with st.form("login_form"):
                    st.text_input("이메일", key="login_email")
                    st.text_input("비밀번호", type="password", key="login_password")
                    st.form_submit_button("로그인", type="primary", on_click=do_login, use_container_width=True)
            with signup_tab:
                with st.form("signup_form"):
                    st.text_input("이메일", key="signup_email")
                    st.text_input(f"비밀번호 ({auth.MIN_PASSWORD_LENGTH}자 이상)", type="password", key="signup_password")
                    st.text_input("비밀번호 확인", type="password", key="signup_password_confirm")
                    st.text_input("닉네임 (비우면 이메일 앞부분)", key="signup_nickname")
                    st.form_submit_button("가입하기", type="primary", on_click=do_signup, use_container_width=True)
            if state.auth_error:
                st.error(state.auth_error)
        st.divider()
        st.caption(f"저장소: {db.backend_name()}")


# ── 탭 1: 레시피 찾기 (1, 2단계) ──────────────────────────────

def render_find() -> None:
    uploaded = st.file_uploader("냉장고 사진 (JPG, PNG, WEBP · 10MB 이하)", type=["jpg", "jpeg", "png", "webp"],
                                key=f"uploader_{state.get('uploader_version', 0)}")
    if uploaded is None:
        reset_results()
        state.photo_id = None
        st.info("먼저 냉장고 사진을 올려 주세요.")
        return

    if uploaded.size > MAX_UPLOAD_BYTES:
        st.error(f"사진이 너무 큽니다({uploaded.size / 1024 / 1024:.1f}MB). 10MB 이하의 사진을 올려 주세요.")
        return

    if uploaded.file_id != state.photo_id:  # 새 사진이면 이전 결과를 지움
        state.photo_id = uploaded.file_id
        reset_results()

    # 1단계: 식재료 인식
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
        return  # 레시피 추천은 식재료를 인식한 뒤에 보임

    # 2단계: 레시피 추천
    st.divider()
    st.header("🍳 레시피 추천")
    condition_col, recipe_col = st.columns([1, 2], gap="large")

    with condition_col:
        st.subheader("추천 조건")
        if state.user:
            st.caption("프로필에 저장한 기본 조건으로 채워져 있어요.")
        cuisine = st.selectbox("요리 종류", CUISINES, key="cuisine")
        time_limit = st.selectbox("조리 시간", list(TIME_LIMITS), key="time_limit")
        difficulty = st.selectbox("난이도", DIFFICULTIES, key="difficulty")
        servings = st.selectbox("인원", SERVINGS, format_func=lambda n: f"{n}인", key="servings")

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
        show_message(state.save_message)

        if state.recipes:
            if state.recipe_basis != basis:
                st.info("식재료나 조건이 바뀌었어요. '다시 추천'을 누르면 반영됩니다.")
            saved_titles = set()
            if state.user:
                try:
                    saved_titles = db.list_titles(state.user["id"])
                except db.DatabaseError as e:
                    st.warning(f"저장 여부를 확인하지 못했습니다. {e}")
            for index, recipe in enumerate(state.recipes):
                with st.container(border=True):
                    title_col, save_col = st.columns([4, 1])
                    title_col.subheader(recipe["title"])
                    if recipe["title"] in saved_titles:
                        save_col.button("저장됨", key=f"saved_{index}", disabled=True, use_container_width=True)
                    else:
                        save_col.button("💾 저장", key=f"save_{index}", on_click=save_recipe, args=(recipe,),
                                        use_container_width=True)
                    render_recipe_body(recipe)
        elif not state.recipe_error:
            st.caption("조건을 고른 뒤 '레시피 추천'을 눌러 주세요. 조건은 모두 선택 사항입니다.")

        if state.recipe_model:
            st.caption(f"레시피 모델: {state.recipe_model}")
        show_failed_attempts(state.recipe_attempts)


# ── 탭 2: 내 레시피 ───────────────────────────────────────────

def render_saved() -> None:
    if not state.user:
        st.info("로그인하면 저장한 레시피를 볼 수 있어요.")
        return
    try:
        saved = db.list_recipes(state.user["id"])
    except db.DatabaseError as e:
        st.error(f"저장한 레시피를 불러오지 못했습니다. {e}")
        return
    if not saved:
        st.info("저장한 레시피가 없습니다. '레시피 찾기'에서 추천받은 레시피의 💾 저장을 눌러 보세요.")
        return

    st.caption(f"저장한 레시피 {len(saved)}개 · 최근 저장 순")
    for item in saved:
        recipe = item["recipe"]
        saved_date = datetime.fromisoformat(item["saved_at"]).astimezone().strftime("%Y-%m-%d")
        label = " · ".join(x for x in [recipe["title"], recipe["cuisine"],
                                       f"{recipe['time_minutes']}분" if recipe["time_minutes"] else "", saved_date] if x)
        with st.expander(label):
            render_recipe_body(recipe)
            st.caption("저장할 때의 식재료: " + ", ".join(i["name"] for i in item["ingredients"])
                       + (f" · 생성 모델: {item['model']}" if item["model"] else ""))
            if state.confirm_delete == item["id"]:
                st.warning("이 레시피를 삭제할까요? 되돌릴 수 없습니다.")
                yes_col, no_col, _ = st.columns([1, 1, 3])
                yes_col.button("삭제", key=f"confirm_{item['id']}", type="primary",
                               on_click=delete_saved, args=(item["id"],), use_container_width=True)
                no_col.button("취소", key=f"cancel_{item['id']}", on_click=cancel_delete, use_container_width=True)
            else:
                st.button("🗑 삭제", key=f"delete_{item['id']}", on_click=ask_delete, args=(item["id"],))


# ── 탭 3: 프로필 ──────────────────────────────────────────────

def render_profile() -> None:
    if not state.user:
        st.info("로그인하면 닉네임과 기본 추천 조건을 저장할 수 있어요.")
        return
    user = state.user
    show_message(state.profile_message)
    with st.form("profile_form"):
        st.text_input("닉네임", value=user["nickname"], max_chars=auth.MAX_NICKNAME_LENGTH, key="profile_nickname")
        st.caption("기본 추천 조건: 레시피 추천 화면이 이 값으로 채워져 열립니다.")
        st.selectbox("기본 요리 종류", CUISINES, index=CUISINES.index(user["default_cuisine"]), key="profile_cuisine")
        st.selectbox("기본 조리 시간", list(TIME_LIMITS), index=list(TIME_LIMITS).index(user["default_time_limit"]),
                     key="profile_time_limit")
        st.selectbox("기본 난이도", DIFFICULTIES, index=DIFFICULTIES.index(user["default_difficulty"]),
                     key="profile_difficulty")
        st.selectbox("기본 인원", SERVINGS, index=SERVINGS.index(user["default_servings"]),
                     format_func=lambda n: f"{n}인", key="profile_servings")
        st.form_submit_button("저장", type="primary", on_click=save_profile)


# ── 페이지 ───────────────────────────────────────────────────

render_sidebar()
st.title("🥕 냉장고 사진으로 레시피 찾기")
st.caption("냉장고 사진을 올리면 AI가 식재료를 찾고, 그 재료로 만들 수 있는 레시피를 추천해 줍니다.")

find_tab, saved_tab, profile_tab = st.tabs(["🥕 레시피 찾기", "📒 내 레시피", "👤 프로필"])
with find_tab:
    render_find()
with saved_tab:
    render_saved()
with profile_tab:
    render_profile()
