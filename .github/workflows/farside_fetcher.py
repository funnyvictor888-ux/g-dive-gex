"""
farside_fetcher.py
==================
Farside.co.uk'dan Bitcoin ETF akış verisini çeker,
data/etf_flow.json olarak GitHub repo'ya commit eder.

Kullanım:
  python farside_fetcher.py           → fetch + commit
  python farside_fetcher.py --dry-run → sadece fetch, commit etme
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FARSIDE_URL = "https://farside.co.uk/btc/"
OUTPUT_PATH = Path("data/etf_flow.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# Bilinen ETF ticker listesi
KNOWN_ETFS = [
    "IBIT", "FBTC", "BITB", "ARKB", "BTCO",
    "EZBC", "BRRR", "HODL", "BTCW", "GBTC",
    "BTC", "MSBT",
]


def fetch_farside() -> dict:
    print(f"  Fetching {FARSIDE_URL}...")
    resp = requests.get(FARSIDE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return parse_farside(resp.text)


def parse_farside(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": FARSIDE_URL,
        "latest_date": None,
        "total_net_flow_usd_m": None,
        "etf_flows": {},
        "last_7_days": [],
        "streak": {
            "direction": "neutral",
            "days": 0,
        },
        "signal": "neutral",
    }

    # Tüm tabloları tara
    tables = soup.find_all("table")
    all_rows = []

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        # Header satırını bul
        header_row = rows[0]
        headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]

        # ETF ticker içeren tablo mu?
        if not any(etf in headers for etf in KNOWN_ETFS):
            continue

        # Data satırlarını parse et
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue

            date_text = cells[0].get_text(strip=True)
            if not date_text or date_text.lower() in ["date", "total", ""]:
                continue

            row_data = {"date": date_text, "etfs": {}, "total": None}

            for i, col_name in enumerate(headers[1:], start=1):
                if i >= len(cells):
                    break
                raw = cells[i].get_text(strip=True).replace(",", "")
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    val = 0.0

                col_upper = col_name.upper()
                if col_upper in ["TOTAL", "TOTAL NET FLOW", "NET"]:
                    row_data["total"] = val
                elif col_name in KNOWN_ETFS or col_upper in KNOWN_ETFS:
                    row_data["etfs"][col_name] = val

            all_rows.append(row_data)

        break  # İlk geçerli tabloyla yetiniyoruz

    if not all_rows:
        print("  ⚠  Parse edilecek satır bulunamadı")
        return result

    # En güncel satır
    latest = all_rows[-1]
    result["latest_date"] = latest["date"]
    result["total_net_flow_usd_m"] = latest["total"]
    result["etf_flows"] = latest["etfs"]

    # Son 7 gün
    for row in all_rows[-7:]:
        result["last_7_days"].append({
            "date": row["date"],
            "total": row["total"],
        })

    # Seri hesabı (pozitif / negatif gün streak)
    streak_dir = None
    streak_count = 0
    for row in reversed(all_rows):
        t = row.get("total")
        if t is None:
            break
        if streak_dir is None:
            streak_dir = "positive" if t > 0 else ("negative" if t < 0 else "neutral")
        cur_dir = "positive" if t > 0 else ("negative" if t < 0 else "neutral")
        if cur_dir == streak_dir and cur_dir != "neutral":
            streak_count += 1
        else:
            break

    result["streak"] = {
        "direction": streak_dir or "neutral",
        "days": streak_count,
    }

    # Sinyal üret
    total = latest.get("total") or 0
    if streak_dir == "positive" and streak_count >= 2:
        result["signal"] = "bullish"
    elif streak_dir == "negative" and streak_count >= 2:
        result["signal"] = "bearish"
    elif total > 200:
        result["signal"] = "bullish"
    elif total < -100:
        result["signal"] = "bearish"
    else:
        result["signal"] = "neutral"

    print(f"  ✓ {latest['date']} | Total: {total}M | "
          f"Streak: {streak_dir} {streak_count}g | Signal: {result['signal']}")
    return result


def commit_to_github(data: dict, repo_path: str = "."):
    """GitHub Actions ortamında JSON'u commit eder."""
    out = Path(repo_path) / OUTPUT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    cmds = [
        ["git", "config", "user.email", "gdive-bot@users.noreply.github.com"],
        ["git", "config", "user.name", "G-DIVE Bot"],
        ["git", "add", str(OUTPUT_PATH)],
    ]
    for cmd in cmds:
        subprocess.run(cmd, cwd=repo_path, check=False)

    # Değişiklik var mı?
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_path
    )

    if diff.returncode != 0:
        date_str = data.get("latest_date", "unknown")
        total = data.get("total_net_flow_usd_m", 0) or 0
        prefix = "+" if total >= 0 else ""
        msg = f"[etf-flow] {date_str} | {prefix}{total:.0f}M"
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_path, check=False)
        subprocess.run(["git", "push"], cwd=repo_path, check=False)
        print(f"  ✓ Committed: {msg}")
    else:
        print("  → No changes, skip commit")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    try:
        data = fetch_farside()
        if dry_run:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            commit_to_github(data)
    except Exception as e:
        print(f"  ✗ Farside fetch hatası: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
