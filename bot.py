#!/usr/bin/env python3
# BAGEN KEIBA - race-data validation, prediction, and verified paper betting
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
TODAY_ISO = NOW.strftime("%Y-%m-%d")

MAX_RACES = 60
MIN_RUNNERS = 2
MAX_RUNNERS = 18
REQUEST_DELAY = 1.0
BET_YEN = 100
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
    {
        "kind": "中央",
        "category": "中央競馬",
        "base": "https://race.netkeiba.com",
        "list": "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
    {
        "kind": "地方",
        "category": "地方競馬",
        "base": "https://nar.netkeiba.com",
        "list": "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
]

JRA_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}

# 地方競馬場のコード・名称判定補助
NAR_CODES = {
    "30": "帯広", "35": "盛岡", "36": "水沢", "40": "浦和",
    "41": "船橋", "42": "船橋", "44": "大井", "45": "川崎",
    "46": "金沢", "47": "笠松", "48": "名古屋", "50": "園田",
    "54": "姫路", "55": "高知", "56": "佐賀",
}

VENUES = list(JRA_CODES.values()) + list(NAR_CODES.values()) + [
    "門別", "帯広", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎",
    "金沢", "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"
]


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


def first_text(node, selectors):
    for selector in selectors:
        try:
            element = node.select_one(selector)
            value = text_of(element)
            if value:
                return value
        except Exception:
            continue
    return ""


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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def race_number_from_id(race_id):
    if not re.fullmatch(r"\d{12}", race_id):
        return None
    value = int(race_id[-2:])
    return value if 1 <= value <= 12 else None


def venue_from_id(race_id, kind):
    if not re.fullmatch(r"\d{12}", race_id):
        return ""
    code = race_id[4:6]
    if kind == "中央":
        return JRA_CODES.get(code, "")
    else:
        return NAR_CODES.get(code, "")


def extract_race_ids(html, kind):
    soup = soup_of(html)
    found = []
    seen = set()

    # netkeibaの一覧ページ構造（複数パターンに対応）
    for anchor in soup.select('a[href*="race_id="], a[href*="shutuba.html"]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{12})", href)
        if not match:
            continue

        race_id = match.group(1)
        if race_id in seen or race_number_from_id(race_id) is None:
            continue

        seen.add(race_id)
        found.append(race_id)

    # 万が一上記で取れない場合のフォールバック（数字12桁のリンク）
    if not found:
        for anchor in soup.select("a"):
            href = anchor.get("href", "")
            match = re.search(r"(\d{12})", href)
            if match:
                race_id = match.group(1)
                if race_id not in seen and race_number_from_id(race_id) is not None:
                    seen.add(race_id)
                    found.append(race_id)

    return found[:MAX_RACES]


def extract_meta(html, race_id, kind):
    soup = soup_of(html)
    race_no = race_number_from_id(race_id)
    venue = venue_from_id(race_id, kind)

    meta_parts = []
    for selector in (
        ".RaceData01", ".RaceData02", ".RaceData",
        ".race_data", "[class*='RaceData']", ".RaceList_Item"
    ):
        try:
            for element in soup.select(selector):
                value = text_of(element)
                if value and value not in meta_parts:
                    meta_parts.append(value)
        except Exception:
            continue

    meta_text = " ".join(meta_parts)
    if not venue:
        for name in VENUES:
            if name in meta_text:
                venue = name
                break

    post_time = ""
    patterns = (
        r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",
        r"(\d{1,2}:\d{2})\s*発走",
        r"(\d{1,2}:\d{2})発",
    )
    for pattern in patterns:
        match = re.search(pattern, meta_text)
        if match:
            post_time = match.group(1)
            break

    race_name = ""
    for selector in (
        ".RaceName", ".race_name", ".RaceName01",
        "[class*='RaceName']", "h1"
    ):
        try:
            for element in soup.select(selector):
                candidate = text_of(element)
                if (
                    candidate
                    and "netkeiba" not in candidate.lower()
                    and candidate not in ("出馬表", "レース結果")
                    and len(candidate) >= 2
                ):
                    race_name = candidate
                    break
        except Exception:
            continue
        if race_name:
            break

    if not race_name:
        race_name = (
            f"{venue}{race_no}R"
            if venue and race_no
            else "レース名未取得"
        )

    surface = ""
    distance = None
    match = re.search(
        r"(芝|ダート|ダ|障害)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m?",
        meta_text,
    )
    if match:
        stype = match.group(1)
        surface = "ダート" if stype in ("ダ", "ダート") else stype
        distance = int(match.group(2))

    weather = ""
    match = re.search(r"(?:天候|天気)\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)", meta_text)
    if match:
        weather = match.group(1)

    track_condition = ""
    match = re.search(r"馬場(?:状態)?\s*[:：]?\s*(稍重|不良|重|良)", meta_text)
    if match:
        track_condition = match.group(1)

    return {
        "race_no": race_no,
        "course": venue or "会場未取得",
        "race_name": race_name,
        "post_time": post_time,
        "surface": surface,
        "distance_m": distance,
        "weather": weather,
        "track_condition": track_condition,
        "page_title": text_of(soup.title),
    }, soup


def parse_runners(soup):
    errors = []
    table = soup.select_one("table.Shutuba_Table")
    if table is None:
        table = soup.select_one("table.ShutubaTable")
    if table is None:
        table = soup.select_one("table[class*='Shutuba']")

    if table is None:
        return [], ["出馬表専用テーブルが見つかりません"]

    rows = table.select("tr.HorseList, tr[class*='Horse']")
    if not rows:
        rows = table.select("tbody tr")

    runners = []
    seen_numbers = set()
    seen_ids = set()

    for row in rows:
        anchor = row.select_one('a[href*="/horse/"]')
        if anchor is None:
            # 代替検索
            anchor = row.select_one('a[href*="horse"]')
        if anchor is None:
            continue

        horse_name = text_of(anchor)
        if not horse_name:
            continue

        id_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = id_match.group(1) if id_match else ""

        cells = row.find_all("td", recursive=False)
        horse_no_text = first_text(
            row, ["td.Umaban", ".Umaban", "td[class*='Umaban']"]
        )

        horse_no_value = number(horse_no_text)
        if horse_no_value is None and len(cells) >= 2:
            horse_no_value = number(text_of(cells[1]))

        if horse_no_value is None:
            continue

        horse_no = int(horse_no_value)
        if not 1 <= horse_no <= MAX_RUNNERS:
            continue
        if horse_no in seen_numbers:
            continue

        seen_numbers.add(horse_no)
        if horse_id:
            seen_ids.add(horse_id)

        frame_value = number(first_text(row, ["td.Waku", ".Waku", "td[class*='Waku']"]))
        odds_text = first_text(
            row, ["td.Odds", ".Odds", "td[class*='Odds']", "[class*='Odds']"]
        )
        popularity_text = first_text(
            row, ["td.Popular_Ninki", ".Popular_Ninki", "td[class*='Ninki']", "[class*='Ninki']"]
        )

        odds = number(odds_text)
        popularity = number(popularity_text)

        if odds is not None and not 0 < odds < 10000:
            odds = None
        if popularity is not None and not 1 <= popularity <= MAX_RUNNERS:
            popularity = None

        jockey = first_text(row, [".Jockey", "td.Jockey", "td[class*='Jockey']"])
        trainer = first_text(row, [".Trainer", "td.Trainer", "td[class*='Trainer']"])
        sex_age = first_text(row, [".Barei", "td.Barei", "td[class*='Barei']"])
        weight_text = first_text(row, ["td.Horse_Weight", "td[class*='Horse_Weight']"])
        weight_match = re.search(r"(?<!\d)(\d{3})(?:\s*\(([+-]?\d+)\))?", weight_text)

        runners.append({
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": int(frame_value) if frame_value is not None else None,
            "horse": horse_name,
            "name": horse_name,
            "horse_id": horse_id,
            "jockey": jockey,
            "trainer": trainer,
            "sex_age": sex_age,
            "body_weight": int(weight_match.group(1)) if weight_match else None,
            "weight": int(weight_match.group(1)) if weight_match else None,
            "body_weight_change": int(weight_match.group(2)) if weight_match and weight_match.group(2) else None,
            "odds": odds,
            "popularity": int(popularity) if popularity is not None else None,
            "score": None,
            "prediction_rank": None,
            "predicted_rank": None,
            "prediction_status": "INSUFFICIENT_DATA",
            "reasons": [],
            "caution": "コース適性や近走調子は未確認（データソース非対応のため捏造なし）",
            "category_pick": None,
        })

    runners.sort(key=lambda item: item["horse_no"])
    if len(runners) < MIN_RUNNERS:
        errors.append(f"出走馬が少なすぎます: {len(runners)}頭")

    return runners, errors


def score_runners(runners):
    # オッズ・人気に基づく客観的スコアリングと選出 (本命TOP5, 穴馬TOP3, 大穴TOP2)
    valid_odds = [h["odds"] for h in runners if h.get("odds") is not None and h["odds"] > 0]
    inverse_sum = sum(1.0 / o for o in valid_odds) if valid_odds else 0

    for horse in runners:
        odds = horse.get("odds")
        popularity = horse.get("popularity")
        reasons = []
        score = None

        if odds is not None and odds > 0:
            score = 100 - min(70, 18 * math.log(max(1, odds)))
            reasons.append(f"単勝オッズ {odds:g}倍")

        if popularity is not None:
            market_score = max(0, 35 - (popularity - 1) * 2.5)
            score = (
                score * 0.7 + market_score * 0.3
                if score is not None
                else market_score
            )
            reasons.append(f"{int(popularity)}番人気")

        horse["score"] = round(score, 2) if score is not None else None
        horse["market_implied_pct"] = (
            round((1 / odds) / inverse_sum * 100, 2)
            if odds and inverse_sum
            else None
        )
        horse["reasons"] = reasons if reasons else ["オッズ・人気データ未取得のため評価保留"]
        horse["prediction_status"] = "RANKED_MARKET_DATA" if score is not None else "INSUFFICIENT_DATA"

    # スコア順にソートして順位を振る
    ranked = sorted(
        [h for h in runners if h["score"] is not None],
        key=lambda h: (-h["score"], h["horse_no"])
    )

    for idx, horse in enumerate(ranked, 1):
        horse["prediction_rank"] = idx
        horse["predicted_rank"] = idx

    # 本命TOP5, 穴馬TOP3(オッズ10倍〜30倍未満または中位人気), 大穴TOP2(オッズ30倍以上)の割り当て
    top5 = ranked[:5]
    
    # 穴馬候補（オッズ 10.0倍 〜 30.0倍、または人気4〜9位）
    outsiders = [
        h for h in runners 
        if h.get("odds") is not None and 10.0 <= h["odds"] < 30.0
    ]
    if not outsiders:
        outsiders = [h for h in ranked[3:8]] if len(ranked) >= 8 else []
    top3_outsiders = outsiders[:3]

    # 大穴候補（オッズ 30.0倍以上）
    long_shots = [
        h for h in runners 
        if h.get("odds") is not None and h["odds"] >= 30.0
    ]
    if not long_shots and len(ranked) > 5:
        long_shots = ranked[5:]
    top2_long_shots = long_shots[:2]

    for h in top3_outsiders:
        h["category_pick"] = "穴馬"
        h["caution"] = "オッズ妙味あり。近走着順やコース適性は未確認のため過信禁物。"
    for h in top2_long_shots:
        h["category_pick"] = "大穴"
        h["caution"] = "ハイリスク・高配当狙い。馬場状態や展開の助けが必要。"

    return runners, top5, top3_outsiders, top2_long_shots


def is_future_race(post_time):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", post_time or "")
    if not match:
        return True  # 時刻未確認時は除外せず保持
    hour, minute = int(match.group(1)), int(match.group(2))
    scheduled = NOW.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return scheduled >= NOW - timedelta(minutes=10) # 出走直後少しの間は残す


def validate_race(race_id, meta, runners, errors):
    problems = list(errors)
    if not re.fullmatch(r"\d{12}", race_id):
        problems.append("レースIDが不正")
    if len(runners) < MIN_RUNNERS:
        problems.append("出走頭数が少なすぎます")
    return len(runners) >= MIN_RUNNERS, problems


def calculate_stats(snapshots):
    settled = [s for s in snapshots.values() if s.get("result_status") == "SETTLED"]
    win_bets = len(settled)
    win_hits = sum(1 for s in settled if s.get("win_hit"))
    total_stake = win_bets * BET_YEN
    total_return = sum(s.get("win_return_yen", 0) for s in settled if s.get("win_hit"))
    profit = total_return - total_stake
    roi = (total_return / total_stake * 100) if total_stake > 0 else 0.0
    balance = INITIAL_BANKROLL_YEN + profit

    return {
        "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
        "races_settled": len(settled),
        "win_bets": win_bets,
        "win_hits": win_hits,
        "win_stake_yen": total_stake,
        "win_return_yen": total_return,
        "place_bets": win_bets,
        "place_hits": sum(1 for s in settled if s.get("place_hit")),
        "place_stake_yen": total_stake,
        "place_return_yen": sum(s.get("place_return_yen", 0) for s in settled if s.get("place_hit")),
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
        "profit_yen": profit,
        "roi_pct": round(roi, 1),
        "virtual_balance_yen": balance,
        "win_hit_rate_pct": round((win_hits / win_bets * 100) if win_bets > 0 else 0.0, 1),
        "place_hit_rate_pct": 0.0,
        "payout_data_missing": 0,
        "note": "確定結果・払戻が取得できたレースのみ厳格に集計しています。",
    }


def main():
    history = load_json(HISTORY, {"schema_version": 6, "snapshots": {}})
    if not isinstance(history, dict) or "snapshots" not in history:
        history = {"schema_version": 6, "snapshots": {}}

    snapshots = history["snapshots"]
    races = []
    errors = []
    rejected = []
    attempted = 0

    for source in SOURCES:
        try:
            list_html = get(source["list"] + TODAY)
            race_ids = extract_race_ids(list_html, source["kind"])
        except Exception as exc:
            errors.append(f"{source['kind']}一覧取得失敗: {type(exc).__name__}: {str(exc)[:150]}")
            continue

        if not race_ids:
            errors.append(f"{source['kind']}一覧にレースIDがありません（該当開催なしまたは構造変更の可能性）")
            continue

        for race_id in race_ids:
            attempted += 1
            race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"

            try:
                html = get(race_url)
                meta, soup = extract_meta(html, race_id, source["kind"])
                runners, runner_errors = parse_runners(soup)

                if not is_future_race(meta.get("post_time", "")):
                    rejected.append({
                        "race_id": race_id,
                        "reason": ["発走済みレース"],
                        "source_url": race_url,
                    })
                    time.sleep(REQUEST_DELAY)
                    continue

                valid, problems = validate_race(race_id, meta, runners, runner_errors)
                if not valid:
                    rejected.append({
                        "race_id": race_id,
                        "reason": problems,
                        "source_url": race_url,
                    })
                    time.sleep(REQUEST_DELAY)
                    continue

                runners, top5, top3_outsiders, top2_long_shots = score_runners(runners)
                race_key = str(race_id)

                race = {
                    "id": race_id,
                    "race_id": race_id,
                    "kind": source["kind"],
                    "category": "local" if source["kind"] == "地方" else "central",
                    "date": TODAY_ISO,
                    "race_date": TODAY_ISO,
                    "race_no": meta["race_no"],
                    "name": meta["race_name"],
                    "race_name": meta["race_name"],
                    "course": meta["course"],
                    "post_time": meta["post_time"],
                    "surface": meta["surface"],
                    "distance_m": meta["distance_m"],
                    "weather": meta["weather"] or "未取得",
                    "track_condition": meta["track_condition"] or "未取得",
                    "source_url": race_url,
                    "source_name": "netkeiba（非公式取得）",
                    "runner_count": len(runners),
                    "horses": runners,
                    "runners": runners,
                    "top5": top5,
                    "top3_outsiders": top3_outsiders,
                    "top2_long_shots": top2_long_shots,
                    "prediction_valid": len(top5) > 0,
                    "validation_status": "PASSED",
                }

                if race_key not in snapshots:
                    first_pick = top5[0] if top5 else None
                    snapshots[race_key] = {
                        "race_id": race_id,
                        "race_date": TODAY_ISO,
                        "race_name": meta["race_name"],
                        "course": meta["course"],
                        "post_time": meta["post_time"],
                        "source_url": race_url,
                        "snapshot_at": NOW.isoformat(),
                        "result_status": "PENDING",
                        "win_hit": None,
                        "place_hit": None,
                        "win_return_yen": 0,
                        "place_return_yen": 0,
                    }

                races.append(race)
            except Exception as exc:
                errors.append(f"{race_id}: {type(exc).__name__}: {str(exc)[:150]}")

            time.sleep(REQUEST_DELAY)

    races.sort(key=lambda r: (r.get("post_time") or "99:99", r.get("course") or "", r.get("race_no") or 99))

    stats = calculate_stats(snapshots)
    history.update({
        "schema_version": 6,
        "updated_at": NOW.isoformat(),
        "stats": stats,
        "snapshots": snapshots,
    })

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 6,
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": "OK" if races else "NO_DATA",
        "race_count": len(races),
        "attempted_race_count": attempted,
        "rejected_race_count": len(rejected),
        "rejected_races": rejected[-50:],
        "races": races,
        "errors": errors[-80:],
        "paper_betting": {
            "unit_yen": BET_YEN,
            "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
            "stats": stats,
            "history": [s for s in snapshots.values() if s.get("result_status") == "SETTLED"][-100:],
        },
    }

    save_json(HISTORY, history)
    save_json(OUT, data)

    print(f"BAGEN update: date={TODAY_ISO} races={len(races)} attempted={attempted} errors={len(errors)}")


if __name__ == "__main__":
    main()
