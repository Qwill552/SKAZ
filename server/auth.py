"""Проверка Bearer-токена."""
import secrets

BEARER_PREFIX = "Bearer "


def check_auth(header_value: str | None, token: str) -> bool:
    if not header_value or not header_value.startswith(BEARER_PREFIX):
        return False
    provided = header_value[len(BEARER_PREFIX):]
    return secrets.compare_digest(provided, token)
