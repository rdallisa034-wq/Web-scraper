#!/usr/bin/env python3
"""Autentikasi: user/password + token (credit | waktu).

Backend:
  - Supabase (jika SUPABASE_URL + SUPABASE_KEY di env / st.secrets)
  - Fallback: file JSON lokal (dev / tanpa Supabase)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")
LOG_FILE = os.path.join(BASE_DIR, "access_log.json")
TOKENS_FILE = os.path.join(BASE_DIR, "tokens.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
OTP_FILE = os.path.join(BASE_DIR, ".otp_temp.json")

DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

COST_PER_STATE = 1
COST_ALL_STATES = 5
COST_TOP25 = 10

_DEFAULT_SETTINGS = {
    "buy_token_url": "https://wa.me/6281234567890",
    "buy_token_text": "Beli token",
    "buy_token_message": "Halo admin, saya ingin beli token MaxPreps Scraper.",
    "buy_token_enabled": True,
}

# -------------------- time / hash --------------------

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


# -------------------- Supabase client --------------------

_sb_client = None
_sb_checked = False


def _secrets_get(key: str, default: str = "") -> str:
    v = os.environ.get(key, "")
    if v:
        return v
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
        # nested [supabase] url / key
        if "supabase" in st.secrets:
            block = st.secrets["supabase"]
            if key == "SUPABASE_URL" and "url" in block:
                return str(block["url"])
            if key == "SUPABASE_KEY" and "key" in block:
                return str(block["key"])
    except Exception:
        pass
    return default


def use_supabase() -> bool:
    return bool(_secrets_get("SUPABASE_URL") and _secrets_get("SUPABASE_KEY"))


def _sb():
    global _sb_client, _sb_checked
    if _sb_checked:
        return _sb_client
    _sb_checked = True
    url = _secrets_get("SUPABASE_URL")
    key = _secrets_get("SUPABASE_KEY")
    if not url or not key:
        _sb_client = None
        return None
    try:
        from supabase import create_client
        _sb_client = create_client(url, key)
    except Exception:
        _sb_client = None
    return _sb_client


def backend_name() -> str:
    return "supabase" if (use_supabase() and _sb()) else "json"


# -------------------- users --------------------

def _maybe_reset_admin_from_secrets() -> None:
    """Auto-create or reset admin user (email-based lookup)."""
    new_pw = _secrets_get("ADMIN_RESET_PASSWORD", "")
    if not new_pw or len(new_pw) < 4:
        return
    
    salt = secrets.token_hex(8)
    ph = _hash_password(new_pw, salt)
    admin_email = "admin@local"
    
    if use_supabase() and _sb():
        try:
            client = _sb()
            # Check by email (new schema)
            r = client.table("app_users").select("email").eq("email", admin_email).execute()
            if r.data:
                # Update existing
                client.table("app_users").update(
                    {"salt": salt, "password_hash": ph, "active": True, "role": "admin"}
                ).eq("email", admin_email).execute()
            else:
                # Create new
                client.table("app_users").insert({
                    "email": admin_email,
                    "username": DEFAULT_ADMIN_USER,
                    "salt": salt,
                    "password_hash": ph,
                    "role": "admin",
                    "created_at": _now_iso(),
                    "active": True,
                    "display_name": "Administrator",
                    "last_login": "",
                }).execute()
        except Exception:
            pass
        return
    
    # JSON fallback
    data = _load_json(USERS_FILE, None)
    if not isinstance(data, dict) or "users" not in data:
        data = {"users": {}}
    data["users"][admin_email] = {
        "email": admin_email,
        "username": DEFAULT_ADMIN_USER,
        "salt": salt,
        "password_hash": ph,
        "role": "admin",
        "created_at": _now_iso(),
        "active": True,
        "display_name": "Administrator",
        "last_login": "",
    }
    _save_json(USERS_FILE, data)



def ensure_users_file() -> Dict[str, Any]:
    """Pastikan admin default ada (JSON atau Supabase)."""
    if use_supabase() and _sb():
        client = _sb()
        try:
            r = client.table("app_users").select("username").eq("username", DEFAULT_ADMIN_USER).execute()
            if not r.data:
                salt = secrets.token_hex(8)
                client.table("app_users").upsert({
                    "username": DEFAULT_ADMIN_USER,
                    "salt": salt,
                    "password_hash": _hash_password(DEFAULT_ADMIN_PASS, salt),
                    "role": "admin",
                    "created_at": _now_iso(),
                    "active": True,
                    "display_name": "Administrator",
                    "last_login": "",
                }).execute()
        except Exception:
            pass
        return {"users": {}}

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


def suspend_user(username: str, hours: int = 24) -> Tuple[bool, str]:
    """Suspend user untuk hours, set suspended_until datetime."""
    username = (username or "").strip().lower()
    if not username or hours < 1:
        return False, "Invalid username atau hours"
    
    suspend_until = _now() + timedelta(hours=hours)
    suspend_until_str = suspend_until.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    if use_supabase() and _sb():
        try:
            _sb().table("app_users").update({
                "suspended_until": suspend_until_str
            }).eq("username", username).execute()
            return True, f"User {username} ditangguhkan hingga {suspend_until_str}"
        except Exception as e:
            return False, str(e)
    
    data = ensure_users_file()
    if username not in data.get("users", {}):
        return False, f"User {username} tidak ditemukan"
    
    data["users"][username]["suspended_until"] = suspend_until_str
    _save_json(USERS_FILE, data)
    return True, f"User {username} ditangguhkan hingga {suspend_until_str}"


def unsuspend_user(username: str) -> Tuple[bool, str]:
    """Clear suspended_until, restore user."""
    username = (username or "").strip().lower()
    
    if use_supabase() and _sb():
        try:
            _sb().table("app_users").update({
                "suspended_until": None
            }).eq("username", username).execute()
            return True, f"User {username} dipulihkan"
        except Exception as e:
            return False, str(e)
    
    data = ensure_users_file()
    if username not in data.get("users", {}):
        return False, f"User {username} tidak ditemukan"
    
    data["users"][username].pop("suspended_until", None)
    _save_json(USERS_FILE, data)
    return True, f"User {username} dipulihkan"


def list_users() -> List[Dict[str, Any]]:
    ensure_users_file()
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_users").select(
                "username,role,active,created_at,display_name,last_login,suspended_until"
            ).execute()
            out = []
            for row in r.data or []:
                out.append({
                    "username": row["username"],
                    "role": row.get("role", "user"),
                    "active": bool(row.get("active", True)),
                    "created_at": row.get("created_at") or "",
                    "display_name": row.get("display_name") or row["username"],
                    "last_login": row.get("last_login") or "",
                    "suspended_until": row.get("suspended_until") or "",
                })
            out.sort(key=lambda u: (0 if u["role"] == "admin" else 1, u["username"]))
            return out
        except Exception:
            return []

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


def verify_login(email_or_username: str, password: str) -> Optional[Dict[str, Any]]:
    identifier = (email_or_username or "").strip().lower()
    if not identifier or not password:
        return None
    ensure_users_file()

    # Optional emergency reset via secrets (sekali jalan)
    _maybe_reset_admin_from_secrets()

    if use_supabase() and _sb():
        try:
            # Try email first, then username for backward compat
            r = _sb().table("app_users").select("*").eq("email", identifier).limit(1).execute()
            if not r.data:
                r = _sb().table("app_users").select("*").eq("username", identifier).limit(1).execute()
            if not r.data:
                return None
            info = r.data[0]
            
            salt = info.get("salt") or ""
            if _hash_password(password, salt) != (info.get("password_hash") or ""):
                return None
            
            # Cek suspended
            susp_until_str = info.get("suspended_until") or ""
            if susp_until_str:
                try:
                    susp_until = datetime.fromisoformat(susp_until_str.replace(" UTC", "+00:00"))
                    if _now() < susp_until:
                        return {"error": "suspended", "message": f"Akun ditangguhkan hingga {susp_until_str}"}
                except Exception:
                    pass
            
            # Cek banned (active=false tanpa suspended_until)
            if info.get("active") is False and not susp_until_str:
                return {"error": "banned", "message": "Akun di-banned."}
            
            try:
                _sb().table("app_users").update({"last_login": _now_iso()}).eq("email", identifier).execute()
            except Exception:
                pass
            
            account = {
                "email": info.get("email") or identifier,
                "username": info.get("username") or identifier,
                "role": info.get("role") or "user",
                "display_name": info.get("display_name") or identifier,
                "auth_type": "password",
            }
            
            # Cek token owner
            try:
                tok_r = _sb().table("app_tokens").select("*").eq("token_owner", identifier).limit(1).execute()
                if tok_r.data:
                    tok_info = tok_r.data[0]
                    account.update(_token_session_dict(tok_info["token"], tok_info))
            except Exception:
                pass
            
            return account
        except Exception:
            pass

    data = ensure_users_file()
    # Try email first, then username for backward compat
    info = data.get("users", {}).get(identifier)
    if not info:
        return None
    
    if _hash_password(password, info.get("salt") or "") != info.get("password_hash"):
        return None
    
    # Cek suspended
    susp_until_str = info.get("suspended_until") or ""
    if susp_until_str:
        try:
            susp_until = datetime.fromisoformat(susp_until_str.replace(" UTC", "+00:00"))
            if _now() < susp_until:
                return {"error": "suspended", "message": f"Akun ditangguhkan hingga {susp_until_str}"}
        except Exception:
            pass
    
    # Cek banned
    if info.get("active") is False and not susp_until_str:
        return {"error": "banned", "message": "Akun di-banned."}
    
    info["last_login"] = _now_iso()
    data["users"][identifier] = info
    _save_json(USERS_FILE, data)
    
    account = {
        "email": info.get("email") or identifier,
        "username": info.get("username") or identifier,
        "role": info.get("role", "user"),
        "display_name": info.get("display_name") or identifier,
        "auth_type": "password",
    }
    
    # Cek token owner di JSON
    tok_data = ensure_tokens_file()
    for tok, tok_info in tok_data.get("tokens", {}).items():
        if tok_info.get("token_owner") == identifier:
            account.update(_token_session_dict(tok, tok_info))
            break
    
    return account


def generate_otp(length: int = 6) -> str:
    """Generate random OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def send_otp(email: str) -> Tuple[bool, str]:
    """Generate + store OTP, send via Resend or Gmail SMTP or console fallback."""
    otp = generate_otp()
    otp_data = _load_json(OTP_FILE, {})
    otp_data[email.lower()] = {
        "code": otp,
        "expires": (_now() + timedelta(minutes=5)).isoformat()
    }
    _save_json(OTP_FILE, otp_data)
    
    # Try Resend first
    resend_key = os.getenv("RESEND_API_KEY")
    if resend_key:
        try:
            import resend
            resend.api_key = resend_key
            resend.Emails.send({
                "from": "onboarding@resend.dev",
                "to": email,
                "subject": "Kode OTP MaxPreps Scraper - 5 Menit",
                "html": f"""
                <div style="font-family: Arial, sans-serif; background: #f5f5f5; padding: 20px;">
                  <div style="max-width: 500px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h2 style="color: #1f2937; margin-bottom: 24px; text-align: center;">🔐 Verifikasi Email</h2>
                    <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px;">Halo,</p>
                    <p style="color: #6b7280; font-size: 14px; margin-bottom: 30px;">Kode OTP Anda untuk MaxPreps Scraper:</p>
                    <div style="background: #f3f4f6; border-left: 4px solid #3b82f6; padding: 20px; margin-bottom: 30px; text-align: center;">
                      <span style="font-size: 32px; font-weight: bold; color: #1f2937; letter-spacing: 4px;">{otp}</span>
                    </div>
                    <p style="color: #ef4444; font-size: 12px; margin-bottom: 20px; text-align: center;">⏱️ Kode berlaku selama 5 menit</p>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 20px 0;">
                    <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                      Jangan bagikan kode ini kepada siapapun.<br/>
                      MaxPreps Scraper Team
                    </p>
                  </div>
                </div>
                """
            })
            return True, f"OTP dikirim ke {email}"
        except Exception as e:
            print(f"[RESEND ERROR] {e}")
    
    # Try Gmail SMTP
    gmail_email = os.getenv("GMAIL_EMAIL")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    
    if gmail_email and gmail_pass:
        try:
            msg = MIMEMultipart()
            msg["From"] = gmail_email
            msg["To"] = email
            msg["Subject"] = "Kode OTP MaxPreps Scraper"
            body = f"Kode OTP Anda: {otp}\n\nKode berlaku selama 5 menit."
            msg.attach(MIMEText(body, "plain"))
            
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_email, gmail_pass)
                server.send_message(msg)
            return True, f"OTP dikirim ke {email}"
        except Exception as e:
            print(f"[GMAIL ERROR] {e}")
    
    # Console fallback
    print(f"[OTP] Email: {email} → Code: {otp}")
    return True, f"OTP dikirim ke {email} (dev mode)"


def verify_otp(email: str, otp: str) -> Tuple[bool, str]:
    """Verify OTP, return True if valid."""
    email = email.lower()
    otp_data = _load_json(OTP_FILE, {})
    if email not in otp_data:
        return False, "OTP tidak ditemukan"
    
    stored = otp_data[email]
    try:
        if _now() > datetime.fromisoformat(stored.get("expires", "")):
            return False, "OTP kadaluarsa (5 menit)"
    except Exception:
        return False, "OTP kadaluarsa"
    
    if stored.get("code") != otp:
        return False, "OTP salah"
    
    otp_data.pop(email, None)
    _save_json(OTP_FILE, otp_data)
    return True, "OTP valid"


def add_user(email: str, password: str, role: str = "user", display_name: str = "") -> Tuple[bool, str]:
    email = (email or "").strip().lower()
    if not email or not password:
        return False, "Email dan password wajib diisi."
    if "@" not in email:
        return False, "Email tidak valid."
    if len(password) < 4:
        return False, "Password minimal 4 karakter."
    if role not in ("admin", "user"):
        role = "user"
    ensure_users_file()
    salt = secrets.token_hex(8)
    row = {
        "email": email,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "role": role,
        "created_at": _now_iso(),
        "active": True,
        "display_name": display_name or email,
        "last_login": "",
    }

    if use_supabase() and _sb():
        try:
            exists = _sb().table("app_users").select("email").eq("email", email).execute()
            if exists.data:
                return False, f"Email '{email}' sudah terdaftar."
            _sb().table("app_users").insert(row).execute()
            return True, f"Akun '{email}' berhasil dibuat."
        except Exception as e:
            return False, f"DB error: {e}"

    data = ensure_users_file()
    if email in data.get("users", {}):
        return False, f"Email '{email}' sudah terdaftar."
    data["users"][email] = row
    _save_json(USERS_FILE, data)
    return True, f"Akun '{email}' berhasil dibuat."


def register_user_with_token(username: str, password: str, token_str: str = "", display_name: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Register user baru (tanpa token di form, token masuk lewat dashboard nanti)."""
    ok, msg = add_user(username, password, role="user", display_name=display_name or username)
    if not ok:
        return False, msg, None
    
    # Login user baru
    account = verify_login(username, password)
    if account:
        log_access(username, "register", "")
        return True, f"{msg}", account
    
    return False, "Register gagal.", None


def set_user_active(username: str, active: bool) -> Tuple[bool, str]:
    if username == DEFAULT_ADMIN_USER and not active:
        return False, "Admin default tidak bisa dinonaktifkan."
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_users").update({"active": bool(active)}).eq("username", username).execute()
            if not r.data:
                return False, "User tidak ditemukan."
            return True, f"User '{username}' {'diaktifkan' if active else 'dinonaktifkan'}."
        except Exception as e:
            return False, str(e)

    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    users[username]["active"] = bool(active)
    _save_json(USERS_FILE, data)
    return True, f"User '{username}' {'diaktifkan' if active else 'dinonaktifkan'}."


def delete_user(username: str) -> Tuple[bool, str]:
    if username == DEFAULT_ADMIN_USER:
        return False, "Admin default tidak bisa dihapus."
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_users").select("role").eq("username", username).execute()
            if not r.data:
                return False, "User tidak ditemukan."
            if r.data[0].get("role") == "admin":
                admins = _sb().table("app_users").select("username").eq("role", "admin").execute()
                if len(admins.data or []) <= 1:
                    return False, "Tidak bisa hapus admin terakhir."
            _sb().table("app_users").delete().eq("username", username).execute()
            return True, f"User '{username}' dihapus."
        except Exception as e:
            return False, str(e)

    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
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
    salt = secrets.token_hex(8)
    ph = _hash_password(new_password, salt)
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_users").update(
                {"salt": salt, "password_hash": ph}
            ).eq("username", username).execute()
            if not r.data:
                return False, "User tidak ditemukan."
            return True, "Password diubah."
        except Exception as e:
            return False, str(e)

    data = ensure_users_file()
    users = data.get("users", {})
    if username not in users:
        return False, "User tidak ditemukan."
    users[username]["salt"] = salt
    users[username]["password_hash"] = ph
    _save_json(USERS_FILE, data)
    return True, "Password diubah."


# -------------------- tokens --------------------

def ensure_tokens_file() -> Dict[str, Any]:
    if use_supabase() and _sb():
        return {"tokens": {}}
    data = _load_json(TOKENS_FILE, None)
    if not isinstance(data, dict) or "tokens" not in data:
        data = {"tokens": {}}
        _save_json(TOKENS_FILE, data)
    return data


def _gen_token_string(length: int = 24) -> str:
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    return "MP-" + "".join(secrets.choice(alphabet) for _ in range(length))


def create_token(
    mode: str,
    *,
    credits: int = 0,
    valid_days: float = 0,
    label: str = "",
    created_by: str = "admin",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    mode = (mode or "").strip().lower()
    if mode not in ("credit", "time"):
        return False, "Mode harus 'credit' atau 'time'.", None

    label = (label or "").strip() or f"token-{mode}"

    if mode == "credit":
        try:
            credits = int(credits)
        except (TypeError, ValueError):
            return False, "Credits tidak valid.", None
        if credits <= 0:
            return False, "Credits harus > 0.", None
        expires_at = ""
        expires_ts = 0.0
        credits_val = credits
        credits_initial = credits
        valid_days = 0
    else:
        try:
            valid_days = float(valid_days)
        except (TypeError, ValueError):
            return False, "Durasi (hari) tidak valid.", None
        if valid_days <= 0:
            return False, "Durasi harus > 0 hari.", None
        expires = _now() + timedelta(days=valid_days)
        expires_at = expires.strftime("%Y-%m-%d %H:%M:%S UTC")
        expires_ts = expires.timestamp()
        credits_val = 0
        credits_initial = 0

    token = _gen_token_string()
    info = {
        "token": token,
        "mode": mode,
        "credits": credits_val,
        "credits_initial": credits_initial,
        "label": label,
        "created_by": created_by,
        "created_at": _now_iso(),
        "expires_at": expires_at,
        "expires_ts": expires_ts,
        "valid_days": float(valid_days) if mode == "time" else 0,
        "active": True,
        "last_used": "",
        "use_count": 0,
    }

    if use_supabase() and _sb():
        try:
            # pastikan unik
            for _ in range(5):
                exists = _sb().table("app_tokens").select("token").eq("token", token).execute()
                if not exists.data:
                    break
                token = _gen_token_string()
                info["token"] = token
            _sb().table("app_tokens").insert(info).execute()
            return True, f"Token mode {mode} dibuat.", info
        except Exception as e:
            return False, f"DB error: {e}", None

    data = ensure_tokens_file()
    while token in data["tokens"]:
        token = _gen_token_string()
        info["token"] = token
    data["tokens"][token] = info
    _save_json(TOKENS_FILE, data)
    return True, f"Token mode {mode} dibuat.", info


def list_tokens() -> List[Dict[str, Any]]:
    now_ts = _now().timestamp()
    rows: List[Dict[str, Any]] = []

    if use_supabase() and _sb():
        try:
            r = _sb().table("app_tokens").select("*").order("created_at", desc=True).execute()
            rows = r.data or []
        except Exception:
            rows = []
    else:
        data = ensure_tokens_file()
        for tok, info in data.get("tokens", {}).items():
            rows.append({**info, "token": tok})

    out = []
    for info in rows:
        tok = info.get("token", "")
        mode = info.get("mode") or "credit"
        exp_ts = float(info.get("expires_ts") or 0)
        expired = mode == "time" and exp_ts > 0 and now_ts > exp_ts
        depleted = mode == "credit" and int(info.get("credits") or 0) <= 0
        if not info.get("active", True):
            status = "nonaktif"
        elif expired:
            status = "kadaluarsa"
        elif depleted:
            status = "credit habis"
        else:
            status = "aktif"
        out.append({**info, "token": tok, "mode": mode, "expired": expired, "status": status})
    return out


def get_token(token: str) -> Optional[Dict[str, Any]]:
    token = (token or "").strip()
    if not token:
        return None
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_tokens").select("*").eq("token", token).limit(1).execute()
            if not r.data:
                return None
            info = r.data[0]
            return {**info, "token": token, "mode": info.get("mode") or "credit"}
        except Exception:
            return None
    data = ensure_tokens_file()
    info = data.get("tokens", {}).get(token)
    if not info:
        return None
    return {**info, "token": token, "mode": info.get("mode") or "credit"}


def _token_session_dict(token: str, info: Dict[str, Any]) -> Dict[str, Any]:
    mode = info.get("mode") or "credit"
    return {
        "auth_type": "token",
        "token": token,
        "token_mode": mode,
        "credits": int(info.get("credits", 0)) if mode == "credit" else None,
        "expires_at": info.get("expires_at", "") if mode == "time" else "",
    }


def invalidate_and_delete_token(token: str, reason: str = "") -> None:
    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").delete().eq("token", token).execute()
        except Exception:
            pass
    else:
        data = ensure_tokens_file()
        if token in data.get("tokens", {}):
            del data["tokens"][token]
            _save_json(TOKENS_FILE, data)
    try:
        log_access(f"token:{token[:10]}…", "token_deleted", reason or "exhausted")
    except Exception:
        pass


def token_status(token: str) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    info = get_token(token)
    if not info:
        return "missing", "Token tidak ditemukan atau sudah dihapus.", None
    if not info.get("active", True):
        invalidate_and_delete_token(token, "inactive")
        return "inactive", "Token nonaktif dan telah dihapus.", None
    mode = info.get("mode") or "credit"
    if mode == "time":
        exp_ts = float(info.get("expires_ts") or 0)
        if exp_ts and _now().timestamp() > exp_ts:
            invalidate_and_delete_token(token, "expired")
            return "expired", "Token sudah kadaluarsa dan telah dihapus. Silakan beli/minta token baru.", None
    else:
        if int(info.get("credits", 0)) <= 0:
            invalidate_and_delete_token(token, "no_credit")
            return "no_credit", "Credit token habis dan token telah dihapus. Silakan beli/minta token baru.", None
    return "ok", "OK", _token_session_dict(token, info)


def refresh_token_session(token: str) -> Optional[Dict[str, Any]]:
    status, _msg, session = token_status(token)
    return session if status == "ok" else None


def verify_token_login(token: str) -> Tuple[Optional[Dict[str, Any]], str]:
    token = (token or "").strip()
    if not token:
        return None, "Token kosong."
    status, msg, session = token_status(token)
    if status != "ok" or not session:
        return None, msg
    # update last_used
    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").update({"last_used": _now_iso()}).eq("token", token).execute()
        except Exception:
            pass
    else:
        data = ensure_tokens_file()
        if token in data.get("tokens", {}):
            data["tokens"][token]["last_used"] = _now_iso()
            _save_json(TOKENS_FILE, data)
    return session, ""


def set_token_active(token: str, active: bool) -> Tuple[bool, str]:
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_tokens").update({"active": bool(active)}).eq("token", token).execute()
            if not r.data:
                return False, "Token tidak ditemukan."
            return True, "Token diubah."
        except Exception as e:
            return False, str(e)
    data = ensure_tokens_file()
    if token not in data.get("tokens", {}):
        return False, "Token tidak ditemukan."
    data["tokens"][token]["active"] = bool(active)
    _save_json(TOKENS_FILE, data)
    return True, "Token diubah."


def delete_token(token: str) -> Tuple[bool, str]:
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_tokens").delete().eq("token", token).execute()
            return True, "Token dihapus."
        except Exception as e:
            return False, str(e)
    data = ensure_tokens_file()
    if token not in data.get("tokens", {}):
        return False, "Token tidak ditemukan."
    del data["tokens"][token]
    _save_json(TOKENS_FILE, data)
    return True, "Token dihapus."


def add_token_credits(token: str, amount: int) -> Tuple[bool, str]:
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, "Jumlah tidak valid."
    info = get_token(token)
    if not info:
        return False, "Token tidak ditemukan."
    if (info.get("mode") or "credit") != "credit":
        return False, "Token ini mode waktu — tidak pakai credit."
    new_c = max(0, int(info.get("credits", 0)) + amount)
    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").update({"credits": new_c}).eq("token", token).execute()
            return True, f"Credit sekarang: {new_c}"
        except Exception as e:
            return False, str(e)
    data = ensure_tokens_file()
    data["tokens"][token]["credits"] = new_c
    _save_json(TOKENS_FILE, data)
    return True, f"Credit sekarang: {new_c}"


def scrape_credit_cost(*, is_all: bool, top25_on: bool) -> int:
    base = COST_ALL_STATES if is_all else COST_PER_STATE
    return base + (COST_TOP25 if top25_on else 0)


def deduct_token_credits(token: str, cost: int) -> Tuple[bool, str, int]:
    info = get_token(token)
    if not info:
        return False, "Token tidak ditemukan.", 0
    if not info.get("active", True):
        return False, "Token nonaktif.", 0
    if (info.get("mode") or "credit") != "credit":
        return False, "Token mode waktu — tidak memotong credit.", 0
    credits = int(info.get("credits", 0))
    if credits < cost:
        return False, f"Credit kurang (punya {credits}, butuh {cost}).", credits
    credits -= cost
    use_count = int(info.get("use_count", 0)) + 1
    last_used = _now_iso()

    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").update({
                "credits": credits,
                "use_count": use_count,
                "last_used": last_used,
            }).eq("token", token).execute()
        except Exception as e:
            return False, f"DB error: {e}", credits + cost
    else:
        data = ensure_tokens_file()
        data["tokens"][token]["credits"] = credits
        data["tokens"][token]["use_count"] = use_count
        data["tokens"][token]["last_used"] = last_used
        _save_json(TOKENS_FILE, data)

    if credits <= 0:
        invalidate_and_delete_token(token, "credit_reached_zero")
        return True, f"Dipotong {cost} credit. Credit habis — token dihapus. Minta token baru.", 0
    return True, f"Dipotong {cost} credit. Sisa {credits}.", credits


def check_token_can_scrape(token: str, cost: int) -> Tuple[bool, str]:
    status, msg, _ = token_status(token)
    if status != "ok":
        return False, msg
    info = get_token(token)
    if not info:
        return False, "Token tidak ditemukan atau sudah dihapus."
    if (info.get("mode") or "credit") == "time":
        return True, "OK (mode waktu)"
    credits = int(info.get("credits", 0))
    if credits < cost:
        return False, f"Credit kurang (punya {credits}, butuh {cost})."
    return True, "OK (mode credit)"


def set_token_owner(token: str, username: str) -> Tuple[bool, str]:
    """Mark token sebagai milik user tertentu. 1 token = 1 user."""
    info = get_token(token)
    if not info:
        return False, "Token tidak ditemukan."
    
    owner = info.get("token_owner", "")
    if owner and owner != username:
        return False, "Token sudah digunakan akun lain. Token tidak valid."
    
    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").update({"token_owner": username}).eq("token", token).execute()
            return True, f"Token ditetapkan ke {username}"
        except Exception as e:
            return False, f"DB error: {e}"
    
    data = ensure_tokens_file()
    if token in data.get("tokens", {}):
        data["tokens"][token]["token_owner"] = username
        _save_json(TOKENS_FILE, data)
        return True, f"Token ditetapkan ke {username}"
    
    return False, "Token tidak ditemukan."


def mark_token_used(token: str) -> None:
    info = get_token(token)
    if not info:
        return
    use_count = int(info.get("use_count", 0)) + 1
    last_used = _now_iso()
    if use_supabase() and _sb():
        try:
            _sb().table("app_tokens").update({
                "use_count": use_count,
                "last_used": last_used,
            }).eq("token", token).execute()
        except Exception:
            pass
        return
    data = ensure_tokens_file()
    if token in data.get("tokens", {}):
        data["tokens"][token]["use_count"] = use_count
        data["tokens"][token]["last_used"] = last_used
        _save_json(TOKENS_FILE, data)


# -------------------- settings --------------------

def get_settings() -> Dict[str, Any]:
    if use_supabase() and _sb():
        try:
            r = _sb().table("app_settings").select("value").eq("key", "buy_token").limit(1).execute()
            if r.data and isinstance(r.data[0].get("value"), dict):
                out = dict(_DEFAULT_SETTINGS)
                out.update(r.data[0]["value"])
                return out
        except Exception:
            pass
    data = _load_json(SETTINGS_FILE, None)
    out = dict(_DEFAULT_SETTINGS)
    if isinstance(data, dict):
        out.update(data)
    return out


def save_settings(**kwargs) -> Tuple[bool, str]:
    data = get_settings()
    for k, v in kwargs.items():
        if k in _DEFAULT_SETTINGS:
            data[k] = v
    if use_supabase() and _sb():
        try:
            existing = _sb().table("app_settings").select("key").eq("key", "buy_token").execute()
            if existing.data:
                _sb().table("app_settings").update({"value": data}).eq("key", "buy_token").execute()
            else:
                _sb().table("app_settings").insert({"key": "buy_token", "value": data}).execute()
            return True, "Pengaturan disimpan."
        except Exception as e:
            return False, str(e)
    _save_json(SETTINGS_FILE, data)
    return True, "Pengaturan disimpan."


def buy_token_link(mode: str = "buy") -> str:
    s = get_settings()
    if mode == "subscribe":
        url = (s.get("subscribe_url") or "").strip()
        msg = (s.get("subscribe_message") or "").strip()
    else:
        url = (s.get("buy_token_url") or "").strip()
        msg = (s.get("buy_token_message") or "").strip()
    if "wa.me" in url and msg and "text=" not in url:
        from urllib.parse import quote
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}text={quote(msg)}"
    return url


# -------------------- logs --------------------

def log_access(username: str, action: str, detail: str = "", ip: str = "") -> None:
    row = {
        "time": _now_iso(),
        "username": username,
        "action": action,
        "detail": detail,
        "ip": ip,
    }
    if use_supabase() and _sb():
        try:
            _sb().table("access_logs").insert(row).execute()
        except Exception:
            pass
        return
    logs = _load_json(LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    logs.append(row)
    logs = logs[-500:]
    _save_json(LOG_FILE, logs)


def get_access_logs(limit: int = 100) -> List[Dict[str, Any]]:
    if use_supabase() and _sb():
        try:
            r = (
                _sb()
                .table("access_logs")
                .select("*")
                .order("id", desc=True)
                .limit(limit)
                .execute()
            )
            return r.data or []
        except Exception:
            return []
    logs = _load_json(LOG_FILE, [])
    if not isinstance(logs, list):
        return []
    return list(reversed(logs[-limit:]))
