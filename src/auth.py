"""이메일·비밀번호 회원 가입과 로그인 (PRD_step3.md 3.1).

비밀번호는 표준 라이브러리 hashlib.scrypt로 해시해 저장하고, 평문은 어디에도 남기지 않는다.
"""

import hashlib
import hmac
import re
import secrets

import db
from recipe import ANY

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_NICKNAME_LENGTH = 20
DEFAULT_CONDITIONS = {"cuisine": ANY, "time_limit": ANY, "difficulty": ANY, "servings": 2}
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1}


class AuthError(Exception):
    """가입·로그인 실패. 메시지는 화면에 그대로 보여 줄 수 있다."""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT_PARAMS)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **SCRYPT_PARAMS)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def sign_up(email: str, password: str, password_confirm: str, nickname: str) -> dict:
    """가입하고 회원 정보(비밀번호 해시 제외)를 돌려준다. 저장소 오류는 db.DatabaseError로 올라간다."""
    email = email.strip().lower()
    nickname = nickname.strip() or email.split("@")[0]
    if not EMAIL_PATTERN.match(email):
        raise AuthError("이메일 형식이 맞지 않습니다.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    if password != password_confirm:
        raise AuthError("비밀번호 확인이 일치하지 않습니다.")
    if len(nickname) > MAX_NICKNAME_LENGTH:
        raise AuthError(f"닉네임은 {MAX_NICKNAME_LENGTH}자 이하로 해 주세요.")

    try:
        user_id = db.create_user(email, hash_password(password), nickname, DEFAULT_CONDITIONS)
    except db.DuplicateError:
        raise AuthError("이미 가입한 이메일입니다. 로그인해 주세요.") from None
    return db.get_user(user_id)


def log_in(email: str, password: str) -> dict:
    """로그인하고 회원 정보(비밀번호 해시 제외)를 돌려준다."""
    row = db.find_login(email.strip().lower())
    # 이메일이 없는 경우와 비밀번호가 틀린 경우를 같은 문구로 알려 가입 여부가 드러나지 않게 함
    if not row or not verify_password(password, row.pop("password_hash")):
        raise AuthError("이메일 또는 비밀번호가 맞지 않습니다.")
    return row
