#!/usr/bin/env python3
"""Autentikasi: user/password + token (expiry + credit)."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
LOG_FILE = os.path.join(BASE_DIR, "access_log.json")
TOKENS_FILE = os.path.join(BASE_DIR, "tokens.json")

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

# Biaya credit scrape
COST_PER_STATE = 1
COST_ALL_STATES = 5
COST_TOP25 = 10  # flat bila mode ranking/top25 aktif


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S UTC")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _load_json(path: str, default: Any) -> Any:
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# -------------------- users --------------------

def ensure_users_file() -> Dict[str, Any]:
    data = _load_json(USERS_FILE, None)
    if not isinstance(data, dict) or "users" not in data:
        salt = secrets.token_hex(8)
        data = {
            "users": {
                DEFAULT_ADMIN_USER: {
                    "salt": salt,
                    "password_hash": _hash_password(DEFAULT_ADMIN_PASS, salt),
                    "role": "admin",
                    "created_at": _now_iso(),
                    "active": True,
                    "display_name": "Administrator",
                }
            }
        }
        _save_json(USERS_FILE, data)
    return data


def list_users() -> List[Dict[str, Any]]:
    data = ensure_users_file()
    out = []
    for username, info in data.get("users", {}).items():
        out.append({
            "username": username,
            "role": info.get("role", "user"),
            "active": bool(info.get("active", True)),
            "created_at": info.get("created_at", ""),
            "display_name": info.get("display_name") or username,
            "last_login": info.get("last_login", ""),
        })
    out.sort(key=lambda u: (0 if u["role"] == "admin" else 1, u["username"]))
    return out


def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    username = (username or "").strip()
    if not username or not password:
        return None
    data = ensure_users_file()
    info = data.get("users", {}).get(username)
    if not info or not info.get("active", True):
        return None
    salt = info.get("salt") or ""
    if _hash_password(password, salt) != info.get("password_hash"):
        return None
    info["last_login"] = _now_iso()
    data["users"][username] = info
    _save_json(USERS_FILE, data)
    return {
        "username": username,
        "role": info.get("role", "user"),
        "display_name": info.get("display_name") or username,
        "auth_type": "password",
    }


def add_user(username: str, password: str, role: str = "user", display_name: str = "") -> Tuple[bool, str]:
    username = (username or "").strip().lower()
    if not username or not password:
        return False, "Username dan password wajib diisi."
    if len(username) < 3:
        return False, "Username minimal 3 karakter."
    if len(password) < 4:
        return False, "Password minimal 4 karakter."
    if role not in ("admin", "user"):
        role = "user"
    data = ensure_users_file()
    if username in data.get("users", {}):
        return False, f"Username '{username}' sudah ada."
    salt = secrets.token_hex(8)
    data["users"][username] = {
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "role": role,
        "created_at": _now_iso(),
        "active": True,
        "display_name": display_name or username,
        "last_login": "",
    }
    _save_json(USERS_FILE, data)
    return True, f"User '{username}' ditambahkan."


def set_user_active(username: str, active: bool) -> Tuple[bool, str]:
    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    if username == DEFAULT_ADMIN_USER and not active:
        return False, "Admin default tidak bisa dinonaktifkan."
    users[username]["active"] = bool(active)
    _save_json(USERS_FILE, data)
    return True, f"User '{username}' {'diaktifkan' if active else 'dinonaktifkan'}."


def delete_user(username: str) -> Tuple[bool, str]:
    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    if username == DEFAULT_ADMIN_USER:
        return False, "Admin default tidak bisa dihapus."
    if users[username].get("role") == "admin":
        admins = [u for u, i in users.items() if i.get("role") == "admin"]
        if len(admins) <= 1:
            return False, "Tidak bisa hapus admin terakhir."
    del users[username]
    _save_json(USERS_FILE, data)
    return True, f"User '{username}' dihapus."


def change_password(username: str, new_password: str) -> Tuple[bool, str]:
    if not new_password or len(new_password) < 4:
        return False, "Password minimal 4 karakter."
    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    salt = secrets.token_hex(8)
    users[username]["salt"] = salt
    users[username]["password_hash"] = _hash_password(new_password, salt)
    _save_json(USERS_FILE, data)
    return True, "Password diubah."


# -------------------- tokens --------------------

def ensure_tokens_file() -> Dict[str, Any]:
    data = _load_json(TOKENS_FILE, None)
    if not isinstance(data, dict) or "tokens" not in data:
        data = {"tokens": {}}
        _save_json(TOKENS_FILE, data)
    return data


def _gen_token_string(length: int = 24) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # hindari karakter membingungkan
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    return "MP-" + "".join(secrets.choice(alphabet) for _ in range(length))


def create_token(
    credits: int,
    valid_hours: float,
    label: str = "",
    created_by: str = "admin",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Buat token baru. valid_hours: masa berlaku dari sekarang."""
    try:
        credits = int(credits)
        valid_hours = float(valid_hours)
    except (TypeError, ValueError):
        return False, "Credits / durasi tidak valid.", None
    if credits < 0:
        return False, "Credits tidak boleh negatif.", None
    if valid_hours <= 0:
        return False, "Durasi harus > 0 jam.", None

    data = ensure_tokens_file()
    token = _gen_token_string()
    while token in data["tokens"]:
        token = _gen_token_string()

    expires = _now() + timedelta(hours=valid_hours)
    info = {
        "token": token,
        "credits": credits,
        "credits_initial": credits,
        "label": (label or "").strip() or "token",
        "created_by": created_by,
        "created_at": _now_iso(),
        "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expires_ts": expires.timestamp(),
        "active": True,
        "last_used": "",
        "use_count": 0,
    }
    data["tokens"][token] = info
    _save_json(TOKENS_FILE, data)
    return True, "Token dibuat.", info


def list_tokens() -> List[Dict[str, Any]]:
    data = ensure_tokens_file()
    now_ts = _now().timestamp()
    out = []
    for tok, info in data.get("tokens", {}).items():
        exp_ts = float(info.get("expires_ts") or 0)
        expired = exp_ts > 0 and now_ts > exp_ts
        out.append({
            **info,
            "token": tok,
            "expired": expired,
            "status": (
                "nonaktif" if not info.get("active", True)
                else ("kadaluarsa" if expired else "aktif")
            ),
        })
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def get_token(token: str) -> Optional[Dict[str, Any]]:
    token = (token or "").strip()
    if not token:
        return None
    data = ensure_tokens_file()
    info = data.get("tokens", {}).get(token)
    if not info:
        return None
    return {**info, "token": token}


def verify_token_login(token: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Login pakai token. Return (session_dict, error_message)."""
    token = (token or "").strip()
    if not token:
        return None, "Token kosong."
    data = ensure_tokens_file()
    info = data.get("tokens", {}).get(token)
    if not info:
        return None, "Token tidak valid."
    if not info.get("active", True):
        return None, "Token nonaktif."
    exp_ts = float(info.get("expires_ts") or 0)
    if exp_ts and _now().timestamp() > exp_ts:
        return None, "Token sudah kadaluarsa."
    if int(info.get("credits", 0)) <= 0:
        return None, "Credit token habis."

    info["last_used"] = _now_iso()
    data["tokens"][token] = info
    _save_json(TOKENS_FILE, data)

    return {
        "username": f"token:{token[:10]}…",
        "role": "token",
        "display_name": info.get("label") or "Token user",
        "auth_type": "token",
        "token": token,
        "credits": int(info.get("credits", 0)),
        "expires_at": info.get("expires_at", ""),
    }, ""


def refresh_token_session(token: str) -> Optional[Dict[str, Any]]:
    """Ambil status credit/expiry terbaru untuk session token."""
    info = get_token(token)
    if not info:
        return None
    exp_ts = float(info.get("expires_ts") or 0)
    if not info.get("active", True):
        return None
    if exp_ts and _now().timestamp() > exp_ts:
        return None
    return {
        "username": f"token:{token[:10]}…",
        "role": "token",
        "display_name": info.get("label") or "Token user",
        "auth_type": "token",
        "token": token,
        "credits": int(info.get("credits", 0)),
        "expires_at": info.get("expires_at", ""),
    }


def set_token_active(token: str, active: bool) -> Tuple[bool, str]:
    data = ensure_tokens_file()
    if token not in data.get("tokens", {}):
        return False, "Token tidak ditemukan."
    data["tokens"][token]["active"] = bool(active)
    _save_json(TOKENS_FILE, data)
    return True, "Token diubah."


def delete_token(token: str) -> Tuple[bool, str]:
    data = ensure_tokens_file()
    if token not in data.get("tokens", {}):
        return False, "Token tidak ditemukan."
    del data["tokens"][token]
    _save_json(TOKENS_FILE, data)
    return True, "Token dihapus."


def add_token_credits(token: str, amount: int) -> Tuple[bool, str]:
    data = ensure_tokens_file()
    if token not in data.get("tokens", {}):
        return False, "Token tidak ditemukan."
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, "Jumlah tidak valid."
    data["tokens"][token]["credits"] = max(0, int(data["tokens"][token].get("credits", 0)) + amount)
    _save_json(TOKENS_FILE, data)
    return True, f"Credit sekarang: {data['tokens'][token]['credits']}"


def scrape_credit_cost(*, is_all: bool, top25_on: bool) -> int:
    """Hitung biaya credit 1x scrape."""
    if top25_on:
        return COST_TOP25
    if is_all:
        return COST_ALL_STATES
    return COST_PER_STATE


def deduct_token_credits(token: str, cost: int) -> Tuple[bool, str, int]:
    """Potong credit. Return (ok, message, remaining)."""
    data = ensure_tokens_file()
    info = data.get("tokens", {}).get(token)
    if not info:
        return False, "Token tidak ditemukan.", 0
    if not info.get("active", True):
        return False, "Token nonaktif.", 0
    exp_ts = float(info.get("expires_ts") or 0)
    if exp_ts and _now().timestamp() > exp_ts:
        return False, "Token kadaluarsa.", 0
    credits = int(info.get("credits", 0))
    if credits < cost:
        return False, f"Credit kurang (punya {credits}, butuh {cost}).", credits
    credits -= cost
    info["credits"] = credits
    info["use_count"] = int(info.get("use_count", 0)) + 1
    info["last_used"] = _now_iso()
    data["tokens"][token] = info
    _save_json(TOKENS_FILE, data)
    return True, f"Dipotong {cost} credit. Sisa {credits}.", credits


# -------------------- logs --------------------

def log_access(username: str, action: str, detail: str = "", ip: str = "") -> None:
    logs = _load_json(LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    logs.append({
        "time": _now_iso(),
        "username": username,
        "action": action,
        "detail": detail,
        "ip": ip,
    })
    logs = logs[-500:]
    _save_json(LOG_FILE, logs)


def get_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    logs = _load_json(LOG_FILE, [])
    if not isinstance(logs, list):
        return []
    return list(reversed(logs[-limit:]))
