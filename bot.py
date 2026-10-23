#!/usr/bin/env python3
"""BAGEN KEIBA - free horse racing data collector and ranking engine."""

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs" / "data.json"

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y%m%d")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BAGEN-Keiba/1.0)"
    )
}

TIMEOUT = 20
PAUSE_SECONDS = 1.2
MAX_RACES_PER_SOURCE = 60

SOURCES = [
    {
        "kind": "中央",
        "base": "https://race.netkeiba.com",
        "list": (
            "https://race.netkeiba.com/top/"
            "race_list_sub.html?kaisai_date="
        ),
    },
    {
        "kind": "地方",
        "base": "https://nar.netkeiba.com",
        "list": (
            "https://nar.netkeiba.com/top/"
            "race_list_sub.html?kaisai_date="
        ),
    },
]


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def number(value):
    if not value:
        return None

    value = clean(value).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", value)

    if not match:
        return None

    try:
        result = float(match.group())
        return result if result > 0 else None
    except ValueError:
        return None


def get_html(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    response.encoding = (
        response.apparent_encoding or "utf-8"
    )
    return response.text


def find_race_ids(html):
    soup = BeautifulSoup(html, "html.parser")
    found = []

    for link in soup.select('a[href*="race_id="]'):
        href = link.get("href", "")
        match = re.search(
            r"race_id=(\d{10,12})",
            href,
        )

        if match:
            found.append(match.group(1))

    return list(dict.fromkeys(found))[:MAX_RACES_PER_SOURCE]


def cell_text(row, selectors):
    for selector in selectors:
        element = row.select_one(selector)

        if element:
            value = clean(
                element.get_text(" ", strip=True)
            )

            if value:
                return value

    return ""


def parse_race(html):
    soup = BeautifulSoup(html, "html.parser")

    title = (
        clean(soup.title.get_text(" ", strip=True))
        if soup.title
        else "レース名未取得"
    )

    page_text = clean(soup.get_text(" ", strip=True))

    surface = ""
    distance = None

    match = re.search(
        r"(芝|ダート|ダ)\s*(\d{3,4})\s*m",
        page_text,
    )

    if match:
        surface = match.group(1)
        distance = int(match.group(2))

    condition = ""
    match = re.search(
        r"馬場状態\s*[:：]?\s*(良|稍重|重|不良)",
        page_text,
    )

    if match:
        condition = match.group(1)

    race_name = re.sub(r"\s*\|.*$", "", title).strip()

    selectors = (
        "tr.HorseList, "
        "tr[class*='HorseList'], "
        "table.Shutuba_Table tr, "
        "table.RaceTable01 tr"
    )

    runners = []
    seen = set()

    for row in soup.select(selectors):
        horse_link = row.select_one(
            'a[href*="/horse/"]'
        )

        if not horse_link:
            continue

        horse_name = clean(
            horse_link.get_text(" ", strip=True)
        )

        if not horse_name or horse_name in seen:
            continue

        seen.add(horse_name)

        href = horse_link.get("href", "")
        horse_match = re.search(
            r"/horse/(\d+)",
            href,
        )

        horse_id = (
            horse_match.group(1)
            if horse_match
            else ""
        )

        horse_no = number(
            cell_text(
                row,
                [
                    ".Umaban",
                    ".Horse_Num",
                    "td[class*='Umaban']",
                    "td[class*='Horse_Num']",
                ],
            )
        )

        frame_no = number(
            cell_text(
                row,
                [
                    ".Waku",
                    ".Wakuban",
                    "td[class*='Waku']",
                ],
            )
        )

        jockey = cell_text(
            row,
            [
                ".Jockey",
                "td[class*='Jockey']",
            ],
        )

        trainer = cell_text(
            row,
            [
                ".Trainer",
                "td[class*='Trainer']",
            ],
        )

        sex_age = cell_text(
            row,
            [
                ".Barei",
                "td[class*='Barei']",
            ],
        )

        odds_text = cell_text(
            row,
            [
                ".Odds",
                ".Popular_Odds",
                "td[class*='Odds']",
            ],
        )

        popularity_text = cell_text(
            row,
            [
                ".Popular",
                "td[class*='Popular']",
            ],
        )

        body_weight_text = cell_text(
            row,
            [
                "td[class*='Horse_Weight']",
            ],
        )

        odds = number(odds_text)
        popularity = number(popularity_text)
        body_weight = number(body_weight_text)

        recent_form = []

        for cell in row.select("td"):
            classes = " ".join(
                cell.get("class", [])
            ).lower()

            if any(
                key in classes
                for key in (
                    "past",
                    "result",
                    "race_history",
                    "horse_past",
                )
            ):
                value = clean(
                    cell.get_text(" ", strip=True)
                )

                if value:
                    recent_form.append(value[:80])

        runners.append(
            {
                "horse_no": (
                    int(horse_no)
                    if horse_no is not None
                    else None
                ),
                "frame_no": (
                    int(frame_no)
                    if frame_no is not None
                    else None
                ),
                "horse": horse_name,
                "horse_id": horse_id,
                "jockey": jockey,
                "trainer": trainer,
                "sex_age": sex_age,
                "body_weight": body_weight,
                "odds": odds,
                "popularity": (
                    int(popularity)
                    if popularity is not None
                    else None
                ),
                "recent_form": recent_form,
            }
        )

    metadata = {
        "title": race_name or title,
        "surface": surface,
        "distance_m": distance,
        "track_condition": condition,
    }

    return metadata, runners


def rank_runners(runners):
    valid_odds = [
        runner["odds"]
        for runner in runners
        if runner.get("odds")
        and runner["odds"] > 1
    ]

    inverse_sum = sum(
        1 / odds for odds in valid_odds
    )

    ranked = []

    for original in runners:
        runner = dict(original)
        odds = runner.get("odds")
        popularity = runner.get("popularity")

        score = 50.0
        reasons = []
        implied_pct = None

        if odds and odds > 1 and inverse_sum:
            implied_pct = (
                (1 / odds) / inverse_sum * 100
            )

            score += min(35.0, implied_pct * 1.8)

            reasons.append(
                "オッズに基づく市場評価 "
                f"{implied_pct:.1f}%相当"
            )

        if popularity:
            score += max(
                0.0,
                12.0 - (popularity - 1) * 1.4,
            )

            reasons.append(
                f"{int(popularity)}番人気"
            )

        if runner.get("recent_form"):
            reasons.append(
                "近走情報を取得（内容の検証が必要）"
            )

        if not odds and not popularity:
            reasons.append(
                "オッズ・人気未取得の暫定評価"
            )

        runner["score"] = round(score, 2)
        runner["market_implied_pct"] = (
            round(implied_pct, 2)
            if implied_pct is not None
            else None
        )
        runner["reasons"] = reasons

        ranked.append(runner)

    ranked.sort(
        key=lambda runner: (
            -runner["score"],
            runner.get("odds") or 999999,
            runner.get("horse_no") or 999,
        )
    )

    for index, runner in enumerate(ranked, start=1):
        runner["prediction_rank"] = index

    return ranked


def collect_source(source):
    races = []
    errors = []

    schedule_url = source["list"] + TODAY

    try:
        schedule_html = get_html(schedule_url)
        race_ids = find_race_ids(schedule_html)

    except Exception as error:
        return [], [
            f"{source['kind']}開催一覧取得エラー: "
            f"{type(error).__name__}: {error}"
        ]

    if not race_ids:
        return [], [
            f"{source['kind']}: レースIDを取得できません。"
            "非開催日、アクセス制限、ページ仕様変更の可能性があります。"
        ]

    for race_id in race_ids:
        race_url = (
            f"{source['base']}/race/shutuba.html"
            f"?race_id={race_id}"
        )

        try:
            html = get_html(race_url)
            metadata, runners = parse_race(html)

            if not runners:
                errors.append(
                    f"{race_id}: 出走馬を読み取れませんでした"
                )
                continue

            ranked = rank_runners(runners)

            race_no_match = re.search(
                r"(\d{2})$",
                race_id,
            )

            race_no = (
                int(race_no_match.group(1))
                if race_no_match
                else None
            )

            races.append(
                {
                    "id": race_id,
                    "kind": source["kind"],
                    "race_no": race_no,
                    "race_name": metadata["title"],
                    "course": "",
                    "post_time": "",
                    "surface": metadata["surface"],
                    "distance_m": metadata["distance_m"],
                    "track_condition": metadata[
                        "track_condition"
                    ],
                    "source_url": race_url,
                    "source_name": "netkeiba・非公式取得",
                    "runner_count": len(ranked),
                    "top5": ranked[:5],
                    "runners": ranked,
                }
            )

        except Exception as error:
            errors.append(
                f"{race_id}: "
                f"{type(error).__name__}: {error}"
            )

        time.sleep(PAUSE_SECONDS)

    return races, errors


def main():
    all_races = []
    all_errors = []

    for source in SOURCES:
        races, errors = collect_source(source)
        all_races.extend(races)
        all_errors.extend(errors)

    all_races.sort(
        key=lambda race: (
            0 if race["kind"] == "中央" else 1,
            race.get("race_no") or 99,
            race["id"],
        )
    )

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 1,
        "generated_at": datetime.now(JST).isoformat(),
        "race_date": datetime.now(JST).strftime(
            "%Y-%m-%d"
        ),
        "status": "OK" if all_races else "NO_DATA",
        "source_policy": (
            "Unofficial public-page scraping. "
            "No paid API or live betting integration."
        ),
        "data_note": (
            "予想順位は取得できたオッズ・人気を使う"
            "簡易スコアです。勝率の実証値ではありません。"
            "データが取得できない項目は推測していません。"
        ),
        "race_count": len(all_races),
        "races": all_races,
        "errors": all_errors[:30],
    }

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"date={data['race_date']} "
        f"status={data['status']} "
        f"races={len(all_races)} "
        f"errors={len(all_errors)}"
    )

    if not all_races:
        raise SystemExit(
            "No race data collected. "
            "Check docs/data.json errors. "
            "No fake race data was published."
        )


if __name__ == "__main__":
    main()
