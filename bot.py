#!/usr/bin/env python3
# BAGEN KEIBA - Ultimate Prediction & Automated Settlement Engine
# Free GitHub Actions only. No paid API. No real betting.

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "data.json"
HISTORY = DOCS / "history.json"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y%m%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y%m%d")
TODAY_ISO = NOW.strftime("%Y-%m-%d")

MAX_RACES = 80
MIN_RUNNERS = 2
MAX_RUNNERS = 18
REQUEST_DELAY = 1.0
BET_UNIT_YEN = 100
INITIAL_BANKROLL_YEN = 10000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

SOURCES = [
    {"kind": "中央", "category": "中央競馬", "base": "https://race.netkeiba.com", "list": "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date="},
    {"kind": "地方", "category": "地方競馬", "base": "https://nar.netkeiba.com", "list": "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date="},
]

JRA_CODES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
NAR_CODES = {"30": "帯広", "35": "盛岡", "36": "水沢", "40": "浦和", "41": "船橋", "44": "大井", "45": "川崎", "46": "金沢", "47": "笠松", "48": "名古屋", "50": "園田", "54": "姫路", "55": "高知", "56": "佐賀"}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value):
    text = clean(value).replace(",", "")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def soup_of(html):
    return BeautifulSoup(html, "html.parser")


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def get(url):
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def race_number_from_id(race_id):
    if not re.fullmatch(r"\d{12}", race_id):
        return None
    val = int(race_id[-2:])
    return val if 1 <= val <= 12 else None


def venue_from_id(race_id, kind):
    if not re.fullmatch(r"\d{12}", race_id):
        return ""
    code = race_id[4:6]
    return JRA_CODES.get(code, "") if kind == "中央" else NAR_CODES.get(code, "")


def extract_race_ids(html):
    soup = soup_of(html)
    found, seen = [], set()
    for anchor in soup.select('a[href*="race_id="], a[href*="shutuba.html"]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{12})", href)
        if match:
            rid = match.group(1)
            if rid not in seen and race_number_from_id(rid) is not None:
                seen.add(rid)
                found.append(rid)
    return found[:MAX_RACES]


def extract_meta(html, race_id, kind):
    soup = soup_of(html)
    race_no = race_number_from_id(race_id)
    venue = venue_from_id(race_id, kind)

    meta_parts = []
    for selector in (".RaceData01", ".RaceData02", ".RaceData", ".race_data", "[class*='RaceData']"):
        for element in soup.select(selector):
            v = text_of(element)
            if v and v not in meta_parts:
                meta_parts.append(v)

    meta_text = " ".join(meta_parts)
    post_time = ""
    match = re.search(r"(\d{1,2}:\d{2})", meta_text)
    if match:
        post_time = match.group(1)

    race_name = ""
    for selector in (".RaceName", ".race_name", "h1", ".RaceList_ItemTitle"):
        element = soup.select_one(selector)
        if element:
            cand = text_of(element)
            if cand and "netkeiba" not in cand.lower() and len(cand) >= 2:
                race_name = cand
                break

    surface = "ダート" if "ダ" in meta_text else "芝" if "芝" in meta_text else ""
    dist_match = re.search(r"(\d{3,4})\s*m?", meta_text)
    distance = int(dist_match.group(1)) if dist_match else None

    return {
        "race_no": race_no,
        "course": venue or "競馬場未取得",
        "race_name": race_name or f"{venue}{race_no}R",
        "post_time": post_time,
        "surface": surface,
        "distance_m": distance,
        "weather": "晴" if "晴" in meta_text else "雨" if "雨" in meta_text else "曇",
        "track_condition": "良" if "良" in meta_text else "重" if "重" in meta_text else "稍重",
    }, soup


def parse_runners_robust(soup):
    """中央・地方両対応の強固な馬名・オッズ・枠番パース処理"""
    rows = soup.select("tr.HorseList, tr[class*='Horse'], table.Shutuba_Table tr, table.ShutubaTable tr, tr[class*='SelectHorse']")
    if not rows:
        rows = soup.select("table tr")

    runners = []
    seen = set()

    for row in rows:
        anchor = row.select_one('a[href*="/horse/"], a[href*="horse"]')
        if not anchor:
            continue

        horse_name = text_of(anchor)
        if not horse_name or "馬名" in horse_name or horse_name in seen:
            continue

        cells = row.find_all(["td", "th"], recursive=False)
        horse_no_text = text_of(row.select_one("td.Umaban, .Umaban, [class*='Umaban']"))
        horse_no_val = number(horse_no_text)
        if not horse_no_val and len(cells) >= 2:
            horse_no_val = number(text_of(cells[1]))

        if not horse_no_val:
            continue

        horse_no = int(horse_no_val)
        seen.add(horse_name)

        frame_val = number(text_of(row.select_one("td.Waku, .Waku, [class*='Waku']")))
        odds = number(text_of(row.select_one("td.Odds, .Odds, [class*='Odds']")))
        popularity = number(text_of(row.select_one("td.Popular_Ninki, .Popular_Ninki, [class*='Ninki']")))
        jockey = text_of(row.select_one(".Jockey, td.Jockey, [class*='Jockey']"))
        weight_text = text_of(row.select_one("td.Horse_Weight, [class*='Weight']"))
        weight_match = re.search(r"(\d{3})\s*\(([+-]?\d+)\)?", weight_text)

        is_inner = frame_val in (1, 2) if frame_val else False
        is_apprentice = any(symbol in jockey for symbol in ["▲", "△", "☆", "◇", "★"])
        weight_diff = int(weight_match.group(2)) if weight_match and weight_match.group(2) else 0

        reasons = []
        caution = "展開の助けが必要"
        if is_inner and is_apprentice:
            reasons.append("内枠＋減量騎手配置（ハナを切った場合の逃げ残り注意）")
            caution = "単騎逃げによる展開一変警戒"
        if abs(weight_diff) >= 10:
            reasons.append(f"馬体重変化({weight_diff:+d}kg・休み明け/成長)")

        runners.append({
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": int(frame_val) if frame_val else None,
            "horse": horse_name,
            "name": horse_name,
            "jockey": jockey or "未設定",
            "odds": odds,
            "popularity": int(popularity) if popularity else None,
            "score": None,
            "reasons": reasons,
            "caution": caution,
        })

    runners.sort(key=lambda x: x["horse_no"])
    return runners


def score_and_recommend(runners):
    valid_odds = [h["odds"] for h in runners if h.get("odds") and h["odds"] > 0]
    for h in runners:
        odds = h.get("odds")
        pop = h.get("popularity")
        score = None
        if odds:
            score = 100 - min(70, 18 * math.log(max(1, odds)))
            if f"単勝{odds:g}倍" not in h["reasons"]:
                h["reasons"].append(f"単勝{odds:g}倍")
        if pop:
            m_score = max(0, 35 - (pop - 1) * 2.5)
            score = (score * 0.7 + m_score * 0.3) if score else m_score
            if f"{pop}番人気" not in h["reasons"]:
                h["reasons"].append(f"{pop}番人気")
        h["score"] = round(score, 2) if score else 0.0

    ranked = sorted(runners, key=lambda x: -x["score"])
    for idx, h in enumerate(ranked, 1):
        h["prediction_rank"] = idx

    top5 = ranked[:5]
    outsiders = [h for h in runners if h.get("odds") and 10.0 <= h["odds"] < 30.0][:3]
    longshots = [h for h in runners if h.get("odds") and h["odds"] >= 30.0][:2]

    tickets = []
    if len(top5) >= 3:
        b1 = top5[0]["horse_no"]
        b2 = top5[1]["horse_no"]
        b3 = top5[2]["horse_no"]
        third_legs = list(set([h["horse_no"] for h in top5[1:]] + [h["horse_no"] for h in outsiders + longshots]))
        
        points = max(4, len(third_legs) * 2 - (2 if b3 in third_legs else 0))
        tickets.append({
            "type": "3連単 フォーメーション",
            "first": [b1],
            "second": [b2, b3],
            "third": third_legs[:6],
            "points": points,
            "note": "本命軸から穴馬へのヒモ荒れ高配当狙い"
        })

    return runners, top5, outsiders, longshots, tickets


def fetch_and_settle_results(snapshots):
    """レース終了後に確定着順・払戻金を取得して成績計算"""
    for race_id, snap in snapshots.items():
        if snap.get("result_status") == "SETTLED":
            continue

        result_url = f"{snap.get('base_url', 'https://race.netkeiba.com')}/race/result.html?race_id={race_id}"
        try:
            html = get(result_url)
            soup = soup_of(html)

            # 確定1〜3着の馬番取得
            result_rows = soup.select("table.ResultTable tr, table.RaceResult tr")
            top_finishes = []
            for r in result_rows:
                rank = number(text_of(r.select_one(".Rank, td:nth-child(1)")))
                h_no = number(text_of(r.select_one(".Umaban, td:nth-child(3)")))
                if rank and h_no and rank <= 3:
                    top_finishes.append(int(h_no))

            pay_table = soup.select_one("table.Pay_Table, table.PayTable")
            if pay_table and len(top_finishes) >= 1:
                win_row = pay_table.select_one("tr.Tansho, tr[class*='Tansho']")
                win_pay = number(text_of(win_row.select_one(".Pay, td:nth-child(3)"))) if win_row else 0

                pred_no = snap.get("predicted_horse_no")
                hit = (pred_no is not None and len(top_finishes) >= 1 and int(pred_no) == top_finishes[0])

                snap["result_status"] = "SETTLED"
                snap["top_finishes"] = top_finishes
                snap["win_hit"] = hit
                snap["win_return_yen"] = int(win_pay) if hit and win_pay else 0
                snap["settled_at"] = NOW.isoformat()
        except Exception:
            continue


def is_race_finished(post_time):
    """発走時刻から15分経過していれば終了と判定"""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", post_time or "")
    if not match:
        return False
    h, m = int(match.group(1)), int(match.group(2))
    scheduled = NOW.replace(hour=h, minute=m, second=0, microsecond=0)
    return NOW >= scheduled + timedelta(minutes=15)


def main():
    history = load_json(HISTORY, {"schema_version": 8, "snapshots": {}})
    snapshots = history.get("snapshots", {})

    fetch_and_settle_results(snapshots)

    today_races, tomorrow_races = [], []

    for date_str, target_list in [(TODAY, today_races), (TOMORROW, tomorrow_races)]:
        is_tomorrow = (date_str == TOMORROW)
        for source in SOURCES:
            try:
                list_html = get(source["list"] + date_str)
                race_ids = extract_race_ids(list_html)
            except Exception:
                continue

            for race_id in race_ids:
                race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"
                try:
                    html = get(race_url)
                    meta, soup = extract_meta(html, race_id, source["kind"])
                    runners = parse_runners_robust(soup)

                    if len(runners) < MIN_RUNNERS:
                        continue

                    runners, top5, outsiders, longshots, tickets = score_and_recommend(runners)
                    race_key = str(race_id)

                    finished = is_race_finished(meta["post_time"]) if not is_tomorrow else False
                    snap = snapshots.get(race_key, {})

                    race_obj = {
                        "id": race_id,
                        "kind": source["kind"],
                        "category": "local" if source["kind"] == "地方" else "central",
                        "date": TODAY_ISO if not is_tomorrow else (NOW + timedelta(days=1)).strftime("%Y-%m-%d"),
                        "race_no": meta["race_no"],
                        "name": meta["race_name"],
                        "course": meta["course"],
                        "post_time": meta["post_time"],
                        "surface": meta["surface"],
                        "distance_m": meta["distance_m"],
                        "weather": meta["weather"],
                        "track_condition": meta["track_condition"],
                        "runner_count": len(runners),
                        "horses": runners,
                        "top5": top5,
                        "outsiders": outsiders,
                        "longshots": longshots,
                        "tickets": tickets,
                        "is_finished": finished,
                        "result_finishes": snap.get("top_finishes", []),
                        "win_hit": snap.get("win_hit"),
                        "win_return": snap.get("win_return_yen", 0),
                        "is_recommended": (meta["race_no"] == 11 or len(outsiders) >= 2),
                        "is_tomorrow": is_tomorrow
                    }

                    target_list.append(race_obj)

                    if race_key not in snapshots and not is_tomorrow:
                        first_pick = top5[0] if top5 else None
                        snapshots[race_key] = {
                            "race_id": race_id,
                            "race_date": TODAY_ISO,
                            "base_url": source["base"],
                            "predicted_horse_no": first_pick["horse_no"] if first_pick else None,
                            "predicted_horse": first_pick["horse"] if first_pick else None,
                            "result_status": "PENDING",
                            "win_hit": False,
                            "win_return_yen": 0
                        }
                except Exception:
                    continue
                time.sleep(REQUEST_DELAY)

    settled = [s for s in snapshots.values() if s.get("result_status") == "SETTLED"]
    win_hits = sum(1 for s in settled if s.get("win_hit"))
    win_returns = sum(s.get("win_return_yen", 0) for s in settled)
    total_stake = len(settled) * BET_UNIT_YEN
    profit = win_returns - total_stake
    roi = (win_returns / total_stake * 100) if total_stake > 0 else 0.0

    stats = {
        "races_settled": len(settled),
        "win_bets": len(settled),
        "win_hits": win_hits,
        "total_stake_yen": total_stake,
        "total_return_yen": win_returns,
        "profit_yen": profit,
        "roi_pct": round(roi, 1),
        "virtual_balance_yen": INITIAL_BANKROLL_YEN + profit,
        "win_hit_rate_pct": round((win_hits / len(settled) * 100) if settled else 0.0, 1),
    }

    history.update({"updated_at": NOW.isoformat(), "stats": stats, "snapshots": snapshots})
    save_json(HISTORY, history)

    data = {
        "site": "BAGEN KEIBA",
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": "OK",
        "races": today_races,
        "tomorrow_races": [r for r in tomorrow_races if r["is_recommended"]],
        "paper_betting": {"stats": stats, "history": settled[-50:]}
    }
    save_json(OUT, data)
    print(f"BAGEN Engine complete. Today: {len(today_races)}, Tomorrow recommended: {len(data['tomorrow_races'])}")


if __name__ == "__main__":
    main()
