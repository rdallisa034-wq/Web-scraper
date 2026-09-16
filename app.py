#!/usr/bin/env python3
"""
MaxPreps Scraper — Streamlit UI

  pip install streamlit
  streamlit run app.py
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import streamlit as st

from maxpreps_scraper import (
    STATES,
    SPORTS,
    WATCH_LIVE_DEFAULT,
    OUTPUT_DIR,
    OUTPUT_FILE,
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
    ON_PYTHONANYWHERE,
)

st.set_page_config(
    page_title="MaxPreps Scraper",
    page_icon="🏈",
    layout="centered",
    initial_sidebar_state="expanded",
)


def _init_state():
    defaults = {
        "dates": [],
        "dates_source": "",
        "preview": "",
        "outfile": "",
        "outfile_bytes": None,
        "outfile_name": "",
        "last_flash": "",
        "last_error": "",
        "top25_list": [],
        "editor_path": "",
        "editor_text": "",
        "editor_msg": "",
        "editor_err": "",
        "find_count": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


def _sport_options():
    return {v[0]: k for k, v in SPORTS.items()}


def _state_options():
    opts = {
        "ALL STATES": "all",
        "⭐ TOP 25 only (national)": "top25",
    }
    for code, name in STATES.items():
        opts[f"{name} ({code.upper()})"] = code
    return opts


with st.sidebar:
    st.title("🏈 MaxPreps")
    st.caption("Scrape · Top 25 · Edit · Download")
    page = st.radio("Menu", ["Scrape", "Edit TXT"], label_visibility="collapsed")
    st.divider()
    st.markdown(
        f"<small>Worker: state={DEFAULT_STATE_WORKERS} · game={DEFAULT_GAME_WORKERS}"
        f"{' · PA mode' if ON_PYTHONANYWHERE else ''}</small>",
        unsafe_allow_html=True,
    )
    st.markdown("<small>scraper by <b>Ridwan</b></small>", unsafe_allow_html=True)


if page == "Scrape":
    st.header("Scrape jadwal")

    col1, col2 = st.columns(2)
    sport_labels = _sport_options()
    state_labels = _state_options()

    with col1:
        sport_label = st.selectbox("Sport", list(sport_labels.keys()), index=0)
        sport = sport_labels[sport_label]
    with col2:
        state_keys = list(state_labels.keys())
        default_idx = next((i for i, k in enumerate(state_keys) if state_labels[k] == "tx"), 2)
        state_label = st.selectbox("State / Mode", state_keys, index=default_idx)
        state = state_labels[state_label]

    mapping = load_watch_map()
    default_watch = (
        mapping.get(f"{state}/{sport}")
        or mapping.get(state)
        or mapping.get("default")
        or WATCH_LIVE_DEFAULT
    )
    watch = st.text_input(
        "📺 Watch live URL",
        value=default_watch,
        placeholder="https://prepwire.com/live/texas",
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        add_title = st.checkbox("Tambah ?title=", value=True)
    with c2:
        split_state = st.checkbox("Simpan ke schedules/", value=True)
    with c3:
        overwrite = st.checkbox("Timpa file", value=False)
    with c4:
        mascots = st.checkbox("Ambil mascot", value=False)

    if state == "top25":
        st.info(
            "Mode **Top 25**: ambil ranking nasional MaxPreps, scrape state terkait, "
            "lalu saring hanya match yang melibatkan tim Top 25."
        )
        if st.button("👀 Lihat Top 25 saat ini", use_container_width=True):
            with st.spinner("Mengambil ranking…"):
                code, url, teams = fetch_top25(sport)
                st.session_state.top25_list = teams
                if code != 200 or not teams:
                    st.error(f"Gagal ranking HTTP {code} · {url}")
                else:
                    st.success(f"{len(teams)} tim · {url}")
        if st.session_state.top25_list:
            rows = [
                f"#{t['rank']:>2}  {t['name']} ({t['state'].upper()})"
                for t in st.session_state.top25_list
            ]
            st.code("\n".join(rows), language=None)

    st.divider()

    if st.button("📅 Cek tanggal", use_container_width=True):
        st.session_state.last_error = ""
        st.session_state.last_flash = ""
        with st.spinner("Mengambil kalender MaxPreps…"):
            try:
                if state in ("all", "top25"):
                    code, url, dates, probe = list_dates_with_fallback(sport)
                    who = f"{'TOP 25' if state == 'top25' else 'ALL STATES'} (acuan {STATES.get(probe, probe)})"
                else:
                    code, url, dates = list_dates(state, sport)
                    who = f"{STATES.get(state, state)} / {SPORTS[sport][0]}"
                st.session_state.dates = dates
                st.session_state.dates_source = f"HTTP {code} · {url}"
                if code != 200:
                    st.session_state.last_error = f"Gagal ambil kalender (HTTP {code}). Cek koneksi / VPN."
                elif dates:
                    st.session_state.last_flash = f"{len(dates)} tanggal punya game — {who}."
                else:
                    st.session_state.last_error = "Kalender kosong (off-season atau diblokir)."
            except Exception as ex:
                st.session_state.last_error = f"{type(ex).__name__}: {ex}"

    if st.session_state.last_flash:
        st.success(st.session_state.last_flash)
    if st.session_state.last_error:
        st.error(st.session_state.last_error)
    if st.session_state.dates_source:
        st.caption(st.session_state.dates_source)

    dates = st.session_state.dates
    selected_mdy = None
    if dates:
        labels = [
            f"{d}  ·  {format_tanggal(d)}  ·  {c} game{'s' if c != 1 else ''}"
            for d, c in dates
        ]
        pick = st.radio("Tanggal tersedia (hari ini & mendatang)", labels, index=0)
        selected_mdy = dates[labels.index(pick)][0]
    else:
        st.info("Klik **Cek tanggal** dulu untuk melihat hari yang ada pertandingan.")

    st.divider()

    if st.button(
        "🚀 Scrape tanggal terpilih",
        type="primary",
        use_container_width=True,
        disabled=not selected_mdy,
    ):
        st.session_state.last_error = ""
        st.session_state.last_flash = ""
        st.session_state.preview = ""
        st.session_state.outfile = ""
        st.session_state.outfile_bytes = None

        if not selected_mdy:
            st.session_state.last_error = "Pilih tanggal dulu."
        else:
            mdy = to_mdy(selected_mdy)
            if watch:
                save_watch_link(watch, "default" if state in ("all", "top25") else state, sport)

            is_all = state == "all"
            is_top25 = state == "top25"
            gi_limit = (12 if mascots else 8) if (is_all or is_top25) else (40 if mascots else 30)
            if ON_PYTHONANYWHERE:
                gi_limit = min(gi_limit, 15)
            st_workers = DEFAULT_STATE_WORKERS if (is_all or is_top25) else 1
            g_workers = DEFAULT_GAME_WORKERS

            progress = st.progress(0, text="Mulai scrape…")
            status = st.empty()

            try:
                if is_top25:
                    status.info("Mode Top 25 · ranking + filter match…")
                    progress.progress(15, text="Ambil ranking Top 25…")
                    last_code, last_url, blocks, top25, failed = scrape_top25(
                        sport, mdy, watch,
                        mascots, gi_limit, False, add_title,
                        with_game_info=True, game_info_limit=gi_limit,
                        game_workers=g_workers, state_workers=st_workers,
                    )
                    st.session_state.top25_list = top25
                    progress.progress(85, text="Menulis file…")
                    dest = temp_output_path("top25", sport, mdy)
                    written, _ = write_blocks(dest, blocks, overwrite=True)
                    if split_state:
                        perm = os.path.join(OUTPUT_DIR, f"top25-{sport}-{mdy_to_iso(mdy)}.txt")
                        write_blocks(perm, blocks, overwrite=overwrite)
                    st.session_state.preview = "".join(blocks[:10])
                    st.session_state.outfile = dest
                    st.session_state.last_flash = (
                        f"Top 25 selesai · {len(blocks)} match → `{os.path.basename(dest)}` "
                        f"(written {written}, ranking {len(top25)} tim)"
                    )
                    if failed:
                        st.session_state.last_error = "Gagal partial: " + ", ".join(failed[:10])
                    if not blocks:
                        st.session_state.last_error = (
                            "Tidak ada match Top 25 di tanggal ini (tim mungkin bye / belum main)."
                        )

                elif is_all:
                    status.info(f"Scrape {len(STATES)} state…")
                    progress.progress(10, text="Mengambil semua state…")
                    all_blocks, failed, last_code, last_url, last_blocks = scrape_states_parallel(
                        list(STATES.keys()), sport, mdy, watch,
                        mascots, gi_limit, False, add_title,
                        with_game_info=True, game_info_limit=gi_limit,
                        state_workers=st_workers, game_workers=g_workers,
                    )
                    progress.progress(80, text="Menulis file…")
                    dest = temp_output_path("all", sport, mdy)
                    written, _ = write_blocks(dest, all_blocks, overwrite=True)
                    if split_state or overwrite:
                        write_blocks(all_states_file(sport, mdy), all_blocks, overwrite=overwrite)
                    st.session_state.preview = "".join(all_blocks[:8])
                    st.session_state.outfile = dest
                    st.session_state.last_flash = (
                        f"Selesai · {len(all_blocks)} match → `{os.path.basename(dest)}` "
                        f"(written {written})"
                    )
                    if failed:
                        st.session_state.last_error = "Gagal: " + ", ".join(failed[:12])
                    if not all_blocks and not failed:
                        st.session_state.last_error = "Tidak ada match yang diambil."
                else:
                    status.info(f"Scrape {STATES.get(state, state)}…")
                    progress.progress(20, text="Mengambil halaman skor…")
                    wurl = resolve_watch_url(watch, load_watch_map(), state, sport)
                    code, url, blocks = scrape_state(
                        state, sport, mdy, wurl or WATCH_LIVE_DEFAULT,
                        mascots, gi_limit, False, add_title=add_title,
                        with_game_info=True, game_info_limit=gi_limit,
                        game_workers=g_workers,
                    )
                    progress.progress(80, text="Menulis file…")
                    if code != 200:
                        st.session_state.last_error = f"Scrape gagal HTTP {code}."
                    else:
                        dest = temp_output_path(state, sport, mdy)
                        written, _ = write_blocks(dest, blocks, overwrite=True)
                        if split_state:
                            write_blocks(state_file(state, sport), blocks, overwrite=overwrite)
                        else:
                            write_blocks(OUTPUT_FILE, blocks, overwrite=overwrite)
                        st.session_state.preview = "".join(blocks[:8])
                        st.session_state.outfile = dest
                        st.session_state.last_flash = (
                            f"Selesai · {len(blocks)} match → `{os.path.basename(dest)}` "
                            f"(written {written})"
                        )
                        if not blocks:
                            st.session_state.last_error = "Parser tidak menemukan game card."

                if st.session_state.outfile and os.path.isfile(st.session_state.outfile):
                    with open(st.session_state.outfile, "rb") as fh:
                        st.session_state.outfile_bytes = fh.read()
                    st.session_state.outfile_name = os.path.basename(st.session_state.outfile)

                progress.progress(100, text="Selesai")
            except Exception as ex:
                st.session_state.last_error = f"{type(ex).__name__}: {ex}"
            finally:
                progress.empty()
                status.empty()

    if st.session_state.last_flash:
        st.success(st.session_state.last_flash)
    if st.session_state.last_error:
        st.error(st.session_state.last_error)

    if st.session_state.outfile_bytes:
        st.download_button(
            label="⬇️ Download hasil (.txt)",
            data=st.session_state.outfile_bytes,
            file_name=st.session_state.outfile_name or "schedules.txt",
            mime="text/plain",
            type="primary",
            use_container_width=True,
        )
        st.caption(f"File sementara: `{st.session_state.outfile}`")

    if st.session_state.preview:
        with st.expander("Preview hasil", expanded=True):
            st.code(st.session_state.preview, language=None)


else:
    st.header("Edit file TXT")
    st.caption("Ketik di editor → preview realtime update. Replace all + Simpan menulis ke disk.")

    files = list_schedule_files()
    if os.path.isdir(TEMP_DIR):
        for name in sorted(os.listdir(TEMP_DIR)):
            if name.endswith(".txt"):
                p = os.path.join(TEMP_DIR, name)
                if p not in files:
                    files.append(p)

    if not files:
        st.warning("Belum ada file. Lakukan scrape dulu di tab Scrape.")
    else:
        labels = [f"{os.path.basename(f)}  —  …/{os.path.basename(os.path.dirname(f))}/" for f in files]
        choice = st.selectbox("Pilih file", labels, key="editor_file_select")
        path = files[labels.index(choice)]

        if path != st.session_state.editor_path:
            try:
                with open(path, encoding="utf-8") as fh:
                    st.session_state.editor_text = fh.read()
                st.session_state.editor_path = path
                st.session_state.editor_msg = (
                    f"Dibuka: {os.path.basename(path)} ({len(st.session_state.editor_text)} karakter)"
                )
                st.session_state.editor_err = ""
                st.session_state.find_count = None
            except Exception as ex:
                st.session_state.editor_err = str(ex)

        if st.session_state.editor_msg:
            st.info(st.session_state.editor_msg)
        if st.session_state.editor_err:
            st.error(st.session_state.editor_err)

        st.subheader("Find & Replace")
        fc1, fc2 = st.columns(2)
        with fc1:
            find = st.text_input("Cari", key="editor_find")
        with fc2:
            repl = st.text_input("Ganti dengan", key="editor_repl")
        case_sens = st.checkbox("Case sensitive", key="editor_case")

        b1, b2, b3 = st.columns(3)
        with b1:
            do_replace = st.button("Replace all", use_container_width=True, type="primary")
        with b2:
            do_save = st.button("💾 Simpan ke disk", use_container_width=True)
        with b3:
            do_reload = st.button("↻ Reload dari disk", use_container_width=True)

        if do_reload and st.session_state.editor_path:
            with open(st.session_state.editor_path, encoding="utf-8") as fh:
                st.session_state.editor_text = fh.read()
            st.session_state.editor_msg = "Di-reload dari disk."
            st.rerun()

        if do_replace:
            if not find:
                st.warning("Isi kata yang dicari.")
            else:
                content = st.session_state.get("editor_area_widget", st.session_state.editor_text) or ""
                if case_sens:
                    count = content.count(find)
                    new_content = content.replace(find, repl)
                else:
                    pattern = re.compile(re.escape(find), re.IGNORECASE)
                    count = len(pattern.findall(content))
                    new_content = pattern.sub(repl, content)
                st.session_state.editor_text = new_content
                st.session_state.find_count = count
                try:
                    with open(st.session_state.editor_path, "w", encoding="utf-8") as fh:
                        fh.write(new_content)
                    st.session_state.editor_msg = (
                        f"Replace all: {count} kemunculan · disimpan "
                        f"{os.path.basename(st.session_state.editor_path)}"
                    )
                except Exception as ex:
                    st.session_state.editor_err = f"Gagal simpan: {ex}"
                st.rerun()

        def _on_text_change():
            st.session_state.editor_text = st.session_state.editor_area_widget

        st.text_area(
            "Editor",
            value=st.session_state.editor_text,
            height=320,
            key="editor_area_widget",
            on_change=_on_text_change,
        )

        if do_save and st.session_state.editor_path:
            try:
                text = st.session_state.get("editor_area_widget", st.session_state.editor_text) or ""
                st.session_state.editor_text = text
                with open(st.session_state.editor_path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                st.session_state.editor_msg = (
                    f"Disimpan: {os.path.basename(st.session_state.editor_path)} ({len(text)} karakter)"
                )
                st.success(st.session_state.editor_msg)
            except Exception as ex:
                st.error(f"Gagal simpan: {ex}")

        st.subheader("Preview realtime")
        preview_text = st.session_state.get("editor_area_widget", st.session_state.editor_text) or ""
        nlines = preview_text.count("\n") + (1 if preview_text else 0)
        extra = ""
        if st.session_state.find_count is not None:
            extra = f" · replace terakhir: {st.session_state.find_count}x"
        st.caption(f"{len(preview_text)} karakter · {nlines} baris{extra}")
        st.code(
            preview_text[:20000] + ("\n… (dipotong)" if len(preview_text) > 20000 else ""),
            language=None,
        )

        if preview_text:
            st.download_button(
                "⬇️ Download file ini",
                data=preview_text.encode("utf-8"),
                file_name=os.path.basename(st.session_state.editor_path or "edit.txt"),
                mime="text/plain",
                use_container_width=True,
            )
