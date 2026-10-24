
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BAGEN KEIBA — strict paper-only race data engine.
Free services only. No real-money betting.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

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

UNIT_YEN = 100
INITIAL_BANKROLL_YEN = 10_000
REQUEST_DELAY_SECONDS = 0.8
MAX_RACES_PER_SOURCE = 80
MIN_RUNNERS = 2
MAX_RUNNERS = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://race.netkeiba.com/",
}

SOURCES = [
    {
        "kind": "中央",
        "category": "central",
        "base": "https://race.netkeiba.com",
        "list": "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
    {
        "kind": "地方",
        "category": "local",
        "base": "https://nar.netkeiba.com",
        "list": "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
]

JRA_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}

# Netkeibaの地方競馬IDは中央競馬と同じ位置・体系と
# 仮定して誤判定しない。地方は出馬表の情報を優先する。
VENUES = [
    "札幌", "函館", "福島", "新潟", "東京", "中山",
    "中京", "京都", "阪神", "小倉", "門別", "盛岡",
    "水沢", "浦和", "船橋", "大井", "川崎", "金沢",
    "笠松", "名古屋", "園田", "姫路", "高知", "佐賀", "帯広",
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def to_number(value: Any) -> float | None:
    text = clean(value).replace(",", "")
    if not text or text in {
        "--", "-", "取消", "除外", "未発表", "発売前", "計不"
    }:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
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
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def text_of(node: Any) -> str:
    return clean(node.get_text(" ", strip=True)) if node else ""


def first_text(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        element = node.select_one(selector)
        value = text_of(element)
        if value:
            return value
    return ""


def first_regex(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return clean(match.group(1))
    return ""


def race_number_from_id(race_id: str) -> int | None:
    if not re.fullmatch(r"\d{12}", race_id):
        return None
    number = int(race_id[-2:])
    return number if 1 <= number <= 12 else None


def venue_from_id(race_id: str, kind: str) -> str:
    # 中央競馬のID形式: YYYY + 競馬場コード + 開催回 + 日目 + R番号
    # 競馬場コードは race_id[4:6]。以前の [8:10] は誤り。
    if kind == "中央" and re.fullmatch(r"\d{12}", race_id):
        return JRA_CODES.get(race_id[4:6], "")
    return ""


def extract_race_ids(html: str) -> list[str]:
    soup = soup_of(html)
    found: list[str] = []
    seen: set[str] = set()

    for anchor in soup.select('a[href*="race_id="]'):
        href = anchor.get("href", "")
        match = re.search(r"(?:\?|&)race_id=(\d{12})(?:&|$)", href)
        if not match:
            # hrefに別のパラメータが続く場合も拾う
            match = re.search(r"race_id=(\d{12})", href)

        if not match:
            continue

        race_id = match.group(1)
        if race_id not in seen and race_number_from_id(race_id):
            seen.add(race_id)
            found.append(race_id)

    return found[:MAX_RACES_PER_SOURCE]


def get_race_name(soup: BeautifulSoup, venue: str, race_no: int | None) -> str:
    for selector in [
        ".RaceName", ".race_name", ".RaceName01",
        "[class*='RaceName']", "h1",
    ]:
        for element in soup.select(selector):
            value = clean(element.get_text(" ", strip=True))
            value = re.sub(r"\s*\|.*$", "", value)
            if not value or len(value) < 2:
                continue
            if "netkeiba" in value.lower():
                continue
            if value in {"出馬表", "レース結果", "競馬データ"}:
                continue
            if re.fullmatch(r"\d{1,2}R", value):
                continue
            return value

    if venue and race_no:
        return f"{venue}{race_no}R（レース名未取得）"
    return "レース名未取得"


def extract_meta(html: str, race_id: str, kind: str) -> tuple[dict, BeautifulSoup]:
    soup = soup_of(html)
    full_text = clean(soup.get_text(" ", strip=True))
    race_no = race_number_from_id(race_id)

    # 中央はレースIDの正しい位置から判定。地方はページ情報を使う。
    venue = venue_from_id(race_id, kind)
    if not venue:
        candidates = []
        for selector in [
            ".RaceData01", ".RaceData02", ".RaceData",
            ".race_data", "[class*='RaceData']",
        ]:
            for element in soup.select(selector):
                value = text_of(element)
                for name in VENUES:
                    if name in value:
                        candidates.append(name)
        if candidates:
            venue = candidates[0]

    meta_text = " ".join(
        text_of(soup.select_one(selector))
        for selector in [
            ".RaceData01", ".RaceData02", ".RaceData",
            ".race_data", "[class*='RaceData']",
        ]
    )
    if not meta_text:
        meta_text = full_text[:5000]

    post_time = first_regex([
        r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",
        r"(\d{1,2}:\d{2})\s*発走",
    ], meta_text)

    surface = first_regex([
        r"(芝|ダート|ダ)\s*(?:・|[-ー]|\s)*\d{3,4}\s*m?",
    ], meta_text)
    distance = first_regex([
        r"(?:芝|ダート|ダ)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m?",
    ], meta_text)

    weather = first_regex([
        r"天候\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)",
        r"天気\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)",
    ], meta_text)

    condition = first_regex([
        r"馬場状態\s*[:：]?\s*(稍重|不良|重|良)",
        r"馬場\s*[:：]?\s*(稍重|不良|重|良)",
    ], meta_text)

    title = text_of(soup.title)
    race_name = get_race_name(soup, venue, race_no)

    # レースID、レース番号、ページ内容が明らかに矛盾する場合は
    # 後段の検証で除外できるよう情報を保持する。
    return {
        "race_name": race_name,
        "course": venue,
        "race_no": race_no,
        "post_time": post_time,
        "surface": surface,
        "distance_m": int(distance) if distance else None,
        "weather": weather,
        "track_condition": condition,
        "page_title": title,
    }, soup


def cell_text(row: Any, selectors: list[str]) -> str:
    return first_text(row, selectors)


def parse_runners(soup: BeautifulSoup) -> tuple[list[dict], list[str]]:
    errors: list[str] = []

    # 広い範囲のテーブルを無差別に走査しない。
    table = soup.select_one("table.Shutuba_Table")
    if table is None:
        table = soup.select_one("table.ShutubaTable")

    if table is None:
        return [], ["出馬表専用テーブルが見つかりません"]

    rows = table.select("tr.HorseList")
    if not rows:
        rows = table.select("tbody tr")
    if not rows:
        return [], ["出馬表テーブル内に馬の行がありません"]

    runners: list[dict] = []
    seen_horse_ids: set[str] = set()
    seen_numbers: set[int] = set()

    for row in rows:
        horse_anchor = row.select_one('a[href*="/horse/"]')
        if horse_anchor is None:
            continue

        horse_name = text_of(horse_anchor)
        href = horse_anchor.get("href", "")
        id_match = re.search(r"/horse/(\d+)", href)
        horse_id = id_match.group(1) if id_match else ""

        if not horse_name:
            errors.append("馬名が空の行を検出")
            continue

        # 馬番は出馬表の馬番セルからだけ取得。行の先頭数字などで推測しない。
        horse_no_text = cell_text(row, [
            "td.Umaban", ".Umaban",
            "td[class*='Umaban']",
        ])
        frame_text = cell_text(row, [
            "td.Waku", ".Waku",
            "td[class*='Waku']",
        ])

        horse_no_num = to_number(horse_no_text)
        frame_num = to_number(frame_text)

        # 既知の出馬表構造でセルクラスが変わった場合に限り、
        # 公式な列見出しを基にセル位置を特定する。
        cells = row.find_all("td", recursive=False)
        if horse_no_num is None and len(cells) >= 2:
            # 一般的な出馬表: 枠、馬番、印、馬名の順
            fallback = to_number(text_of(cells[1]))
            if fallback is not None and 1 <= int(fallback) <= MAX_RUNNERS:
                horse_no_num = fallback

        if horse_no_num is None:
            errors.append(f"{horse_name}: 馬番を取得できないため除外")
            continue

        horse_no = int(horse_no_num)
        if not 1 <= horse_no <= MAX_RUNNERS:
            errors.append(f"{horse_name}: 不正な馬番 {horse_no}")
            continue

        if horse_no in seen_numbers:
            errors.append(f"馬番 {horse_no} が重複。レースを要確認")
            continue

        if horse_id and horse_id in seen_horse_ids:
            errors.append(f"馬ID {horse_id} が重複。レースを要確認")
            continue

        seen_numbers.add(horse_no)
        if horse_id:
            seen_horse_ids.add(horse_id)

        odds_text = cell_text(row, [
            "td.Popular", "td.Odds", ".Odds",
            "[class*='Odds']", "[class*='odds']",
        ])
        popularity_text = cell_text(row, [
            "td.Popular_Ninki", ".Popular_Ninki",
            "td[class*='Ninki']", "[class*='popular']",
        ])

        # 人気セルとオッズセルがどちらもPopular系の場合があるため、
        # クラス名が特定できない時は数値を断定しない。
        odds = to_number(odds_text)
        popularity = to_number(popularity_text)

        if odds is not None and not (0 < odds < 10000):
            odds = None
        if popularity is not None and not (1 <= popularity <= MAX_RUNNERS):
            popularity = None

        jockey = cell_text(row, [
            ".Jockey", "td.Jockey",
            "td[class*='Jockey']", "a[href*='/jockey/']",
        ])
        trainer = cell_text(row, [
            ".Trainer", "td.Trainer",
            "td[class*='Trainer']", "a[href*='/trainer/']",
        ])
        sex_age = cell_text(row, [
            ".Barei", "td.Barei", "td[class*='Barei']",
        ])
        weight_text = cell_text(row, [
            "td.Horse_Weight", "td[class*='Horse_Weight']",
        ])
        weight_match = re.search(r"(\d{3})\s*(?:\(([+-]?\d+)\))?", weight_text)

        runners.append({
            "horse_no": horse_no,
            "frame_no": int(frame_num) if frame_num is not None else None,
            "horse": horse_name,
            "horse_id": horse_id,
            "jockey": jockey,
            "trainer": trainer,
            "sex_age": sex_age,
            "body_weight": int(weight_match.group(1)) if weight_match else None,
            "body_weight_change": (
                int(weight_match.group(2))
                if weight_match and weight_match.group(2)
                else None
            ),
            "odds": odds,
            "popularity": int(popularity) if popularity is not None else None,
            "recent_form": [],
        })

    runners.sort(key=lambda item: item["horse_no"])

    if len(runners) < MIN_RUNNERS:
        errors.append(f"取得頭数が少なすぎます: {len(runners)}頭")
    if len(runners) > MAX_RUNNERS:
        errors.append(f"取得頭数が上限超過: {len(runners)}頭")

    # 欠番があっても即座に除外とはしない。取消・除外等もあり得るため、
    # 重複・馬番欠落・頭数異常を警告として残す。
    return runners, errors


def score_runners(runners: list[dict]) -> list[dict]:
    valid_odds = [
        horse["odds"] for horse in runners
        if horse.get("odds") is not None and horse["odds"] > 0
    ]
    inverse_sum = sum(1 / odds for odds in valid_odds)

    for horse in runners:
        odds = horse.get("odds")
        popularity = horse.get("popularity")
        score = None
        reasons = []
        implied = None

        if odds is not None and odds > 0:
            score = 100.0 - min(70.0, 18.0 * math.log(max(1.0, odds)))
            reasons.append(f"単勝オッズ {odds:g}倍")

        if popularity is not None:
            popularity_score = max(0.0, 35.0 - (popularity - 1) * 2.5)
            score = (
                score * 0.7 + popularity_score * 0.3
                if score is not None else popularity_score
            )
            reasons.append(f"{int(popularity)}番人気")

        if odds and inverse_sum:
            implied = round((1 / odds) / inverse_sum * 100, 2)

        horse["score"] = round(score, 2) if score is not None else None
        horse["market_implied_pct"] = implied
        horse["reasons"] = reasons or ["オッズ・人気未取得。順位は算出不可"]
        horse["prediction_status"] = (
            "RANKED_MARKET_DATA" if score is not None else "INSUFFICIENT_DATA"
        )
        horse["surface_fit"] = "適性データ未取得"

    ranked = sorted(
        runners,
        key=lambda horse: (
            horse["score"] is None,
            -(horse["score"] if horse["score"] is not None else -999),
            horse.get("odds") if horse.get("odds") is not None else float("inf"),
            horse.get("horse_no", 999),
        ),
    )

    for rank, horse in enumerate(ranked, start=1):
        horse["prediction_rank"] = rank if horse.get("score") is not None else None
        horse["predicted_rank"] = horse["prediction_rank"]
        horse["number"] = horse.get("horse_no")
        horse["name"] = horse.get("horse")
        horse["weight"] = horse.get("body_weight")

    return ranked


def valid_race(race_id: str, meta: dict, runners: list[dict],
               runner_errors: list[str]) -> tuple[bool, list[str]]:
    reasons = list(runner_errors)

    if not re.fullmatch(r"\d{12}", race_id):
        reasons.append("レースIDが12桁ではありません")

    expected_no = race_number_from_id(race_id)
    if expected_no is None or meta.get("race_no") != expected_no:
        reasons.append("レース番号とレースIDが一致しません")

    if len(runners) < MIN_RUNNERS or len(runners) > MAX_RUNNERS:
        reasons.append("出走頭数が許容範囲外です")

    numbers = [horse.get("horse_no") for horse in runners]
    if len(numbers) != len(set(numbers)):
        reasons.append("馬番が重複しています")

    if any(number is None for number in numbers):
        reasons.append("馬番不明の馬が含まれています")

    # 少なくとも、出馬表から馬名と馬番が取得できていること。
    if not runners or any(not horse.get("horse") for horse in runners):
        reasons.append("馬名を確認できません")

    fatal_terms = (
        "出馬表専用テーブルが見つかりません",
        "出馬表テーブル内に馬の行がありません",
        "馬番を取得できない",
        "馬番が重複",
        "不正な馬番",
        "馬ID",
        "取得頭数が少なすぎます",
        "取得頭数が上限超過",
    )
    fatal = any(term in reason for reason in reasons for term in fatal_terms)
    return (not fatal and len(runners) >= MIN_RUNNERS), reasons


def make_snapshot(race: dict, runners: list[dict]) -> dict:
    pick = next(
        (horse for horse in runners if horse.get("prediction_rank") == 1),
        None,
    )
    can_bet = bool(
        pick
        and pick.get("horse_no") is not None
        and pick.get("odds") is not None
        and pick.get("prediction_rank") == 1
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
        "prediction_method": "オッズ・人気の簡易市場スコア。学習済みAIではありません",
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
        "settlement_note": "確定払戻を確認できない場合は実払戻として集計しません。",
    }


def normalize_history(history: Any) -> dict:
    if not isinstance(history, dict):
        history = {}
    if not isinstance(history.get("snapshots"), dict):
        history["snapshots"] = {}
    history["snapshots"] = {
        str(key): value
        for key, value in history["snapshots"].items()
        if isinstance(value, dict)
    }
    history.setdefault("schema_version", 4)
    return history


def parse_positions(html: str) -> dict[str, int]:
    soup = soup_of(html)
    positions: dict[str, int] = {}

    table = soup.select_one("table.RaceTable01")
    if table is None:
        table = soup.select_one("table.Result_Table")
    if table is None:
        return positions

    for row in table.select("tr.HorseList, tr[class*='Result']"):
        anchor = row.select_one('a[href*="/horse/"]')
        if anchor is None:
            continue

        rank_text = cell_text(row, [
            ".Rank", "td.Rank", "td[class*='Rank']",
            "td[class*='Order']", "td[class*='着順']",
        ])
        match = re.match(r"^\s*(\d{1,2})\s*$", rank_text)
        if not match:
            continue

        horse_id_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = horse_id_match.group(1) if horse_id_match else ""
        position = int(match.group(1))

        if horse_id and 1 <= position <= MAX_RUNNERS:
            positions[horse_id] = position

    return positions


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
            if bet.get("return_yen") is None:
                stats["payout_data_missing"] += 1
                continue

            stats[bet_type + "_bets"] += 1
            stats[bet_type + "_stake_yen"] += int(bet.get("stake_yen") or 0)
            stats[bet_type + "_return_yen"] += int(bet.get("return_yen") or 0)
            if bet.get("hit") is True:
                stats[bet_type + "_hits"] += 1

    stats["total_stake_yen"] = stats["win_stake_yen"] + stats["place_stake_yen"]
    stats["total_return_yen"] = stats["win_return_yen"] + stats["place_return_yen"]
    stats["profit_yen"] = stats["total_return_yen"] - stats["total_stake_yen"]
    stats["virtual_balance_yen"] = INITIAL_BANKROLL_YEN + stats["profit_yen"]

    if stats["total_stake_yen"]:
        stats["roi_pct"] = round(
            stats["total_return_yen"] / stats["total_stake_yen"] * 100, 2
        )

    for bet_type in ("win", "place"):
        bets = stats[bet_type + "_bets"]
        hits = stats[bet_type + "_hits"]
        stats[bet_type + "_hit_rate_pct"] = round(hits / bets * 100, 2) if bets else 0.0

    return stats


def main() -> None:
    history = normalize_history(
        load_json(HISTORY, {"schema_version": 4, "snapshots": {}})
    )
    snapshots = history["snapshots"]
    races: list[dict] = []
    errors: list[str] = []
    rejected: list[dict] = []
    attempted = 0

    for source in SOURCES:
        try:
            list_html = get(source["list"] + TODAY)
            race_ids = extract_race_ids(list_html)
        except Exception as exc:
            errors.append(
                f"{source['kind']}一覧取得失敗: {type(exc).__name__}: {str(exc)[:160]}"
            )
            continue

        if not race_ids:
            errors.append(
                f"{source['kind']}一覧からレースIDを取得できません。"
                "非開催日・アクセス制限・ページ構造変更を確認してください。"
            )
            continue

        for race_id in race_ids:
            attempted += 1
            race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"

            try:
                html = get(race_url)
                meta, soup = extract_meta(html, race_id, source["kind"])
                runners, runner_errors = parse_runners(soup)

                for issue in runner_errors:
                    errors.append(f"{race_id}: {issue}")

                ok, validation_errors = valid_race(
                    race_id, meta, runners, runner_errors
                )
                if not ok:
                    rejected.append({
                        "race_id": race_id,
                        "kind": source["kind"],
                        "reason": validation_errors,
                        "source_url": race_url,
                    })
                    errors.append(
                        f"{race_id}: 出馬表の検証に失敗したため公開対象外"
                    )
                    time.sleep(REQUEST_DELAY_SECONDS)
                    continue

                runners = score_runners(runners)

                race_name = meta["race_name"]
                race = {
                    "id": race_id,
                    "kind": source["kind"],
                    "category": source["category"],
                    "date": TODAY_ISO,
                    "race_date": TODAY_ISO,
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
                    "validation_status": "BASIC_CHECKS_PASSED",
                    "prediction_note": (
                        "オッズ・人気に基づく簡易市場スコア。"
                        "競走能力や過去成績を学習したAI予測ではありません。"
                    ),
                }

                key = str(race_id)

                # 初回の予想を保持し、同一レースの再取得で賭け記録を作り直さない。
                if key not in snapshots:
                    snapshots[key] = make_snapshot(race, runners)

                snapshot = snapshots[key]
                snapshot["latest_seen_at"] = NOW.isoformat()
                snapshot["latest_odds"] = {
                    str(horse["horse_no"]): horse.get("odds")
                    for horse in runners
                }

                # 結果ページで馬IDと着順を照合する。
                # 頭数だけで結果の正しさを判定しない。
                try:
                    result_url = f"{source['base']}/race/result.html?race_id={race_id}"
                    result_html = get(result_url)
                    positions_by_id = parse_positions(result_html)

                    original_rankings = snapshot.get("predicted_rankings", [])
                    original_pick_no = snapshot.get("predicted_horse_no")
                    original_pick = next(
                        (
                            item for item in original_rankings
                            if item.get("horse_no") == original_pick_no
                        ),
                        None,
                    )
                    original_horse_id = ""
                    if original_pick:
                        original_horse = next(
                            (
                                horse for horse in runners
                                if horse.get("horse_no") == original_pick_no
                            ),
                            None,
                        )
                        if original_horse:
                            original_horse_id = original_horse.get("horse_id", "")

                    finish = (
                        positions_by_id.get(original_horse_id)
                        if original_horse_id else None
                    )

                    if finish is not None:
                        snapshot["finish_positions_by_horse_id"] = positions_by_id
                        snapshot["predicted_finish_position"] = finish
                        snapshot["result_status"] = "SETTLED"

                        win_bet = snapshot.get("paper_bets", {}).get("win", {})
                        if win_bet.get("placed"):
                            win_bet["hit"] = finish == 1
                            odds = win_bet.get("odds_at_prediction")
                            if finish == 1 and odds:
                                win_bet["return_yen"] = int(round(
                                    float(odds) * int(win_bet.get("stake_yen") or UNIT_YEN)
                                ))
                            else:
                                win_bet["return_yen"] = 0

                        snapshot["settlement_note"] = (
                            "初回取得オッズによる単勝概算。確定払戻データとは異なります。"
                        )
                    else:
                        errors.append(f"{race_id}: 結果ページで予想馬の着順を照合できません")

                except Exception as exc:
                    errors.append(
                        f"{race_id} 結果取得失敗: {type(exc).__name__}: {str(exc)[:100]}"
                    )

                races.append(race)

            except Exception as exc:
                errors.append(
                    f"{race_id}: {type(exc).__name__}: {str(exc)[:160]}"
                )

            time.sleep(REQUEST_DELAY_SECONDS)

    stats = calculate_stats(snapshots)
    history.update({
        "schema_version": 4,
        "updated_at": NOW.isoformat(),
        "stats": stats,
    })
    save_json(HISTORY, history)

    races.sort(key=lambda race: (
        0 if race["kind"] == "中央" else 1,
        race.get("post_time") or "99:99",
        race.get("race_no") or 99,
    ))

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 4,
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": "OK" if races else "NO_DATA",
        "source_policy": (
            "非公式公開ページからの取得。無料サービスのみ。"
            "実際の馬券購入・注文機能はありません。"
        ),
        "data_note": (
            "出走馬は出馬表専用テーブルから抽出し、馬番等の基本検証を行います。"
            "検証に失敗したレースは表示対象外です。"
            "オッズ・人気による簡易スコアであり、学習済みAIの勝率ではありません。"
            "払戻しは初回オッズによる概算です。"
        ),
        "race_count": len(races),
        "attempted_race_count": attempted,
        "rejected_race_count": len(rejected),
        "rejected_races": rejected[-50:],
        "races": races,
        "errors": errors[-80:],
        "history_count": len(snapshots),
        "paper_betting": {
            "unit_yen": UNIT_YEN,
            "initial_bankroll_yen": INITIAL_BANKROLL_YEN,
            "types": ["単勝（初回オッズによる概算）"],
            "real_money": False,
            "stats": stats,
            "history": [
                snapshot for snapshot in snapshots.values()
                if snapshot.get("result_status") == "SETTLED"
            ][-100:],
        },
    }

    save_json(OUT, data)

    print(
        f"BAGEN update: date={TODAY_ISO} "
        f"races={len(races)} attempted={attempted} "
        f"rejected={len(rejected)} snapshots={len(snapshots)} "
        f"errors={len(errors)}"
    )
    print(
        f"stats: settled={stats['races_settled']} "
        f"bets={stats['win_bets']} hits={stats['win_hits']} "
        f"profit={stats['profit_yen']} "
        f"balance={stats['virtual_balance_yen']}"
    )

    for item in rejected[-10:]:
        print(
            "REJECTED:",
            item["race_id"],
            "|",
            " / ".join(item["reason"][:5]),
        )

    for error in errors[-15:]:
        print("WARNING:", error)

    if not races:
        print("WARNING: No validated races were published.")


if __name__ == "__main__":
    main()
