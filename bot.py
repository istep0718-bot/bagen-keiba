#!/usr/bin/env python3
# BAGEN KEIBA - race-data validation, prediction, ticket recommendation, and automated settlement
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
    for selector in (".RaceName", ".race_name", "h1"):
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


def parse_runners(soup):
    table = soup.select_one("table.Shutuba_Table, table.ShutubaTable, table[class*='Shutuba']")
    if not table:
        return [], ["出馬表テーブル未検出"]

    runners = []
    for row in table.select("tr.HorseList, tr[class*='Horse'], tbody tr"):
        anchor = row.select_one('a[href*="/horse/"], a[href*="horse"]')
        if not anchor:
            continue

        horse_name = text_of(anchor)
        cells = row.find_all("td", recursive=False)
        horse_no_text = text_of(row.select_one("td.Umaban, .Umaban"))
        horse_no_val = number(horse_no_text) or (number(text_of(cells[1])) if len(cells) >= 2 else None)

        if not horse_no_val:
            continue

        horse_no = int(horse_no_val)
        frame_val = number(text_of(row.select_one("td.Waku, .Waku")))
        odds = number(text_of(row.select_one("td.Odds, .Odds, [class*='Odds']")))
        popularity = number(text_of(row.select_one("td.Popular_Ninki, .Popular_Ninki, [class*='Ninki']")))
        jockey = text_of(row.select_one(".Jockey, td.Jockey"))
        weight_text = text_of(row.select_one("td.Horse_Weight"))
        weight_match = re.search(r"(\d{3})\s*\(([+-]?\d+)\)?", weight_text)

        # 穴馬フラグ判定（内枠＋減量騎手、大幅馬体重変化）
        is_inner = frame_val in (1, 2) if frame_val else False
        is_apprentice = any(symbol in jockey for symbol in ["▲", "△", "☆", "◇", "★"])
        weight_diff = int(weight_match.group(2)) if weight_match and weight_match.group(2) else 0

        reasons = []
        caution = "コース適性・展開の助けが必要"
        if is_inner and is_apprentice:
            reasons.append("内枠＋減量騎手配置（一気にハナを主張した場合の逃げ残り警戒）")
            caution = "前走大敗でも軽量活かした逃げの手で展開一変の可能性あり"
        if abs(weight_diff) >= 10:
            reasons.append(f"馬体重大幅変化({weight_diff:+d}kg・休み明け/成長)")

        runners.append({
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": int(frame_val) if frame_val else None,
            "horse": horse_name,
            "name": horse_name,
            "jockey": jockey,
            "odds": odds,
            "popularity": int(popularity) if popularity else None,
            "score": None,
            "reasons": reasons,
            "caution": caution,
        })

    runners.sort(key=lambda x: x["horse_no"])
    return runners, []


def score_and_recommend(runners):
    valid_odds = [h["odds"] for h in runners if h.get("odds") and h["odds"] > 0]
    for h in runners:
        odds = h.get("odds")
        pop = h.get("popularity")
        score = None
        if odds:
            score = 100 - min(70, 18 * math.log(max(1, odds)))
            h["reasons"].append(f"単勝{odds:g}倍")
        if pop:
            m_score = max(0, 35 - (pop - 1) * 2.5)
            score = (score * 0.7 + m_score * 0.3) if score else m_score
            h["reasons"].append(f"{pop}番人気")
        h["score"] = round(score, 2) if score else None

    ranked = sorted([h for h in runners if h["score"] is not None], key=lambda x: -x["score"])
    for idx, h in enumerate(ranked, 1):
        h["prediction_rank"] = idx

    top5 = ranked[:5]
    outsiders = [h for h in runners if h.get("odds") and 10.0 <= h["odds"] < 30.0][:3]
    longshots = [h for h in runners if h.get("odds") and h["odds"] >= 30.0][:2]

    # 具体的な3連単フォーメーション買い目構築
    tickets = []
    if len(top5) >= 3:
        b1 = top5[0]["horse_no"]
        b2 = top5[1]["horse_no"]
        b3 = top5[2]["horse_no"]
        third_legs = list(set([h["horse_no"] for h in top5[1:]] + [h["horse_no"] for h in outsiders + longshots]))
        
        # 3連単 軸1頭フォーメーション
        points = len(third_legs) * 2 - (2 if b3 in third_legs else 0)
        tickets.append({
            "type": "3連単 フォーメーション",
            "first": [b1],
            "second": [b2, b3],
            "third": third_legs[:6],
            "points": max(4, points),
            "note": "本命軸から穴馬へのヒモ荒れ高配当狙い"
        })

    return runners, top5, outsiders, longshots, tickets


def fetch_and_settle_results(snapshots):
    """確定レースの払戻・着順を取得して仮想収支を計算"""
    for race_id, snap in snapshots.items():
        if snap.get("result_status") == "SETTLED":
            continue

        result_url = f"{snap.get('base_url', 'https://race.netkeiba.com')}/race/result.html?race_id={race_id}"
        try:
            html = get(result_url)
            soup = soup_of(html)

            # 着順・払戻金の解析 (簡易スクレイピング)
            pay_table = soup.select_one("table.Pay_Table, table.PayTable")
            if not pay_table:
                continue

            # 単勝払戻金の取得
            win_row = pay_table.select_one("tr.Tansho, tr[class*='Tansho']")
            if win_row:
                win_horse = number(text_of(win_row.select_one(".Result, td:nth-child(2)")))
                win_pay = number(text_of(win_row.select_one(".Pay, td:nth-child(3)")))

                pred_no = snap.get("predicted_horse_no")
                if pred_no and win_horse and win_pay:
                    hit = (int(pred_no) == int(win_horse))
                    snap["result_status"] = "SETTLED"
                    snap["win_hit"] = hit
                    snap["win_return_yen"] = int(win_pay) if hit else 0
                    snap["settled_at"] = NOW.isoformat()
        except Exception:
            continue


def main():
    history = load_json(HISTORY, {"schema_version": 7, "snapshots": {}})
    snapshots = history.get("snapshots", {})

    # 未確定スナップショットの払戻照合実行
    fetch_and_settle_results(snapshots)

    today_races, tomorrow_races = [], []
    errors = []

    # 当日および翌日のデータを取得
    for date_str, target_list in [(TODAY, today_races), (TOMORROW, tomorrow_races)]:
        is_tomorrow = (date_str == TOMORROW)
        for source in SOURCES:
            try:
                list_html = get(source["list"] + date_str)
                race_ids = extract_race_ids(list_html)
            except Exception as e:
                errors.append(f"{source['kind']}({date_str})取得失敗: {str(e)[:100]}")
                continue

            for race_id in race_ids[:20]:
                race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"
                try:
                    html = get(race_url)
                    meta, soup = extract_meta(html, race_id, source["kind"])
                    runners, _ = parse_runners(soup)

                    if len(runners) < MIN_RUNNERS:
                        continue

                    runners, top5, outsiders, longshots, tickets = score_and_recommend(runners)
                    race_key = str(race_id)

                    is_recommend = (meta["race_no"] == 11 or len(outsiders) >= 2)

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
                        "is_recommended": is_recommend,
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

    # 収支集計
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
        "tomorrow_races": [r for r in tomorrow_races if r["is_recommended"]], # 翌日おすすめ
        "paper_betting": {"stats": stats, "history": settled[-50:]}
    }
    save_json(OUT, data)
    print(f"Update done. Today races: {len(today_races)}, Tomorrow recommended: {len(data['tomorrow_races'])}")


if __name__ == "__main__":
    main()
