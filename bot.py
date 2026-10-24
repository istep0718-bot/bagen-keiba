
#!/usr/bin/env python3
"""BAGEN KEIBA — free, paper-only racing data and prediction engine."""
from __future__ import annotations

import json
import re
import time
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "data.json"
HISTORY = DOCS / "history.json"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y%m%d")

UNIT_YEN = 100
INITIAL_BANKROLL_YEN = 10_000
MAX_RACES_PER_SOURCE = 60
REQUEST_DELAY_SECONDS = 0.7

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

SOURCES = [
    {
        "kind": "中央",
        "category": "central",
        "base": "https://race.netkeiba.com",
        "list": (
            "https://race.netkeiba.com/top/"
            "race_list_sub.html?kaisai_date="
        ),
    },
    {
        "kind": "地方",
        "category": "local",
        "base": "https://nar.netkeiba.com",
        "list": (
            "https://nar.netkeiba.com/top/"
            "race_list_sub.html?kaisai_date="
        ),
    },
]

VENUES = [
    "札幌", "函館", "福島", "新潟", "東京", "中山",
    "中京", "京都", "阪神", "小倉", "門別", "盛岡",
    "水沢", "浦和", "船橋", "大井", "川崎", "金沢",
    "笠松", "名古屋", "園田", "姫路", "高知", "佐賀", "帯広",
]

JRA_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}

NAR_CODES = {
    "30": "門別", "35": "盛岡", "36": "水沢",
    "42": "浦和", "43": "船橋", "44": "大井",
    "45": "川崎", "46": "金沢", "47": "笠松",
    "48": "名古屋", "50": "園田", "51": "姫路",
    "54": "高知", "55": "佐賀", "65": "帯広",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value: Any) -> float | None:
    if value is None:
        return None

    text = clean(value).replace(",", "")
    if text in {"", "--", "-", "取消", "除外", "未発表", "発売前"}:
        return None

    match = re.search(r"\d+(?:\.\d+)?", text)
    try:
        return float(match.group()) if match else None
    except (ValueError, AttributeError):
        return None


def get(url: str) -> str:
    response = SESSION.get(url, timeout=(10, 25))
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def page_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def page_text(soup: BeautifulSoup) -> str:
    return clean(soup.get_text(" ", strip=True))


def first_text(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            element = node.select_one(selector)
        except Exception:
            element = None

        if element:
            value = clean(element.get_text(" ", strip=True))
            if value:
                return value

    return ""


def first_regex(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return clean(match.group(1))
    return ""


def venue_from_id(race_id: str, kind: str) -> str:
    if len(race_id) >= 10:
        mapping = JRA_CODES if kind == "中央" else NAR_CODES
        return mapping.get(race_id[8:10], "")
    return ""


def find_venue(text: str, title: str, race_id: str, kind: str) -> str:
    combined = f"{title} {text[:3500]}"
    found = [venue for venue in VENUES if venue in combined]

    if found:
        return max(found, key=len)

    return venue_from_id(race_id, kind)


def extract_race_ids(html: str) -> list[str]:
    soup = page_soup(html)
    found = []
    seen = set()

    for anchor in soup.select('a[href*="race_id="]'):
        match = re.search(r"race_id=(\d{10,12})", anchor.get("href", ""))
        if match:
            race_id = match.group(1)
            if race_id not in seen:
                seen.add(race_id)
                found.append(race_id)

    return found[:MAX_RACES_PER_SOURCE]


def extract_race_name(
    soup: BeautifulSoup,
    venue: str,
    race_no: int | None,
) -> str:
    for selector in [".RaceName", ".race_name", "h1", "h2", "title"]:
        for element in soup.select(selector):
            value = clean(element.get_text(" ", strip=True))
            value = re.sub(r"\s*\|.*$", "", value)
            value = re.sub(r"^\d{4}年\d+月\d+日\s*", "", value)

            if not value or len(value) < 2:
                continue
            if "netkeiba" in value.lower():
                continue
            if value in {"出馬表", "レース結果", "競馬データ", venue}:
                continue

            return value

    if venue and race_no:
        return f"{venue}{race_no}R（レース名未取得）"

    return "レース名未取得"


def extract_meta(
    html: str,
    race_id: str,
    kind: str,
) -> tuple[dict, BeautifulSoup]:
    soup = page_soup(html)
    text = page_text(soup)
    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""

    race_no_match = re.search(r"(\d{2})$", race_id)
    race_no = int(race_no_match.group(1)) if race_no_match else None
    venue = find_venue(text, title, race_id, kind)

    data_line = " ".join([
        first_text(soup, [
            ".RaceData01", ".race_data", ".RaceData",
            "[class*='RaceData']", "[class*='race_data']",
        ]),
        text[:6000],
    ])

    post_time = first_regex([
        r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",
        r"(\d{1,2}:\d{2})\s*発走",
    ], data_line)

    surface = first_regex([
        r"(芝|ダート|ダ)\s*(?:・|[-ー]|\s)*\d{3,4}\s*m?",
        r"(芝|ダート|ダ)\s*\d{3,4}",
    ], text[:8000])

    distance_match = re.search(
        r"(?:芝|ダート|ダ)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m?",
        text[:8000],
        re.I,
    )

    weather = first_regex([
        r"天候\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)",
        r"天気\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)",
    ], text[:9000])

    condition = first_regex([
        r"馬場状態\s*[:：]?\s*(稍重|不良|重|良)",
        r"馬場\s*[:：]?\s*(稍重|不良|重|良)",
    ], text[:9000])

    return {
        "race_name": extract_race_name(soup, venue, race_no),
        "course": venue,
        "race_no": race_no,
        "post_time": post_time,
        "surface": surface,
        "distance_m": (
            int(distance_match.group(1)) if distance_match else None
        ),
        "weather": weather,
        "track_condition": condition,
    }, soup


def row_value(row: Any, selectors: list[str]) -> str:
    return first_text(row, selectors)


def parse_runners(soup: BeautifulSoup) -> list[dict]:
    rows = []
    seen_rows = set()

    selectors = [
        "tr.HorseList",
        "tr[class*='HorseList']",
        "table.Shutuba_Table tr",
        "table.RaceTable01 tr",
        "table.RaceTable tr",
    ]

    for selector in selectors:
        for row in soup.select(selector):
            marker = id(row)
            if marker not in seen_rows:
                seen_rows.add(marker)
                rows.append(row)

    runners = []
    seen_horses = set()

    for row in rows:
        anchor = row.select_one('a[href*="/horse/"]')
        if not anchor:
            continue

        horse_name = clean(anchor.get_text(" ", strip=True))
        horse_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = horse_match.group(1) if horse_match else ""
        identity = horse_id or horse_name

        if not horse_name or identity in seen_horses:
            continue
        seen_horses.add(identity)

        horse_no = number(row_value(row, [
            ".Umaban", ".Horse_Num",
            "td[class*='Umaban']", "td[class*='Horse_Num']",
        ]))

        frame_no = number(row_value(row, [
            ".Waku", ".Wakuban", "td[class*='Waku']",
        ]))

        odds = number(row_value(row, [
            ".Odds", ".Popular_Odds", "td[class*='Odds']",
            "span[class*='Odds']", "[class*='odds']",
        ]))

        popularity = number(row_value(row, [
            ".Popular", "td[class*='Popular']", "[class*='popular']",
        ]))

        jockey = row_value(row, [
            ".Jockey", "td[class*='Jockey']", "a[href*='/jockey/']",
        ])

        trainer = row_value(row, [
            ".Trainer", "td[class*='Trainer']", "a[href*='/trainer/']",
        ])

        sex_age = row_value(row, [
            ".Barei", "td[class*='Barei']",
        ])

        weight_text = row_value(row, [
            "td[class*='Horse_Weight']", "td[class*='Weight']",
        ])

        weight_match = re.search(
            r"(\d{3})\s*(?:\(([+-]?\d+)\))?",
            weight_text,
        )

        runners.append({
            "horse_no": int(horse_no) if horse_no is not None else None,
            "frame_no": int(frame_no) if frame_no is not None else None,
            "horse": horse_name,
            "horse_id": horse_id,
            "jockey": jockey,
            "trainer": trainer,
            "sex_age": sex_age,
            "body_weight": (
                int(weight_match.group(1)) if weight_match else None
            ),
            "body_weight_change": (
                int(weight_match.group(2))
                if weight_match and weight_match.group(2)
                else None
            ),
            "odds": odds if odds and odds > 0 else None,
            "popularity": (
                int(popularity) if popularity and popularity > 0 else None
            ),
            "recent_form": [],
        })

    valid_odds = [
        horse["odds"] for horse in runners
        if horse.get("odds") and horse["odds"] > 0
    ]
    inverse_sum = sum(1 / odds for odds in valid_odds)

    for horse in runners:
        odds = horse.get("odds")
        popularity = horse.get("popularity")
        score = None
        reasons = []
        implied = None

        if odds and odds > 0:
            score = 100.0 - min(70.0, 18.0 * math.log(max(1.0, odds)))
            reasons.append(f"単勝オッズ {odds:g}倍")

        if popularity:
            popularity_score = max(0.0, 35.0 - (popularity - 1) * 2.5)
            score = (
                score * 0.7 + popularity_score * 0.3
                if score is not None else popularity_score
            )
            reasons.append(f"{popularity}番人気")

        if odds and inverse_sum:
            implied = round((1 / odds) / inverse_sum * 100, 2)

        horse["score"] = round(score, 2) if score is not None else None
        horse["market_implied_pct"] = implied
        horse["reasons"] = reasons or [
            "オッズ・人気未取得。根拠ある順位は算出不可"
        ]
        horse["prediction_status"] = (
            "RANKED_MARKET_DATA"
            if score is not None else "INSUFFICIENT_DATA"
        )

    ranked = sorted(
        runners,
        key=lambda horse: (
            horse["score"] is None,
            -(horse["score"] or 0),
            horse.get("odds") or float("inf"),
            horse.get("horse_no") or 999,
        ),
    )

    for index, horse in enumerate(ranked, start=1):
        # No fabricated ranking for horses without market evidence.
        horse["prediction_rank"] = (
            index if horse.get("score") is not None else None
        )
        horse["number"] = horse.get("horse_no")
        horse["name"] = horse.get("horse")
        horse["predicted_rank"] = horse["prediction_rank"]
        horse["weight"] = horse.get("body_weight")
        horse["surface_fit"] = "適性データ未取得"

    return ranked


def parse_positions(html: str, race: dict) -> dict[str, int]:
    soup = page_soup(html)
    positions = {}

    selectors = [
        "tr.HorseList", "tr[class*='HorseList']",
        "table.RaceTable01 tr", "table.Result_Table tr",
        "tr[class*='Result']",
    ]

    for selector in selectors:
        for row in soup.select(selector):
            anchor = row.select_one('a[href*="/horse/"]')
            if not anchor:
                continue

            position_text = row_value(row, [
                ".Rank", "td[class*='Rank']", "td[class*='Order']",
                "td[class*='着順']", ".着順",
            ])

            match = re.match(r"^\s*(\d{1,2})\s*$", position_text)
            if not match:
                continue

            position = int(match.group(1))
            if not 1 <= position <= 30:
                continue

            horse_match = re.search(
                r"/horse/(\d+)", anchor.get("href", "")
            )
            horse_id = horse_match.group(1) if horse_match else ""
            horse_name = clean(anchor.get_text(" ", strip=True))

            for horse in race.get("runners", []):
                same_id = horse_id and horse_id == horse.get("horse_id")
                same_name = (
                    not horse_id and horse_name
                    and horse_name == horse.get("horse")
                )

                if (same_id or same_name) and horse.get("horse_no") is not None:
                    positions[str(horse["horse_no"])] = position

    return positions


def make_snapshot(race: dict, runners: list[dict]) -> dict:
    pick = next(
        (horse for horse in runners if horse.get("prediction_rank") == 1),
        None,
    )

    can_bet = bool(
        pick
        and pick.get("horse_no") is not None
        and pick.get("odds") is not None
        and pick.get("prediction_rank") is not None
    )

    return {
        "race_id": str(race["id"]),
        "kind": race["kind"],
        "category": race["category"],
        "race_date": race["race_date"],
        "race_name": race["name"],
        "course": race["course"],
        "post_time": race["post_time"],
        "source_url": race["source_url"],
        "snapshot_at": NOW.isoformat(),
        "prediction_method": "市場オッズ・人気の簡易スコア。学習済みAIではありません",
        "prediction_valid": bool(pick and pick.get("score") is not None),
        "predicted_horse_no": pick.get("horse_no") if pick else None,
        "predicted_horse": pick.get("horse") if pick else None,
        "predicted_rankings": [
            {
                "horse_no": horse.get("horse_no"),
                "horse": horse.get("horse"),
                "rank": horse.get("prediction_rank"),
                "score": horse.get("score"),
                "odds_at_prediction": horse.get("odds"),
                "popularity_at_prediction": horse.get("popularity"),
            }
            for horse in runners
        ],
        "result_status": "PENDING",
        "predicted_finish_position": None,
        "paper_bets": {
            "win": {
                "placed": can_bet,
                "horse_no": pick.get("horse_no") if can_bet else None,
                "stake_yen": UNIT_YEN if can_bet else 0,
                "odds_at_prediction": pick.get("odds") if can_bet else None,
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
            "単勝は初回予想時オッズで仮想計算。"
            "複勝は公式払戻を確認できるまで集計しません。"
        ),
    }


def normalize_history(history: Any) -> dict:
    if not isinstance(history, dict):
        history = {}

    snapshots = history.get("snapshots")
    if not isinstance(snapshots, dict):
        snapshots = {}

    history["snapshots"] = {
        str(key): value
        for key, value in snapshots.items()
        if isinstance(value, dict)
    }
    history.setdefault("schema_version", 3)
    return history


def calculate_stats(snapshots: dict) -> dict:
    stats = {
        "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
        "races_settled": 0,
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
        "payout_data_missing": 0,
    }

    for snapshot in snapshots.values():
        if snapshot.get("result_status") != "SETTLED":
            continue

        stats["races_settled"] += 1

        for bet_type in ("win", "place"):
            bet = snapshot.get("paper_bets", {}).get(bet_type, {})

            if not bet.get("placed"):
                continue

            # Unknown payouts are excluded rather than treated as zero.
            if bet.get("return_yen") is None:
                stats["payout_data_missing"] += 1
                continue

            stats[bet_type + "_bets"] += 1
            stats[bet_type + "_stake_yen"] += int(
                bet.get("stake_yen") or 0
            )
            stats[bet_type + "_return_yen"] += int(
                bet.get("return_yen") or 0
            )

            if bet.get("hit") is True:
                stats[bet_type + "_hits"] += 1

    stats["total_stake_yen"] = (
        stats["win_stake_yen"] + stats["place_stake_yen"]
    )
    stats["total_return_yen"] = (
        stats["win_return_yen"] + stats["place_return_yen"]
    )
    stats["profit_yen"] = (
        stats["total_return_yen"] - stats["total_stake_yen"]
    )
    stats["virtual_balance_yen"] = (
        INITIAL_BANKROLL_YEN + stats["profit_yen"]
    )
    stats["roi_pct"] = (
        round(
            stats["total_return_yen"] / stats["total_stake_yen"] * 100,
            2,
        )
        if stats["total_stake_yen"] else 0.0
    )

    for bet_type in ("win", "place"):
        bets = stats[bet_type + "_bets"]
        hits = stats[bet_type + "_hits"]
        stats[bet_type + "_hit_rate_pct"] = (
            round(hits / bets * 100, 2) if bets else 0.0
        )

    return stats


def main() -> None:
    history = normalize_history(load_json(
        HISTORY, {"schema_version": 3, "snapshots": {}}
    ))
    snapshots = history["snapshots"]

    races = []
    errors = []
    attempted = 0

    for source in SOURCES:
        try:
            list_html = get(source["list"] + TODAY)
            race_ids = extract_race_ids(list_html)
        except Exception as exc:
            errors.append(
                f"{source['kind']}一覧取得失敗: "
                f"{type(exc).__name__}: {str(exc)[:180]}"
            )
            continue

        if not race_ids:
            errors.append(
                f"{source['kind']}: レースIDを取得できません。"
                "非開催日・アクセス制限・ページ変更の可能性"
            )

        for race_id in race_ids:
            attempted += 1
            race_url = (
                f"{source['base']}/race/shutuba.html?race_id={race_id}"
            )

            try:
                html = get(race_url)
                meta, soup = extract_meta(html, race_id, source["kind"])
                runners = parse_runners(soup)

                if not runners:
                    errors.append(
                        f"{race_id}: 出走馬0頭。"
                        "ページ構造またはアクセス制限を確認"
                    )
                    time.sleep(REQUEST_DELAY_SECONDS)
                    continue

                race_name = meta["race_name"]
                race = {
                    "id": race_id,
                    "kind": source["kind"],
                    "category": source["category"],
                    "date": NOW.strftime("%Y-%m-%d"),
                    "race_date": NOW.strftime("%Y-%m-%d"),
                    "race_no": meta["race_no"],
                    "name": race_name,
                    "race_name": race_name,
                    "course": meta["course"],
                    "post_time": meta["post_time"],
                    "surface": meta["surface"],
                    "distance_m": meta["distance_m"],
                    "weather": meta["weather"],
                    "track_condition": meta["track_condition"],
                    "source_url": race_url,
                    "source_name": "netkeiba（非公式取得）",
                    "runner_count": len(runners),
                    "horses": runners,
                    "runners": runners,
                    "top5": [
                        horse for horse in runners
                        if horse.get("prediction_rank") is not None
                    ][:5],
                    "prediction_valid": any(
                        horse.get("score") is not None for horse in runners
                    ),
                    "prediction_note": (
                        "オッズ・人気に基づく簡易市場スコア。"
                        "取得不能時は順位を捏造しません"
                    ),
                }

                key = str(race_id)

                # Freeze first-seen predictions; keep latest data separate.
                if key not in snapshots:
                    snapshots[key] = make_snapshot(race, runners)

                snapshot = snapshots[key]
                snapshot["latest_seen_at"] = NOW.isoformat()
                snapshot["latest_odds"] = {
                    str(horse.get("horse_no")): horse.get("odds")
                    for horse in runners
                    if horse.get("horse_no") is not None
                }

                try:
                    result_url = (
                        f"{source['base']}/race/result.html?race_id={race_id}"
                    )
                    result_html = get(result_url)
                    positions = parse_positions(result_html, race)
                    pick_no = snapshot.get("predicted_horse_no")
                    finish = (
                        positions.get(str(pick_no))
                        if pick_no is not None else None
                    )

                    minimum_positions = max(
                        1, math.ceil(len(runners) / 3)
                    )

                    if (
                        finish is not None
                        and len(positions) >= minimum_positions
                    ):
                        snapshot["finish_positions"] = positions
                        snapshot["predicted_finish_position"] = finish
                        snapshot["result_status"] = "SETTLED"

                        win_bet = snapshot["paper_bets"]["win"]
                        if win_bet.get("placed"):
                            win_bet["hit"] = finish == 1
                            odds = win_bet.get("odds_at_prediction")

                            if finish == 1 and odds:
                                win_bet["return_yen"] = int(round(
                                    float(odds)
                                    * int(win_bet.get("stake_yen") or UNIT_YEN)
                                ))
                            else:
                                win_bet["return_yen"] = 0

                        place_bet = snapshot["paper_bets"]["place"]
                        place_bet.update({
                            "placed": False,
                            "stake_yen": 0,
                            "hit": None,
                            "return_yen": None,
                        })

                        snapshot["settlement_note"] = (
                            "単勝払戻は初回予想時オッズによる概算。"
                            "複勝は公式払戻未確認のため未集計。"
                        )

                except Exception as exc:
                    errors.append(
                        f"{race_id} 結果照合失敗: {type(exc).__name__}"
                    )

                races.append(race)

            except Exception as exc:
                errors.append(
                    f"{race_id}: {type(exc).__name__}: {str(exc)[:180]}"
                )

            time.sleep(REQUEST_DELAY_SECONDS)

    stats = calculate_stats(snapshots)
    history.update({
        "schema_version": 3,
        "updated_at": NOW.isoformat(),
        "stats": stats,
    })
    save_json(HISTORY, history)

    settled = [
        snapshot for snapshot in snapshots.values()
        if snapshot.get("result_status") == "SETTLED"
    ]

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 3,
        "generated_at": NOW.isoformat(),
        "race_date": NOW.strftime("%Y-%m-%d"),
        "status": "OK" if races else "NO_DATA",
        "source_policy": (
            "Unofficial public-page scraping; free services only; "
            "no real-money betting integration."
        ),
        "data_note": (
            "オッズ・人気を使った簡易市場スコアで、"
            "学習済みAI勝率ではありません。"
            "取得できない情報は推測で補いません。"
            "単勝払戻は初回予想時オッズによる概算。"
            "複勝公式払戻は未取得のため集計対象外です。"
        ),
        "race_count": len(races),
        "attempted_race_count": attempted,
        "races": sorted(
            races,
            key=lambda race: (
                0 if race["kind"] == "中央" else 1,
                race.get("post_time") or "99:99",
                race.get("race_no") or 99,
            ),
        ),
        "errors": errors[-30:],
        "history_count": len(snapshots),
        "paper_betting": {
            "unit_yen": UNIT_YEN,
            "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
            "types": ["単勝（概算払戻）"],
            "real_money": False,
            "stats": stats,
            "history": settled[-100:],
        },
    }

    save_json(OUT, data)

    print(
        f"BAGEN update: races={len(races)} "
        f"attempted={attempted} snapshots={len(snapshots)} "
        f"errors={len(errors)}"
    )
    print(
        f"stats: settled={stats['races_settled']} "
        f"bets={stats['win_bets']} hits={stats['win_hits']} "
        f"profit={stats['profit_yen']} "
        f"balance={stats['virtual_balance_yen']}"
    )

    for error in errors[-10:]:
        print("WARNING:", error)

    if not races:
        print(
            "WARNING: No races parsed; check source access, "
            "date, and page structure."
        )


if __name__ == "__main__":
    main()
