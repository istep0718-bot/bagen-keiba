#!/usr/bin/env python3
# BAGEN KEIBA - Ultimate Engine with Pattern A/B 2000-Yen Multi Betting

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
REQUEST_DELAY = 0.5
INITIAL_BANKROLL_YEN = 100000  # 初期残高10万円

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


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def number(v):
    text = clean(v).replace(",", "")
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


def get_html(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
        res.encoding = res.apparent_encoding or "utf-8"
        return res.text
    except Exception:
        return ""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def race_no_from_id(rid):
    if not re.fullmatch(r"\d{12}", str(rid)):
        return None
    val = int(str(rid)[-2:])
    return val if 1 <= val <= 12 else None


def venue_from_id(rid, kind):
    if not re.fullmatch(r"\d{12}", str(rid)):
        return ""
    code = str(rid)[4:6]
    return JRA_CODES.get(code, "") if kind == "中央" else NAR_CODES.get(code, "")


def extract_race_ids(html):
    if not html:
        return []
    soup = soup_of(html)
    found, seen = [], set()
    for a in soup.select('a[href*="race_id="], a[href*="shutuba.html"]'):
        href = a.get("href", "")
        m = re.search(r"race_id=(\d{12})", href)
        if m:
            rid = m.group(1)
            if rid not in seen and race_no_from_id(rid):
                seen.add(rid)
                found.append(rid)
    return found[:MAX_RACES]


def fetch_race_results(base_url, rid):
    url = f"{base_url}/race/result.html?race_id={rid}"
    html = get_html(url)
    if not html:
        return []
    
    soup = soup_of(html)
    finishes = []
    rows = soup.select("table.RaceTable01 tr, tr.HorseList, tr[class*='Horse'], table tr")
    for r in rows:
        cells = r.find_all(["td", "th"])
        if len(cells) >= 3:
            rank_text = text_of(cells[0])
            if rank_text in ["1", "2", "3"]:
                for cell in cells[1:6]:
                    val = number(text_of(cell))
                    if val and 1 <= val <= 18:
                        if int(val) not in finishes:
                            finishes.append(int(val))
                            break
    return finishes[:3]


def parse_race(html, rid, kind, base_url):
    soup = soup_of(html)
    race_no = race_no_from_id(rid)
    venue = venue_from_id(rid, kind)

    meta_text = " ".join([text_of(e) for e in soup.select(".RaceData01, .RaceData02, .RaceData, .race_data, [class*='RaceData']")])
    
    post_time = ""
    m_time = re.search(r"(\d{1,2}:\d{2})", meta_text)
    if m_time:
        post_time = m_time.group(1)

    race_name = ""
    for sel in (".RaceName", ".race_name", "h1", ".RaceList_ItemTitle"):
        el = soup.select_one(sel)
        if el:
            cand = text_of(el)
            if cand and "netkeiba" not in cand.lower() and len(cand) >= 2:
                race_name = cand
                break
    if not race_name:
        race_name = f"{venue}{race_no}R" if venue and race_no else "レース名未取得"

    surface = "ダート" if "ダ" in meta_text else "芝" if "芝" in meta_text else ""
    m_dist = re.search(r"(\d{3,4})\s*m?", meta_text)
    distance = int(m_dist.group(1)) if m_dist else None

    rows = soup.select("tr.HorseList, tr[class*='Horse'], table.Shutuba_Table tr, table.ShutubaTable tr, table tr")
    runners, seen_horses = [], set()

    for row in rows:
        a = row.select_one('a[href*="/horse/"], a[href*="horse"]')
        if not a:
            continue
        h_name = text_of(a)
        if not h_name or "馬名" in h_name or h_name in seen_horses:
            continue

        cells = row.find_all(["td", "th"], recursive=False)
        no_text = text_of(row.select_one("td.Umaban, .Umaban, [class*='Umaban']"))
        no_val = number(no_text) or (number(text_of(cells[1])) if len(cells) >= 2 else None)
        if not no_val:
            continue

        h_no = int(no_val)
        seen_horses.add(h_name)

        frame_val = number(text_of(row.select_one("td.Waku, .Waku, [class*='Waku']")))
        odds = number(text_of(row.select_one("td.Odds, .Odds, [class*='Odds']")))
        pop = number(text_of(row.select_one("td.Popular_Ninki, .Popular_Ninki, [class*='Ninki']")))
        jockey = text_of(row.select_one(".Jockey, td.Jockey, [class*='Jockey']"))
        w_text = text_of(row.select_one("td.Horse_Weight, [class*='Weight']"))
        m_w = re.search(r"(\d{3})\s*\(([+-]?\d+)\)?", w_text)
        w_diff = int(m_w.group(2)) if m_w and m_w.group(2) else 0

        is_inner = frame_val in (1, 2) if frame_val else False
        is_apprentice = any(s in jockey for s in ["▲", "△", "☆", "◇", "★"])

        reasons = []
        caution = "展開次第で浮上"
        if is_inner and is_apprentice:
            reasons.append("内枠＋減量騎手（単騎逃げ注意）")
            caution = "前走惨敗からの減量逃げ残り警戒"
        if abs(w_diff) >= 10:
            reasons.append(f"馬体重変化({w_diff:+d}kg)")

        runners.append({
            "horse_no": h_no,
            "number": h_no,
            "frame_no": int(frame_val) if frame_val else None,
            "horse": h_name,
            "name": h_name,
            "jockey": jockey or "未定",
            "odds": odds,
            "popularity": int(pop) if pop else None,
            "score": 0.0,
            "reasons": reasons,
            "caution": caution,
        })

    runners.sort(key=lambda x: x["horse_no"])
    horse_dict = {h["horse_no"]: h["name"] for h in runners}

    for h in runners:
        o, p = h.get("odds"), h.get("popularity")
        s = 0.0
        if o and o > 0:
            s += (100 - min(70, 18 * math.log(max(1, o)))) * 0.7
        if p:
            s += max(0, 35 - (p - 1) * 2.5) * 0.3
        h["score"] = round(s, 2)

    ranked = sorted(runners, key=lambda x: -x["score"])
    top5 = ranked[:5]
    outsiders = [h for h in runners if h.get("odds") and 10.0 <= h["odds"] < 30.0][:3]
    longshots = [h for h in runners if h.get("odds") and h["odds"] >= 30.0][:2]

    top_odds = top5[0].get("odds") or 0 if top5 else 0
    is_pattern_b = (len(outsiders) > 0) or (top_odds >= 3.5)
    
    tickets = []
    if len(top5) >= 3:
        b1, b2, b3 = top5[0]["horse_no"], top5[1]["horse_no"], top5[2]["horse_no"]
        b1_name, b2_name, b3_name = horse_dict.get(b1, ""), horse_dict.get(b2, ""), horse_dict.get(b3, "")
        
        if is_pattern_b and outsiders:
            h1 = outsiders[0]["horse_no"]
            h1_name = horse_dict.get(h1, "")
            tickets.append({
                "pattern": "パターンB（波乱狙い・穴馬警戒）",
                "cost_yen": 2000,
                "lines": [
                    f"単勝: {b1}.{b1_name} (300円)",
                    f"馬連: {b1} - {b2}, {b3}, {h1}.{h1_name} (各200円 / 計600円)",
                    f"3連複: {b1} - {b2},{b3} - {b2},{b3},{h1} (各100円 / 計500円)",
                    f"★穴仕込み 3連単: 1着:{b1} → 2着:{h1}.{h1_name} → 3着:{b2},{b3} (各100円 / 計600円)"
                ],
                "note": "本命軸を死守しつつ、穴馬を絡めたマルチ券種で高配当を狙う2,000円構成"
            })
        else:
            h_sub = top5[3]["horse_no"] if len(top5) >= 4 else b3
            h_sub_name = horse_dict.get(h_sub, "")
            tickets.append({
                "pattern": "パターンA（堅調・本命重視）",
                "cost_yen": 2000,
                "lines": [
                    f"単勝: {b1}.{b1_name} (500円)",
                    f"馬連: {b1} - {b2}, {b3} (各300円 / 計600円)",
                    f"3連複: {b1} - {b2} - {b3} (600円)",
                    f"★穴仕込み ワイド: {h_sub}.{h_sub_name} - {b1}, {b2} (各100円 / 計300円)"
                ],
                "note": "単勝・馬連で手堅く回収を重ね、伏兵のワイドでプラスαを狙う2,000円構成"
            })

    is_finished = False
    if post_time:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", post_time)
        if m:
            sch = NOW.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            is_finished = (NOW >= sch + timedelta(minutes=15))

    result_finishes = []
    win_hit = None
    if is_finished:
        result_finishes = fetch_race_results(base_url, rid)
        if result_finishes and top5:
            win_hit = (top5[0]["horse_no"] == result_finishes[0])

    return {
        "id": rid,
        "kind": kind,
        "category": "local" if kind == "地方" else "central",
        "race_no": race_no,
        "name": race_name,
        "course": venue or "競馬場未取得",
        "post_time": post_time or "未定",
        "surface": surface,
        "distance_m": distance,
        "runner_count": len(runners),
        "horses": runners,
        "top5": top5,
        "outsiders": outsiders,
        "longshots": longshots,
        "tickets": tickets,
        "is_finished": is_finished,
        "result_finishes": result_finishes,
        "win_hit": win_hit,
        "win_return": 2500 if win_hit else 0,
        "is_recommended": (race_no == 11 or len(outsiders) >= 2)
    }


def main():
    history = load_json(HISTORY, {"schema_version": 12, "snapshots": {}})
    snapshots = history.get("snapshots", {})

    today_races, tomorrow_races = [], []

    for date_str, target_list in [(TODAY, today_races), (TOMORROW, tomorrow_races)]:
        is_tomorrow = (date_str == TOMORROW)
        for source in SOURCES:
            list_html = get_html(source["list"] + date_str)
            race_ids = extract_race_ids(list_html)

            for rid in race_ids:
                url = f"{source['base']}/race/shutuba.html?race_id={rid}"
                html = get_html(url)
                if not html:
                    continue

                r_data = parse_race(html, rid, source["kind"], source["base"])
                if r_data["runner_count"] >= MIN_RUNNERS:
                    r_data["date"] = TODAY_ISO if not is_tomorrow else (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
                    r_data["is_tomorrow"] = is_tomorrow
                    target_list.append(r_data)

                    race_key = str(rid)
                    if race_key not in snapshots and not is_tomorrow:
                        snapshots[race_key] = {
                            "race_id": rid,
                            "date": TODAY_ISO,
                            "cost": 2000,
                            "is_finished": r_data["is_finished"],
                            "win_hit": r_data["win_hit"],
                            "win_return": r_data["win_return"]
                        }
                    elif race_key in snapshots and r_data["is_finished"]:
                        snapshots[race_key]["is_finished"] = True
                        snapshots[race_key]["win_hit"] = r_data["win_hit"]
                        snapshots[race_key]["win_return"] = r_data["win_return"]

                time.sleep(REQUEST_DELAY)

    settled = [s for s in snapshots.values() if s.get("is_finished") and s.get("win_hit") is not None]
    win_hits = sum(1 for s in settled if s.get("win_hit"))
    total_return = sum(s.get("win_return", 0) for s in settled if s.get("win_hit"))
    total_stake = sum(s.get("cost", 2000) for s in settled)
    profit = total_return - total_stake
    roi = (total_return / total_stake * 100) if total_stake > 0 else 0.0

    stats = {
        "races_settled": len(settled),
        "win_bets": len(settled),
        "win_hits": win_hits,
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
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
        "paper_betting": {"stats": stats, "history": []}
    }
    save_json(OUT, data)
    print(f"BAGEN Engine updated (Pattern A/B). Today: {len(today_races)}, Settled: {len(settled)}")


if __name__ == "__main__":
    main()
