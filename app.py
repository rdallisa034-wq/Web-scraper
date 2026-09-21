#!/usr/bin/env python3
"""MaxPreps Scraper — Streamlit + Login & Admin."""

from __future__ import annotations

import os
import re

import streamlit as st

from auth import (
    ensure_users_file,
    ensure_tokens_file,
    verify_login,
    verify_token_login,
    refresh_token_session,
    token_status,
    list_users,
    add_user,
    set_user_active,
    delete_user,
    change_password,
    log_access,
    get_access_logs,
    create_token,
    list_tokens,
    set_token_active,
    delete_token,
    add_token_credits,
    scrape_credit_cost,
    deduct_token_credits,
    check_token_can_scrape,
    mark_token_used,
    COST_PER_STATE,
    COST_ALL_STATES,
    COST_TOP25,
    get_settings,
    save_settings,
    buy_token_link,
    backend_name,
)
from maxpreps_scraper import (
    STATES,
    SPORTS,
    WATCH_LIVE_DEFAULT,
    TEMP_DIR,
    load_watch_map,
    save_watch_link,
    resolve_watch_url,
    list_dates,
    list_dates_with_fallback,
    scrape_state,
    scrape_states_parallel,
    scrape_top25,
    fetch_top25,
    top25_in_state,
    top25_status_message,
    filter_blocks_top25,
    dedupe_blocks,
    temp_output_path,
    write_blocks,
    to_mdy,
    format_tanggal,
    DEFAULT_STATE_WORKERS,
    DEFAULT_GAME_WORKERS,
)

st.set_page_config(page_title="MaxPreps Scraper", page_icon="🏈", layout="centered")

# Pastikan file users ada
ensure_users_file()
ensure_tokens_file()

# ---- session defaults ----
for k, v in {
    "auth_user": None,  # dict {username, role, display_name}
    "dates": [],
    "date_msg": "",
    "preview": "",
    "outfile": "",
    "file_bytes": None,
    "file_name": "",
    "msg": "",
    "err": "",
    "top25": [],
    "editor_path": "",
    "editor_text": "",
    "edit_msg": "",
    "token_dead_msg": "",
    "token_dead_after_msg": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _sports():
    return {label: key for key, (label, _) in SPORTS.items()}


def _states():
    o = {"Semua state": "all"}
    o.update({f"{n} ({c.upper()})": c for c, n in STATES.items()})
    return o


def _show_token_dead_screen(message: str) -> None:
    """Pemberitahuan token habis — user konfirmasi dulu baru logout."""
    st.session_state.token_dead_msg = message
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
        st.session_state.auth_user = None
        st.session_state.token_dead_msg = ""
        st.rerun()
    st.stop()


def _require_login() -> bool:
    """Tampilkan form login (password atau token). Return True jika sudah login."""
    # Masih di layar pemberitahuan token habis
    if st.session_state.get("token_dead_msg") and not st.session_state.auth_user:
        _show_token_dead_screen(st.session_state.token_dead_msg)

    if st.session_state.auth_user:
        u = st.session_state.auth_user
        if u.get("auth_type") == "token" and u.get("token"):
            status, msg, refreshed = token_status(u["token"])
            if status != "ok":
                # Jangan logout diam-diam — tampilkan popup/layar dulu
                st.session_state.auth_user = None
                _show_token_dead_screen(msg)
            else:
                st.session_state.auth_user = refreshed
        return True

    st.title("🔐 Login")
    st.caption("MaxPreps Scraper — akses terbatas")

    tab_pw, tab_token = st.tabs(["Username / Password", "Token"])

    with tab_pw:
        with st.form("login_form"):
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            ok = st.form_submit_button("Masuk", type="primary", use_container_width=True)
        if ok:
            account = verify_login(user, pw)
            if account:
                st.session_state.auth_user = account
                log_access(account["username"], "login", "password")
                st.rerun()
            else:
                log_access(user or "?", "login_failed", "invalid credentials")
                st.error("Username atau password salah, atau akun nonaktif.")

    with tab_token:
        with st.form("token_form"):
            tok = st.text_input("Token akses", placeholder="MP-XXXXXXXX...")
            ok_t = st.form_submit_button("Masuk dengan token", type="primary", use_container_width=True)
        if ok_t:
            account, err = verify_token_login(tok)
            if account:
                st.session_state.auth_user = account
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

    return False


# ===================== LOGIN GATE =====================
if not _require_login():
    st.stop()

user = st.session_state.auth_user
is_admin = user.get("role") == "admin"

# ---- sidebar ----
with st.sidebar:
    st.title("🏈 MaxPreps")
    st.markdown(f"**{user.get('display_name') or user['username']}**")
    if user.get("auth_type") == "token":
        mode = user.get("token_mode") or "credit"
        if mode == "credit":
            st.caption(f"Token credit · 💳 {user.get('credits', 0)}")
        else:
            st.caption(f"Token waktu · valid s/d {user.get('expires_at') or '-'}")
    else:
        st.caption(f"@{user['username']} · {user['role']}")

    menu_opts = ["Scrape", "Edit file"]
    if is_admin:
        menu_opts.append("Admin")
    menu = st.radio("Menu", menu_opts, label_visibility="collapsed")

    if user.get("auth_type") == "token":
        _s = get_settings()
        _link = buy_token_link()
        if _s.get("buy_token_enabled") and _link:
            st.link_button(
                f"🛒 {_s.get('buy_token_text') or 'Beli token'}",
                _link,
                use_container_width=True,
            )

    if st.button("Logout", use_container_width=True):
        log_access(user["username"], "logout")
        st.session_state.auth_user = None
        st.rerun()

    st.caption(f"Storage: {backend_name()} · by Ridwan")


# ===================== ADMIN =====================
if menu == "Admin":
    if not is_admin:
        st.error("Akses ditolak.")
        st.stop()

    st.header("⚙️ Admin")
    tab_users, tab_tokens, tab_logs, tab_pw, tab_set = st.tabs(
        ["Kelola user", "Token & credit", "Log akses", "Ganti password", "Beli token"]
    )

    with tab_users:
        st.subheader("Daftar user")
        users = list_users()
        for u in users:
            status = "✅ aktif" if u["active"] else "⛔ nonaktif"
            st.markdown(
                f"**{u['username']}** · {u['role']} · {status}  \n"
                f"<small>dibuat {u['created_at'] or '-'} · login terakhir {u['last_login'] or '-'}</small>",
                unsafe_allow_html=True,
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if u["active"]:
                    if st.button("Nonaktifkan", key=f"off_{u['username']}", use_container_width=True):
                        ok, msg = set_user_active(u["username"], False)
                        log_access(user["username"], "deactivate_user", u["username"])
                        st.toast(msg)
                        st.rerun()
                else:
                    if st.button("Aktifkan", key=f"on_{u['username']}", use_container_width=True):
                        ok, msg = set_user_active(u["username"], True)
                        log_access(user["username"], "activate_user", u["username"])
                        st.toast(msg)
                        st.rerun()
            with c2:
                if st.button("Hapus", key=f"del_{u['username']}", use_container_width=True):
                    ok, msg = delete_user(u["username"])
                    if ok:
                        log_access(user["username"], "delete_user", u["username"])
                    st.toast(msg)
                    st.rerun()
            with c3:
                pass
            st.divider()

        st.subheader("Tambah user")
        with st.form("add_user_form"):
            nu = st.text_input("Username baru")
            npw = st.text_input("Password", type="password")
            ndn = st.text_input("Nama tampilan (opsional)")
            nrole = st.selectbox("Role", ["user", "admin"])
            submitted = st.form_submit_button("Tambah", type="primary")
        if submitted:
            ok, msg = add_user(nu, npw, role=nrole, display_name=ndn)
            if ok:
                log_access(user["username"], "add_user", nu)
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with tab_tokens:
        st.subheader("Buat token")
        st.markdown(
            f"""
**Mode token (pilih salah satu):**
- **Credit** — hanya credit, tanpa batas waktu
- **Waktu** — hanya masa berlaku (hari), tanpa credit

**Biaya credit (dijumlahkan):**
- 1 state = **{COST_PER_STATE}**
- Semua state = **{COST_ALL_STATES}**
- + Top 25 / ranking = **+{COST_TOP25}**
- Contoh: all + Top 25 = **{COST_ALL_STATES + COST_TOP25}** · 1 state + Top 25 = **{COST_PER_STATE + COST_TOP25}**
"""
        )
        with st.form("create_token_form"):
            t_mode = st.radio(
                "Jenis token",
                ["credit", "time"],
                format_func=lambda m: "💳 Credit saja" if m == "credit" else "⏱️ Waktu saja (hari)",
                horizontal=True,
            )
            t_label = st.text_input("Label (opsional)", placeholder="client-A")
            t_credits = st.number_input("Credit (mode credit)", min_value=1, value=20, step=1)
            t_days = st.number_input(
                "Berlaku berapa hari (mode waktu)",
                min_value=0.5, value=7.0, step=1.0,
                help="Hanya dipakai jika jenis = Waktu",
            )
            t_go = st.form_submit_button("Generate token", type="primary")
        if t_go:
            if t_mode == "credit":
                ok, msg, info = create_token(
                    "credit", credits=int(t_credits), label=t_label, created_by=user["username"]
                )
            else:
                ok, msg, info = create_token(
                    "time", valid_days=float(t_days), label=t_label, created_by=user["username"]
                )
            if ok and info:
                log_access(user["username"], "create_token", f"{info['mode']}:{info['token']}")
                st.success(msg)
                st.code(info["token"], language=None)
                if info["mode"] == "credit":
                    st.caption(f"Mode credit · 💳 {info['credits']} (tanpa kadaluarsa waktu)")
                else:
                    st.caption(f"Mode waktu · valid s/d {info['expires_at']} (tanpa credit)")
            else:
                st.error(msg)

        st.divider()
        st.subheader("Daftar token")
        tokens = list_tokens()
        if not tokens:
            st.info("Belum ada token.")
        for t in tokens:
            mode = t.get("mode") or "credit"
            if mode == "credit":
                detail = f"💳 {t.get('credits',0)} / {t.get('credits_initial',0)} credit"
            else:
                detail = f"⏱️ s/d {t.get('expires_at','-')}"
            st.markdown(
                f"**{t.get('label','token')}** · `{t['token']}`  \n"
                f"Mode: **{mode}** · Status: **{t['status']}** · {detail} · pakai {t.get('use_count',0)}x  \n"
                f"<small>dibuat {t.get('created_at','')}</small>",
                unsafe_allow_html=True,
            )
            a1, a2, a3, a4 = st.columns(4)
            with a1:
                if t.get("active") and t["status"] not in ("kadaluarsa",):
                    if st.button("Nonaktif", key=f"toff_{t['token']}", use_container_width=True):
                        set_token_active(t["token"], False)
                        st.rerun()
                else:
                    if st.button("Aktifkan", key=f"ton_{t['token']}", use_container_width=True):
                        set_token_active(t["token"], True)
                        st.rerun()
            with a2:
                if st.button("Hapus", key=f"tdel_{t['token']}", use_container_width=True):
                    delete_token(t["token"])
                    log_access(user["username"], "delete_token", t["token"])
                    st.rerun()
            with a3:
                if mode == "credit":
                    add_c = st.number_input(
                        "Tambah credit", min_value=1, value=10, step=1, key=f"taddn_{t['token']}"
                    )
                else:
                    st.caption("Mode waktu")
                    add_c = 0
            with a4:
                if mode == "credit" and st.button("+ Credit", key=f"tadd_{t['token']}", use_container_width=True):
                    ok, msg = add_token_credits(t["token"], int(add_c))
                    st.toast(msg)
                    st.rerun()
            st.divider()

    with tab_logs:
        st.subheader("Riwayat akses")
        logs = get_access_logs(150)
        if not logs:
            st.info("Belum ada log.")
        else:
            for row in logs:
                st.text(
                    f"{row.get('time','')}  |  {row.get('username','')}  |  "
                    f"{row.get('action','')}  {row.get('detail','')}"
                )

    with tab_pw:
        st.subheader("Ganti password akun ini")
        with st.form("pw_form"):
            p1 = st.text_input("Password baru", type="password")
            p2 = st.text_input("Ulangi password", type="password")
            go = st.form_submit_button("Simpan password")
        if go:
            if p1 != p2:
                st.error("Password tidak sama.")
            else:
                ok, msg = change_password(user["username"], p1)
                if ok:
                    log_access(user["username"], "change_password")
                    st.success(msg)
                else:
                    st.error(msg)

    with tab_set:
        st.subheader("Tombol Beli token")
        st.caption("Tampil di halaman login & saat token habis. Arahkan ke WhatsApp / halaman order.")
        s = get_settings()
        with st.form("buy_settings_form"):
            en = st.checkbox("Tampilkan tombol Beli token", value=bool(s.get("buy_token_enabled", True)))
            label = st.text_input("Teks tombol", value=s.get("buy_token_text") or "Beli token")
            url = st.text_input(
                "Link (WhatsApp / URL)",
                value=s.get("buy_token_url") or "https://wa.me/6281234567890",
                help="Contoh: https://wa.me/6281234567890",
            )
            msg = st.text_area(
                "Pesan default (untuk wa.me)",
                value=s.get("buy_token_message") or "Halo admin, saya ingin beli token MaxPreps Scraper.",
            )
            save = st.form_submit_button("Simpan", type="primary")
        if save:
            ok, m = save_settings(
                buy_token_enabled=en,
                buy_token_text=label,
                buy_token_url=url.strip(),
                buy_token_message=msg.strip(),
            )
            st.success(m)
            st.rerun()
        st.markdown("**Preview link:**")
        st.code(buy_token_link() or "(kosong)", language=None)

    st.stop()


# ===================== SCRAPE =====================
if menu == "Scrape":
    st.header("Scrape jadwal")

    st.subheader("1. Pilih sport & state")
    a, b = st.columns(2)
    sports = _sports()
    states = _states()
    with a:
        sport = sports[st.selectbox("Sport", list(sports.keys()))]
    with b:
        keys = list(states.keys())
        idx = next((i for i, k in enumerate(keys) if states[k] == "tx"), 0)
        state = states[st.selectbox("State", keys, index=idx)]

    watch_map = load_watch_map()
    watch = st.text_input(
        "Link watch live",
        value=watch_map.get(state) or watch_map.get("default") or WATCH_LIVE_DEFAULT,
        placeholder="https://...",
    )

    top25_on = st.checkbox(
        "Hanya tim ranking (Top 25)",
        value=False,
        help="State: ranking state MaxPreps. Semua state: ranking nasional.",
    )

    if top25_on:
        if st.button("Cek ranking Top 25"):
            with st.spinner("Ambil ranking…"):
                try:
                    code, url, teams = fetch_top25(
                        sport, state="" if state == "all" else state
                    )
                    st.session_state.top25 = teams or []
                    if code != 200:
                        st.error(f"Gagal ranking (HTTP {code})")
                    else:
                        st.session_state.msg = top25_status_message(teams, state)
                except Exception as e:
                    st.session_state.top25 = []
                    st.error(f"Error: {e}")

        if st.session_state.top25:
            info = top25_status_message(st.session_state.top25, state)
            subset = top25_in_state(st.session_state.top25, state)
            if state != "all" and not subset:
                st.warning(info)
            elif subset or state == "all":
                st.success(info)
            else:
                st.info(info)
            with st.expander("Daftar tim"):
                show = subset if state != "all" else st.session_state.top25
                st.code(
                    "\n".join(
                        f"#{t['rank']:>2}  {t['name']} ({t['state'].upper()})"
                        for t in show
                    )
                )

    with st.expander("Opsi tambahan"):
        add_title = st.checkbox("Tambah ?title= di link watch", value=True)
        mascots = st.checkbox(
            "Paksa ambil mascot untuk semua match (lebih lambat)", value=False
        )

    st.divider()
    st.subheader("2. Pilih tanggal")
    if st.button("Cek tanggal", use_container_width=True):
        st.session_state.err = ""
        st.session_state.date_msg = ""
        with st.spinner("Cek kalender…"):
            try:
                if state == "all":
                    code, url, dates, probe = list_dates_with_fallback(sport)
                    who = f"semua state (acuan {STATES.get(probe, probe)})"
                else:
                    code, url, dates = list_dates(state, sport)
                    who = STATES.get(state, state)
                st.session_state.dates = dates
                if code != 200:
                    st.session_state.err = (
                        f"Gagal kalender HTTP {code}. Coba lagi / cek koneksi."
                    )
                elif dates:
                    st.session_state.date_msg = f"{len(dates)} tanggal tersedia — {who}"
                else:
                    st.session_state.err = "Tidak ada tanggal (off-season atau diblokir)."
            except Exception as e:
                st.session_state.err = str(e)

    if st.session_state.date_msg:
        st.success(st.session_state.date_msg)

    selected = None
    if st.session_state.dates:
        labels = [
            f"{d} — {format_tanggal(d)} ({c} game)" for d, c in st.session_state.dates
        ]
        pick = st.radio("Tanggal", labels, index=0)
        selected = st.session_state.dates[labels.index(pick)][0]
    else:
        st.caption("Tekan **Cek tanggal** dulu.")

    st.divider()
    st.subheader("3. Scrape")
    can_run = bool(selected)
    if top25_on and state != "all" and st.session_state.top25:
        if not top25_in_state(st.session_state.top25, state):
            can_run = False
            st.warning(
                "State ini tidak ada di Top 25 — matikan opsi ranking atau pilih state lain."
            )

    # Info biaya (token credit) / status (token waktu)
    is_all_preview = state == "all"
    cost_preview = scrape_credit_cost(is_all=is_all_preview, top25_on=top25_on)
    if user.get("auth_type") == "token":
        mode = user.get("token_mode") or "credit"
        if mode == "credit":
            st.info(
                f"Biaya scrape ini: **{cost_preview} credit** "
                f"(sisa: **{user.get('credits', 0)}**). "
                f"1 state={COST_PER_STATE} · all={COST_ALL_STATES} · +Top25=+{COST_TOP25}."
            )
            if int(user.get("credits") or 0) < cost_preview:
                st.warning("Credit tidak cukup untuk scrape ini.")
                can_run = False
        else:
            st.info(f"Token **waktu** · valid s/d **{user.get('expires_at') or '-'}** (tanpa potong credit).")

    if st.button(
        "Mulai scrape", type="primary", use_container_width=True, disabled=not can_run
    ):
        st.session_state.err = ""
        st.session_state.msg = ""
        st.session_state.preview = ""
        st.session_state.file_bytes = None
        mdy = to_mdy(selected)

        # Token: cek dulu (belum potong) — potong credit SETELAH scrape berhasil
        pending_token_charge = None  # (mode, token, cost)
        if user.get("auth_type") == "token":
            cost = scrape_credit_cost(is_all=(state == "all"), top25_on=top25_on)
            mode = user.get("token_mode") or "credit"
            ok_c, msg_c = check_token_can_scrape(user["token"], cost)
            if not ok_c:
                st.session_state.err = msg_c
                st.error(msg_c)
                st.stop()
            pending_token_charge = (mode, user["token"], cost)
        if watch:
            save_watch_link(watch, "default" if state == "all" else state, sport)

        is_all = state == "all"
        if top25_on:
            gi = 40 if is_all else 60
        else:
            gi = 25 if is_all else 50

        bar = st.progress(0, text="Scraping…")
        try:
            blocks = []
            failed = []

            if top25_on and is_all:
                bar.progress(20, text="Top 25 nasional…")
                _, _, blocks, teams, failed = scrape_top25(
                    sport,
                    mdy,
                    watch,
                    mascots,
                    gi,
                    False,
                    add_title,
                    True,
                    gi,
                    DEFAULT_GAME_WORKERS,
                    DEFAULT_STATE_WORKERS,
                )
                st.session_state.top25 = teams
                tag = "top25"
            elif top25_on:
                bar.progress(20, text="Scrape + filter ranking…")
                if not st.session_state.top25:
                    _, _, st.session_state.top25 = fetch_top25(
                        sport, state="" if state == "all" else state
                    )
                wurl = resolve_watch_url(watch, load_watch_map(), state, sport)
                prefer = {t["name"] for t in st.session_state.top25 if t.get("name")}
                code, _, raw = scrape_state(
                    state,
                    sport,
                    mdy,
                    wurl or WATCH_LIVE_DEFAULT,
                    True,
                    gi,
                    False,
                    add_title,
                    True,
                    gi,
                    DEFAULT_GAME_WORKERS,
                    prefer_teams=prefer,
                )
                if code != 200:
                    st.session_state.err = f"Gagal HTTP {code}"
                    raw = []
                blocks = dedupe_blocks(
                    filter_blocks_top25(raw, st.session_state.top25)
                )
                tag = state
            elif is_all:
                bar.progress(15, text="Scrape semua state…")
                blocks, failed, _, _, _ = scrape_states_parallel(
                    list(STATES.keys()),
                    sport,
                    mdy,
                    watch,
                    mascots,
                    gi,
                    False,
                    add_title,
                    True,
                    gi,
                    DEFAULT_STATE_WORKERS,
                    DEFAULT_GAME_WORKERS,
                )
                blocks = dedupe_blocks(blocks)
                tag = "all"
            else:
                bar.progress(25, text=f"Scrape {STATES.get(state, state)}…")
                wurl = resolve_watch_url(watch, load_watch_map(), state, sport)
                code, _, blocks = scrape_state(
                    state,
                    sport,
                    mdy,
                    wurl or WATCH_LIVE_DEFAULT,
                    mascots,
                    gi,
                    False,
                    add_title,
                    True,
                    gi,
                    DEFAULT_GAME_WORKERS,
                )
                if code != 200:
                    st.session_state.err = f"Gagal HTTP {code}"
                    blocks = []
                else:
                    blocks = dedupe_blocks(blocks)
                tag = state

            bar.progress(85, text="Simpan file…")
            blocks = dedupe_blocks(blocks)
            dest = temp_output_path(tag, sport, mdy)
            written, _ = write_blocks(dest, blocks, overwrite=True)

            st.session_state.preview = "".join(blocks[:8])
            st.session_state.outfile = dest
            if os.path.isfile(dest):
                with open(dest, "rb") as f:
                    st.session_state.file_bytes = f.read()
                st.session_state.file_name = os.path.basename(dest)

            st.session_state.msg = (
                f"Selesai: **{len(blocks)} match** → `{os.path.basename(dest)}`"
            )
            log_access(
                user["username"],
                "scrape",
                f"{tag}/{sport}/{mdy} → {len(blocks)} match",
            )

            # Potong credit / catat token SETELAH scrape berhasil
            token_dead_after = None
            if pending_token_charge:
                mode, tok, cost = pending_token_charge
                if mode == "credit":
                    ok_d, msg_d, left = deduct_token_credits(tok, cost)
                    if ok_d:
                        log_access(user["username"], "credit_deduct", f"-{cost} sisa={left}")
                        st.session_state.msg += f" · −{cost} credit (sisa {left})"
                        if left <= 0:
                            token_dead_after = (
                                "Scrape berhasil. Credit token habis dan token telah dihapus. "
                                "Silakan beli/minta token baru ke admin."
                            )
                        else:
                            refreshed = refresh_token_session(tok)
                            if refreshed:
                                st.session_state.auth_user = refreshed
                    else:
                        # Jangan hapus hasil scrape; credit gagal dipotong (race)
                        st.session_state.err = (st.session_state.err or "") + f" | Credit: {msg_d}"
                else:
                    mark_token_used(tok)
                    log_access(user["username"], "time_token_use", mdy)
                    refreshed = refresh_token_session(tok)
                    if not refreshed:
                        token_dead_after = (
                            "Scrape berhasil. Token waktu sudah kadaluarsa dan telah dihapus. "
                            "Silakan beli/minta token baru."
                        )
                    elif refreshed:
                        st.session_state.auth_user = refreshed
            if token_dead_after:
                st.session_state.token_dead_after_msg = token_dead_after
            if failed:
                st.session_state.err = "Sebagian gagal: " + ", ".join(failed[:8])
            if not blocks and not st.session_state.err:
                st.session_state.err = "Tidak ada match di tanggal ini."
            bar.progress(100, text="Selesai")
        except Exception as e:
            st.session_state.err = f"{type(e).__name__}: {e}"
        finally:
            bar.empty()

    if st.session_state.msg:
        st.success(st.session_state.msg)
    if st.session_state.err:
        st.error(st.session_state.err)

    if st.session_state.file_bytes:
        st.subheader("4. Download")
        st.download_button(
            "⬇️ Download hasil .txt",
            data=st.session_state.file_bytes,
            file_name=st.session_state.file_name or "hasil.txt",
            mime="text/plain",
            type="primary",
            use_container_width=True,
        )
        if st.session_state.preview:
            with st.expander("Preview"):
                st.code(st.session_state.preview)

    # Setelah scrape: token habis — tetap bisa download dulu, lalu konfirmasi logout
    if st.session_state.get("token_dead_after_msg"):
        st.warning(st.session_state.token_dead_after_msg)
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
            st.session_state.auth_user = None
            st.session_state.token_dead_after_msg = ""
            st.session_state.token_dead_msg = ""
            st.rerun()


# ===================== EDIT =====================
elif menu == "Edit file":
    st.header("Edit file")
    files = []
    if os.path.isdir(TEMP_DIR):
        for n in sorted(os.listdir(TEMP_DIR)):
            if n.endswith(".txt"):
                files.append(os.path.join(TEMP_DIR, n))

    if not files:
        st.info("Belum ada file. Scrape dulu di menu Scrape.")
    else:
        labels = [os.path.basename(f) for f in files]
        i = st.selectbox(
            "File", range(len(labels)), format_func=lambda i: labels[i]
        )
        path = files[i]

        if path != st.session_state.editor_path:
            st.session_state.editor_path = path
            st.session_state.ed_area = open(path, encoding="utf-8").read()
            st.session_state.editor_text = st.session_state.ed_area

        if "ed_area" not in st.session_state:
            st.session_state.ed_area = open(path, encoding="utf-8").read()

        c1, c2 = st.columns(2)
        with c1:
            find = st.text_input("Cari", key="edit_find")
        with c2:
            repl = st.text_input("Ganti dengan", key="edit_repl")
        case_sens = st.checkbox("Case sensitive", value=False, key="edit_case")

        r1, r2, r3 = st.columns(3)
        with r1:
            do_replace = st.button(
                "Replace all", type="primary", use_container_width=True
            )
        with r2:
            do_save = st.button("Simpan", use_container_width=True)
        with r3:
            do_reload = st.button("Reload", use_container_width=True)

        if do_reload:
            st.session_state.ed_area = open(path, encoding="utf-8").read()
            st.session_state.editor_text = st.session_state.ed_area
            st.session_state.edit_msg = "File di-reload dari disk."
            st.rerun()

        if do_replace:
            find = (st.session_state.get("edit_find") or "").strip()
            repl = st.session_state.get("edit_repl") or ""
            text = st.session_state.get("ed_area") or ""
            if not find:
                st.warning("Isi kata yang dicari.")
            else:
                if st.session_state.get("edit_case"):
                    count = text.count(find)
                    new_text = text.replace(find, repl)
                else:
                    pattern = re.compile(re.escape(find), re.IGNORECASE)
                    count = len(pattern.findall(text))
                    new_text = pattern.sub(repl, text)
                st.session_state.ed_area = new_text
                st.session_state.editor_text = new_text
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(new_text)
                    st.session_state.edit_msg = (
                        f"Replace all: {count} kemunculan diganti & disimpan."
                    )
                    log_access(user["username"], "edit_replace", os.path.basename(path))
                except Exception as ex:
                    st.session_state.edit_msg = f"Gagal simpan: {ex}"
                st.rerun()

        if do_save:
            text = st.session_state.get("ed_area") or ""
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                st.session_state.editor_text = text
                st.session_state.edit_msg = f"Disimpan ({len(text)} karakter)."
                log_access(user["username"], "edit_save", os.path.basename(path))
            except Exception as ex:
                st.session_state.edit_msg = f"Gagal simpan: {ex}"
            st.rerun()

        if st.session_state.get("edit_msg"):
            st.success(st.session_state.edit_msg)

        st.text_area("Isi file", height=320, key="ed_area")
        text = st.session_state.get("ed_area") or ""
        st.caption(
            f"{len(text)} karakter · {text.count(chr(10)) + (1 if text else 0)} baris"
        )
        st.subheader("Preview")
        st.code(text[:15000] + ("\n…" if len(text) > 15000 else ""))
        st.download_button(
            "⬇️ Download",
            data=text.encode("utf-8"),
            file_name=os.path.basename(path),
            mime="text/plain",
            use_container_width=True,
        )
