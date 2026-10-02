"""Regresi: watch map harus terpisah per user (tmp_out/<owner>/watch_links.txt).

Bug lama: satu file watch_links.txt global → user B melihat link watch user A.
Jalankan: python test_watch_map_per_user.py
"""
import os
import maxpreps_scraper as m

m.save_watch_link("http://A/", "tx", "football", owner="a@x.com")
m.save_watch_link("http://B/", "tx", "football", owner="b@x.com")

# User A hanya melihat link A, user B hanya link B
assert m.load_watch_map("a@x.com")["tx"] == "http://A/"
assert m.load_watch_map("b@x.com")["tx"] == "http://B/"

# File benar-benar berbeda dan berada di folder owner
fa, fb = m.watch_file_for("a@x.com"), m.watch_file_for("b@x.com")
assert fa != fb, "file watch dua user tidak boleh sama"
assert fa == os.path.join(m.TEMP_DIR, "a_x.com", "watch_links.txt")

# CLI (tanpa owner) tetap pakai file global lama
assert m.watch_file_for("") == m.WATCH_FILE

print("OK: watch map terpisah per user")
