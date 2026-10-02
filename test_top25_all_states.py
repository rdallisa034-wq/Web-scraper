"""Regresi: mode All States + Top 25 = Top 25 tiap state (bukan 1 ranking nasional).

Jalankan: python test_top25_all_states.py
"""
import maxpreps_scraper as m

# --- fetch_top25_states menggabungkan Top 25 tiap state ---
calls = []
def fake_fetch(sport, insecure=False, state=""):
    calls.append(state)
    return 200, f"http://x/{state}", [
        {"rank": i, "name": f"Team {state}{i}", "state": state, "href": ""}
        for i in range(1, 26)
    ]
m.fetch_top25 = fake_fetch
code, label, teams, failed = m.fetch_top25_states("football", workers=4)
assert code == 200, code
assert not failed, failed
assert set(calls) == set(m.STATES), "harus ambil ranking tiap state"
assert len(teams) == 25 * len(m.STATES), len(teams)
assert len({t["state"] for t in teams}) == len(m.STATES), "tiap state terwakili"
assert all(t["state"] == s for s in m.STATES for t in teams if t["name"].startswith(f"Team {s}")), \
    "tim harus tetap terikat state-nya (bukan ranking nasional)"

# state yang gagal HTTP tidak menggagalkan seluruh proses
def fake_fail(sport, insecure=False, state=""):
    if state == "tx":
        return 403, "http://x/tx", []
    return 200, f"http://x/{state}", [{"rank": 1, "name": "A", "state": state, "href": ""}]
m.fetch_top25 = fake_fail
code, label, teams, failed = m.fetch_top25_states("football", workers=4)
assert code == 200 and any("TX" in f for f in failed), (code, failed)
assert len(teams) == len(m.STATES) - 1, len(teams)

# semua state gagal → code != 200
m.fetch_top25 = lambda *a, **k: (403, "u", [])
code, label, teams, failed = m.fetch_top25_states("football")
assert code != 200 and not teams, (code, teams)

print(f"OK: Top 25 per state ({len(m.STATES)} state)")
