#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BAGEN KEIBA - Paper Prediction Engine
Python 3.12 / GitHub Actions / paper-only

- No real betting or payment actions.
- Scrapes publicly accessible race pages.
- Writes docs/data.json and docs/history.json.
- Settles only when the required result and payout data are available.
"""

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ============================================================
# Configuration
# ============================================================

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
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20
HISTORY_RETENTION_DAYS = 180
BET_BUDGET_YEN = 2000

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
        "list": (
            "https://race.netkeiba.com/"
            "top/race_list_sub.html?kaisai_date="
        ),
    },
    {
        "kind": "地方",
        "category": "local",
        "base": "https://nar.netkeiba.com",
        "list": (
            "https://nar.netkeiba.com/"
            "top/race_list_sub.html?kaisai_date="
        ),
    },
]

JRA_CODES = {
    "01": "札幌",
    "02": "函館",
    "03": "福島",
    "04": "新潟",
    "05": "東京",
    "06": "中山",
    "07": "中京",
    "08": "京都",
    "09": "阪神",
    "10": "小倉",
}

NAR_CODES = {
    "30": "帯広",
    "35": "盛岡",
    "36": "水沢",
    "40": "浦和",
    "41": "船橋",
    "42": "大井",
    "43": "川崎",
    "44": "大井",
    "45": "川崎",
    "46": "金沢",
    "47": "笠松",
    "48": "名古屋",
    "50": "園田",
    "51": "姫路",
    "54": "姫路",
    "55": "高知",
    "56": "佐賀",
}

DIRT_SIRES = [
    "ヘニーヒューズ",
    "シニスターミニスター",
    "パイロ",
    "マジェスティックウォリアー",
    "ホッコータルマエ",
    "アジアエクスプレス",
    "スマートファルコン",
    "ゴールドアリュール",
    "コパノリッキー",
]

POWER_SIRES = [
    "ロードカナロア",
    "エピファネイア",
    "キズナ",
    "オルフェーヴル",
    "モーリス",
    "ドゥラメンテ",
    "ハーツクライ",
    "ルーラーシップ",
    "ジャスタウェイ",
    "サトノダイヤモンド",
]

TOP_JOCKEYS = [
    "ルメール",
    "川田",
    "武豊",
    "戸崎",
    "横山武",
    "坂井",
    "松山",
    "デムーロ",
    "岩田望",
    "浜中",
    "菅原明",
    "横山和",
    "吉村智",
    "笹川翼",
    "森泰斗",
    "矢野貴",
]

POSITIVE_WORDS = [
    "好気配",
    "一変",
    "立て直し",
    "上向き",
    "絶好",
    "シャープ",
]

NEGATIVE_WORDS = [
    "太目",
    "硬い",
    "入れ込み",
    "不安",
    "モタれる",
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ============================================================
# General utilities
# ============================================================

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value):
    text = clean(value)
    text = text.replace(",", "").replace("．", ".")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", text)

    if not match:
        return None

    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def text_of(node):
    if node is None:
        return ""
    return clean(node.get_text(" ", strip=True))


def first_text(soup, selectors):
    for selector in selectors:
        try:
            element = soup.select_one(selector)
        except Exception:
            continue

        value = text_of(element)

        if value and "netkeiba" not in value.lower():
            return value

    return ""


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(path.suffix + ".tmp")

    temp.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    temp.replace(path)


def load_json(path, default):
    if not path.exists():
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[WARN] JSON read failed: {path.name}: {exc}")
        return default


def get_html(url):
    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        response.encoding = (
            response.apparent_encoding or "utf-8"
        )

        return response.text

    except requests.RequestException as exc:
        print(
            f"[WARN] GET failed: {url} "
            f"({exc.__class__.__name__})"
        )
        return ""


# ============================================================
# Race ID and venue
# ============================================================

def race_no_from_id(race_id):
    race_id = str(race_id)

    if not re.fullmatch(r"\d{12,14}", race_id):
        return None

    race_no = int(race_id[-2:])

    if 1 <= race_no <= 12:
        return race_no

    return None


def venue_from_id(race_id, kind):
    race_id = str(race_id)

    if not re.fullmatch(r"\d{12,14}", race_id):
        return ""

    code = race_id[4:6]

    mapping = JRA_CODES if kind == "中央" else NAR_CODES

    return mapping.get(code, "")


def extract_race_ids(html):
    if not html:
        return []

    soup = soup_of(html)
    found = []
    seen = set()

    for anchor in soup.select(
        'a[href*="race_id="], a[href*="shutuba.html"]'
    ):
        href = anchor.get("href", "")

        match = re.search(r"race_id=(\d{12,14})", href)

        if not match:
            continue

        race_id = match.group(1)

        if race_id in seen:
            continue

        if race_no_from_id(race_id) is None:
            continue

        seen.add(race_id)
        found.append(race_id)

    return found[:MAX_RACES_PER_SOURCE]


# ============================================================
# Race metadata
# ============================================================

def parse_meta(soup):
    parts = []
    selectors = [
        ".RaceData01",
        ".RaceData02",
        ".RaceData",
        ".race_data",
        "[class*='RaceData']",
        ".raceData01",
        ".raceData02",
    ]

    for selector in selectors:
        try:
            elements = soup.select(selector)
        except Exception:
            continue

        for element in elements:
            value = text_of(element)

            if value and value not in parts:
                parts.append(value)

    return " ".join(parts)


def parse_race_time(meta_text):
    match = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        meta_text or "",
    )

    if not match:
        return ""

    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_race_distance(meta_text):
    match = re.search(
        r"(?:芝|ダート|ダ)?\s*(\d{3,4})\s*m",
        meta_text or "",
        re.IGNORECASE,
    )

    if not match:
        match = re.search(
            r"(\d{3,4})\s*m",
            meta_text or "",
            re.IGNORECASE,
        )

    return int(match.group(1)) if match else None


# ============================================================
# Runner parsing
# ============================================================

def parse_runner_number(row):
    selectors = [
        "td.Umaban",
        ".Umaban",
        "[class*='Umaban']",
        "td.Num",
        "[class*='Num']",
    ]

    for selector in selectors:
        try:
            element = row.select_one(selector)
        except Exception:
            element = None

        value = number(text_of(element))

        if value is not None and 1 <= value <= 18:
            return int(value)

    for cell in row.find_all(
        ["td", "th"],
        recursive=False,
    )[:5]:
        classes = " ".join(cell.get("class", []))

        if "Waku" in classes:
            continue

        value = number(text_of(cell))

        if value is not None and 1 <= value <= 18:
            return int(value)

    return None


def parse_frame(row):
    for selector in [
        "td.Waku",
        ".Waku",
        "[class*='Waku']",
    ]:
        try:
            element = row.select_one(selector)
        except Exception:
            element = None

        value = number(text_of(element))

        if value is not None and 1 <= value <= 8:
            return int(value)

    return None


def parse_odds_popularity(row):
    odds = None
    popularity = None

    odds_selectors = [
        "td.Odds",
        ".Odds",
        "[class*='Odds']",
        ".odds",
        "td[class*='Odds']",
    ]

    for selector in odds_selectors:
        try:
            element = row.select_one(selector)
        except Exception:
            element = None

        value = number(text_of(element))

        if value is not None and 0 < value <= 9999:
            odds = value
            break

    popularity_selectors = [
        "td.Popular_Ninki",
        ".Popular_Ninki",
        "[class*='Ninki']",
        ".Popular",
        "td[class*='Popular']",
    ]

    for selector in popularity_selectors:
        try:
            element = row.select_one(selector)
        except Exception:
            element = None

        value = number(text_of(element))

        if value is not None and 1 <= value <= 18:
            popularity = int(value)
            break

    return odds, popularity


def parse_runner_rows(soup, surface, venue):
    rows = soup.select(
        "tr.HorseList, "
        "tr[class*='Horse'], "
        "table.Shutuba_Table tr, "
        "table.ShutubaTable tr"
    )

    runners = []
    seen_numbers = set()

    for row in rows:
        horse_anchor = row.select_one(
            'a[href*="/horse/"], a[href*="horse"]'
        )

        horse_name = text_of(horse_anchor)

        if not horse_name:
            continue

        if "馬名" in horse_name:
            continue

        horse_no = parse_runner_number(row)

        if horse_no is None:
            continue

        # 馬番で重複を防止する。馬名だけでは判定しない。
        if horse_no in seen_numbers:
            continue

        seen_numbers.add(horse_no)

        row_text = text_of(row)
        frame_no = parse_frame(row)
        odds, popularity = parse_odds_popularity(row)

        # FIX: 不正な ". jockey" セレクターを使用しない。
        jockey = text_of(
            row.select_one(
                ".Jockey, "
                "td.Jockey, "
                "[class*='Jockey'], "
                ".jockey, "
                "td[class*='jockey']"
            )
        )

        weight_text = text_of(
            row.select_one(
                "td.Horse_Weight, "
                ".Horse_Weight, "
                "[class*='HorseWeight'], "
                "[class*='Weight']"
            )
        )

        weight_match = re.search(
            r"\d{3}\s*\(([+-]?\d+)\)",
            weight_text,
        )

        weight_diff = (
            int(weight_match.group(1))
            if weight_match
            else 0
        )

        sire = ""

        sire_match = re.search(
            r"(?:父|種牡馬|Sire)[:：]?\s*([^\s（）()]+)",
            row_text,
        )

        if sire_match:
            sire = sire_match.group(1)

        is_dirt_blood = any(
            name in row_text or name in sire
            for name in DIRT_SIRES
        )

        is_power_blood = any(
            name in row_text or name in sire
            for name in POWER_SIRES
        )

        is_apprentice = any(
            mark in jockey
            for mark in ["▲", "△", "☆", "◇"]
        )

        is_top_jockey = any(
            name in jockey
            for name in TOP_JOCKEYS
        )

        is_positive = any(
            word in row_text
            for word in POSITIVE_WORDS
        )

        is_negative = any(
            word in row_text
            for word in NEGATIVE_WORDS
        )

        is_inner = frame_no in (1, 2) if frame_no else False
        is_outer = frame_no in (7, 8) if frame_no else False

        reasons = []

        if odds is not None:
            reasons.append(f"取得単勝オッズ {odds:g}倍")

        if popularity is not None:
            reasons.append(f"取得人気順位 {popularity}番人気")

        if jockey:
            reasons.append(f"騎手情報：{jockey}")

        if is_apprentice:
            reasons.append("減量記号のある騎手")

        if is_top_jockey:
            reasons.append("登録騎手リストに一致")

        if surface == "ダート" and is_dirt_blood:
            reasons.append("ダート適性候補の血統情報を検出")

        if surface == "芝" and is_power_blood:
            reasons.append("芝・持続力型血統の候補を検出")

        if weight_match and abs(weight_diff) >= 6:
            reasons.append(
                f"馬体重増減 {weight_diff:+d}kg"
            )

        if is_positive:
            reasons.append("掲載テキストに好材料ワード")

        if is_negative:
            reasons.append("掲載テキストに注意ワード")

        data_quality = {
            "odds": odds is not None,
            "popularity": popularity is not None,
            "jockey": bool(jockey),
            "frame": frame_no is not None,
            "weight_change": weight_match is not None,
        }

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
            "rank": None,
            "reasons": reasons,
            "caution": (
                "取得できた情報に基づく参考評価。"
                "実績・調教・展開を完全に反映したものではありません。"
            ),
            "is_apprentice": is_apprentice,
            "is_top_jockey": is_top_jockey,
            "is_inner": is_inner,
            "is_outer": is_outer,
            "is_dirt_blood": is_dirt_blood,
            "is_power_blood": is_power_blood,
            "is_positive_memo": is_positive,
            "is_negative_memo": is_negative,
            "w_diff": weight_diff,
            "data_quality": data_quality,
        })

    runners.sort(
        key=lambda item: item["horse_no"]
    )

    return runners


# ============================================================
# Ranking model
# ============================================================

def score_runners(
    runners,
    surface,
    venue,
    is_heavy_track=False,
):
    for horse in runners:
        score = 0.0

        odds = horse.get("odds")
        popularity = horse.get("popularity")

        # オッズ・人気は市場評価の代理指標。
        # 勝率そのものとして扱わない。
        if odds is not None and odds > 0:
            score += max(
                0.0,
                42.0 - 8.0 * math.log(max(1.0, odds)),
            )

        if popularity is not None:
            score += max(
                0.0,
                16.0 - (popularity - 1) * 1.1,
            )

        if horse["is_top_jockey"]:
            score += 3.0

        if horse["is_apprentice"]:
            score += 1.5

        blood_multiplier = 1.5 if is_heavy_track else 1.0

        if surface == "ダート" and horse["is_dirt_blood"]:
            score += 2.0 * blood_multiplier

            if is_heavy_track:
                horse["reasons"].append(
                    "道悪ダート血統の簡易補正"
                )

        elif surface == "芝" and horse["is_power_blood"]:
            score += 1.5 * blood_multiplier

            if is_heavy_track:
                horse["reasons"].append(
                    "道悪芝血統の簡易補正"
                )

        if venue in ["東京", "新潟"] and horse["is_outer"]:
            score += 1.0
            horse["reasons"].append(
                "競馬場・外枠の簡易補正"
            )

        elif venue in [
            "中山",
            "小倉",
            "福島",
            "札幌",
        ] and horse["is_inner"]:
            score += 1.0
            horse["reasons"].append(
                "競馬場・内枠の簡易補正"
            )

        diff = horse.get("w_diff", 0)

        if 8 <= diff <= 16:
            score += 1.0
            horse["reasons"].append(
                "馬体重増加の簡易評価"
            )

        if horse["is_positive_memo"]:
            score += 1.0

        if horse["is_negative_memo"]:
            score -= 2.0
            horse["reasons"].append(
                "注意ワード検出による減点"
            )

        if (
            popularity == 1
            and odds is not None
            and odds < 1.8
        ):
            score -= 1.0
            horse["reasons"].append(
                "低オッズのため妙味を控えめ評価"
            )

        quality = horse.get("data_quality", {})

        confidence_ratio = (
            sum(bool(value) for value in quality.values()) / 5
        )

        score *= 0.8 + 0.2 * confidence_ratio

        horse["score"] = round(score, 2)
        horse["score_confidence"] = round(
            confidence_ratio * 100
        )

        if not horse["reasons"]:
            horse["reasons"].append(
                "取得情報が少ないため評価根拠は限定的"
            )

        if odds is None:
            horse["reasons"].append(
                "単勝オッズ未取得"
            )

        if horse["score_confidence"] < 60:
            horse["reasons"].append(
                "取得項目が少なく信頼度に制限"
            )

    return sorted(
        runners,
        key=lambda item: (
            -item["score"],
            item["horse_no"],
        ),
    )


# ============================================================
# Ticket construction
# ============================================================

def ticket_item(kind, horses, stake, label):
    return {
        "type": kind,
        "horses": list(horses),
        "stake_yen": int(stake),
        "label": label,
    }


def build_tickets(ranked, outsiders):
    if len(ranked) < 3:
        return []

    top = ranked[:5]

    h1 = top[0]["horse_no"]
    h2 = top[1]["horse_no"]
    h3 = top[2]["horse_no"]
    h4 = top[3]["horse_no"] if len(top) >= 4 else h3

    outsider = None

    for horse in outsiders:
        candidate = horse["horse_no"]

        if candidate not in {h1, h2, h3, h4}:
            outsider = candidate
            break

    pattern_b = (
        outsider is not None
        and (
            (top[0].get("odds") or 0) >= 2.8
            or len(outsiders) >= 2
        )
    )

    lines = []

    if pattern_b:
        lines.extend([
            ticket_item(
                "win", [h1], 300,
                f"単勝: {h1}番 (300円)"
            ),
            ticket_item(
                "quinella", sorted([h1, h2]), 200,
                f"馬連: {h1}-{h2} (200円)"
            ),
            ticket_item(
                "quinella", sorted([h1, h3]), 200,
                f"馬連: {h1}-{h3} (200円)"
            ),
            ticket_item(
                "quinella", sorted([h1, outsider]), 200,
                f"馬連: {h1}-{outsider} (200円)"
            ),
            ticket_item(
                "trio", sorted([h1, h2, h3]), 100,
                f"3連複: {h1}-{h2}-{h3} (100円)"
            ),
            ticket_item(
                "trio", sorted([h1, h2, outsider]), 100,
                f"3連複: {h1}-{h2}-{outsider} (100円)"
            ),
            ticket_item(
                "trio", sorted([h1, h3, outsider]), 100,
                f"3連複: {h1}-{h3}-{outsider} (100円)"
            ),
            ticket_item(
                "wide", sorted([h1, outsider]), 100,
                f"ワイド: {h1}-{outsider} (100円)"
            ),
            ticket_item(
                "wide", sorted([h2, outsider]), 100,
                f"ワイド: {h2}-{outsider} (100円)"
            ),
            ticket_item(
                "wide", sorted([h3, outsider]), 100,
                f"ワイド: {h3}-{outsider} (100円)"
            ),
            ticket_item(
                "trifecta", [h1, outsider, h2], 100,
                f"3連単: {h1}→{outsider}→{h2} (100円)"
            ),
            ticket_item(
                "trifecta", [h1, outsider, h3], 100,
                f"3連単: {h1}→{outsider}→{h3} (100円)"
            ),
            ticket_item(
                "trifecta", [h1, outsider, h4], 100,
                f"3連単: {h1}→{outsider}→{h4} (100円)"
            ),
        ])

        pattern = "パターンB（穴馬を含む波乱型）"
        note = (
            "穴馬の根拠は取得できた情報に限定。"
            "3連単は着順まで一致した場合のみ的中判定。"
        )

    else:
        lines.extend([
            ticket_item(
                "win", [h1], 500,
                f"単勝: {h1}番 (500円)"
            ),
            ticket_item(
                "quinella", sorted([h1, h2]), 300,
                f"馬連: {h1}-{h2} (300円)"
            ),
            ticket_item(
                "quinella", sorted([h1, h3]), 300,
                f"馬連: {h1}-{h3} (300円)"
            ),
            ticket_item(
                "trio", sorted([h1, h2, h3]), 600,
                f"3連複: {h1}-{h2}-{h3} (600円)"
            ),
            ticket_item(
                "wide", sorted([h1, h4]), 100,
                f"ワイド: {h1}-{h4} (100円)"
            ),
            ticket_item(
                "wide", sorted([h2, h4]), 100,
                f"ワイド: {h2}-{h4} (100円)"
            ),
        ])

        pattern = "パターンA（上位評価中心）"
        note = (
            "取得情報に基づく紙上シミュレーション。"
            "的中や利益を保証するものではありません。"
        )

    # 2,000円に合わせる。
    # 追加するワイドは、既存の組み合わせと重複させない。
    total = sum(item["stake_yen"] for item in lines)

    candidate_pairs = [
        sorted([h1, h2]),
        sorted([h1, h3]),
        sorted([h2, h3]),
        sorted([h1, h4]),
        sorted([h2, h4]),
        sorted([h3, h4]),
    ]

    existing = {
        (item["type"], tuple(item["horses"]))
        for item in lines
    }

    pair_index = 0

    while total < BET_BUDGET_YEN:
        pair = candidate_pairs[pair_index % len(candidate_pairs)]
        pair_index += 1

        key = ("wide", tuple(pair))

        if key in existing:
            # 既存買い目と同じ組み合わせでも、追加購入は可能。
            # 同一券種・組み合わせへの追加購入として記録する。
            pass

        lines.append(
            ticket_item(
                "wide",
                pair,
                100,
                f"ワイド: {pair[0]}-{pair[1]} (100円)"
            )
        )

        existing.add(key)
        total += 100

    # 念のため、予算が超過した場合は末尾から調整。
    while total > BET_BUDGET_YEN and lines:
        last = lines.pop()
        total -= last["stake_yen"]

    if total != BET_BUDGET_YEN:
        print(
            f"[WARN] Ticket budget mismatch: {total} yen"
        )

    return [{
        "pattern_type": "B" if pattern_b else "A",
        "pattern": pattern,
        "cost_yen": total,
        "lines": [
            item["label"] for item in lines
        ],
        "line_items": lines,
        "note": note,
    }]


# ============================================================
# Result parsing and payout mapping
# ============================================================

def canonical_combo(kind, numbers):
    values = [int(value) for value in numbers]

    if kind in ("win",):
        return str(values[0]) if values else ""

    if kind in ("quinella", "wide", "trio"):
        return "-".join(
            str(value) for value in sorted(values)
        )

    if kind == "trifecta":
        return "-".join(str(value) for value in values)

    return ""


def detect_payout_type(text):
    text = clean(text)

    # 3連単と3連複を先に判定する。
    if "3連単" in text or "三連単" in text:
        return "trifecta"

    if "3連複" in text or "三連複" in text:
        return "trio"

    if "馬連" in text:
        return "quinella"

    if "ワイド" in text:
        return "wide"

    if "単勝" in text:
        return "win"

    return None


def parse_payouts(soup):
    """
    払戻表を券種ごと・組み合わせごとに解析する。

    payout value is yen per 100 yen stake.
    If a combination cannot be identified, it is not guessed.
    """

    payouts = {
        "win": {},
        "quinella": {},
        "trio": {},
        "wide": {},
        "trifecta": {},
    }

    # Netkeibaの払戻表で使われることのある表クラス。
    rows = soup.select(
        "table.Payout_Detail_Table tr, "
        "table.PayoutTable tr, "
        "table.RacePayout tr, "
        "table[class*='Payout'] tr, "
        "tr"
    )

    seen_rows = set()

    for row in rows:
        row_text = text_of(row)

        if not row_text:
            continue

        # 重複した行の処理を避ける。
        if row_text in seen_rows:
            continue

        seen_rows.add(row_text)

        kind = detect_payout_type(row_text)

        if not kind:
            continue

        cells = row.find_all(
            ["td", "th"],
            recursive=False,
        )

        if not cells:
            continue

        cell_texts = [
            text_of(cell) for cell in cells
        ]

        # 金額候補を抽出。払戻金は通常「1,230円」形式。
        amounts = []

        for value in cell_texts:
            match = re.search(
                r"([\d,]+)\s*円",
                value,
            )

            if match:
                try:
                    amounts.append(
                        int(match.group(1).replace(",", ""))
                    )
                except ValueError:
                    pass

        if not amounts:
            continue

        payout_yen = amounts[-1]

        if payout_yen < 0:
            continue

        combo = ""

        # 馬番の組み合わせを含むセルを優先する。
        for value in cell_texts:
            if re.search(r"\d+\s*[-－]\s*\d+", value):
                nums = re.findall(r"\d+", value)

                if kind == "win" and len(nums) >= 1:
                    combo = canonical_combo(
                        kind,
                        [nums[0]],
                    )
                    break

                if kind in ("quinella", "wide") and len(nums) >= 2:
                    combo = canonical_combo(
                        kind,
                        nums[:2],
                    )
                    break

                if kind == "trio" and len(nums) >= 3:
                    combo = canonical_combo(
                        kind,
                        nums[:3],
                    )
                    break

                if kind == "trifecta" and len(nums) >= 3:
                    combo = canonical_combo(
                        kind,
                        nums[:3],
                    )
                    break

        # 表が「馬番」と「払戻金」を別々にしているケースへの対応。
        if not combo:
            for value in cell_texts:
                if re.search(r"円", value):
                    continue

                nums = re.findall(r"\d+", value)

                if kind == "win" and len(nums) == 1:
                    combo = canonical_combo(kind, nums[:1])
                    break

                if kind in ("quinella", "wide") and len(nums) == 2:
                    combo = canonical_combo(kind, nums[:2])
                    break

                if kind in ("trio", "trifecta") and len(nums) == 3:
                    combo = canonical_combo(kind, nums[:3])
                    break

        if combo:
            payouts[kind][combo] = payout_yen

    return payouts


def parse_finish_rows(soup):
    """
    着順と馬番を可能な範囲で抽出する。
    同じ着順の重複や、馬番の誤認を避けるため候補を検証する。
    """

    finish_map = {}

    rows = soup.select(
        "table.RaceTable01 tr, "
        "table.ResultTable tr, "
        "table.RaceTable tr, "
        "table.race_table_01 tr, "
        "tr.HorseList"
    )

    for row in rows:
        row_text = text_of(row)

        if not row_text:
            continue

        finish = None

        for selector in [
            "td.Rank",
            ".Rank",
            "td.Result_Num",
            ".Result_Num",
            "td[class*='Rank']",
            "td[class*='Result']",
        ]:
            try:
                element = row.select_one(selector)
            except Exception:
                element = None

            value = number(text_of(element))

            if value is not None and 1 <= value <= 18:
                finish = int(value)
                break

        cells = row.find_all(
            ["td", "th"],
            recursive=False,
        )

        # 順位専用クラスがない場合は先頭セルを候補にする。
        if finish is None and cells:
            first = text_of(cells[0])

            match = re.fullmatch(
                r"(\d{1,2})",
                first,
            )

            if match:
                value = int(match.group(1))

                if 1 <= value <= 18:
                    finish = value

        if finish is None:
            continue

        horse_no = None

        for selector in [
            "td.Umaban",
            ".Umaban",
            "[class*='Umaban']",
        ]:
            try:
                element = row.select_one(selector)
            except Exception:
                element = None

            value = number(text_of(element))

            if value is not None and 1 <= value <= 18:
                horse_no = int(value)
                break

        # 馬番専用セルがない場合、先頭の順位セルを除いて確認する。
        if horse_no is None:
            for cell in cells[1:6]:
                classes = " ".join(cell.get("class", []))

                if "Rank" in classes or "Result" in classes:
                    continue

                value = number(text_of(cell))

                if value is not None and 1 <= value <= 18:
                    horse_no = int(value)
                    break

        if horse_no is None:
            continue

        if finish not in finish_map:
            finish_map[finish] = horse_no

    return finish_map


def get_result_data(base_url, race_id):
    url = f"{base_url}/race/result.html?race_id={race_id}"
    html = get_html(url)

    if not html:
        return [], {
            "win": {},
            "quinella": {},
            "trio": {},
            "wide": {},
            "trifecta": {},
        }

    soup = soup_of(html)

    finish_map = parse_finish_rows(soup)

    finishes = [
        finish_map[position]
        for position in sorted(finish_map)
        if position in (1, 2, 3)
    ]

    payouts = parse_payouts(soup)

    return finishes, payouts


# ============================================================
# Ticket settlement
# ============================================================

def settle_tickets(tickets, finish_numbers, payouts):
    """
    全券種の組み合わせを照合する。

    払戻情報が必要なのに見つからない場合は、
    収支を確定扱いにしない。
    """

    if not tickets or len(finish_numbers) < 3:
        return {
            "race_cost": BET_BUDGET_YEN,
            "win_return": 0,
            "race_profit": -BET_BUDGET_YEN,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "着順データ不足",
        }

    items = tickets[0].get("line_items", [])

    cost = int(
        tickets[0].get("cost_yen", BET_BUDGET_YEN)
    )

    first = int(finish_numbers[0])
    top2 = set(int(x) for x in finish_numbers[:2])
    top3 = set(int(x) for x in finish_numbers[:3])

    total_return = 0
    win_hit = False
    missing_hit_payout = False

    for item in items:
        kind = item.get("type")
        horses = item.get("horses", [])
        stake = int(item.get("stake_yen", 0))

        if not horses or stake <= 0:
            continue

        hit = False
        combo = ""

        if kind == "win":
            hit = int(horses[0]) == first
            combo = canonical_combo("win", horses[:1])

            if hit:
                win_hit = True

        elif kind == "quinella":
            hit = (
                len(horses) == 2
                and set(int(x) for x in horses) == top2
            )
            combo = canonical_combo(kind, horses)

        elif kind == "trio":
            hit = (
                len(horses) == 3
                and set(int(x) for x in horses) == top3
            )
            combo = canonical_combo(kind, horses)

        elif kind == "wide":
            hit = (
                len(horses) == 2
                and set(int(x) for x in horses).issubset(top3)
            )
            combo = canonical_combo(kind, horses)

        elif kind == "trifecta":
            hit = (
                len(horses) == 3
                and [int(x) for x in horses]
                == [int(x) for x in finish_numbers[:3]]
            )
            combo = canonical_combo(kind, horses)

        if not hit:
            continue

        payout_table = payouts.get(kind, {})
        payout_yen = payout_table.get(combo)

        if payout_yen is None:
            missing_hit_payout = True
            continue

        # 払戻金は100円購入時の金額。
        total_return += int(
            stake * int(payout_yen) / 100
        )

    if missing_hit_payout:
        return {
            "race_cost": cost,
            "win_return": 0,
            "race_profit": 0,
            "win_hit": win_hit,
            "settlement_complete": False,
            "settlement_status": (
                "的中候補あり・払戻金未取得のため収支未確定"
            ),
        }

    return {
        "race_cost": cost,
        "win_return": total_return,
        "race_profit": total_return - cost,
        "win_hit": win_hit,
        "settlement_complete": True,
        "settlement_status": "決済完了",
    }


# ============================================================
# Parse a race
# ============================================================

def parse_race(html, race_id, kind, base_url):
    soup = soup_of(html)

    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)
    meta_text = parse_meta(soup)

    post_time = parse_race_time(meta_text)

    race_name = first_text(
        soup,
        [
            ".RaceName",
            ".race_name",
            "h1",
            ".RaceList_ItemTitle",
            "[class*='RaceName']",
            "[class*='raceName']",
        ],
    )

    if not race_name or race_name in [
        "出馬表",
        "レース情報",
    ]:
        race_name = (
            f"{venue}{race_no}R"
            if venue and race_no
            else "レース名未取得"
        )

    if re.search(r"ダート|ダ\s*\d{3,4}", meta_text):
        surface = "ダート"
    elif "芝" in meta_text:
        surface = "芝"
    else:
        surface = ""

    is_heavy_track = bool(
        re.search(r"重|不良", meta_text)
    )

    distance = parse_race_distance(meta_text)

    runners = parse_runner_rows(
        soup,
        surface,
        venue,
    )

    ranked = score_runners(
        runners,
        surface,
        venue,
        is_heavy_track,
    )

    outsiders = sorted(
        [
            item for item in ranked
            if item.get("odds") is not None
            and 10 <= item["odds"] < 30
        ],
        key=lambda item: (
            -item["score"],
            item["horse_no"],
        ),
    )[:3]

    longshots = sorted(
        [
            item for item in ranked
            if item.get("odds") is not None
            and item["odds"] >= 30
        ],
        key=lambda item: (
            -item["score"],
            item["horse_no"],
        ),
    )[:3]

    tickets = build_tickets(
        ranked,
        outsiders,
    )

    is_finished = False

    if post_time:
        try:
            scheduled = NOW.replace(
                hour=int(post_time[:2]),
                minute=int(post_time[3:5]),
                second=0,
                microsecond=0,
            )

            is_finished = (
                NOW >= scheduled + timedelta(minutes=10)
            )

        except (ValueError, IndexError):
            is_finished = False

    result_finishes = []
    win_hit = None
    win_return = 0
    race_cost = (
        tickets[0]["cost_yen"]
        if tickets
        else 0
    )
    race_profit = 0

    settlement_complete = False
    settlement_status = "発走前または結果待ち"

    payout_values = {
        "win": {},
        "quinella": {},
        "trio": {},
        "wide": {},
        "trifecta": {},
    }

    if is_finished:
        result_finishes, payout_values = get_result_data(
            base_url,
            race_id,
        )

        if len(result_finishes) >= 3 and tickets:
            settlement = settle_tickets(
                tickets,
                result_finishes,
                payout_values,
            )

            win_hit = settlement["win_hit"]
            win_return = settlement["win_return"]
            race_cost = settlement["race_cost"]
            race_profit = settlement["race_profit"]

            settlement_complete = settlement[
                "settlement_complete"
            ]

            settlement_status = settlement[
                "settlement_status"
            ]

        else:
            settlement_status = (
                "着順または買い目データを確定できず"
            )

    for index, horse in enumerate(ranked, 1):
        horse["rank"] = index

    recommended = (
        race_no == 11
        or len(outsiders) >= 2
    )

    return {
        "id": str(race_id),
        "kind": kind,
        "category": (
            "local" if kind == "地方" else "central"
        ),
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
        "settlement_complete": settlement_complete,
        "settlement_status": settlement_status,
        "payouts": payout_values,
        "is_recommended": bool(recommended),
    }


# ============================================================
# History and statistics
# ============================================================

def load_history():
    default = {
        "schema_version": 22,
        "snapshots": {},
    }

    value = load_json(HISTORY, default)

    if not isinstance(value, dict):
        value = default

    if not isinstance(value.get("snapshots"), dict):
        value["snapshots"] = {}

    value["schema_version"] = 22

    return value


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})

    # 決済完了済みのレースは、後続の取得失敗で上書きしない。
    if old.get("settlement_complete") is True:
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
        "settlement_complete": bool(
            race.get("settlement_complete")
        ),
        "settlement_status": race.get(
            "settlement_status",
            "",
        ),
        "updated_at": NOW.isoformat(),
    }

    snapshots[race_id] = snapshot


def calculate_stats(snapshots):
    settled = [
        item for item in snapshots.values()
        if (
            item.get("settlement_complete") is True
            and item.get("is_finished") is True
            and item.get("win_hit") is not None
        )
    ]

    total_stake = sum(
        int(item.get("cost") or 0)
        for item in settled
    )

    total_return = sum(
        int(item.get("win_return") or 0)
        for item in settled
    )

    win_hits = sum(
        1 for item in settled
        if item.get("win_hit") is True
    )

    count = len(settled)

    roi = (
        total_return / total_stake * 100
        if total_stake > 0
        else 0.0
    )

    return {
        "races_settled": count,
        "win_bets": count,
        "win_hits": win_hits,
        "total_stake_yen": total_stake,
        "total_return_yen": total_return,
        "roi_pct": round(roi, 1),
        "win_hit_rate_pct": (
            round(win_hits / count * 100, 1)
            if count
            else 0.0
        ),
        "accounting_note": (
            "紙上シミュレーション。"
            "着順・券種・馬番の組み合わせを照合し、"
            "払戻データ不足のレースは集計対象外。"
        ),
    }


# ============================================================
# Main
# ============================================================

def main():
    history_data = load_history()
    snapshots = history_data["snapshots"]

    today_races = []
    tomorrow_races = []
    errors = []

    targets = [
        (TODAY, today_races, False),
        (TOMORROW, tomorrow_races, True),
    ]

    for date_str, target_list, is_tomorrow in targets:
        for source in SOURCES:
            list_url = source["list"] + date_str
            list_html = get_html(list_url)

            race_ids = extract_race_ids(list_html)

            if not race_ids:
                errors.append(
                    f"{source['kind']} {date_str}: "
                    "レース一覧からIDを取得できませんでした"
                )
                continue

            for race_id in race_ids:
                race_url = (
                    f"{source['base']}/race/"
                    f"shutuba.html?race_id={race_id}"
                )

                html = get_html(race_url)

                if not html:
                    errors.append(
                        f"{source['kind']} {race_id}: "
                        "出馬表取得失敗"
                    )
                    time.sleep(REQUEST_DELAY)
                    continue

                try:
                    race = parse_race(
                        html,
                        race_id,
                        source["kind"],
                        source["base"],
                    )

                except Exception as exc:
                    errors.append(
                        f"{source['kind']} {race_id}: "
                        f"解析エラー {type(exc).__name__}: {exc}"
                    )
                    time.sleep(REQUEST_DELAY)
                    continue

                if race["runner_count"] >= MIN_RUNNERS:
                    race["date"] = (
                        (
                            NOW + timedelta(days=1)
                        ).strftime("%Y-%m-%d")
                        if is_tomorrow
                        else TODAY_ISO
                    )

                    race["is_tomorrow"] = is_tomorrow
                    target_list.append(race)

                    if not is_tomorrow:
                        update_snapshot(
                            snapshots,
                            race,
                        )

                else:
                    errors.append(
                        f"{source['kind']} {race_id}: "
                        f"解析できた出走馬が"
                        f"{race['runner_count']}頭"
                    )

                time.sleep(REQUEST_DELAY)

    # 取得失敗時に既存データを消さない。
    # 今日のレースが全く取れなかった場合は、
    # 前回データが存在すれば保護して終了する。
    previous_data = load_json(OUT, {})

    if (
        not today_races
        and not tomorrow_races
        and isinstance(previous_data, dict)
        and (
            previous_data.get("races")
            or previous_data.get("tomorrow_races")
        )
    ):
        print(
            "[ERROR] No races were parsed. "
            "Keeping existing docs/data.json to avoid "
            "overwriting valid data with an empty result."
        )
        print(
            "[WARN] Check docs/data.json -> warnings "
            "and the race-list response."
        )
        raise RuntimeError(
            "全レースの取得・解析に失敗したため、"
            "既存データを保護して処理を停止しました。"
        )

    cutoff = (
        NOW - timedelta(days=HISTORY_RETENTION_DAYS)
    ).date()

    for race_id, item in list(snapshots.items()):
        try:
            item_date = datetime.strptime(
                item.get("date", ""),
                "%Y-%m-%d",
            ).date()

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

    tomorrow_recommended = [
        race for race in tomorrow_races
        if race.get("is_recommended")
    ]

    status = (
        "OK"
        if today_races or tomorrow_races
        else "NO_RACES"
    )

    output = {
        "site": "BAGEN KEIBA",
        "engine_version": "BAGEN_22.0",
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
                key=lambda item: (
                    item.get("date", ""),
                    item.get("race_id", ""),
                ),
                reverse=True,
            )[:100],
        },
    }

    save_json(OUT, output)

    print(
        f"BAGEN KEIBA v22.0 | "
        f"status={status} | "
        f"today={len(today_races)} | "
        f"tomorrow={len(tomorrow_races)} | "
        f"tomorrow_recommended={len(tomorrow_recommended)} | "
        f"settled={stats['races_settled']} | "
        f"ROI={stats['roi_pct']}%"
    )

    if errors:
        print(
            f"[WARN] {len(errors)} retrieval/parsing warning(s). "
            "See docs/data.json -> warnings."
        )


if __name__ == "__main__":
    main()