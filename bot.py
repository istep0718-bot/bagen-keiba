
#!/usr/bin/env python3
# BAGEN KEIBA - race-data validation and pre-race prediction
# Free GitHub Actions only. No paid API. No real betting.

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

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

MAX_RACES = 48
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

VENUES = [
    "札幌", "函館", "福島", "新潟", "東京", "中山", "中京",
    "京都", "阪神", "小倉", "門別", "盛岡", "水沢", "浦和",
    "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田",
    "姫路", "高知", "佐賀", "帯広",
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
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=25,
    )
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
    if kind == "中央" and re.fullmatch(r"\d{12}", race_id):
        return JRA_CODES.get(race_id[4:6], "")
    return ""


def extract_race_ids(html):
    soup = soup_of(html)
    found = []
    seen = set()

    for anchor in soup.select('a[href*="race_id="]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{12})", href)
        if not match:
            continue

        race_id = match.group(1)
        if race_id in seen or race_number_from_id(race_id) is None:
            continue

        seen.add(race_id)
        found.append(race_id)

    return found[:MAX_RACES]


def extract_meta(html, race_id, kind):
    soup = soup_of(html)
    race_no = race_number_from_id(race_id)
    venue = venue_from_id(race_id, kind)

    meta_parts = []
    for selector in (
        ".RaceData01",
        ".RaceData02",
        ".RaceData",
        ".race_data",
        "[class*='RaceData']",
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
    )
    for pattern in patterns:
        match = re.search(pattern, meta_text)
        if match:
            post_time = match.group(1)
            break

    race_name = ""
    for selector in (
        ".RaceName",
        ".race_name",
        ".RaceName01",
        "[class*='RaceName']",
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
            f"{venue}{race_no}R（レース名未取得）"
            if venue and race_no
            else "レース名未取得"
        )

    surface = ""
    distance = None
    match = re.search(
        r"(芝|ダート|ダ)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m?",
        meta_text,
    )
    if match:
        surface = "ダート" if match.group(1) == "ダ" else match.group(1)
        distance = int(match.group(2))

    weather = ""
    match = re.search(
        r"(?:天候|天気)\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)",
        meta_text,
    )
    if match:
        weather = match.group(1)

    track_condition = ""
    match = re.search(
        r"馬場(?:状態)?\s*[:：]?\s*(稍重|不良|重|良)",
        meta_text,
    )
    if match:
        track_condition = match.group(1)

    return {
        "race_no": race_no,
        "course": venue,
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
        return [], ["出馬表専用テーブルが見つかりません"]

    rows = table.select("tr.HorseList")
    if not rows:
        rows = table.select("tbody tr")

    runners = []
    seen_numbers = set()
    seen_ids = set()

    for row in rows:
        anchor = row.select_one('a[href*="/horse/"]')
        if anchor is None:
            continue

        horse_name = text_of(anchor)
        if not horse_name:
            continue

        id_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = id_match.group(1) if id_match else ""

        cells = row.find_all("td", recursive=False)
        horse_no_text = first_text(
            row,
            ["td.Umaban", ".Umaban", "td[class*='Umaban']"],
        )

        horse_no_value = number(horse_no_text)
        if horse_no_value is None and len(cells) >= 2:
            horse_no_value = number(text_of(cells[1]))

        if horse_no_value is None:
            errors.append(f"{horse_name}: 馬番不明")
            continue

        horse_no = int(horse_no_value)
        if not 1 <= horse_no <= MAX_RUNNERS:
            errors.append(f"{horse_name}: 不正な馬番")
            continue
        if horse_no in seen_numbers:
            errors.append(f"馬番 {horse_no} が重複")
            continue
        if horse_id and horse_id in seen_ids:
            errors.append(f"馬ID {horse_id} が重複")
            continue

        seen_numbers.add(horse_no)
        if horse_id:
            seen_ids.add(horse_id)

        frame_value = number(
            first_text(row, ["td.Waku", ".Waku", "td[class*='Waku']"])
        )
        odds_text = first_text(
            row,
            [
                "td.Odds",
                ".Odds",
                "td[class~='Odds']",
                "[class*='Odds']",
            ],
        )
        popularity_text = first_text(
            row,
            [
                "td.Popular_Ninki",
                ".Popular_Ninki",
                "td[class*='Ninki']",
            ],
        )

        odds = number(odds_text)
        popularity = number(popularity_text)

        if odds is not None and not 0 < odds < 10000:
            odds = None
        if popularity is not None and not 1 <= popularity <= MAX_RUNNERS:
            popularity = None

        jockey = first_text(
            row,
            [".Jockey", "td.Jockey", "td[class*='Jockey']"],
        )
        trainer = first_text(
            row,
            [".Trainer", "td.Trainer", "td[class*='Trainer']"],
        )
        sex_age = first_text(
            row,
            [".Barei", "td.Barei", "td[class*='Barei']"],
        )
        weight_text = first_text(
            row,
            ["td.Horse_Weight", "td[class*='Horse_Weight']"],
        )
        weight_match = re.search(
            r"(?<!\d)(\d{3})(?:\s*\(([+-]?\d+)\))?",
            weight_text,
        )

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
            "body_weight_change": (
                int(weight_match.group(2))
                if weight_match and weight_match.group(2)
                else None
            ),
            "odds": odds,
            "popularity": int(popularity) if popularity is not None else None,
            "score": None,
            "prediction_rank": None,
            "predicted_rank": None,
            "prediction_status": "INSUFFICIENT_DATA",
            "reasons": [],
            "surface_fit": "適性データ未取得",
        })

    runners.sort(key=lambda item: item["horse_no"])

    if len(runners) < MIN_RUNNERS:
        errors.append(f"出走馬が少なすぎます: {len(runners)}頭")

    return runners, errors


def score_runners(runners):
    # オッズまたは人気が実際に取得できた場合のみ採点する。
    valid_odds = [
        horse["odds"]
        for horse in runners
        if horse.get("odds") is not None and horse["odds"] > 0
    ]
    inverse_sum = sum(1.0 / odds for odds in valid_odds)

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
        horse["reasons"] = reasons
        horse["prediction_status"] = (
            "RANKED_MARKET_DATA"
            if score is not None
            else "INSUFFICIENT_DATA"
        )

    ranked = sorted(
        runners,
        key=lambda horse: (
            horse["score"] is None,
            -(horse["score"] if horse["score"] is not None else -999),
            horse["horse_no"],
        ),
    )

    rank = 0
    for horse in ranked:
        if horse["score"] is None:
            horse["prediction_rank"] = None
            horse["predicted_rank"] = None
        else:
            rank += 1
            horse["prediction_rank"] = rank
            horse["predicted_rank"] = rank

    return ranked


def is_future_race(post_time):
    """発走時刻が確認でき、現在より後のレースだけTrue。"""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", post_time or "")
    if not match:
        return False

    hour, minute = int(match.group(1)), int(match.group(2))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return False

    scheduled = NOW.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return scheduled > NOW


def validate_race(race_id, meta, runners, errors):
    problems = list(errors)

    if not re.fullmatch(r"\d{12}", race_id):
        problems.append("レースIDが不正")
    if meta.get("race_no") != race_number_from_id(race_id):
        problems.append("レース番号とIDが不一致")
    if len(runners) < MIN_RUNNERS or len(runners) > MAX_RUNNERS:
        problems.append("出走頭数が不正")
    if not meta.get("course"):
        problems.append("競馬場を確認できない")
    if not meta.get("post_time"):
        problems.append("発走時刻を確認できない")

    numbers = [horse["horse_no"] for horse in runners]
    if len(numbers) != len(set(numbers)):
        problems.append("馬番が重複")

    fatal_terms = (
        "見つかりません",
        "不正",
        "重複",
        "不明",
        "少なすぎます",
        "確認できない",
        "不一致",
    )
    valid = (
        len(runners) >= MIN_RUNNERS
        and all(horse.get("horse") for horse in runners)
        and not any(
            term in problem
            for problem in problems
            for term in fatal_terms
        )
    )
    return valid, problems


def calculate_stats(snapshots):
    settled = [
        value for value in snapshots.values()
        if value.get("result_status") == "SETTLED"
    ]
    return {
        "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
        "races_settled": len(settled),
        "win_bets": 0,
        "win_hits": 0,
        "win_stake_yen": 0,
        "win_return_yen": 0,
        "place_bets": 0,
        "place_hits": 0,
        "place_stake_yen": 0,
        "place_return_yen": 0,
        "total_stake_yen": 0,
        "total_return_yen": 0,
        "profit_yen": 0,
        "roi_pct": 0.0,
        "virtual_balance_yen": INITIAL_BANKROLL_YEN,
        "win_hit_rate_pct": 0.0,
        "place_hit_rate_pct": 0.0,
        "payout_data_missing": len(settled),
        "note": "確定払戻を検証していないため、収支は未計上です。",
    }


def main():
    history = load_json(
        HISTORY,
        {"schema_version": 5, "snapshots": {}},
    )
    if not isinstance(history, dict):
        history = {"schema_version": 5, "snapshots": {}}
    if not isinstance(history.get("snapshots"), dict):
        history["snapshots"] = {}

    snapshots = history["snapshots"]
    races = []
    errors = []
    rejected = []
    attempted = 0

    for source in SOURCES:
        try:
            list_html = get(source["list"] + TODAY)
            race_ids = extract_race_ids(list_html)
        except Exception as exc:
            errors.append(
                f"{source['kind']}一覧取得失敗: "
                f"{type(exc).__name__}: {str(exc)[:150]}"
            )
            continue

        if not race_ids:
            errors.append(
                f"{source['kind']}一覧にレースIDがありません"
            )
            continue

        for race_id in race_ids:
            attempted += 1
            race_url = (
                f"{source['base']}/race/shutuba.html?race_id={race_id}"
            )

            try:
                html = get(race_url)
                meta, soup = extract_meta(html, race_id, source["kind"])
                runners, runner_errors = parse_runners(soup)

                # 発走前のレースだけを掲載する。
                if not is_future_race(meta.get("post_time", "")):
                    rejected.append({
                        "race_id": race_id,
                        "reason": ["発走済み、または発走時刻を確認できない"],
                        "source_url": race_url,
                    })
                    time.sleep(REQUEST_DELAY)
                    continue

                valid, problems = validate_race(
                    race_id, meta, runners, runner_errors
                )
                if not valid:
                    rejected.append({
                        "race_id": race_id,
                        "reason": problems,
                        "source_url": race_url,
                    })
                    errors.append(
                        f"{race_id}: 検証失敗のため公開対象外"
                    )
                    time.sleep(REQUEST_DELAY)
                    continue

                runners = score_runners(runners)
                ranked = sorted(
                    [
                        horse for horse in runners
                        if horse.get("prediction_rank") is not None
                    ],
                    key=lambda horse: horse["prediction_rank"],
                )
                top5 = ranked[:5]
                race_key = str(race_id)

                race = {
                    "id": race_id,
                    "race_id": race_id,
                    "kind": source["kind"],
                    "category": source["category"],
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
                    "prediction_valid": len(top5) > 0,
                    "validation_status": "BASIC_CHECKS_PASSED",
                    "prediction_method": (
                        "オッズ・人気の簡易市場スコア。"
                        "学習済みAIではありません。"
                    ),
                    "prediction_note": (
                        "オッズまたは人気が取得できた馬のみ順位を算出。"
                        "未取得の情報は推測していません。"
                    ),
                }

                # 初回スナップショットはその時点の馬IDも保存する。
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
                        "predicted_horse_no": (
                            first_pick["horse_no"] if first_pick else None
                        ),
                        "predicted_horse": (
                            first_pick["horse"] if first_pick else None
                        ),
                        "predicted_horse_id": (
                            first_pick["horse_id"] if first_pick else None
                        ),
                        "predicted_rankings": [
                            {
                                "horse_no": horse["horse_no"],
                                "horse": horse["horse"],
                                "horse_id": horse["horse_id"],
                                "rank": horse["prediction_rank"],
                                "score": horse["score"],
                                "odds_at_prediction": horse["odds"],
                                "popularity_at_prediction": horse["popularity"],
                            }
                            for horse in runners
                        ],
                        "result_status": "PENDING",
                        "predicted_finish_position": None,
                        "paper_bets": {
                            "win": {
                                "placed": False,
                                "horse_no": None,
                                "stake_yen": 0,
                                "hit": None,
                                "return_yen": None,
                            },
                            "place": {
                                "placed": False,
                                "horse_no": None,
                                "stake_yen": 0,
                                "hit": None,
                                "return_yen": None,
                            },
                        },
                        "settlement_note": (
                            "確定払戻を検証していないため、"
                            "仮想収支には計上していません。"
                        ),
                    }

                races.append(race)

            except Exception as exc:
                errors.append(
                    f"{race_id}: {type(exc).__name__}: {str(exc)[:150]}"
                )

            time.sleep(REQUEST_DELAY)

    races.sort(key=lambda race: (
        race.get("post_time") or "99:99",
        race.get("course") or "",
        race.get("race_no") or 99,
    ))

    stats = calculate_stats(snapshots)
    history.update({
        "schema_version": 5,
        "updated_at": NOW.isoformat(),
        "stats": stats,
        "snapshots": snapshots,
    })

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 5,
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": "OK" if races else "NO_DATA",
        "message": (
            "発走前のレースを表示しています。"
            if races else
            "現在、発走前と確認できたレースはありません。"
            "発走済みレースを予想一覧には表示していません。"
        ),
        "source_policy": (
            "非公式公開ページからの取得。無料サービスのみ。"
            "実際の馬券購入機能はありません。"
        ),
        "data_note": (
            "発走時刻を確認できないレースは予想対象外です。"
            "馬番・馬名を検証できないレースも公開しません。"
            "オッズ・人気の簡易スコアであり、"
            "学習済みAIの勝率ではありません。"
            "確定払戻を検証していない収支は計上しません。"
        ),
        "race_count": len(races),
        "attempted_race_count": attempted,
        "rejected_race_count": len(rejected),
        "rejected_races": rejected[-50:],
        "races": races,
        "errors": errors[-80:],
        "history_count": len(snapshots),
        "paper_betting": {
            "unit_yen": BET_YEN,
            "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
            "types": [],
            "real_money": False,
            "stats": stats,
            "history": [
                snapshot for snapshot in snapshots.values()
                if snapshot.get("result_status") == "SETTLED"
            ][-100:],
        },
    }

    save_json(HISTORY, history)
    save_json(OUT, data)

    print(
        f"BAGEN update: date={TODAY_ISO} "
        f"races={len(races)} attempted={attempted} "
        f"rejected={len(rejected)} snapshots={len(snapshots)} "
        f"errors={len(errors)}"
    )
    print(f"Generated: {OUT}")
    print(f"Status: {data['status']}")

    for race in races:
        print(
            f"RACE {race['course']} {race['race_no']}R "
            f"{race['post_time']} runners={race['runner_count']} "
            f"ranked={len(race['top5'])}"
        )

    for item in rejected[-10:]:
        print(
            "REJECTED:",
            item["race_id"],
            "|",
            " / ".join(item["reason"][:4]),
        )

    for error in errors[-15:]:
        print("WARNING:", error)

    if not races:
        print("INFO: No confirmed upcoming races were published.")


if __name__ == "__main__":
    main()
