
#!/usr/bin/env python3
# BAGEN KEIBA - free paper prediction engine
# No real betting. No paid API.

import json
import re
import time
from datetime import datetime, timezone, timedelta
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
UNIT = 100

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
        "base": "https://race.netkeiba.com",
        "list": "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
    {
        "kind": "地方",
        "base": "https://nar.netkeiba.com",
        "list": "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date=",
    },
]

VENUES = [
    "札幌", "函館", "福島", "新潟", "東京", "中山",
    "中京", "京都", "阪神", "小倉", "門別", "盛岡",
    "水沢", "浦和", "船橋", "大井", "川崎", "金沢",
    "笠松", "名古屋", "園田", "姫路", "高知", "佐賀", "帯広",
]

# Race-ID venue-code fallback. Used only when the ID structure matches.
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


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value):
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", clean(value).replace(",", ""))
    try:
        return float(match.group()) if match else None
    except ValueError:
        return None


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


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def page_soup(html):
    return BeautifulSoup(html, "html.parser")


def page_text(soup):
    return clean(soup.get_text(" ", strip=True))


def first_text(soup, selectors):
    for selector in selectors:
        try:
            element = soup.select_one(selector)
        except Exception:
            element = None
        if element:
            value = clean(element.get_text(" ", strip=True))
            if value:
                return value
    return ""


def first_regex(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return clean(match.group(1))
    return ""


def venue_from_id(race_id, kind):
    # Netkeiba race IDs usually include the venue code in positions 8-9.
    if len(race_id) >= 10:
        code = race_id[8:10]
        mapping = JRA_CODES if kind == "中央" else NAR_CODES
        if code in mapping:
            return mapping[code]
    return ""


def find_venue(text, title, race_id, kind):
    combined = f"{title} {text[:2500]}"
    for venue in VENUES:
        if venue in combined:
            return venue
    return venue_from_id(race_id, kind)


def extract_race_ids(html):
    soup = page_soup(html)
    found = []
    seen = set()

    for anchor in soup.select('a[href*="race_id="]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{10,12})", href)
        if match:
            race_id = match.group(1)
            if race_id not in seen:
                seen.add(race_id)
                found.append(race_id)

    return found[:60]


def extract_race_name(soup, venue, race_no):
    # Prefer a heading that looks like a race title.
    for selector in [
        ".RaceName",
        ".race_name",
        ".RaceName span",
        "h1",
        "h2",
        "title",
    ]:
        for element in soup.select(selector):
            value = clean(element.get_text(" ", strip=True))
            value = re.sub(r"\s*\|.*$", "", value).strip()
            value = re.sub(r"^\d{4}年\d+月\d+日\s*", "", value)
            if value and len(value) >= 2:
                if "netkeiba" in value.lower() and len(value) < 24:
                    continue
                if value in ("出馬表", "レース結果", "競馬データ"):
                    continue
                if venue and value == venue:
                    continue
                return value

    if venue and race_no:
        return f"{venue}{race_no}R（レース名未取得）"
    if venue:
        return f"{venue}（レース名未取得）"
    return "レース名未取得"


def extract_meta(html, race_id, kind):
    soup = page_soup(html)
    text = page_text(soup)

    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    race_no_match = re.search(r"(\d{2})$", race_id)
    race_no = int(race_no_match.group(1)) if race_no_match else None

    venue = find_venue(text, title, race_id, kind)
    race_name = extract_race_name(soup, venue, race_no)

    # Race pages use different class names across page versions.
    post_time = first_text(soup, [
        ".RaceData01",
        ".race_data",
        ".RaceData",
        ".RaceList_Itemtime",
        ".RaceList_Item02",
        "[class*='RaceData']",
        "[class*='race_data']",
    ])

    post_time = first_regex(
        [
            r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",
            r"(\d{1,2}:\d{2})\s*発走",
        ],
        post_time + " " + text[:3500],
    )

    surface = first_regex(
        [
            r"(芝|ダート|ダ)\s*(?:・|[-ー]|\s)*\d{3,4}\s*m",
            r"(芝|ダート|ダ)\s*\d{3,4}",
        ],
        text[:5000],
    )
    distance_match = re.search(
        r"(?:芝|ダート|ダ)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m",
        text[:5000],
        re.I,
    )
    distance = int(distance_match.group(1)) if distance_match else None

    weather = first_regex(
        [
            r"天候\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)",
            r"天気\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)",
        ],
        text[:6000],
    )

    condition = first_regex(
        [
            r"馬場状態\s*[:：]?\s*(稍重|不良|重|良)",
            r"馬場\s*[:：]?\s*(稍重|不良|重|良)",
        ],
        text[:6000],
    )

    # Do not invent weather or track condition when the source omits it.
    return {
        "race_name": race_name,
        "course": venue,
        "race_no": race_no,
        "post_time": post_time,
        "surface": surface,
        "distance_m": distance,
        "weather": weather,
        "track_condition": condition,
    }, soup


def row_value(row, selectors):
    return first_text(row, selectors)


def parse_runners(soup):
    runners = []
    seen = set()

    row_selectors = [
        "tr.HorseList",
        "tr[class*='HorseList']",
        "table.Shutuba_Table tr",
        "table.RaceTable01 tr",
        "tr[class*='HorseList']",
    ]

    rows = []
    for selector in row_selectors:
        rows.extend(soup.select(selector))

    for row in rows:
        anchor = row.select_one('a[href*="/horse/"]')
        if not anchor:
            continue

        horse_name = clean(anchor.get_text(" ", strip=True))
        if not horse_name or horse_name in seen:
            continue
        seen.add(horse_name)

        horse_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = horse_match.group(1) if horse_match else ""

        horse_no = number(row_value(row, [
            ".Umaban", ".Horse_Num", "td[class*='Umaban']",
            "td[class*='Horse_Num']",
        ]))
        frame_no = number(row_value(row, [
            ".Waku", ".Wakuban", "td[class*='Waku']",
        ]))
        odds = number(row_value(row, [
            ".Odds", ".Popular_Odds", "td[class*='Odds']",
            "span[class*='Odds']",
        ]))
        popularity = number(row_value(row, [
            ".Popular", "td[class*='Popular']",
        ]))
        jockey = row_value(row, [
            ".Jockey", "td[class*='Jockey']",
        ])
        trainer = row_value(row, [
            ".Trainer", "td[class*='Trainer']",
        ])
        sex_age = row_value(row, [
            ".Barei", "td[class*='Barei']",
        ])

        weight_text = row_value(row, [
            "td[class*='Horse_Weight']",
            "td[class*='Weight']",
        ])
        weight_match = re.search(
            r"(\d{3})\s*(?:\(([+-]?\d+)\))?",
            weight_text,
        )
        body_weight = int(weight_match.group(1)) if weight_match else None
        weight_change = (
            int(weight_match.group(2))
            if weight_match and weight_match.group(2)
            else None
        )

        runners.append({
            "horse_no": int(horse_no) if horse_no is not None else None,
            "frame_no": int(frame_no) if frame_no is not None else None,
            "horse": horse_name,
            "horse_id": horse_id,
            "jockey": jockey,
            "trainer": trainer,
            "sex_age": sex_age,
            "body_weight": body_weight,
            "body_weight_change": weight_change,
            "odds": odds,
            "popularity": int(popularity) if popularity is not None else None,
            "recent_form": [],
        })

    # Simple market-based score. This is not a trained AI model.
    inverse_sum = sum(
        1 / h["odds"]
        for h in runners
        if h.get("odds") and h["odds"] > 1
    )

    for horse in runners:
        score = 50.0
        reasons = []
        implied = None

        odds = horse.get("odds")
        popularity = horse.get("popularity")

        if odds and odds > 1 and inverse_sum:
            implied = (1 / odds) / inverse_sum * 100
            score += min(35, implied * 1.8)
            reasons.append(f"市場評価 {implied:.1f}%相当")

        if popularity:
            score += max(0, 12 - (popularity - 1) * 1.4)
            reasons.append(f"{popularity}番人気")

        if not odds and not popularity:
            reasons.append("オッズ・人気未取得")

        horse["score"] = round(score, 2)
        horse["market_implied_pct"] = (
            round(implied, 2) if implied is not None else None
        )
        horse["reasons"] = reasons

    runners.sort(key=lambda h: (
        -h["score"],
        h.get("odds") or 999999,
        h.get("horse_no") or 999,
    ))

    for rank, horse in enumerate(runners, start=1):
        horse["prediction_rank"] = rank

        # Names compatible with the current HTML.
        horse["number"] = horse.get("horse_no")
        horse["name"] = horse.get("horse")
        horse["predicted_rank"] = rank
        horse["weight"] = horse.get("body_weight")
        horse["surface_fit"] = "適性データ未取得"

    return runners


def parse_positions(html, race):
    soup = page_soup(html)
    positions = {}

    for row in soup.select(
        "tr.HorseList, tr[class*='HorseList'], "
        "table.RaceTable01 tr, table.Result_Table tr"
    ):
        anchor = row.select_one('a[href*="/horse/"]')
        if not anchor:
            continue

        position_text = row_value(row, [
            ".Rank", "td[class*='Rank']",
            "td[class*='Order']", "td[class*='着順']",
        ])
        match = re.match(r"^\s*(\d{1,2})\s*$", position_text)
        if not match:
            continue

        position = int(match.group(1))
        if not 1 <= position <= 30:
            continue

        horse_match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
        horse_id = horse_match.group(1) if horse_match else ""
        horse_name = clean(anchor.get_text(" ", strip=True))

        for horse in race.get("runners", []):
            if horse_id and horse_id == horse.get("horse_id"):
                positions[str(horse.get("horse_no"))] = position
            elif horse_name and horse_name == horse.get("horse"):
                positions[str(horse.get("horse_no"))] = position

    return positions


def calculate_stats(snapshots):
    stats = {
        "races_settled": 0,
        "win_bets": 0, "win_hits": 0,
        "win_stake_yen": 0, "win_return_yen": 0,
        "place_bets": 0, "place_hits": 0,
        "place_stake_yen": 0, "place_return_yen": 0,
        "total_stake_yen": 0, "total_return_yen": 0,
        "profit_yen": 0, "roi_pct": 0,
        "virtual_balance_yen": 0,
    }

    for snapshot in snapshots.values():
        if snapshot.get("result_status") != "SETTLED":
            continue

        stats["races_settled"] += 1
        for bet_type in ("win", "place"):
            bet = snapshot.get("paper_bets", {}).get(bet_type, {})
            if not bet.get("placed"):
                continue

            # Do not count an unknown payout as a zero-yen payout.
            if bet.get("return_yen") is None:
                continue

            stats[bet_type + "_bets"] += 1
            stats[bet_type + "_stake_yen"] += int(bet.get("stake_yen") or 0)
            stats[bet_type + "_return_yen"] += int(bet.get("return_yen") or 0)

            if bet.get("hit"):
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
    stats["roi_pct"] = (
        round(stats["total_return_yen"] / stats["total_stake_yen"] * 100, 2)
        if stats["total_stake_yen"] else 0
    )

    stats["virtual_balance_yen"] = stats["profit_yen"]

    for bet_type in ("win", "place"):
        bets = stats[bet_type + "_bets"]
        hits = stats[bet_type + "_hits"]
        stats[bet_type + "_hit_rate_pct"] = (
            round(hits / bets * 100, 2) if bets else 0
        )

    return stats


def main():
    history = load_json(HISTORY, {
        "schema_version": 1,
        "snapshots": {},
        "updated_at": None,
        "stats": {},
    })

    if not isinstance(history, dict):
        history = {"schema_version": 1, "snapshots": {}}

    snapshots = history.setdefault("snapshots", {})
    races = []
    errors = []

    for source in SOURCES:
        try:
            list_html = get(source["list"] + TODAY)
            race_ids = extract_race_ids(list_html)
        except Exception as exc:
            errors.append(
                f'{source["kind"]}一覧取得失敗: '
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if not race_ids:
            errors.append(
                f'{source["kind"]}: レースIDなし。非開催日、'
                "アクセス制限、またはページ構造変更の可能性。"
            )

        for race_id in race_ids:
            race_url = (
                f'{source["base"]}/race/shutuba.html?race_id={race_id}'
            )

            try:
                html = get(race_url)
                meta, soup = extract_meta(html, race_id, source["kind"])
                runners = parse_runners(soup)

                if not runners:
                    errors.append(
                        f"{race_id}: 出走馬を取得できませんでした"
                    )
                    continue

                race_no = meta["race_no"]
                race_name = meta["race_name"]
                venue = meta["course"]

                # Fallback name remains explicit about missing data.
                if race_name == "レース名未取得" and venue and race_no:
                    race_name = f"{venue}{race_no}R（レース名未取得）"

                race = {
                    "id": race_id,
                    "kind": source["kind"],
                    "category": "central" if source["kind"] == "中央" else "local",
                    "date": NOW.strftime("%Y-%m-%d"),
                    "race_date": NOW.strftime("%Y-%m-%d"),
                    "race_no": race_no,
                    "name": race_name,
                    "race_name": race_name,
                    "course": venue,
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
                    "top5": runners[:5],
                }

                key = str(race_id)

                # Freeze prediction only on first observation.
                if key not in snapshots:
                    pick = next(
                        (h for h in runners if h["prediction_rank"] == 1),
                        None,
                    )

                    snapshots[key] = {
                        "race_id": key,
                        "kind": source["kind"],
                        "race_date": race["race_date"],
                        "race_name": race_name,
                        "course": venue,
                        "post_time": meta["post_time"],
                        "source_url": race_url,
                        "snapshot_at": NOW.isoformat(),
                        "predicted_horse_no": (
                            pick.get("horse_no") if pick else None
                        ),
                        "predicted_horse": pick.get("horse") if pick else None,
                        "predicted_rankings": [
                            {
                                "horse_no": h.get("horse_no"),
                                "horse": h.get("horse"),
                                "rank": h.get("prediction_rank"),
                                "odds_at_prediction": h.get("odds"),
                            }
                            for h in runners
                        ],
                        "result_status": "PENDING",
                        "predicted_finish_position": None,
                        "paper_bets": {
                            "win": {
                                "placed": bool(
                                    pick
                                    and pick.get("horse_no") is not None
                                    and pick.get("odds")
                                    and pick["odds"] >= 1
                                ),
                                "horse_no": pick.get("horse_no") if pick else None,
                                "stake_yen": UNIT,
                                "odds_at_prediction": pick.get("odds") if pick else None,
                                "hit": None,
                                "return_yen": None,
                            },
                            "place": {
                                "placed": bool(
                                    pick and pick.get("horse_no") is not None
                                ),
                                "horse_no": pick.get("horse_no") if pick else None,
                                "stake_yen": UNIT,
                                "hit": None,
                                "return_yen": None,
                            },
                        },
                    }

                # Result matching: settle only when a finish position
                # for the frozen predicted horse is found.
                try:
                    result_url = (
                        f'{source["base"]}/race/result.html?race_id={race_id}'
                    )
                    result_html = get(result_url)
                    positions = parse_positions(result_html, race)
                    snapshot = snapshots[key]
                    pick_no = snapshot.get("predicted_horse_no")
                    finish = positions.get(str(pick_no)) if pick_no is not None else None

                    if finish is not None:
                        snapshot["finish_positions"] = positions
                        snapshot["predicted_finish_position"] = finish
                        snapshot["result_status"] = "SETTLED"

                        win_bet = snapshot["paper_bets"]["win"]
                        place_bet = snapshot["paper_bets"]["place"]

                        win_bet["hit"] = finish == 1
                        if win_bet.get("placed"):
                            if finish == 1 and win_bet.get("odds_at_prediction"):
                                win_bet["return_yen"] = int(round(
                                    win_bet["odds_at_prediction"] * UNIT
                                ))
                            else:
                                win_bet["return_yen"] = 0

                        place_bet["hit"] = finish <= 3
                        # Official place payout is not scraped; do not
                        # invent a payout or include it in ROI.
                        place_bet["return_yen"] = None

                        snapshot["settlement_note"] = (
                            "単勝払戻は予想時オッズによる概算。"
                            "複勝は公式払戻未取得のため収支集計から除外。"
                        )
                except Exception as exc:
                    errors.append(
                        f"{race_id} 結果照合: {type(exc).__name__}"
                    )

                races.append(race)

            except Exception as exc:
                errors.append(
                    f"{race_id}: {type(exc).__name__}: {exc}"
                )

            time.sleep(1.0)

    stats = calculate_stats(snapshots)
    history["updated_at"] = NOW.isoformat()
    history["stats"] = stats
    save_json(HISTORY, history)

    settled = [
        snapshot for snapshot in snapshots.values()
        if snapshot.get("result_status") == "SETTLED"
    ][-100:]

    data = {
        "site": "BAGEN KEIBA",
        "schema_version": 2,
        "generated_at": NOW.isoformat(),
        "race_date": NOW.strftime("%Y-%m-%d"),
        "status": "OK" if races else "NO_DATA",
        "source_policy": (
            "Unofficial public-page scraping. "
            "No paid API or real-money betting integration."
        ),
        "data_note": (
            "オッズ・人気を使った簡易予想で、実証済みAI勝率ではありません。"
            "取得できない情報は推測で埋めません。"
            "単勝払戻は予想時オッズによる概算、複勝の公式払戻は未取得です。"
        ),
        "race_count": len(races),
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
            "unit_yen": UNIT,
            "types": ["単勝", "複勝"],
            "real_money": False,
            "stats": stats,
            "history": settled,
        },
    }

    save_json(OUT, data)
    print(
        f"BAGEN update: {len(races)} races; "
        f"{len(snapshots)} snapshots; {len(errors)} warnings"
    )

    for error in errors[-10:]:
        print("WARNING:", error)

    if not races:
        print(
            "WARNING: No races were parsed. Check source access, "
            "the current race date, and page structure."
        )


if __name__ == "__main__":
    main()