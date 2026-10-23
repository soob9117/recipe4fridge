"""회원, 프로필, 저장한 레시피 저장소 (PRD_step3.md 3.5).

DATABASE_URL이 있으면 Postgres(Supabase), 없으면 프로젝트 루트의 data/app.db(SQLite)를 쓴다.
SQL은 SQLite 형식(? 자리표시자)으로 쓰고, Postgres에서는 %s로 바꿔 실행한다.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"
USER_FIELDS = "id, email, nickname, default_cuisine, default_time_limit, default_difficulty, default_servings"

SCHEMA = {
    "sqlite": [
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            nickname TEXT NOT NULL,
            default_cuisine TEXT NOT NULL,
            default_time_limit TEXT NOT NULL,
            default_difficulty TEXT NOT NULL,
            default_servings INTEGER NOT NULL,
            created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS saved_recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            recipe_json TEXT NOT NULL,
            ingredients_json TEXT NOT NULL,
            model TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            UNIQUE (user_id, title))""",
    ],
    "postgres": [
        """CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            nickname TEXT NOT NULL,
            default_cuisine TEXT NOT NULL,
            default_time_limit TEXT NOT NULL,
            default_difficulty TEXT NOT NULL,
            default_servings INTEGER NOT NULL,
            created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS saved_recipes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            recipe_json TEXT NOT NULL,
            ingredients_json TEXT NOT NULL,
            model TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            UNIQUE (user_id, title))""",
        # Supabase의 공개 API(anon key)로는 표를 읽지 못하게 함. 앱은 표 소유자로 접속하므로 영향 없음
        "ALTER TABLE users ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE saved_recipes ENABLE ROW LEVEL SECURITY",
    ],
}

_initialized: set[str] = set()  # 이번 프로세스에서 표를 만든 저장소


class DatabaseError(Exception):
    """저장소에 연결하지 못했거나 쿼리가 실패함. 메시지는 화면에 그대로 보여 줄 수 있다."""


class DuplicateError(Exception):
    """UNIQUE 조건 위반 (같은 이메일, 같은 사용자의 같은 제목 레시피)."""


def database_url() -> str:
    # 로컬에서는 .env, Streamlit Community Cloud에서는 Secrets의 최상위 키가 환경변수로 들어옴
    load_dotenv()
    return os.getenv("DATABASE_URL", "").strip()


def backend_name() -> str:
    return "Supabase(Postgres)" if database_url() else "SQLite(내 PC)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Connection:
    def __init__(self, conn, kind: str):
        self.conn = conn
        self.kind = kind

    def execute(self, sql: str, params: tuple = ()):
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return cursor

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.execute(sql, params).fetchall()]


@contextmanager
def connect() -> Iterator[_Connection]:
    """작업마다 새로 연결하고 끝나면 닫는다. 잠들었다 깬 앱이 끊긴 연결을 재사용하는 문제를 피한다."""
    url = database_url()
    try:
        if url:
            import psycopg
            from psycopg.rows import dict_row

            # prepare_threshold=None: Supabase transaction pooler(pgbouncer)와 함께 쓰기 위함
            raw = psycopg.connect(url, row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
            kind = "postgres"
        else:
            SQLITE_PATH.parent.mkdir(exist_ok=True)
            raw = sqlite3.connect(SQLITE_PATH, timeout=10)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys = ON")
            kind = "sqlite"
    except Exception as e:
        raise DatabaseError(f"저장소에 연결하지 못했습니다 ({type(e).__name__}). 잠시 뒤 다시 시도해 주세요.") from e

    conn = _Connection(raw, kind)
    try:
        if (url or kind) not in _initialized:
            for statement in SCHEMA[kind]:
                conn.execute(statement)
            _initialized.add(url or kind)
        yield conn
        raw.commit()
    except Exception as e:
        raw.rollback()
        if any(cls.__name__ == "IntegrityError" for cls in type(e).__mro__):
            raise DuplicateError(str(e)) from e
        if isinstance(e, (DatabaseError, DuplicateError)):
            raise
        raise DatabaseError(f"저장소 작업에 실패했습니다 ({type(e).__name__}).") from e
    finally:
        raw.close()


# ── 회원과 프로필 ─────────────────────────────────────────────

def create_user(email: str, password_hash: str, nickname: str, defaults: dict) -> int:
    with connect() as conn:
        row = conn.fetch_one(
            "INSERT INTO users (email, password_hash, nickname, default_cuisine, default_time_limit,"
            " default_difficulty, default_servings, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (email, password_hash, nickname, defaults["cuisine"], defaults["time_limit"],
             defaults["difficulty"], defaults["servings"], _now()),
        )
    return row["id"]


def find_login(email: str) -> dict | None:
    """로그인 확인용. password_hash를 포함한다."""
    with connect() as conn:
        return conn.fetch_one(f"SELECT {USER_FIELDS}, password_hash FROM users WHERE email = ?", (email,))


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        return conn.fetch_one(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (user_id,))


def update_profile(user_id: int, nickname: str, cuisine: str, time_limit: str, difficulty: str, servings: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET nickname = ?, default_cuisine = ?, default_time_limit = ?,"
            " default_difficulty = ?, default_servings = ? WHERE id = ?",
            (nickname, cuisine, time_limit, difficulty, servings, user_id),
        )


# ── 저장한 레시피 (모든 쿼리를 user_id로 제한해 자기 것만 읽고 지움) ──────────

def save_recipe(user_id: int, recipe: dict, ingredients: list[dict], model: str) -> None:
    """같은 사용자가 같은 제목을 다시 저장하면 DuplicateError."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO saved_recipes (user_id, title, recipe_json, ingredients_json, model, saved_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, recipe["title"], json.dumps(recipe, ensure_ascii=False),
             json.dumps(ingredients, ensure_ascii=False), model, _now()),
        )


def list_titles(user_id: int) -> set[str]:
    with connect() as conn:
        return {row["title"] for row in conn.fetch_all("SELECT title FROM saved_recipes WHERE user_id = ?", (user_id,))}


def list_recipes(user_id: int) -> list[dict]:
    """최근 저장 순. 각 항목: id, recipe, ingredients, model, saved_at."""
    with connect() as conn:
        rows = conn.fetch_all(
            "SELECT id, recipe_json, ingredients_json, model, saved_at FROM saved_recipes"
            " WHERE user_id = ? ORDER BY saved_at DESC, id DESC",
            (user_id,),
        )
    return [{
        "id": row["id"],
        "recipe": json.loads(row["recipe_json"]),
        "ingredients": json.loads(row["ingredients_json"]),
        "model": row["model"],
        "saved_at": row["saved_at"],
    } for row in rows]


def delete_recipe(user_id: int, recipe_id: int) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM saved_recipes WHERE id = ? AND user_id = ?", (recipe_id, user_id))
        return cursor.rowcount > 0
