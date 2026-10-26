#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BAGEN KEIBA - paper prediction and results engine.
Free GitHub Actions compatible. No betting or payment actions are performed.
"""

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
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y%m%d")
TODAY_ISO = NOW.strftime("%Y-%m-%d")
MAX_RACES_PER_SOURCE = 80
MIN_RUNNERS = 2
REQUEST_DELAY = 0.35
REQUEST_TIMEOUT = 18
HISTORY_RETENTION_DAYS = 180

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
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}
NAR_CODES = {
    "30": "帯広", "35": "盛岡", "36": "水沢", "40": "浦和", "41": "船橋",
    "42": "大井", "43": "川崎", "44": "大井", "45": "川崎", "46": "金沢",
    "47": "笠松", "48": "名古屋", "50": "園田", "51": "姫路", "54": "姫路",
    "55": "高知", "56": "佐賀",
}
DIRT_SIRES = [
    "ヘニーヒューズ", "シニスターミニスター", "パイロ",
    "マジェスティックウォリアー", "ホッコータルマエ", "アジアエクスプレス",
    "スマートファルコン", "ゴールドアリュール", "コパノリッキー",
]
POWER_SIRES = [
    "ロードカナロア", "エピファネイア", "キズナ", "オルフェーヴル",
    "モーリス", "ドゥラメンテ", "ハーツクライ", "ルーラーシップ",
    "ジャスタウェイ", "サトノダイヤモンド",
]
TOP_JOCKEYS = [
    "ルメール", "川田", "武豊", "戸崎", "横山武", "坂井", "松山",
    "デムーロ", "岩田望", "浜中", "菅原明", "横山和", "吉村智",
    "笹川翼", "森泰斗", "矢野貴",
]
POSITIVE_WORDS = ["好気配", "一変", "立て直し", "上向き", "絶好", "シャープ"]
NEGATIVE_WORDS = ["太目", "硬い", "入れ込み", "不安", "モタれる", "休み明け"]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value):
    text = clean(value).replace(",", "").replace("．", ".")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (ValueError, TypeError):
        return None


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def get_html(url):
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except requests.RequestException as exc:
        print(f"[WARN] GET failed: {url} ({exc.__class__.__name__})")
        return ""


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def race_no_from_id(race_id):
    race_id = str(race_id)
    if not re.fullmatch(r"\d{12,14}", race_id):
        return None
    race_no = int(race_id[-2:])
    return race_no if 1 <= race_no <= 12 else None


def venue_from_id(race_id, kind):
    race_id = str(race_id)
    if not re.fullmatch(r"\d{12,14}", race_id):
        return ""
    # netkeiba race IDs normally place the venue code at positions 5-6.
    code = race_id[4:6]
    return (JRA_CODES if kind == "中央" else NAR_CODES).get(code, "")


def extract_race_ids(html):
    if not html:
        return []
    soup = soup_of(html)
    found, seen = [], set()
    for anchor in soup.select('a[href*="race_id="], a[href*="shutuba.html"]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{12,14})", href)
        if not match:
            continue
        race_id = match.group(1)
        if race_id not in seen and race_no_from_id(race_id):
            seen.add(race_id)
            found.append(race_id)
    return found[:MAX_RACES_PER_SOURCE]


def parse_meta(soup):
    parts = []
    selectors = [
        ".RaceData01", ".RaceData02", ".RaceData", ".race_data",
        "[class*='RaceData']", ".raceData01", ".raceData02",
    ]
    for selector in selectors:
        for element in soup.select(selector):
            value = text_of(element)
            if value and value not in parts:
                parts.append(value)
    return " ".join(parts)


def first_text(soup, selectors):
    for selector in selectors:
        element = soup.select_one(selector)
        value = text_of(element)
        if value and "netkeiba" not in value.lower():
            return value
    return ""


def parse_odds_popularity(row):
    odds = None
    popularity = None
    for selector in [
        "td.Odds", ".Odds", "[class*='Odds']", ".odds",
        "td[class*='Odds']",
    ]:
        element = row.select_one(selector)
        value = number(text_of(element))
        if value is not None and value > 0:
            odds = value
            break
    for selector in [
        "td.Popular_Ninki", ".Popular_Ninki", "[class*='Ninki']",
        ".Popular", "td[class*='Popular']",
    ]:
        element = row.select_one(selector)
        value = number(text_of(element))
        if value is not None and 1 <= value <= 18:
            popularity = int(value)
            break

    # Fallback: inspect cells only when class-based selectors are absent.
    if odds is None or popularity is None:
        for cell in row.find_all(["td", "th"], recursive=False):
            cls = " ".join(cell.get("class", []))
            value = number(text_of(cell))
            if value is None:
                continue
            if odds is None and ("Odds" in cls or re.fullmatch(r"\d+(?:\.\d+)?", text_of(cell))):
                if 1.0 <= value <= 9999:
                    odds = value
            if popularity is None and ("Ninki" in cls or "Popular" in cls):
                if 1 <= value <= 18:
                    popularity = int(value)
    return odds, popularity


def parse_runner_number(row):
    for selector in [
        "td.Umaban", ".Umaban", "[class*='Umaban']", "td.Num",
        "[class*='Num']",
    ]:
        element = row.select_one(selector)
        value = number(text_of(element))
        if value is not None and 1 <= value <= 18:
            return int(value)

    for cell in row.find_all(["td", "th"], recursive=False)[:5]:
        classes = " ".join(cell.get("class", []))
        if "Waku" in classes:
            continue
        value = number(text_of(cell))
        if value is not None and 1 <= value <= 18:
            return int(value)
    return None


def parse_frame(row):
    for selector in ["td.Waku", ".Waku", "[class*='Waku']"]:
        value = number(text_of(row.select_one(selector)))
        if value is not None and 1 <= value <= 8:
            return int(value)
    return None


def parse_runner_rows(soup, surface, venue):
    rows = soup.select(
        "tr.HorseList, tr[class*='Horse'], table.Shutuba_Table tr, "
        "table.ShutubaTable tr"
    )
    runners = []
    seen = set()

    for row in rows:
        horse_anchor = row.select_one('a[href*="/horse/"], a[href*="horse"]')
        horse_name = text_of(horse_anchor)
        if not horse_name or horse_name in seen or "馬名" in horse_name:
            continue
        horse_no = parse_runner_number(row)
        if horse_no is None:
            continue
        seen.add(horse_name)

        row_text = text_of(row)
        frame_no = parse_frame(row)
        odds, popularity = parse_odds_popularity(row)
        jockey = text_of(row.select_one(
            ".Jockey, td.Jockey, [class*='Jockey'], . jockey"
        ))
        weight_text = text_of(row.select_one(
            "td.Horse_Weight, .Horse_Weight, [class*='HorseWeight'], [class*='Weight']"
        ))
        weight_match = re.search(r"\d{3}\s*\(([+-]?\d+)\)", weight_text)
        weight_diff = int(weight_match.group(1)) if weight_match else 0

        # Sire/comment data are only credited when the page actually contains them.
        sire = ""
        sire_match = re.search(r"(?:父|種牡馬|Sire)[:：]?\s*([^\s（）()]+)", row_text)
        if sire_match:
            sire = sire_match.group(1)
        is_dirt_blood = any(name in row_text or name in sire for name in DIRT_SIRES)
        is_power_blood = any(name in row_text or name in sire for name in POWER_SIRES)
        is_apprentice = any(mark in jockey for mark in ["▲", "△", "☆", "◇", "★"])
        is_top_jockey = any(name in jockey for name in TOP_JOCKEYS)
        is_positive = any(word in row_text for word in POSITIVE_WORDS)
        is_negative = any(word in row_text for word in NEGATIVE_WORDS)
        is_inner = frame_no in (1, 2) if frame_no else False
        is_outer = frame_no in (7, 8) if frame_no else False

        reasons = []
        if is_apprentice:
            reasons.append("減量記号のある騎手")
        if is_top_jockey:
            reasons.append("騎手評価対象")
        if surface == "ダート" and is_dirt_blood:
            reasons.append("ダート適性候補の血統情報を検出")
        if surface == "芝" and is_power_blood:
            reasons.append("芝・持続力型血統の候補を検出")
        if weight_match and abs(weight_diff) >= 6:
            reasons.append(f"馬体重増減 {weight_diff:+d}kg")
        if is_positive:
            reasons.append("掲載テキストに好材料ワード")
        if is_negative:
            reasons.append("掲載テキストに注意ワード")

        runners.append({
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": frame_no,
            "horse": horse_name,
            "name": horse_name,
            "jockey": jockey or "未取得",
            "odds": odds,
            "popularity": popularity,
            "score": 0.0,
            "reasons": reasons,
            "caution": "オッズ・出走情報だけでは判断できない要素あり",
            "is_apprentice": is_apprentice,
            "is_top_jockey": is_top_jockey,
            "is_inner": is_inner,
            "is_outer": is_outer,
            "is_dirt_blood": is_dirt_blood,
            "is_power_blood": is_power_blood,
            "is_positive_memo": is_positive,
            "is_negative_memo": is_negative,
            "w_diff": weight_diff,
            "data_quality": {
                "odds": odds is not None,
                "popularity": popularity is not None,
                "jockey": bool(jockey),
                "frame": frame_no is not None,
                "weight_change": weight_match is not None,
            },
        })

    runners.sort(key=lambda item: item["horse_no"])
    return runners


def score_runners(runners, surface, venue):
    count = len(runners)
    for horse in runners:
        score = 0.0
        odds = horse.get("odds")
        popularity = horse.get("popularity")

        # Market information has the highest weight; no odds means no fake odds score.
        if odds is not None and odds > 0:
            score += max(0.0, 42.0 - 8.0 * math.log(max(1.0, odds)))
        if popularity is not None:
            score += max(0.0, 16.0 - (popularity - 1) * 1.1)

        if horse["is_top_jockey"]:
            score += 3.0
            horse["reasons"].append("登録騎手リストによる加点（実績保証ではない）")
        if horse["is_apprentice"]:
            score += 1.5
        if surface == "ダート" and horse["is_dirt_blood"]:
            score += 2.0
        elif surface == "芝" and horse["is_power_blood"]:
            score += 1.5

        if venue in ["東京", "新潟"] and horse["is_outer"]:
            score += 1.0
            horse["reasons"].append("競馬場・外枠の簡易補正")
        elif venue in ["中山", "小倉", "福島", "札幌"] and horse["is_inner"]:
            score += 1.0
            horse["reasons"].append("競馬場・内枠の簡易補正")

        diff = horse.get("w_diff", 0)
        if 8 <= diff <= 16:
            score += 1.0
        if horse["is_positive_memo"]:
            score += 1.0
        if horse["is_negative_memo"]:
            score -= 2.0
            horse["reasons"].append("注意ワード検出のため減点")
        if horse.get("popularity") == 1 and odds is not None and odds < 1.8:
            score -= 1.0
            horse["reasons"].append("極端な低オッズのため妙味を控えめ評価")

        horse["score"] = round(score, 2)
        if not horse["reasons"]:
            horse["reasons"].append("取得できた出走情報・オッズを基に評価")
        horse["score_confidence"] = round(
            sum(bool(v) for v in horse["data_quality"].values()) / 5 * 100
        )

    return sorted(runners, key=lambda item: (-item["score"], item["horse_no"]))


def get_result_data(base_url, race_id):
    """Read result page conservatively; never infer finish order from arbitrary cells."""
    html = get_html(f"{base_url}/race/result.html?race_id={race_id}")
    if not html:
        return [], {"win": 0, "quinella": 0, "trio": 0, "wide": 0}, {}

    soup = soup_of(html)
    finishes = []
    # Typical netkeiba result table has finish position in the first cell and horse number
    # in a cell/class labelled Umaban. Avoid treating the first cell as a horse number.
    result_rows = soup.select(
        "table.RaceTable01 tr, table.ResultTable tr, tr.HorseList, "
        "table.RaceTable tr, table.race_table_01 tr"
    )
    for row in result_rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 3:
            continue
        first = text_of(cells[0])
        if not re.fullmatch(r"\d{1,2}", first):
            continue
        finish = int(first)
        if not 1 <= finish <= 3:
            continue
        horse_no = None
        for selector in ["td.Num", ".Umaban", "td.Umaban", "[class*='Umaban']"]:
            value = number(text_of(row.select_one(selector)))
            if value is not None and 1 <= value <= 18:
                horse_no = int(value)
                break
        if horse_no is None:
            # Common result table layout: finish, frame, horse number, horse name...
            for cell in cells[1:5]:
                value = number(text_of(cell))
                if value is not None and 1 <= value <= 18:
                    horse_no = int(value)
                    break
        if horse_no is not None and all(item["finish"] != finish for item in finishes):
            finishes.append({"finish": finish, "horse_no": horse_no})

    finishes.sort(key=lambda item: item["finish"])
    finish_numbers = [item["horse_no"] for item in finishes[:3]]

    payouts = {"win": 0, "quinella": 0, "trio": 0, "wide": 0}
    payout_combinations = {}
    # Row-based parsing is safer than scanning arbitrary page text.
    for row in soup.find_all("tr"):
        row_text = text_of(row)
        if not row_text:
            continue
        cells_text = [text_of(cell) for cell in row.find_all(["th", "td"], recursive=False)]
        if not cells_text:
            continue
        joined = " ".join(cells_text)
        amounts = [int(value.replace(",", "")) for value in re.findall(r"([\d,]+)\s*円", joined)]
        if not amounts:
            continue
        bet_type = None
        if "単勝" in joined:
            bet_type = "win"
        elif "馬連" in joined:
            bet_type = "quinella"
        elif "3連複" in joined or "三連複" in joined:
            bet_type = "trio"
        elif "ワイド" in joined:
            bet_type = "wide"
        if bet_type and payouts[bet_type] == 0:
            payouts[bet_type] = amounts[-1]
            payout_combinations[bet_type] = joined

    return finish_numbers, payouts, payout_combinations


def build_tickets(ranked, outsiders):
    """Fixed 2,000-yen paper ticket set. Every line has a matching settlement rule."""
    if len(ranked) < 3:
        return []
    top = ranked[:5]
    h1, h2, h3 = [item["horse_no"] for item in top[:3]]
    h4 = top[3]["horse_no"] if len(top) > 3 else h3
    pattern_b = bool(outsiders) and (
        (top[0].get("odds") or 0) >= 2.8 or len(outsiders) >= 2
    )

    if pattern_b:
        outsider = outsiders[0]["horse_no"]
        lines = [
            {"type": "win", "horses": [h1], "stake_yen": 300, "label": f"単勝: {h1}番 (300円)"},
            {"type": "quinella", "horses": sorted([h1, h2]), "stake_yen": 200, "label": f"馬連: {h1}-{h2} (200円)"},
            {"type": "quinella", "horses": sorted([h1, h3]), "stake_yen": 200, "label": f"馬連: {h1}-{h3} (200円)"},
            {"type": "quinella", "horses": sorted([h1, outsider]), "stake_yen": 200, "label": f"馬連: {h1}-{outsider} (200円)"},
            {"type": "trio", "horses": sorted([h1, h2, h3]), "stake_yen": 100, "label": f"3連複: {h1}-{h2}-{h3} (100円)"},
            {"type": "trio", "horses": sorted([h1, h2, outsider]), "stake_yen": 100, "label": f"3連複: {h1}-{h2}-{outsider} (100円)"},
            {"type": "trio", "horses": sorted([h1, h3, outsider]), "stake_yen": 100, "label": f"3連複: {h1}-{h3}-{outsider} (100円)"},
            {"type": "wide", "horses": sorted([h1, outsider]), "stake_yen": 100, "label": f"ワイド: {h1}-{outsider} (100円)"},
            {"type": "wide", "horses": sorted([h2, outsider]), "stake_yen": 100, "label": f"ワイド: {h2}-{outsider} (100円)"},
            {"type": "wide", "horses": sorted([h3, outsider]), "stake_yen": 100, "label": f"ワイド: {h3}-{outsider} (100円)"},
            {"type": "exacta", "horses": [h1, outsider, h2], "stake_yen": 100, "label": f"3連単: {h1}→{outsider}→{h2} (100円)"},
            {"type": "exacta", "horses": [h1, outsider, h3], "stake_yen": 100, "label": f"3連単: {h1}→{outsider}→{h3} (100円)"},
            {"type": "exacta", "horses": [h1, outsider, h4], "stake_yen": 100, "label": f"3連単: {h1}→{outsider}→{h4} (100円)"},
        ]
        # Scale the original idea into a consistent total: remove last lines if needed.
        lines = lines[:]
        pattern = "パターンB（穴馬を含む波乱型）"
        note = "穴馬の根拠は表示された取得情報に限定。高配当を保証するものではありません。"
    else:
        lines = [
            {"type": "win", "horses": [h1], "stake_yen": 500, "label": f"単勝: {h1}番 (500円)"},
            {"type": "quinella", "horses": sorted([h1, h2]), "stake_yen": 300, "label": f"馬連: {h1}-{h2} (300円)"},
            {"type": "quinella", "horses": sorted([h1, h3]), "stake_yen": 300, "label": f"馬連: {h1}-{h3} (300円)"},
            {"type": "trio", "horses": sorted([h1, h2, h3]), "stake_yen": 600, "label": f"3連複: {h1}-{h2}-{h3} (600円)"},
            {"type": "wide", "horses": sorted([h1, h4]), "stake_yen": 100, "label": f"ワイド: {h1}-{h4} (100円)"},
            {"type": "wide", "horses": sorted([h2, h4]), "stake_yen": 100, "label": f"ワイド: {h2}-{h4} (100円)"},
        ]
        pattern = "パターンA（上位評価中心）"
        note = "取得できた情報に基づく紙上シミュレーションです。的中・利益を保証しません。"

    # Ensure exactly 2,000 yen: trim or add a non-duplicated 100-yen wide line.
    total = sum(line["stake_yen"] for line in lines)
    while total > 2000 and lines:
        last = lines.pop()
        total -= last["stake_yen"]
    if total < 2000:
        for pair in ([h1, h2], [h1, h3], [h2, h3]):
            if total >= 2000:
                break
            lines.append({
                "type": "wide", "horses": sorted(pair), "stake_yen": 100,
                "label": f"ワイド: {pair[0]}-{pair[1]} (100円)",
            })
            total += 100
    return [{
        "pattern_type": "B" if pattern_b else "A",
        "pattern": pattern,
        "cost_yen": sum(line["stake_yen"] for line in lines),
        "lines": [line["label"] for line in lines],
        "line_items": lines,
        "note": note,
    }]


def settle_tickets(tickets, finish_numbers, payouts, payout_combinations):
    if not tickets or not finish_numbers:
        return {"race_cost": 2000, "win_return": 0, "race_profit": -2000, "win_hit": None, "settlement_status": "結果未取得"}
    finish_pos = {horse_no: index + 1 for index, horse_no in enumerate(finish_numbers)}
    # Exact combinations cannot be safely confirmed from all page layouts.
    # Win settlement is confirmed only when winner and win payout are both available.
    win_hit = None
    total_return = 0
    all_items = tickets[0].get("line_items", [])
    for item in all_items:
        kind = item["type"]
        horses = item["horses"]
        stake = int(item["stake_yen"])
        if kind == "win":
            hit = bool(finish_numbers and horses[0] == finish_numbers[0])
            if hit:
                win_hit = True
                if payouts.get("win", 0) > 0:
                    total_return += int(stake * payouts["win"] / 100)
            elif win_hit is None:
                win_hit = False
        # Other bet types are not settled unless combination data is confidently parsed.
        # Prevent fabricated returns from a generic payout amount with unknown combination.
    cost = int(tickets[0].get("cost_yen", 2000))
    return {
        "race_cost": cost,
        "win_return": total_return,
        "race_profit": total_return - cost,
        "win_hit": win_hit,
        "settlement_status": "単勝のみ確定・他券種は組合せ検証未対応",
    }


def parse_race(html, race_id, kind, base_url):
    soup = soup_of(html)
    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)
    meta_text = parse_meta(soup)

    time_match = re.search(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)", meta_text)
    post_time = time_match.group(1) if time_match else ""

    race_name = first_text(soup, [
        ".RaceName", ".race_name", "h1", ".RaceList_ItemTitle",
        "[class*='RaceName']", "[class*='raceName']",
    ])
    if not race_name or race_name in ["出馬表", "レース情報"]:
        race_name = f"{venue}{race_no}R" if venue and race_no else "レース名未取得"

    surface = "ダート" if re.search(r"ダート|ダ\s*\d{3,4}", meta_text) else (
        "芝" if "芝" in meta_text else ""
    )
    distance_match = re.search(r"(?:芝|ダート|ダ)?\s*(\d{3,4})\s*m", meta_text, re.I)
    if not distance_match:
        distance_match = re.search(r"(\d{3,4})\s*m", meta_text, re.I)
    distance = int(distance_match.group(1)) if distance_match else None

    runners = parse_runner_rows(soup, surface, venue)
    ranked = score_runners(runners, surface, venue)
    horse_by_no = {item["horse_no"]: item["name"] for item in ranked}

    outsiders = sorted(
        [item for item in ranked if item.get("odds") is not None and 10 <= item["odds"] < 30],
        key=lambda item: (-item["score"], item["horse_no"]),
    )[:3]
    longshots = sorted(
        [item for item in ranked if item.get("odds") is not None and item["odds"] >= 30],
        key=lambda item: (-item["score"], item["horse_no"]),
    )[:3]

    tickets = build_tickets(ranked, outsiders)
    is_finished = False
    if post_time:
        try:
            scheduled = NOW.replace(
                hour=int(post_time.split(":")[0]),
                minute=int(post_time.split(":")[1]),
                second=0, microsecond=0,
            )
            is_finished = NOW >= scheduled + timedelta(minutes=10)
        except (ValueError, IndexError):
            pass

    result_finishes = []
    win_hit = None
    win_return = 0
    race_cost = tickets[0]["cost_yen"] if tickets else 0
    race_profit = 0
    settlement_status = "発走前または結果待ち"
    payout_values = {"win": 0, "quinella": 0, "trio": 0, "wide": 0}

    if is_finished:
        result_finishes, payout_values, payout_combinations = get_result_data(base_url, race_id)
        if result_finishes:
            settlement = settle_tickets(tickets, result_finishes, payout_values, payout_combinations)
            win_hit = settlement["win_hit"]
            win_return = settlement["win_return"]
            race_cost = settlement["race_cost"]
            race_profit = settlement["race_profit"]
            settlement_status = settlement["settlement_status"]
        else:
            settlement_status = "結果ページから着順を確定できず"
    else:
        payout_combinations = {}

    # Give every ranking/outsider a human-readable reason, including uncertainty.
    for index, horse in enumerate(ranked, 1):
        horse["rank"] = index
        if horse.get("odds") is None:
            horse["reasons"].append("単勝オッズ未取得：市場評価の精度に制限")
        if horse.get("score_confidence", 0) < 60:
            horse["reasons"].append("取得項目が少ないため評価信頼度は低め")

    return {
        "id": str(race_id),
        "kind": kind,
        "category": "local" if kind == "地方" else "central",
        "race_no": race_no,
        "name": race_name,
        "course": venue or "競馬場未取得",
        "post_time": post_time or "未取得",
        "surface": surface or "未取得",
        "distance_m": distance,
        "runner_count": len(runners),
        "horses": ranked,
        "top5": ranked[:5],
        "outsiders": outsiders,
        "longshots": longshots,
        "tickets": tickets,
        "is_finished": is_finished,
        "result_finishes": result_finishes,
        "win_hit": win_hit,
        "win_return": win_return,
        "race_cost": race_cost,
        "race_profit": race_profit,
        "settlement_status": settlement_status,
        "payouts": payout_values,
        "is_recommended": bool(race_no == 11 or len(outsiders) >= 2),
    }


def load_history():
    if not HISTORY.exists():
        return {"schema_version": 20, "snapshots": {}}
    try:
        value = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("history root is not object")
        if not isinstance(value.get("snapshots"), dict):
            value["snapshots"] = {}
        value["schema_version"] = 20
        return value
    except (OSError, ValueError, json.JSONDecodeError):
        print("[WARN] history.json could not be read; starting a new history file")
        return {"schema_version": 20, "snapshots": {}}


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})
    # Keep the latest prediction for unsettled races. Once settled, retain the first
    # settled record to avoid silently rewriting historical performance on reruns.
    if old.get("is_finished") and old.get("win_hit") is not None:
        return
    snapshot = {
        "race_id": race_id,
        "date": race.get("date", TODAY_ISO),
        "kind": race.get("kind"),
        "course": race.get("course"),
        "race_no": race.get("race_no"),
        "name": race.get("name"),
        "cost": int(race.get("race_cost") or 0),
        "is_finished": bool(race.get("is_finished")),
        "win_hit": race.get("win_hit"),
        "win_return": int(race.get("win_return") or 0),
        "race_profit": int(race.get("race_profit") or 0),
        "settlement_status": race.get("settlement_status", ""),
        "updated_at": NOW.isoformat(),
    }
    snapshots[race_id] = snapshot


def calculate_stats(snapshots):
    settled = [
        item for item in snapshots.values()
        if item.get("is_finished") and item.get("win_hit") is not None
    ]
    total_return = sum(int(item.get("win_return") or 0) for item in settled)
    total_stake = sum(int(item.get("cost") or 0) for item in settled)
    win_hits = sum(1 for item in settled if item.get("win_hit") is True)
    roi = total_return / total_stake * 100 if total_stake else 0.0
    return {
        "races_settled": len(settled),
        "win_bets": len(settled),
        "win_hits": win_hits,
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
        "roi_pct": round(roi, 1),
        "win_hit_rate_pct": round(win_hits / len(settled) * 100, 1) if settled else 0.0,
        "accounting_note": "現状は単勝のみ払戻を計上。全券種の回収率ではありません。",
    }


def main():
    history_data = load_history()
    snapshots = history_data["snapshots"]
    today_races = []
    tomorrow_races = []
    errors = []

    for date_str, target_list, is_tomorrow in [
        (TODAY, today_races, False),
        (TOMORROW, tomorrow_races, True),
    ]:
        for source in SOURCES:
            list_html = get_html(source["list"] + date_str)
            race_ids = extract_race_ids(list_html)
            if not race_ids:
                errors.append(f"{source['kind']} {date_str}: レース一覧からIDを取得できませんでした")
                continue

            for race_id in race_ids:
                race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"
                html = get_html(race_url)
                if not html:
                    errors.append(f"{source['kind']} {race_id}: 出馬表取得失敗")
                    continue
                race = parse_race(html, race_id, source["kind"], source["base"])
                if race["runner_count"] >= MIN_RUNNERS:
                    race["date"] = (
                        (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
                        if is_tomorrow else TODAY_ISO
                    )
                    race["is_tomorrow"] = is_tomorrow
                    target_list.append(race)
                    if not is_tomorrow:
                        update_snapshot(snapshots, race)
                else:
                    errors.append(
                        f"{source['kind']} {race_id}: 出走馬を{race['runner_count']}頭しか解析できませんでした"
                    )
                time.sleep(REQUEST_DELAY)

    # Prune old history to keep the JSON file from growing without bound.
    cutoff = (NOW - timedelta(days=HISTORY_RETENTION_DAYS)).date()
    for race_id, item in list(snapshots.items()):
        try:
            item_date = datetime.strptime(item.get("date", ""), "%Y-%m-%d").date()
            if item_date < cutoff:
                del snapshots[race_id]
        except (ValueError, TypeError):
            continue

    stats = calculate_stats(snapshots)
    history_data.update({
        "updated_at": NOW.isoformat(),
        "stats": stats,
        "snapshots": snapshots,
    })
    save_json(HISTORY, history_data)

    tomorrow_recommended = [race for race in tomorrow_races if race.get("is_recommended")]
    status = "OK" if today_races or tomorrow_races else "NO_RACES"
    data = {
        "site": "BAGEN KEIBA",
        "engine_version": "BAGEN_20.0",
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": status,
        "warnings": errors[:100],
        "races": today_races,
        "tomorrow_races": tomorrow_recommended,
        "tomorrow_race_count": len(tomorrow_races),
        "paper_betting": {
            "mode": "paper_only",
            "stats": stats,
            "history": sorted(
                snapshots.values(),
                key=lambda item: (item.get("date", ""), item.get("race_id", "")),
                reverse=True,
            )[:100],
        },
    }
    save_json(OUT, data)
    print(
        f"BAGEN KEIBA v20.0 | status={status} | today={len(today_races)} "
        f"| tomorrow={len(tomorrow_races)} | tomorrow_recommended={len(tomorrow_recommended)} "
        f"| settled={stats['races_settled']} | ROI={stats['roi_pct']}%"
    )
    if errors:
        print(f"[WARN] {len(errors)} data retrieval/parsing warning(s). See docs/data.json -> warnings.")


if __name__ == "__main__":
    main()
