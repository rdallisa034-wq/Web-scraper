"""Regresi: style='game_day' harus fetch mascot untuk SEMUA match, bukan hanya `fetch_limit`.

Bug lama: scrape_state() hanya fetch `fetch_limit` match pertama → blok bawah tanpa mascot.
Jalankan: python test_game_day_mascots.py
"""
import maxpreps_scraper as m

# 12 kartu, limit kecil (5) → dulu hanya 5 dapat mascot.
CARDS = "".join(
    f'<div class="contest-box-item" data-contest-state="TX">'
    f'<a class="c-c" href="/game/{i}/"></a>'
    f'<div class="name">Team{i}A</div><div class="score"></div>'
    f'<div class="name">Team{i}B</div><div class="score"></div>'
    f'<div class="details">7p</div></div>'
    for i in range(12)
)
SCORES = f"<html>{CARDS}</html>"
GAME = '<html><div class="mascot-name">Eagle</div><div class="mascot-name">Bear</div></html>'


def fake_fetch(url, referer="", insecure=False):
    return (200, GAME if "/game/" in url else SCORES)


m.fetch = fake_fetch
m.load_cache_safe = lambda: {}
m.merge_save_cache = lambda u: None

_code, _url, blocks = m.scrape_state(
    "tx", "football", "10/2/2026", "http://w/",
    with_mascots=False, mascot_limit=5, insecure=False,
    with_game_info=False, game_info_limit=5, style="game_day",
)

# Setiap blok game_day harus punya baris mascot "Eagle @ Bear"
with_mascot = [b for b in blocks if "Eagle @ Bear" in b]
assert len(blocks) == 12, f"harus 12 blok, dapat {len(blocks)}"
assert len(with_mascot) == 12, f"harus 12 blok bermascot, dapat {len(with_mascot)}"
print(f"OK: {len(with_mascot)}/{len(blocks)} blok punya mascot")
