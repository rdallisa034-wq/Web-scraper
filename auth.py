#!/usr/bin/env python3
"""Autentikasi sederhana untuk Streamlit MaxPreps Scraper.

- File users: users.json (hash password SHA-256 + salt)
- Log akses: access_log.json
- Admin default: admin / admin123  (GANTI setelah login pertama)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "access_log.json")

# Default admin — ganti password setelah deploy
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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


def ensure_users_file() -> Dict[str, Any]:
    """Buat users.json + admin default jika belum ada."""
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
    """Return user dict jika login OK, else None."""
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
    # update last_login
    info["last_login"] = _now_iso()
    data["users"][username] = info
    _save_json(USERS_FILE, data)
    return {
        "username": username,
        "role": info.get("role", "user"),
        "display_name": info.get("display_name") or username,
    }


def add_user(
    username: str,
    password: str,
    role: str = "user",
    display_name: str = "",
) -> tuple[bool, str]:
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


def set_user_active(username: str, active: bool) -> tuple[bool, str]:
    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    if username == DEFAULT_ADMIN_USER and not active:
        return False, "Admin default tidak bisa dinonaktifkan."
    users[username]["active"] = bool(active)
    _save_json(USERS_FILE, data)
    return True, f"User '{username}' {'diaktifkan' if active else 'dinonaktifkan'}."


def delete_user(username: str) -> tuple[bool, str]:
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


def change_password(username: str, new_password: str) -> tuple[bool, str]:
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


def log_access(
    username: str,
    action: str,
    detail: str = "",
    ip: str = "",
) -> None:
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
    # simpan max 500 entri terakhir
    logs = logs[-500:]
    _save_json(LOG_FILE, logs)


def get_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    logs = _load_json(LOG_FILE, [])
    if not isinstance(logs, list):
        return []
    return list(reversed(logs[-limit:]))
