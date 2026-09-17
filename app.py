#!/usr/bin/env python3
"""MaxPreps Scraper — UI sederhana. Jalankan: streamlit run app.py"""

from __future__ import annotations

import os
import re

import streamlit as st

from maxpreps_scraper import (
    STATES,
    SPORTS,
    WATCH_LIVE_DEFAULT,
    OUTPUT_DIR,
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
    state_file,
    all_states_file,
    to_mdy,
    mdy_to_iso,
    format_tanggal,
    list_schedule_files,
    DEFAULT_STATE_WORKERS,
    DEFAULT_GAME_WORKERS,
)

st.set_page_config(page_title="MaxPreps Scraper", page_icon="🏈", layout="centered")

# ---- session ----
for k, v in {
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
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _sports():
    return {label: key for key, (label, _) in SPORTS.items()}


def _states():
    o = {"Semua state": "all"}
    o.update({f"{n} ({c.upper()})": c for c, n in STATES.items()})
    return o


# ---- sidebar ----
with st.sidebar:
    st.title("🏈 MaxPreps")
    menu = st.radio("Menu", ["Scrape", "Edit file"], label_visibility="collapsed")
    st.caption("by Ridwan")


# ===================== SCRAPE =====================
if menu == "Scrape":
    st.header("Scrape jadwal")

    # --- 1. Pilihan dasar ---
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

    top25_on = st.checkbox("Hanya Top 25 MaxPreps", value=False)

    if top25_on:
        if st.button("Cek ranking Top 25"):
            with st.spinner("Ambil ranking…"):
                try:
                    code, url, teams = fetch_top25(sport)
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
            else:
                st.success(info)
            with st.expander("Daftar tim"):
                show = subset if state != "all" else st.session_state.top25
                st.code("\n".join(f"#{t['rank']:>2}  {t['name']} ({t['state'].upper()})" for t in show))

    with st.expander("Opsi tambahan"):
        add_title = st.checkbox("Tambah ?title= di link watch", value=True)
        save_disk = st.checkbox("Simpan juga ke folder schedules/", value=True)
        overwrite = st.checkbox("Timpa file lama", value=False)
        mascots = st.checkbox("Paksa ambil mascot untuk semua match (lebih lambat)", value=False)

    # defaults if expander not opened still need vars - checkbox always runs
    # (expander content still executes in Streamlit)

    st.divider()

    # --- 2. Tanggal ---
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
                    st.session_state.err = f"Gagal kalender HTTP {code}. Coba lagi / cek koneksi."
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
        labels = [f"{d} — {format_tanggal(d)} ({c} game)" for d, c in st.session_state.dates]
        pick = st.radio("Tanggal", labels, index=0)
        selected = st.session_state.dates[labels.index(pick)][0]
    else:
        st.caption("Tekan **Cek tanggal** dulu.")

    st.divider()

    # --- 3. Scrape ---
    st.subheader("3. Scrape")
    can_run = bool(selected)
    if top25_on and state != "all" and st.session_state.top25:
        if not top25_in_state(st.session_state.top25, state):
            can_run = False
            st.warning("State ini tidak ada di Top 25 — matikan opsi Top 25 atau pilih state lain.")

    if st.button("Mulai scrape", type="primary", use_container_width=True, disabled=not can_run):
        st.session_state.err = ""
        st.session_state.msg = ""
        st.session_state.preview = ""
        st.session_state.file_bytes = None
        mdy = to_mdy(selected)
        if watch:
            save_watch_link(watch, "default" if state == "all" else state, sport)

        is_all = state == "all"
        # Limit fetch detail: cukup besar agar mascot + Game Info terisi
        if top25_on:
            gi = 40 if is_all else 60
        else:
            gi = 25 if is_all else 50
        if not mascots and not top25_on:
            # tetap ambil Game Info (mascot ikut jika halaman menyediakan)
            pass
        bar = st.progress(0, text="Scraping…")
        try:
            blocks = []
            failed = []

            if top25_on and is_all:
                bar.progress(20, text="Top 25 nasional…")
                _, _, blocks, teams, failed = scrape_top25(
                    sport, mdy, watch, mascots, gi, False, add_title,
                    True, gi, DEFAULT_GAME_WORKERS, DEFAULT_STATE_WORKERS,
                )
                st.session_state.top25 = teams
                tag = "top25"
            elif top25_on:
                bar.progress(20, text="Scrape + filter Top 25…")
                if not st.session_state.top25:
                    _, _, st.session_state.top25 = fetch_top25(sport)
                wurl = resolve_watch_url(watch, load_watch_map(), state, sport)
                prefer = {t["name"] for t in st.session_state.top25 if t.get("name")}
                code, _, raw = scrape_state(
                    state, sport, mdy, wurl or WATCH_LIVE_DEFAULT,
                    True, gi, False, add_title, True, gi, DEFAULT_GAME_WORKERS,
                    prefer_teams=prefer,
                )
                if code != 200:
                    st.session_state.err = f"Gagal HTTP {code}"
                    raw = []
                blocks = dedupe_blocks(filter_blocks_top25(raw, st.session_state.top25))
                tag = state
            elif is_all:
                bar.progress(15, text="Scrape semua state…")
                blocks, failed, _, _, _ = scrape_states_parallel(
                    list(STATES.keys()), sport, mdy, watch,
                    mascots, gi, False, add_title, True, gi,
                    DEFAULT_STATE_WORKERS, DEFAULT_GAME_WORKERS,
                )
                blocks = dedupe_blocks(blocks)
                tag = "all"
            else:
                bar.progress(25, text=f"Scrape {STATES.get(state, state)}…")
                wurl = resolve_watch_url(watch, load_watch_map(), state, sport)
                code, _, blocks = scrape_state(
                    state, sport, mdy, wurl or WATCH_LIVE_DEFAULT,
                    mascots, gi, False, add_title, True, gi, DEFAULT_GAME_WORKERS,
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

            if save_disk:
                if is_all and top25_on:
                    perm = os.path.join(OUTPUT_DIR, f"top25-{sport}-{mdy_to_iso(mdy)}.txt")
                    write_blocks(perm, blocks, overwrite=overwrite)
                elif is_all:
                    write_blocks(all_states_file(sport, mdy), blocks, overwrite=overwrite)
                else:
                    write_blocks(state_file(state, sport), blocks, overwrite=overwrite)

            st.session_state.preview = "".join(blocks[:8])
            st.session_state.outfile = dest
            if os.path.isfile(dest):
                with open(dest, "rb") as f:
                    st.session_state.file_bytes = f.read()
                st.session_state.file_name = os.path.basename(dest)

            st.session_state.msg = f"Selesai: **{len(blocks)} match** → `{os.path.basename(dest)}`"
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

    # --- 4. Download ---
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


# ===================== EDIT =====================
else:
    st.header("Edit file")
    files = list_schedule_files()
    if os.path.isdir(TEMP_DIR):
        for n in sorted(os.listdir(TEMP_DIR)):
            if n.endswith(".txt"):
                p = os.path.join(TEMP_DIR, n)
                if p not in files:
                    files.append(p)

    if not files:
        st.info("Belum ada file. Scrape dulu di menu Scrape.")
    else:
        labels = [os.path.basename(f) for f in files]
        i = st.selectbox("File", range(len(labels)), format_func=lambda i: labels[i])
        path = files[i]

        # Satu sumber kebenaran: session_state["ed_area"] (key widget)
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
            do_replace = st.button("Replace all", type="primary", use_container_width=True)
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
                st.session_state.edit_msg = ""
                st.warning("Isi kata yang dicari.")
            else:
                if st.session_state.get("edit_case"):
                    count = text.count(find)
                    new_text = text.replace(find, repl)
                else:
                    pattern = re.compile(re.escape(find), re.IGNORECASE)
                    count = len(pattern.findall(text))
                    new_text = pattern.sub(repl, text)
                # Update widget state LANGSUNG (ini yang bikin replace “keliatan”)
                st.session_state.ed_area = new_text
                st.session_state.editor_text = new_text
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(new_text)
                    st.session_state.edit_msg = f"Replace all: {count} kemunculan diganti & disimpan."
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
            except Exception as ex:
                st.session_state.edit_msg = f"Gagal simpan: {ex}"
            st.rerun()

        if st.session_state.get("edit_msg"):
            st.success(st.session_state.edit_msg)

        # Jangan pakai value= bersama key= — cukup key, isi dari session_state
        st.text_area("Isi file", height=320, key="ed_area")

        text = st.session_state.get("ed_area") or ""
        st.caption(f"{len(text)} karakter · {text.count(chr(10)) + (1 if text else 0)} baris")
        st.subheader("Preview")
        st.code(text[:15000] + ("\n…" if len(text) > 15000 else ""))
        st.download_button(
            "⬇️ Download",
            data=text.encode("utf-8"),
            file_name=os.path.basename(path),
            mime="text/plain",
            use_container_width=True,
        )
