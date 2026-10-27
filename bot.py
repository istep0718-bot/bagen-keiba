#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v28.3
中央・地方競馬 / レース一覧取得 / 出走馬解析 / 簡易予想 / 紙上検証 / 結果精算

無料GitHub Actions向け。実際の馬券購入・口座接続は行わない。
既存 history.json の snapshots / stats / horse_form_cache を維持する。
"""

import json
import math
import re
import time
import html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from itertools import combinations

import requests
from bs4 import BeautifulSoup


# ============================================================
# 1. 設定
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

ENGINE_VERSION = "BAGEN_28.3"

TIMEOUT = (10, 25)
DELAY = 0.35
MAX_WARNINGS = 150
MAX_RACES_PER_SOURCE = 100
RETENTION_DAYS = 180
PAPER_BUDGET_YEN = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6",
    "Referer": "https://race.netkeiba.com/",
}

SOURCES = [
    {
        "kind": "中央",
        "category": "central",
        "base": "https://race.netkeiba.com",
        "list_urls": [
            "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
            "https://race.netkeiba.com/top/race_list.html?kaisai_date={date}",
        ],
    },
    {
        "kind": "地方",
        "category": "local",
        "base": "https://nar.netkeiba.com",
        "list_urls": [
            "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
            "https://nar.netkeiba.com/top/race_list.html?kaisai_date={date}",
        ],
    },
]

JRA_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}

NAR_CODES = {
    "30": "帯広",
    "35": "盛岡",
    "36": "水沢",
    "37": "門別",
    "38": "門別",
    "39": "門別",
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
    "ヘニーヒューズ", "シニスターミニスター", "パイロ",
    "マジェスティックウォリアー", "ホッコータルマエ",
    "アジアエクスプレス", "スマートファルコン",
    "ゴールドアリュール", "コパノリッキー",
]

POWER_SIRES = [
    "ロードカナロア", "エピファネイア", "キズナ",
    "オルフェーヴル", "モーリス", "ドゥラメンテ",
    "ハーツクライ", "ルーラーシップ", "ジャスタウェイ",
    "サトノダイヤモンド",
]

TOP_JOCKEYS = [
    "ルメール", "川田", "武豊", "戸崎", "横山武", "坂井",
    "松山", "デムーロ", "岩田望", "浜中", "菅原明",
    "横山和", "吉村智", "笹川翼", "森泰斗", "矢野貴",
]

POSITIVE_WORDS = ["好気配", "一変", "立て直し", "上向き", "絶好", "シャープ"]
NEGATIVE_WORDS = ["太目", "硬い", "入れ込み", "不安", "モタれる"]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)
WARNINGS = []


# ============================================================
# 2. 共通処理
# ============================================================

def warn(message):
    message = str(message)
    print("[WARN]", message)
    if len(WARNINGS) < MAX_WARNINGS:
        WARNINGS.append(message)


def clean(value):
    value = html_lib.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def soup_of(source):
    return BeautifulSoup(source or "", "html.parser")


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def numeric(value):
    value = clean(value).replace(",", "").replace("．", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def get_html(url):
    try:
        response = SESSION.get(url, timeout=TIMEOUT)
        response.raise_for_status()

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        source = response.text

        if not source or len(source) < 100:
            warn(f"HTMLが空または短すぎます: {url}")
            return ""

        lower = source.lower()
        if (
            "アクセスが集中" in source
            or "アクセス制限" in source
            or "too many requests" in lower
        ):
            warn(f"アクセス制限の可能性: {url}")
            return ""

        time.sleep(DELAY)
        return source

    except requests.RequestException as exc:
        warn(f"HTTP取得失敗: {url} ({exc.__class__.__name__})")
        return ""


def valid_race_id(value):
    return bool(re.fullmatch(r"\d{12,14}", str(value or "")))


def race_no_from_id(race_id):
    if not valid_race_id(race_id):
        return None
    number = safe_int(str(race_id)[-2:], 0)
    return number if 1 <= number <= 12 else None


def venue_from_id(race_id, kind):
    if not valid_race_id(race_id):
        return ""
    code = str(race_id)[4:6]
    table = JRA_CODES if kind == "中央" else NAR_CODES
    return table.get(code, "")


def extract_ids_from_url(url):
    ids = []

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        ids.extend(query.get("race_id", []))
        ids.extend(re.findall(r"/race/(\d{12,14})(?:/|$)", parsed.path))
    except Exception:
        pass

    ids.extend(re.findall(r"race_id=(\d{12,14})", url or ""))

    return [x for x in ids if valid_race_id(x) and race_no_from_id(x)]


def combo_key(horses, ordered=False):
    """JSONシリアライズ可能な組み合わせキーを生成"""
    if ordered:
        return "-".join(str(h) for h in horses)
    return "-".join(str(h) for h in sorted(horses))


# ============================================================
# 3. レース一覧取得
# ============================================================

def extract_race_ids(source_html):
    if not source_html:
        return []

    soup = soup_of(source_html)
    found = []
    seen = set()

    def add(value):
        value = str(value or "")
        if valid_race_id(value) and race_no_from_id(value) and value not in seen:
            seen.add(value)
            found.append(value)

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        for race_id in extract_ids_from_url(href):
            add(race_id)

    patterns = [
        r"race_id\s*[\"']?\s*[:=]\s*[\"']?(\d{12,14})",
        r"race_id%3D(\d{12,14})",
        r"/race/(\d{12,14})(?:/|[\"'?&#])",
        r"race_id=(\d{12,14})",
    ]

    for pattern in patterns:
        for match in re.findall(pattern, source_html, flags=re.I):
            add(match)

    return found[:MAX_RACES_PER_SOURCE]


def fetch_race_ids(source, date_str):
    combined = []
    seen = set()
    attempted = []

    for template in source["list_urls"]:
        url = template.format(date=date_str)
        attempted.append(url)
        page = get_html(url)

        if not page:
            continue

        ids = extract_race_ids(page)
        print(
            f"[INFO] 一覧解析 {source['kind']} {date_str}: "
            f"{len(ids)}件 ({url})"
        )

        for race_id in ids:
            if source["kind"] == "地方":
                id_date = str(race_id)[6:10]
                expected = date_str[4:8]
                if id_date != expected:
                    continue

            if race_id not in seen:
                seen.add(race_id)
                combined.append(race_id)

        if combined:
            break

    if not combined:
        warn(
            f"{source['kind']} {date_str}: 一覧からレースIDを取得できません。"
            f"試行URL={'; '.join(attempted)}"
        )

    return combined[:MAX_RACES_PER_SOURCE]


# ============================================================
# 4. レース情報
# ============================================================

def parse_meta(soup):
    selectors = [
        ".RaceData01",
        ".RaceData02",
        ".RaceData",
        ".race_data",
        ".data_intro",
        "[class*='RaceData']",
    ]

    values = []
    for selector in selectors:
        for node in soup.select(selector):
            value = text_of(node)
            if value and value not in values:
                values.append(value)

    return " ".join(values)


def first_text(soup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        value = text_of(node)
        if value and value not in ("netkeiba", "出馬表", "レース情報"):
            return value
    return ""


def parse_post_time(meta, soup):
    match = re.search(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        meta,
    )
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    for node in soup.select(".RaceData01, .RaceData02, [class*='RaceData']"):
        value = text_of(node)
        match = re.search(
            r"(?:発走|発走時刻|予定)\s*[:：]?\s*"
            r"([01]?\d|2[0-3]):([0-5]\d)",
            value,
        )
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"

    return ""


def parse_surface_distance(meta, soup):
    text = meta or ""
    if not text:
        text = " ".join(
            text_of(node)
            for node in soup.select(".RaceData01, .RaceData02")
        )

    surface = ""
    if re.search(r"障害|障芝|障ダ", text):
        surface = "障害"
    elif re.search(r"ダート|ダ\s*\d{3,4}\s*[mｍ]", text):
        surface = "ダート"
    elif re.search(r"芝\s*\d{3,4}\s*[mｍ]", text):
        surface = "芝"

    distance = None
    match = re.search(
        r"(?:芝|ダート|ダ|障害|障芝|障ダ)?\s*"
        r"(\d{3,4})\s*[mｍ]",
        text,
        re.I,
    )
    if match:
        value = safe_int(match.group(1))
        if 800 <= value <= 5000:
            distance = value

    return surface, distance


def parse_weather_going(meta):
    weather = ""
    going = ""

    match = re.search(r"天候\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)", meta)
    if match:
        weather = match.group(1)

    match = re.search(r"馬場\s*[:：]?\s*(稍重|不良|良|重)", meta)
    if match:
        going = match.group(1)

    return weather, going


# ============================================================
# 5. 出馬表テーブルの選択
# ============================================================

def row_has_horse_link(row):
    for anchor in row.find_all("a", href=True):
        href = anchor.get("href", "")
        name = text_of(anchor)
        if "/horse/" in href and name:
            return True
    return False


def choose_shutuba_table(soup):
    candidates = []
    seen = set()

    for selector in [
        "table.Shutuba_Table",
        "table.ShutubaTable",
        "table.RaceTable01",
        "table.race_table_01",
        "table",
    ]:
        for table in soup.select(selector):
            identity = id(table)
            if identity in seen:
                continue
            seen.add(identity)

            rows = table.select("tr.HorseList")
            if not rows:
                rows = table.select("tbody tr")

            horse_rows = [row for row in rows if row_has_horse_link(row)]
            score = len(horse_rows)

            if score:
                candidates.append((score, table, rows))

    if not candidates:
        return None, []

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best_table, best_rows = candidates[0]

    if len(candidates) > 1:
        print(
            f"[INFO] 出馬表候補テーブル={len(candidates)} "
            f"採用行={best_score}"
        )

    return best_table, best_rows


def get_cell(row, selectors):
    for selector in selectors:
        node = row.select_one(selector)
        if node:
            return node
    return None


def parse_horse_no(row):
    node = get_cell(row, [
        "td.Umaban",
        "td[class*='Umaban']",
        ".Umaban",
        "td.HorseNo",
        "td[class*='HorseNo']",
    ])

    if node:
        value = numeric(text_of(node))
        if value is not None and 1 <= value <= 18:
            return int(value)

    cells = row.find_all("td", recursive=False)
    horse_cell = get_cell(row, [
        "td.HorseInfo",
        "td.Horse_Name",
        "td.HorseName",
        ".HorseInfo",
    ])

    if horse_cell:
        try:
            index = cells.index(horse_cell)
        except ValueError:
            index = -1

        if index > 0:
            for cell in reversed(cells[max(0, index - 3):index]):
                classes = " ".join(cell.get("class", []))
                if any(token in classes for token in ("Waku", "Frame")):
                    continue

                value = numeric(text_of(cell))
                if value is not None and 1 <= value <= 18:
                    return int(value)

    return None


def parse_frame_no(row):
    node = get_cell(row, [
        "td.Waku",
        "td[class*='Waku']",
        "td.Frame",
        "td[class*='Frame']",
    ])
    value = numeric(text_of(node))
    return int(value) if value is not None and 1 <= value <= 8 else None


def parse_horse_name(row):
    node = get_cell(row, [
        "td.HorseInfo a",
        "td.Horse_Name a",
        "td.HorseName a",
        ".HorseInfo a",
        "a[href*='/horse/']",
    ])

    if not node:
        return ""

    name = clean(node.get("title") or text_of(node))
    if not name or name in ("馬名", "出走馬", "馬"):
        return ""

    return name


def parse_jockey(row):
    node = get_cell(row, [
        "td.Jockey a",
        "td.Jockey",
        "td[class*='Jockey']",
        ".Jockey",
    ])
    return text_of(node)


def parse_odds_popularity(row):
    odds = None
    popularity = None

    for selector in [
        "td.Odds span",
        "td.Odds",
        "td[class*='Odds']",
        ".Odds",
    ]:
        for node in row.select(selector):
            value = text_of(node)
            if not value or "---" in value or "取消" in value:
                continue

            match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", value)
            if match:
                candidate = float(match.group(1))
                if 0 < candidate <= 9999:
                    odds = candidate
                    break
        if odds is not None:
            break

    for selector in [
        "td.Popular_Ninki",
        "td.Popular",
        "td[class*='Ninki']",
        "td[class*='Popular']",
    ]:
        for node in row.select(selector):
            value = numeric(text_of(node))
            if value is not None and 1 <= value <= 18:
                popularity = int(value)
                break
        if popularity is not None:
            break

    return odds, popularity


def parse_weight_change(row):
    node = get_cell(row, [
        "td.Horse_Weight",
        "td.Weight",
        "td[class*='HorseWeight']",
        "td[class*='Weight']",
    ])
    value = text_of(node)
    match = re.search(r"\d{3}\s*\(([+-]?\d+)\)", value)
    if match:
        return int(match.group(1))
    return None


def parse_runners(soup, surface):
    table, rows = choose_shutuba_table(soup)

    if table is None:
        warn("出馬表テーブルが見つかりません")
        return [], {
            "table_found": False,
            "rows_found": 0,
            "valid_rows": 0,
            "unique_horses": 0,
            "duplicate_numbers": [],
        }

    runners = {}
    valid_rows = 0
    duplicates = []

    for row in rows:
        name = parse_horse_name(row)
        horse_no = parse_horse_no(row)

        if not name or horse_no is None:
            continue

        valid_rows += 1

        if horse_no in runners:
            duplicates.append(horse_no)
            continue

        frame_no = parse_frame_no(row)
        jockey = parse_jockey(row)
        odds, popularity = parse_odds_popularity(row)
        weight_diff = parse_weight_change(row)
        row_text = text_of(row)

        is_dirt_blood = any(x in row_text for x in DIRT_SIRES)
        is_power_blood = any(x in row_text for x in POWER_SIRES)
        is_apprentice = any(x in jockey for x in ["▲", "△", "☆", "◇", "★"])
        is_top_jockey = any(x in jockey for x in TOP_JOCKEYS)
        is_positive = any(x in row_text for x in POSITIVE_WORDS)
        is_negative = any(x in row_text for x in NEGATIVE_WORDS)

        reasons = []
        if is_top_jockey:
            reasons.append("登録騎手リストに該当（実績保証ではない）")
        if is_apprentice:
            reasons.append("騎手欄に減量記号あり")
        if surface == "ダート" and is_dirt_blood:
            reasons.append("掲載テキストにダート血統候補")
        if surface == "芝" and is_power_blood:
            reasons.append("掲載テキストに芝・持続力型血統候補")
        if weight_diff is not None and abs(weight_diff) >= 6:
            reasons.append(f"馬体重増減 {weight_diff:+d}kg")
        if is_positive:
            reasons.append("掲載テキストに好材料ワード")
        if is_negative:
            reasons.append("掲載テキストに注意ワード")

        runners[horse_no] = {
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": frame_no,
            "horse": name,
            "name": name,
            "jockey": jockey or "未取得",
            "odds": odds,
            "popularity": popularity,
            "score": 0.0,
            "rank": None,
            "reasons": reasons,
            "caution": "簡易評価。過去走・調教・展開の検証は限定的",
            "is_apprentice": is_apprentice,
            "is_top_jockey": is_top_jockey,
            "is_inner": frame_no in (1, 2) if frame_no else False,
            "is_outer": frame_no in (7, 8) if frame_no else False,
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
                "weight_change": weight_diff is not None,
            },
        }

    result = sorted(runners.values(), key=lambda x: x["horse_no"])

    diagnostic = {
        "table_found": True,
        "rows_found": len(rows),
        "valid_rows": valid_rows,
        "unique_horses": len(result),
        "duplicate_numbers": sorted(set(duplicates)),
    }

    if duplicates:
        warn(f"馬番重複を除外: {sorted(set(duplicates))}")

    if len(result) < 5:
        warn(
            f"出走馬取得数が少ない: {len(result)}頭。"
            f"テーブル行={len(rows)}、有効行={valid_rows}。"
            "HTML構造または取得ページを確認してください"
        )

    return result, diagnostic


# ============================================================
# 6. スコア・穴馬候補
# ============================================================

def score_runners(runners, surface, venue):
    for horse in runners:
        score = 0.0
        odds = horse.get("odds")
        popularity = horse.get("popularity")

        if odds is not None and odds > 0:
            score += max(0.0, 42.0 - 8.0 * math.log(max(1.0, odds)))

        if popularity is not None:
            score += max(0.0, 16.0 - (popularity - 1) * 1.1)

        if horse["is_top_jockey"]:
            score += 3.0
        if horse["is_apprentice"]:
            score += 1.5
        if surface == "ダート" and horse["is_dirt_blood"]:
            score += 2.0
        elif surface == "芝" and horse["is_power_blood"]:
            score += 1.5

        if venue in ("東京", "新潟") and horse["is_outer"]:
            score += 1.0
            horse["reasons"].append("外枠の簡易補正（未検証）")
        elif venue in ("中山", "小倉", "福島", "札幌") and horse["is_inner"]:
            score += 1.0
            horse["reasons"].append("内枠の簡易補正（未検証）")

        diff = horse.get("w_diff")
        if diff is not None and 8 <= diff <= 16:
            score += 1.0

        if horse["is_positive_memo"]:
            score += 1.0
        if horse["is_negative_memo"]:
            score -= 2.0
            horse["reasons"].append("注意ワード検出による簡易減点")

        if popularity == 1 and odds is not None and odds < 1.8:
            score -= 1.0
            horse["reasons"].append("低オッズのため妙味を控えめ評価")

        horse["score"] = round(score, 2)

        if not horse["reasons"]:
            horse["reasons"].append("取得できた情報に基づく簡易評価")

        quality = horse.get("data_quality", {})
        total = len(quality)
        available = sum(bool(x) for x in quality.values())
        horse["score_confidence"] = round(available / total * 100) if total else 0

        if odds is None:
            horse["reasons"].append("単勝オッズ未取得")
        if horse["score_confidence"] < 60:
            horse["reasons"].append("取得項目が少なく評価の不確実性が高い")

    ranked = sorted(
        runners,
        key=lambda x: (-x["score"], x["horse_no"]),
    )

    for rank, horse in enumerate(ranked, 1):
        horse["rank"] = rank

    return ranked


def select_outsiders(ranked):
    outsiders = []
    longshots = []

    for horse in ranked:
        odds = horse.get("odds")
        if odds is None:
            continue
        if 10 <= odds < 30:
            outsiders.append(horse)
        elif odds >= 30:
            longshots.append(horse)

    outsiders.sort(key=lambda x: (-x["score"], x["horse_no"]))
    longshots.sort(key=lambda x: (-x["score"], x["horse_no"]))

    for horse in outsiders:
        horse["outsider_reason"] = (
            "単勝10〜30倍。条件該当を示すだけで、好走保証ではない。"
        )
    for horse in longshots:
        horse["outsider_reason"] = (
            "単勝30倍以上。高配当候補の条件であり、好走保証ではない。"
        )

    return outsiders[:5], longshots[:5]


# ============================================================
# 7. 紙上買い目
# ============================================================

def build_tickets(ranked, outsiders):
    if len(ranked) < 3:
        return []

    top = ranked[:5]
    h1, h2, h3 = [x["horse_no"] for x in top[:3]]
    h4 = top[3]["horse_no"] if len(top) >= 4 else h3

    outsider = next(
        (
            h["horse_no"] for h in outsiders
            if h["horse_no"] not in (h1, h2, h3)
        ),
        None,
    )

    pattern_b = outsider is not None and (
        (top[0].get("odds") or 0) >= 2.8 or len(outsiders) >= 2
    )

    if pattern_b:
        lines = [
            {"type": "win", "horses": [h1], "stake_yen": 300},
            {"type": "quinella", "horses": sorted([h1, h2]), "stake_yen": 200},
            {"type": "quinella", "horses": sorted([h1, h3]), "stake_yen": 200},
            {"type": "quinella", "horses": sorted([h1, outsider]), "stake_yen": 200},
            {"type": "trio", "horses": sorted([h1, h2, h3]), "stake_yen": 100},
            {"type": "trio", "horses": sorted([h1, h2, outsider]), "stake_yen": 100},
            {"type": "trio", "horses": sorted([h1, h3, outsider]), "stake_yen": 100},
            {"type": "wide", "horses": sorted([h1, outsider]), "stake_yen": 100},
            {"type": "wide", "horses": sorted([h2, outsider]), "stake_yen": 100},
            {"type": "wide", "horses": sorted([h3, outsider]), "stake_yen": 100},
            {"type": "trifecta", "horses": [h1, outsider, h2], "stake_yen": 100},
            {"type": "trifecta", "horses": [h1, outsider, h3], "stake_yen": 100},
            {"type": "trifecta", "horses": [h1, outsider, h4], "stake_yen": 100},
        ]
        pattern = "パターンB（穴馬を含む波乱型）"
        note = "未検証の評価に基づく紙上買い目。利益を保証しない。"
    else:
        lines = [
            {"type": "win", "horses": [h1], "stake_yen": 500},
            {"type": "quinella", "horses": sorted([h1, h2]), "stake_yen": 300},
            {"type": "quinella", "horses": sorted([h1, h3]), "stake_yen": 300},
            {"type": "trio", "horses": sorted([h1, h2, h3]), "stake_yen": 600},
            {"type": "wide", "horses": sorted([h1, h4]), "stake_yen": 100},
            {"type": "wide", "horses": sorted([h2, h4]), "stake_yen": 100},
        ]
        pattern = "パターンA（上位評価中心）"
        note = "取得情報に基づく紙上シミュレーション。実購入は行わない。"

    labels = []
    valid_lines = []
    names = {
        "win": "単勝",
        "quinella": "馬連",
        "trio": "3連複",
        "wide": "ワイド",
        "trifecta": "3連単",
    }

    for line in lines:
        horses = line["horses"]
        if not horses or len(set(horses)) != len(horses):
            continue
        if not all(isinstance(x, int) and 1 <= x <= 18 for x in horses):
            continue
        valid_lines.append(line)

    while sum(x["stake_yen"] for x in valid_lines) > PAPER_BUDGET_YEN:
        valid_lines.pop()

    total = sum(x["stake_yen"] for x in valid_lines)

    for line in valid_lines:
        combo = (
            "→".join(map(str, line["horses"]))
            if line["type"] == "trifecta"
            else "-".join(map(str, line["horses"]))
        )
        line["label"] = (
            f"{names.get(line['type'], line['type'])}: "
            f"{combo} ({line['stake_yen']}円)"
        )
        labels.append(line["label"])

    return [{
        "pattern_type": "B" if pattern_b else "A",
        "pattern": pattern,
        "cost_yen": total,
        "lines": labels,
        "line_items": valid_lines,
        "note": note,
    }]


# ============================================================
# 8. 結果取得・精算（v28.3 着順抽出を完全書き直し）
# ============================================================

def parse_result_page(html, race_id):
    """結果ページから着順と払戻を抽出（NAR/JRA両対応）
    着順は「着順」「枠」「馬番」の列構造を正しく読む
    """
    soup = soup_of(html)
    finishes = []
    payouts = {
        "win": {},
        "place": {},
        "quinella": {},
        "wide": {},
        "trio": {},
        "trifecta": {},
        "exacta": {},
    }

    # ========== 着順抽出（完全書き直し） ==========
    # 着順テーブルを探す（ヘッダーに「着順」「馬番」があるもの）
    result_table = None
    for table in soup.find_all("table"):
        headers = []
        for th in table.select("th, thead td, tr:first-child td"):
            headers.append(text_of(th))
        header_text = " ".join(headers)
        if "着順" in header_text and ("馬番" in header_text or "馬名" in header_text):
            result_table = table
            break

    if result_table is None:
        # フォールバック
        for sel in ["#All_Result_Table", "table.RaceTable01", "table.Result_Table"]:
            result_table = soup.select_one(sel)
            if result_table:
                break

    if result_table:
        rows = result_table.select("tr")
        for tr in rows:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            # 列の位置を推定
            # 一般的な構造: 着順 | 枠 | 馬番 | 馬名 | ...
            rank = None
            horse_no = None

            cell_texts = [text_of(c) for c in cells[:5]]

            # 1列目が着順の可能性が高い
            first_val = safe_int(cell_texts[0]) if cell_texts else 0
            if 1 <= first_val <= 18:
                rank = first_val

                # 馬番は通常3列目（index 2）
                if len(cell_texts) >= 3:
                    cand = safe_int(cell_texts[2])
                    if 1 <= cand <= 18:
                        horse_no = cand

                # 見つからなければ2列目や他を探す
                if horse_no is None:
                    for txt in cell_texts[1:4]:
                        cand = safe_int(txt)
                        if 1 <= cand <= 18 and cand != rank:
                            horse_no = cand
                            break

            if rank and horse_no and 1 <= rank <= 18 and 1 <= horse_no <= 18:
                while len(finishes) < rank:
                    finishes.append(None)
                if finishes[rank - 1] is None:
                    finishes[rank - 1] = horse_no

    # Noneを除去して確定
    finishes = [x for x in finishes if x is not None]

    # 重複チェック（おかしい場合は警告）
    if finishes and len(finishes) != len(set(finishes)):
        warn(f"{race_id}: 着順に重複あり {finishes} → パーサー要再確認")

    # ========== 払戻抽出 ==========
    for table in soup.select("table.Payout_Detail_Table, table"):
        for tr in table.select("tr"):
            th = tr.select_one("th")
            if not th:
                continue
            label = text_of(th)
            if not label:
                continue

            tds = tr.select("td")
            if not tds:
                continue

            result_td = tds[0] if tds else None
            payout_td = tds[1] if len(tds) > 1 else tds[0]

            if not result_td or not payout_td:
                continue

            # 馬番抽出
            horse_nums = []
            for span in result_td.select("span"):
                val = safe_int(text_of(span))
                if 1 <= val <= 18:
                    horse_nums.append(val)
            if not horse_nums:
                nums = re.findall(r"\b([1-9]|1[0-8])\b", text_of(result_td))
                horse_nums = [safe_int(n) for n in nums if 1 <= safe_int(n) <= 18]

            # 金額抽出
            payout_text = text_of(payout_td)
            money_list = []
            for m in re.finditer(r"([\d,]+)\s*円", payout_text):
                money_list.append(safe_int(m.group(1).replace(",", "")))
            if not money_list:
                for m in re.finditer(r"([\d,]+)", payout_text):
                    val = safe_int(m.group(1).replace(",", ""))
                    if 100 <= val <= 10000000:
                        money_list.append(val)

            if not horse_nums or not money_list:
                continue

            if "単勝" in label:
                payouts["win"][str(horse_nums[0])] = money_list[0]
            elif "複勝" in label:
                for h, p in zip(horse_nums, money_list):
                    payouts["place"][str(h)] = p
            elif "馬連" in label:
                if len(horse_nums) >= 2:
                    key = combo_key(horse_nums[:2], ordered=False)
                    payouts["quinella"][key] = money_list[0]
            elif "ワイド" in label:
                pairs = [horse_nums[i:i+2] for i in range(0, len(horse_nums)-1, 2)]
                for pair, p in zip(pairs, money_list):
                    if len(pair) == 2:
                        key = combo_key(pair, ordered=False)
                        payouts["wide"][key] = p
            elif "3連複" in label or "三連複" in label:
                if len(horse_nums) >= 3:
                    key = combo_key(horse_nums[:3], ordered=False)
                    payouts["trio"][key] = money_list[0]
            elif "3連単" in label or "三連単" in label:
                if len(horse_nums) >= 3:
                    key = combo_key(horse_nums[:3], ordered=True)
                    payouts["trifecta"][key] = money_list[0]
            elif "馬単" in label:
                if len(horse_nums) >= 2:
                    key = combo_key(horse_nums[:2], ordered=True)
                    payouts["exacta"][key] = money_list[0]

    return finishes, payouts


def settle_tickets(tickets, finishes, payouts):
    """紙上買い目を着順・払戻で精算。着順一致を優先。"""
    if not tickets or not finishes:
        return {
            "settlement_complete": False,
            "all_bet_return": 0,
            "race_profit": None,
            "settled_lines": [],
            "win_hit": None,
            "win_return": 0,
            "settlement_status": "結果未取得または着順不足",
        }

    ticket = tickets[0]
    line_items = ticket.get("line_items", [])
    cost = ticket.get("cost_yen", 0)

    settled = []
    total_return = 0
    win_hit = False
    win_return = 0
    any_hit = False
    any_payout_found = False

    top1 = finishes[0] if len(finishes) >= 1 else None
    top2 = set(finishes[:2]) if len(finishes) >= 2 else set()
    top3 = set(finishes[:3]) if len(finishes) >= 3 else set()

    for line in line_items:
        typ = line["type"]
        horses = line["horses"]
        stake = line["stake_yen"]
        hit = False
        ret = 0
        payout = 0
        match_by_finish = False

        if typ == "win":
            if top1 is not None and horses[0] == top1:
                match_by_finish = True
                payout = payouts["win"].get(str(horses[0]), 0)
                if payout:
                    any_payout_found = True
                hit = True
                ret = int(stake / 100 * payout) if payout else 0
                win_hit = True
                win_return = ret

        elif typ == "quinella":
            key = combo_key(horses, ordered=False)
            if len(horses) == 2 and set(horses) == top2:
                match_by_finish = True
            payout = payouts["quinella"].get(key, 0)
            if payout:
                any_payout_found = True
            if match_by_finish or payout:
                hit = True
                ret = int(stake / 100 * payout) if payout else 0

        elif typ == "wide":
            key = combo_key(horses, ordered=False)
            if len(horses) == 2 and set(horses).issubset(top3):
                match_by_finish = True
            payout = payouts["wide"].get(key, 0)
            if payout:
                any_payout_found = True
            if match_by_finish or payout:
                hit = True
                ret = int(stake / 100 * payout) if payout else 0

        elif typ == "trio":
            key = combo_key(horses, ordered=False)
            if len(horses) == 3 and set(horses) == top3:
                match_by_finish = True
            payout = payouts["trio"].get(key, 0)
            if payout:
                any_payout_found = True
            if match_by_finish or payout:
                hit = True
                ret = int(stake / 100 * payout) if payout else 0

        elif typ == "trifecta":
            key = combo_key(horses, ordered=True)
            if len(horses) == 3 and horses == finishes[:3]:
                match_by_finish = True
            payout = payouts["trifecta"].get(key, 0)
            if payout:
                any_payout_found = True
            if match_by_finish or payout:
                hit = True
                ret = int(stake / 100 * payout) if payout else 0

        if hit:
            any_hit = True

        settled.append({
            "label": line.get("label", ""),
            "type": typ,
            "horses": horses,
            "stake_yen": stake,
            "hit": hit,
            "return_yen": ret,
            "payout_per_100": payout,
            "matched_by_finish": match_by_finish,
        })
        total_return += ret

    profit = total_return - cost if cost else None

    if finishes and not any_payout_found and any_hit:
        status = "着順一致・払戻一部未取得（パーサー要確認）"
    elif finishes and any_hit:
        status = "全券種精算完了"
    elif finishes:
        status = "全券種精算完了（的中なし）"
    else:
        status = "着順未取得"

    return {
        "settlement_complete": bool(finishes and len(finishes) >= 1),
        "all_bet_return": total_return,
        "race_profit": profit,
        "settled_lines": settled,
        "win_hit": win_hit,
        "win_return": win_return,
        "settlement_status": status,
        "result_finishes": finishes,
        "payouts_summary": {
            "win": payouts.get("win", {}),
            "quinella_count": len(payouts.get("quinella", {})),
            "wide_count": len(payouts.get("wide", {})),
            "trio_count": len(payouts.get("trio", {})),
            "trifecta_count": len(payouts.get("trifecta", {})),
        },
    }


def fetch_and_settle_result(race, source):
    """結果ページを取得して精算する"""
    race_id = race["id"]
    base = source["base"]
    urls = [
        f"{base}/race/result.html?race_id={race_id}",
        f"{base}/race/result.html?race_id={race_id}&rf=race_submenu",
    ]

    finishes = []
    payouts = {}
    for url in urls:
        page = get_html(url)
        if not page:
            continue
        if "着順" not in page and "払戻" not in page and "単勝" not in page:
            continue
        finishes, payouts = parse_result_page(page, race_id)
        if finishes:
            break

    if not finishes:
        race["settlement_status"] = "結果ページから着順を取得できませんでした"
        race["result_finishes"] = []
        return race

    settlement = settle_tickets(race.get("tickets", []), finishes, payouts)

    race["result_finishes"] = finishes
    race["payouts"] = payouts
    race["win_hit"] = settlement["win_hit"]
    race["win_return"] = settlement["win_return"]
    race["all_bet_return"] = settlement["all_bet_return"]
    race["race_profit"] = settlement["race_profit"]
    race["settlement_complete"] = settlement["settlement_complete"]
    race["settled_lines"] = settlement["settled_lines"]
    race["settlement_status"] = settlement["settlement_status"]
    race["is_finished"] = True

    print(
        f"[SETTLE] {race_id} 着順={finishes} "
        f"回収={settlement['all_bet_return']}円 "
        f"収支={settlement['race_profit']} "
        f"status={settlement['settlement_status']}"
    )
    return race


# ============================================================
# 9. レース解析
# ============================================================

def parse_race(source_html, race_id, source, date_iso, is_tomorrow):
    soup = soup_of(source_html)

    kind = source["kind"]
    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)

    meta = parse_meta(soup)
    post_time = parse_post_time(meta, soup)
    surface, distance = parse_surface_distance(meta, soup)
    weather, going = parse_weather_going(meta)

    race_name = first_text(soup, [
        ".RaceName",
        "h1.RaceName",
        ".race_name",
        "[class*='RaceName']",
    ])

    if not race_name:
        title = first_text(soup, ["title"])
        if title and "出馬表" not in title:
            race_name = title.split("|")[0].strip()

    if not race_name:
        race_name = f"{venue}{race_no}R" if venue and race_no else "レース名未取得"

    runners, diagnostic = parse_runners(soup, surface)
    ranked = score_runners(runners, surface, venue)
    outsiders, longshots = select_outsiders(ranked)

    count = len(runners)
    verified = (
        count >= 5
        and diagnostic.get("table_found", False)
        and len({x["horse_no"] for x in runners}) == count
        and not diagnostic.get("duplicate_numbers")
    )

    if not verified:
        warn(
            f"{race_id}: 出走頭数の検証未通過 "
            f"(取得={count}頭、行={diagnostic.get('rows_found', 0)}、"
            f"有効行={diagnostic.get('valid_rows', 0)})"
        )

    tickets = build_tickets(ranked, outsiders) if verified else []

    is_finished = False
    if post_time and not is_tomorrow:
        try:
            hour, minute = map(int, post_time.split(":"))
            scheduled = NOW.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            is_finished = NOW >= scheduled + timedelta(minutes=10)
        except ValueError:
            pass

    recommended = bool(
        verified and (
            race_no == 11 or len(outsiders) >= 2 or len(longshots) >= 2
        )
    )

    return {
        "id": str(race_id),
        "date": date_iso,
        "kind": kind,
        "category": source["category"],
        "race_no": race_no,
        "name": race_name,
        "course": venue or "競馬場未取得",
        "post_time": post_time or "未取得",
        "surface": surface or "未取得",
        "distance_m": distance,
        "weather": weather or "未取得",
        "going": going or "未取得",
        "runner_count": count,
        "runner_count_verified": verified,
        "runner_diagnostic": diagnostic,
        "horses": ranked,
        "top5": ranked[:5],
        "outsiders": outsiders,
        "longshots": longshots,
        "tickets": tickets,
        "is_finished": is_finished,
        "result_finishes": [],
        "payouts": {},
        "win_hit": None,
        "win_return": 0,
        "all_bet_return": None,
        "race_cost": tickets[0]["cost_yen"] if tickets else 0,
        "race_profit": None,
        "settlement_complete": False,
        "settled_lines": [],
        "settlement_status": "結果精算は未実装・または結果待ち",
        "is_recommended": recommended,
        "is_tomorrow": is_tomorrow,
        "prediction_status": (
            "未検証の簡易評価" if verified
            else "出走頭数未検証・予想注意"
        ),
        "probability_note": (
            "順位・スコアは簡易評価であり、校正済み勝率や利益を保証しません。"
        ),
    }


# ============================================================
# 10. 日付別レース取得
# ============================================================

def fetch_races_for_date(date_str, is_tomorrow):
    all_races = []
    date_iso = (
        (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
        if is_tomorrow else TODAY_ISO
    )

    for source in SOURCES:
        race_ids = fetch_race_ids(source, date_str)

        print(
            f"[INFO] {source['kind']} {date_str}: "
            f"一覧ID {len(race_ids)}件"
        )

        for race_id in race_ids:
            urls = [
                f"{source['base']}/race/shutuba.html?race_id={race_id}",
                f"{source['base']}/race/shutuba.html?race_id={race_id}&rf=race_submenu",
            ]

            parsed_race = None

            for url in urls:
                page = get_html(url)
                if not page:
                    continue

                soup = soup_of(page)
                has_horse_link = bool(soup.select("a[href*='/horse/']"))
                if not has_horse_link:
                    warn(
                        f"{source['kind']} {race_id}: "
                        f"馬プロフィールリンクなし ({url})"
                    )
                    continue

                try:
                    parsed_race = parse_race(
                        page, race_id, source, date_iso, is_tomorrow
                    )
                except Exception as exc:
                    warn(
                        f"{source['kind']} {race_id}: "
                        f"解析例外 {exc.__class__.__name__}"
                    )
                    parsed_race = None

                if parsed_race and parsed_race["runner_count"] >= 2:
                    break

            if parsed_race is None:
                warn(f"{source['kind']} {race_id}: レースページ解析失敗")
                continue

            if parsed_race.get("is_finished") and not is_tomorrow:
                try:
                    parsed_race = fetch_and_settle_result(parsed_race, source)
                except Exception as exc:
                    warn(
                        f"{race_id}: 結果精算例外 {exc.__class__.__name__}"
                    )

            all_races.append(parsed_race)

    all_races.sort(
        key=lambda r: (
            r.get("post_time") == "未取得",
            r.get("post_time", ""),
            r.get("course", ""),
            r.get("race_no") or 0,
        )
    )

    return all_races


# ============================================================
# 11. 履歴互換
# ============================================================

def load_history():
    if not HISTORY.exists():
        return {
            "schema_version": 28,
            "snapshots": {},
            "stats": {},
            "horse_form_cache": {},
        }

    try:
        value = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("history root is not object")

        value.setdefault("snapshots", {})
        value.setdefault("stats", {})
        value.setdefault("horse_form_cache", {})

        if not isinstance(value["snapshots"], dict):
            value["snapshots"] = {}
        if not isinstance(value["stats"], dict):
            value["stats"] = {}
        if not isinstance(value["horse_form_cache"], dict):
            value["horse_form_cache"] = {}

        value["schema_version"] = 28
        return value

    except Exception as exc:
        warn(
            "history.json 読み込み失敗。既存履歴保護のため処理中止: "
            + exc.__class__.__name__
        )
        raise


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})

    if old.get("settlement_complete") is True and race.get("settlement_complete") is not True:
        return

    if not race.get("runner_count_verified"):
        if old:
            old["last_data_warning"] = "出走頭数未検証"
            old["updated_at"] = NOW.isoformat()
            snapshots[race_id] = old
        return

    tickets = race.get("tickets", [])
    ticket = tickets[0] if tickets else {}

    snapshot = {
        "race_id": race_id,
        "date": race.get("date", TODAY_ISO),
        "kind": race.get("kind"),
        "course": race.get("course"),
        "race_no": race.get("race_no"),
        "name": race.get("name"),
        "cost": safe_int(race.get("race_cost"), 0),
        "is_finished": bool(race.get("is_finished")),
        "win_hit": race.get("win_hit"),
        "win_return": safe_int(race.get("win_return"), 0),
        "race_profit": race.get("race_profit"),
        "all_bet_return": race.get("all_bet_return"),
        "settlement_complete": bool(race.get("settlement_complete")),
        "settlement_status": race.get("settlement_status", ""),
        "result_finishes": race.get("result_finishes", []),
        "updated_at": NOW.isoformat(),
        "frozen_prediction": old.get("frozen_prediction") or {
            "top5": [
                {
                    "horse_no": h.get("horse_no"),
                    "name": h.get("name"),
                    "score": h.get("score"),
                    "odds": h.get("odds"),
                    "rank": h.get("rank"),
                }
                for h in race.get("top5", [])
            ],
            "tickets": ticket,
            "prediction_status": race.get("prediction_status"),
        },
        "last_odds": {
            str(h.get("horse_no")): h.get("odds")
            for h in race.get("horses", [])
        },
        "runner_count": race.get("runner_count"),
        "runner_count_verified": race.get("runner_count_verified"),
        "odds_snapshots": old.get("odds_snapshots", []),
        "prediction_created_at": (
            old.get("prediction_created_at") or NOW.isoformat()
        ),
    }

    snapshots[race_id] = snapshot


def calculate_stats(snapshots):
    items = list(snapshots.values())

    settled_win = [
        x for x in items
        if x.get("is_finished")
        and x.get("win_hit") is not None
        and x.get("settlement_status")
        in (
            "単勝のみ確定・他券種は組合せ検証未対応",
            "win_only_legacy",
            "全券種精算完了",
            "全券種精算完了（的中なし）",
            "着順一致・払戻一部未取得（パーサー要確認）",
        )
    ]

    settled_all = [
        x for x in items
        if x.get("settlement_complete") is True
        and x.get("all_bet_return") is not None
        and x.get("race_profit") is not None
    ]

    win_stake = sum(safe_int(x.get("cost"), 0) for x in settled_win)
    win_return = sum(safe_int(x.get("win_return"), 0) for x in settled_win)
    win_hits = sum(1 for x in settled_win if x.get("win_hit") is True)

    all_stake = sum(safe_int(x.get("cost"), 0) for x in settled_all)
    all_return = sum(safe_int(x.get("all_bet_return"), 0) for x in settled_all)
    all_hits = sum(
        1 for x in settled_all
        if safe_int(x.get("all_bet_return"), 0) > 0
    )

    return {
        "races_seen": len(items),
        "races_settled": len(settled_win) + len(settled_all),
        "win_bets": len(settled_win),
        "win_hits": win_hits,
        "total_stake_yen": win_stake,
        "total_return_yen": win_return,
        "roi_pct": round(win_return / win_stake * 100, 1) if win_stake else 0.0,
        "win_hit_rate_pct": (
            round(win_hits / len(settled_win) * 100, 1)
            if settled_win else 0.0
        ),
        "all_bet_settled_races": len(settled_all),
        "all_bet_stake_yen": all_stake,
        "all_bet_return_yen": all_return,
        "all_bet_roi_pct": (
            round(all_return / all_stake * 100, 1) if all_stake else 0.0
        ),
        "all_bet_hit_races": all_hits,
        "accounting_note": (
            "旧履歴の単勝成績と全券種精算成績は別集計。"
            "未取得・精算保留のレースは回収率に含めません。"
        ),
    }


# ============================================================
# 12. メイン
# ============================================================

def main():
    print(f"=== {ENGINE_VERSION} START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")
    print(f"[INFO] TODAY={TODAY} TOMORROW={TOMORROW}")

    history_data = load_history()
    snapshots = history_data["snapshots"]

    today_races = fetch_races_for_date(TODAY, False)
    tomorrow_races = fetch_races_for_date(TOMORROW, True)

    for race in today_races:
        update_snapshot(snapshots, race)

    cutoff = (NOW - timedelta(days=RETENTION_DAYS)).date()

    for race_id, item in list(snapshots.items()):
        try:
            item_date = datetime.strptime(
                item.get("date", ""), "%Y-%m-%d"
            ).date()
            if item_date < cutoff:
                del snapshots[race_id]
        except (ValueError, TypeError):
            continue

    stats = calculate_stats(snapshots)

    history_data["schema_version"] = 28
    history_data["updated_at"] = NOW.isoformat()
    history_data["stats"] = stats
    history_data["snapshots"] = snapshots
    save_json(HISTORY, history_data)

    tomorrow_recommended = [
        r for r in tomorrow_races if r.get("is_recommended")
    ]

    status = "OK" if today_races or tomorrow_races else "NO_RACES"
    verified_count = sum(
        1 for r in today_races if r.get("runner_count_verified")
    )
    settled_count = sum(
        1 for r in today_races if r.get("settlement_complete")
    )

    data = {
        "site": "BAGEN KEIBA",
        "engine_version": ENGINE_VERSION,
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": status,
        "warnings": WARNINGS[:MAX_WARNINGS],
        "races": today_races,
        "tomorrow_races": tomorrow_recommended,
        "tomorrow_race_count": len(tomorrow_races),
        "runner_validation": {
            "today_races": len(today_races),
            "verified_races": verified_count,
            "unverified_races": len(today_races) - verified_count,
            "settled_races": settled_count,
            "note": (
                "出走頭数はHTMLから取得した馬番の数です。"
                "頭数未検証のレースは表示しても予想・買い目を作成しません。"
                "終了レースは結果ページから着順・払戻を取得して精算します。"
            ),
        },
        "prediction_notice": (
            "予想順位・スコアは未検証の簡易評価です。"
            "校正済み勝率ではなく、的中や利益を保証しません。"
        ),
        "paper_betting": {
            "mode": "paper_only",
            "real_betting_enabled": False,
            "stats": stats,
            "history": sorted(
                snapshots.values(),
                key=lambda x: (x.get("date", ""), x.get("race_id", "")),
                reverse=True,
            )[:100],
        },
    }

    save_json(OUT, data)

    print(
        f"{ENGINE_VERSION} | status={status}"
        f" | today={len(today_races)}"
        f" | verified={verified_count}"
        f" | settled={settled_count}"
        f" | tomorrow={len(tomorrow_races)}"
        f" | tomorrow_recommended={len(tomorrow_recommended)}"
        f" | history={len(snapshots)}"
    )

    print(f"[INFO] warning_count={len(WARNINGS)}")
    for message in WARNINGS:
        print("[DIAGNOSTIC]", message)

    print("=== FINISHED ===")


if __name__ == "__main__":
    main()