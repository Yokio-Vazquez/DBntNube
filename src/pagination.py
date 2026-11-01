"""Versioned cursor and unique chronological storage key for M08."""
import base64
import binascii
import json
from datetime import datetime


class InvalidCursor(ValueError):
    pass


def time_key(item):
    value = item["occurred_at"]
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("occurred_at debe ser UTC YYYY-MM-DDTHH:MM:SSZ")
    key = value + "#" + item["event_key"]
    if len(key.encode("utf-8")) > 1024:
        raise ValueError("Clave de orden excede 1024 bytes")
    return key


def encode_cursor(item):
    payload = {"v": 1, "game_id": int(item["game_id"]),
               "occurred_at": item["occurred_at"], "event_key": item["event_key"]}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":"),
                                             ensure_ascii=False).encode()).decode().rstrip("=")


def decode_cursor(cursor, game_id):
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 4096:
            raise ValueError()
        payload = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4),
                                             altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != {"v", "game_id", "occurred_at", "event_key"}:
            raise ValueError()
        if type(payload["v"]) is not int or payload["v"] != 1:
            raise ValueError()
        if type(payload["game_id"]) is not int or payload["game_id"] != game_id or game_id <= 0:
            raise ValueError()
        if any(not isinstance(payload[k], str) or not payload[k] for k in ("occurred_at", "event_key")):
            raise ValueError()
        return {"game_id": game_id, "event_key": payload["event_key"],
                "game_time_key": time_key(payload)}
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as error:
        raise InvalidCursor("Cursor invalido para este juego") from error
