#!/usr/bin/env python3
"""Middleware autentikasi terpusat.

Streamlit:
  from auth_middleware import require_streamlit_auth, current_user, is_admin

FastAPI:
  from auth_middleware import require_api_admin, require_api_token_or_admin
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

# ---- Streamlit session helpers ----

SESSION_USER_KEY = "auth_user"
SESSION_TOKEN_DEAD = "token_dead_msg"
SESSION_TOKEN_DEAD_AFTER = "token_dead_after_msg"


def current_user() -> Optional[Dict[str, Any]]:
    """User yang sedang login (session Streamlit), atau None."""
    try:
        import streamlit as st
        return st.session_state.get(SESSION_USER_KEY)
    except Exception:
        return None


def is_admin(user: Optional[Dict[str, Any]] = None) -> bool:
    u = user if user is not None else current_user()
    return bool(u and u.get("role") == "admin")


def is_token_user(user: Optional[Dict[str, Any]] = None) -> bool:
    u = user if user is not None else current_user()
    return bool(u and u.get("auth_type") == "token")


def logout_streamlit() -> None:
    import streamlit as st
    from auth import log_access
    u = st.session_state.get(SESSION_USER_KEY)
    if u:
        log_access(u.get("username") or "?", "logout")
    st.session_state[SESSION_USER_KEY] = None
    st.session_state[SESSION_TOKEN_DEAD] = ""
    st.session_state[SESSION_TOKEN_DEAD_AFTER] = ""


def require_streamlit_auth() -> Dict[str, Any]:
    """Middleware Streamlit: wajib login.

    - Refresh/validasi token setiap rerun
    - Token habis → layar pemberitahuan (bukan logout diam-diam)
    - Return dict user jika OK; st.stop() jika belum login
    """
    import streamlit as st
    from auth import (
        token_status,
        get_settings,
        buy_token_link,
        verify_login,
        verify_token_login,
        log_access,
        ensure_users_file,
        ensure_tokens_file,
    )

    ensure_users_file()
    ensure_tokens_file()

    # Init keys
    for k, v in {
        SESSION_USER_KEY: None,
        SESSION_TOKEN_DEAD: "",
        SESSION_TOKEN_DEAD_AFTER: "",
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Layar token mati (setelah logout dari session)
    if st.session_state.get(SESSION_TOKEN_DEAD) and not st.session_state.get(SESSION_USER_KEY):
        _render_token_dead(st.session_state[SESSION_TOKEN_DEAD])
        st.stop()

    user = st.session_state.get(SESSION_USER_KEY)
    if user:
        # Validasi token setiap request
        if user.get("auth_type") == "token" and user.get("token"):
            status, msg, refreshed = token_status(user["token"])
            if status != "ok":
                st.session_state[SESSION_USER_KEY] = None
                st.session_state[SESSION_TOKEN_DEAD] = msg
                _render_token_dead(msg)
                st.stop()
            st.session_state[SESSION_USER_KEY] = refreshed
            return refreshed
        return user

    # Belum login → form
    _render_login_form()
    st.stop()
    return {}  # unreachable


def _render_token_dead(message: str) -> None:
    import streamlit as st
    from auth import get_settings, buy_token_link

    st.session_state[SESSION_TOKEN_DEAD] = message
    st.title("⚠️ Token tidak berlaku")
    st.error(message)
    st.info(
        "Token yang habis/kadaluarsa **sudah dihapus otomatis** dan tidak bisa dipakai lagi. "
        "Silakan beli token baru atau hubungi admin."
    )
    settings = get_settings()
    link = buy_token_link()
    if settings.get("buy_token_enabled") and link:
        st.link_button(
            f"🛒 {settings.get('buy_token_text') or 'Beli token'}",
            link,
            type="primary",
            use_container_width=True,
        )
    if st.button("Mengerti — kembali ke login", use_container_width=True):
        st.session_state[SESSION_USER_KEY] = None
        st.session_state[SESSION_TOKEN_DEAD] = ""
        st.rerun()


def _render_login_form() -> None:
    import streamlit as st
    from auth import verify_login, verify_token_login, log_access, get_settings, buy_token_link

    st.title("🔐 Login")
    st.caption("MaxPreps Scraper — akses terbatas")

    tab_pw, tab_token = st.tabs(["Username / Password", "Token"])

    with tab_pw:
        with st.form("login_form_mw"):
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Masuk", type="primary", use_container_width=True)
        if ok:
            account = verify_login(user, pw)
            if account:
                st.session_state[SESSION_USER_KEY] = account
                log_access(account["username"], "login", "password")
                st.rerun()
            else:
                log_access(user or "?", "login_failed", "invalid credentials")
                st.error("Username atau password salah, atau akun nonaktif.")

    with tab_token:
        with st.form("token_form_mw"):
            tok = st.text_input("Token akses", placeholder="MP-XXXXXXXX...")
            ok_t = st.form_submit_button("Masuk dengan token", type="primary", use_container_width=True)
        if ok_t:
            account, err = verify_token_login(tok)
            if account:
                st.session_state[SESSION_USER_KEY] = account
                log_access(account["username"], "login", f"token credits={account.get('credits')}")
                st.rerun()
            else:
                log_access("token", "login_failed", err)
                st.error(err or "Token tidak valid.")

    st.divider()
    settings = get_settings()
    link = buy_token_link()
    if settings.get("buy_token_enabled") and link:
        st.markdown("**Belum punya token?**")
        st.link_button(
            f"🛒 {settings.get('buy_token_text') or 'Beli token'}",
            link,
            use_container_width=True,
        )
        st.caption("Hubungi admin untuk membeli token credit atau token waktu.")


def require_admin_streamlit(user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Middleware: wajib role admin."""
    import streamlit as st
    u = user or current_user()
    if not is_admin(u):
        st.error("Akses ditolak — hanya admin.")
        st.stop()
    return u  # type: ignore


# ---- FastAPI dependencies ----

def _api_admin_key() -> str:
    return os.environ.get("ADMIN_API_KEY", "ganti-api-key-ini")


def require_api_admin(authorization: Optional[str] = None) -> None:
    """FastAPI dependency-style: Bearer ADMIN_API_KEY."""
    from fastapi import HTTPException, Header
    # dipanggil manual atau via Depends wrapper di api.py
    if authorization is None:
        raise HTTPException(401, "Butuh Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Format: Authorization: Bearer <key>")
    if authorization[7:].strip() != _api_admin_key():
        raise HTTPException(403, "API key salah")


def verify_bearer_token(authorization: Optional[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Validasi Bearer bisa API key admin ATAU token MP- user."""
    if not authorization or not authorization.startswith("Bearer "):
        return None, "Butuh Authorization: Bearer ..."
    raw = authorization[7:].strip()
    if raw == _api_admin_key():
        return {"role": "admin", "auth_type": "api_key", "username": "api"}, ""
    from auth import token_status
    status, msg, session = token_status(raw)
    if status != "ok" or not session:
        return None, msg
    return session, ""
