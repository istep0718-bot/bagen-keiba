#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v27.0
中央・地方競馬データ取得 / 出走頭数検証 / 予想 / 紙上検証

・GitHub Actions 無料枠を想定
・実際の馬券購入、口座接続、決済は一切しない
・出走馬は馬番を検証して重複排除
・発走時刻、距離、馬場などを推測で補完しない
・既存 history.json の snapshots / stats / horse_form_cache を維持
・取得に失敗したデータは未取得として扱う
"""

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

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

ENGINE_VERSION = "BAGEN_27.0"

REQUEST_TIMEOUT = (8, 20)
REQUEST_DELAY = 0.45
MAX_RACES_PER_SOURCE = 80
MAX_WARNINGS = 100
HISTORY_RETENTION_DAYS = 180
PAPER_BUDGET_YEN = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6",
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

# 地方のコードはサイト側のID体系に依存するため、
# 未知のコードを別の競馬場名に推測変換しない。
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
    return re.sub(r"\s+", " ", str(value or "")).strip()


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def number(value):
    value = clean(value).replace(",", "").replace("．", ".")
    match = re.fullmatch(r"[^\d]*(\d+(?:\.\d+)?)[^\d]*", value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (ValueError, TypeError):
        return None


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def get_html(url):
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        # netkeibaのページでは apparent_encoding が
        # 不適切な場合があるため、UTF-8を先に試す。
        response.encoding = "utf-8"
        html = response.text

        if not html or len(html) < 100:
            warn(f"HTMLが空または短すぎます: {url}")
            return ""

        if "アクセスが集中" in html or "アクセス制限" in html:
            warn(f"アクセス制限の可能性: {url}")
            return ""

        time.sleep(REQUEST_DELAY)
        return html

    except requests.RequestException as exc:
        warn(f"HTTP取得失敗: {url} ({exc.__class__.__name__})")
        return ""


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def valid_race_id(race_id):
    return bool(re.fullmatch(r"\d{12,14}", str(race_id or "")))


def race_no_from_id(race_id):
    if not valid_race_id(race_id):
        return None

    value = safe_int(str(race_id)[-2:], 0)
    return value if 1 <= value <= 12 else None


def venue_from_id(race_id, kind):
    if not valid_race_id(race_id):
        return ""

    code = str(race_id)[4:6]
    table = JRA_CODES if kind == "中央" else NAR_CODES
    return table.get(code, "")


def parse_race_ids_from_url(url):
    """URLの形式が異なっても race_id を取得する。"""
    if not url:
        return []

    values = []

    try:
        query = parse_qs(urlparse(url).query)
        values.extend(query.get("race_id", []))
    except Exception:
        pass

    values.extend(re.findall(r"race_id=(\d{12,14})", url))
    values.extend(re.findall(r"/race/(\d{12,14})(?:/|$)", url))

    return [x for x in values if valid_race_id(x)]


# ============================================================
# 3. レース一覧
# ============================================================

def extract_race_ids(html):
    if not html:
        return []

    soup = soup_of(html)
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        ids = parse_race_ids_from_url(href)

        for race_id in ids:
            if race_id in seen or not race_no_from_id(race_id):
                continue

            seen.add(race_id)
            found.append(race_id)

    # ページ内スクリプト等に埋め込まれたIDも確認
    for match in re.findall(r"race_id[\"'=:\s]+(\d{12,14})", html):
        if match not in seen and race_no_from_id(match):
            seen.add(match)
            found.append(match)

    return found[:MAX_RACES_PER_SOURCE]


# ============================================================
# 4. レース情報解析
# ============================================================

def parse_meta(soup):
    selectors = [
        ".RaceData01",
        ".RaceData02",
        ".RaceData",
        ".RaceTableArea .RaceData01",
        ".RaceTableArea .RaceData02",
        ".race_data",
        "[class*='RaceData']",
        ".data_intro",
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
        if value and value.lower() not in ("netkeiba", "出馬表"):
            return value
    return ""


def parse_post_time(meta_text, soup):
    # レース情報欄を優先する
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", meta_text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    # ページ全体から探す場合も、時刻として明確なものだけ採用
    for selector in [
        ".RaceData01",
        ".RaceData02",
        ".RaceNum",
        "[class*='RaceData']",
    ]:
        node = soup.select_one(selector)
        value = text_of(node)
        match = re.search(
            r"(?:発走|発走時刻|予定)\s*[:：]?\s*([01]?\d|2[0-3]):([0-5]\d)",
            value,
        )
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"

    return ""


def parse_surface_distance(meta_text, soup):
    """
    芝・ダートと距離は、レースデータ欄の文字列から独立して解析。
    不明時に芝1600mなどのデフォルトを入れない。
    """
    text = meta_text

    if not text:
        for selector in [".RaceData01", ".RaceData02", ".RaceData"]:
            value = text_of(soup.select_one(selector))
            if value:
                text += " " + value

    surface = ""

    if re.search(r"ダート|ダ\s*\d{3,4}\s*m|ダ\s*\d{3,4}ｍ", text):
        surface = "ダート"
    elif re.search(r"芝\s*\d{3,4}\s*[mｍ]", text):
        surface = "芝"
    elif "障害" in text or re.search(r"障\s*\d{3,4}\s*[mｍ]", text):
        surface = "障害"

    distance = None

    # 「芝1600m」「ダート 1200m」など
    match = re.search(
        r"(?:芝|ダート|ダ|障害|障)?\s*(\d{3,4})\s*[mｍ]",
        text,
        re.I,
    )
    if match:
        value = safe_int(match.group(1), 0)
        if 800 <= value <= 5000:
            distance = value

    return surface, distance


def parse_weather_going(meta_text):
    weather = ""
    going = ""

    weather_match = re.search(
        r"天候\s*[:：]?\s*(晴|曇|雨|小雨|雪|小雪)",
        meta_text,
    )
    if weather_match:
        weather = weather_match.group(1)

    going_match = re.search(
        r"馬場\s*[:：]?\s*(良|稍重|重|不良)",
        meta_text,
    )
    if going_match:
        going = going_match.group(1)

    return weather, going


# ============================================================
# 5. 出走馬解析
# ============================================================

def cell_number(row, selectors, minimum, maximum):
    for selector in selectors:
        for node in row.select(selector):
            value = number(text_of(node))
            if value is not None and minimum <= value <= maximum:
                return int(value)
    return None


def parse_runner_number(row):
    # まず馬番専用の列を探す
    value = cell_number(
        row,
        [
            "td.Umaban",
            "td[class^='Umaban']",
            "td[class*=' Umaban']",
            ".Umaban",
            "td.Num",
        ],
        1,
        18,
    )
    if value is not None:
        return value

    # 次に、テーブル列順で馬番を確認する。
    # 枠番セルの値を馬番として採用しない。
    cells = row.find_all("td", recursive=False)

    for cell in cells:
        classes = " ".join(cell.get("class", []))
        if "Waku" in classes or "Frame" in classes:
            continue

        if "Umaban" in classes or "Num" in classes:
            value = number(text_of(cell))
            if value is not None and 1 <= value <= 18:
                return int(value)

    # 馬名セルの前後を見て馬番を探す
    horse_cell = row.select_one("td.HorseInfo, td.Horse_Name, .HorseInfo")
    if horse_cell:
        cells = row.find_all("td", recursive=False)
        try:
            index = cells.index(horse_cell)
            for cell in reversed(cells[max(0, index - 3):index]):
                classes = " ".join(cell.get("class", []))
                if "Waku" in classes:
                    continue
                value = number(text_of(cell))
                if value is not None and 1 <= value <= 18:
                    return int(value)
        except ValueError:
            pass

    return None


def parse_frame(row):
    return cell_number(
        row,
        ["td.Waku", "td[class*='Waku']", ".Waku"],
        1,
        8,
    )


def parse_odds_popularity(row):
    odds = None
    popularity = None

    # オッズはOdds列を優先
    for selector in [
        "td.Odds span",
        "td.Odds",
        ".Odds",
        "td[class*='Odds']",
        "[class*='Odds']",
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
        "[class*='Ninki']",
        "td[class*='Popular']",
    ]:
        for node in row.select(selector):
            value = number(text_of(node))
            if value is not None and 1 <= value <= 18:
                popularity = int(value)
                break

        if popularity is not None:
            break

    return odds, popularity


def parse_weight_change(row):
    for selector in [
        "td.Horse_Weight",
        "td.Weight",
        "[class*='HorseWeight']",
        "[class*='Weight']",
    ]:
        node = row.select_one(selector)
        value = text_of(node)

        match = re.search(r"\d{3}\s*\(([+-]?\d+)\)", value)
        if match:
            return int(match.group(1)), True

    return None, False


def parse_horse_name(row):
    # 馬名セルを優先し、馬プロフィールのリンクを補助にする
    node = row.select_one("td.HorseInfo a, td.Horse_Name a, .HorseInfo a")
    if node:
        name = clean(node.get("title") or text_of(node))
        if name and name not in ("馬名", "出走馬"):
            return name

    for anchor in row.find_all("a", href=True):
        href = anchor.get("href", "")
        if "/horse/" not in href:
            continue

        name = clean(anchor.get("title") or text_of(anchor))
        if name and name not in ("馬名", "出走馬"):
            return name

    return ""


def parse_jockey(row):
    node = row.select_one(
        "td.Jockey a, td.Jockey, .Jockey, td[class*='Jockey']"
    )
    return text_of(node)


def parse_runner_rows(soup, surface, venue):
    """
    出馬表テーブルを最優先で解析する。
    行数そのものではなく、有効な馬番の重複除去後の数を頭数とする。
    """
    table = soup.select_one("table.Shutuba_Table")

    if table is None:
        table = soup.select_one("table.ShutubaTable")

    if table is None:
        table = soup.select_one("table.RaceTable01")

    if table is None:
        warn("出馬表テーブルが見つかりません")
        return [], {
            "table_found": False,
            "rows_found": 0,
            "valid_rows": 0,
            "unique_horses": 0,
            "duplicate_numbers": [],
        }

    rows = table.select("tr.HorseList")
    if not rows:
        rows = table.select("tbody tr")

    # ヘッダー行を除き、馬番・馬名を両方確認できる行だけ採用
    runners_by_number = {}
    duplicate_numbers = []
    valid_rows = 0

    for row in rows:
        horse_name = parse_horse_name(row)
        horse_no = parse_runner_number(row)

        if not horse_name or horse_no is None:
            continue

        valid_rows += 1

        if horse_no in runners_by_number:
            duplicate_numbers.append(horse_no)
            continue

        frame_no = parse_frame(row)
        odds, popularity = parse_odds_popularity(row)
        weight_diff, has_weight_change = parse_weight_change(row)
        jockey = parse_jockey(row)
        row_text = text_of(row)

        is_dirt_blood = any(
            name in row_text for name in DIRT_SIRES
        )
        is_power_blood = any(
            name in row_text for name in POWER_SIRES
        )
        is_apprentice = any(
            mark in jockey for mark in ["▲", "△", "☆", "◇", "★"]
        )
        is_top_jockey = any(name in jockey for name in TOP_JOCKEYS)
        is_positive = any(word in row_text for word in POSITIVE_WORDS)
        is_negative = any(word in row_text for word in NEGATIVE_WORDS)

        reasons = []

        if is_apprentice:
            reasons.append("騎手欄に減量記号あり")

        if is_top_jockey:
            reasons.append("登録騎手リストに該当（実績保証ではない）")

        if surface == "ダート" and is_dirt_blood:
            reasons.append("掲載テキストにダート適性候補の血統名")

        if surface == "芝" and is_power_blood:
            reasons.append("掲載テキストに芝・持続力型候補の血統名")

        if weight_diff is not None and abs(weight_diff) >= 6:
            reasons.append(f"馬体重増減 {weight_diff:+d}kg")

        if is_positive:
            reasons.append("掲載テキストに好材料ワード")

        if is_negative:
            reasons.append("掲載テキストに注意ワード")

        runners_by_number[horse_no] = {
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
                "weight_change": has_weight_change,
            },
        }

    runners = sorted(
        runners_by_number.values(),
        key=lambda item: item["horse_no"],
    )

    diagnostic = {
        "table_found": True,
        "rows_found": len(rows),
        "valid_rows": valid_rows,
        "unique_horses": len(runners),
        "duplicate_numbers": sorted(set(duplicate_numbers)),
    }

    if duplicate_numbers:
        warn(f"馬番重複を除外: {sorted(set(duplicate_numbers))}")

    if len(runners) != len(set(x["horse_no"] for x in runners)):
        warn("出走馬の馬番重複が残っています")

    if len(runners) < 5:
        warn(
            f"出走馬取得数が少ない: {len(runners)}頭。"
            "実際の出走頭数と一致するか確認が必要です"
        )

    return runners, diagnostic


# ============================================================
# 6. 予想スコア
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

        if venue in ["東京", "新潟"] and horse["is_outer"]:
            score += 1.0
            horse["reasons"].append("競馬場・外枠の簡易補正（未検証）")

        elif venue in ["中山", "小倉", "福島", "札幌"] and horse["is_inner"]:
            score += 1.0
            horse["reasons"].append("競馬場・内枠の簡易補正（未検証）")

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
            horse["reasons"].append("低オッズのため簡易的に妙味を控えめ評価")

        horse["score"] = round(score, 2)

        if not horse["reasons"]:
            horse["reasons"].append("取得できた出走情報を基にした簡易評価")

        quality = horse.get("data_quality", {})
        total = len(quality)
        available = sum(1 for value in quality.values() if value)

        horse["score_confidence"] = (
            round(available / total * 100) if total else 0
        )

        if odds is None:
            horse["reasons"].append("単勝オッズ未取得")

        if horse["score_confidence"] < 60:
            horse["reasons"].append("取得項目が少なく評価の不確実性が高い")

    ranked = sorted(
        runners,
        key=lambda item: (-item["score"], item["horse_no"]),
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

    outsiders.sort(key=lambda h: (-h["score"], h["horse_no"]))
    longshots.sort(key=lambda h: (-h["score"], h["horse_no"]))

    for horse in outsiders:
        horse["outsider_reason"] = (
            "単勝10〜30倍の条件に該当。"
            "評価スコアは未検証で、好走を保証しない。"
        )

    for horse in longshots:
        horse["outsider_reason"] = (
            "単勝30倍以上の条件に該当。"
            "高配当候補の条件であり、好走可能性を証明するものではない。"
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

    valid_lines = []

    for line in lines:
        horses = line.get("horses", [])
        if not horses or not all(
            isinstance(n, int) and 1 <= n <= 18 for n in horses
        ):
            continue

        if len(set(horses)) != len(horses):
            continue

        valid_lines.append(line)

    total = sum(x["stake_yen"] for x in valid_lines)

    while total > PAPER_BUDGET_YEN and valid_lines:
        total -= valid_lines.pop()["stake_yen"]

    labels = []
    type_labels = {
        "win": "単勝",
        "quinella": "馬連",
        "trio": "3連複",
        "wide": "ワイド",
        "trifecta": "3連単",
    }

    for line in valid_lines:
        horses = line["horses"]
        kind = line["type"]
        combo = (
            "→".join(map(str, horses))
            if kind == "trifecta"
            else "-".join(map(str, horses))
        )

        line["label"] = (
            f"{type_labels.get(kind, kind)}: "
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
# 8. 着順・払戻
# ============================================================

def parse_finish_rows(soup):
    result = {}

    table = (
        soup.select_one("#All_Result_Table")
        or soup.select_one("table.ResultTable")
        or soup.select_one("table.RaceTable01")
        or soup.select_one("table.race_table_01")
    )

    if not table:
        return []

    for row in table.select("tr.HorseList, tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue

        finish = None
        for selector in [
            "td.Result_Num",
            "td.Rank",
            ".Rank",
            "td[class*='Rank']",
        ]:
            node = row.select_one(selector)
            value = number(text_of(node))
            if value is not None and 1 <= value <= 18:
                finish = int(value)
                break

        if finish is None:
            value = number(text_of(cells[0]))
            if value is not None and 1 <= value <= 18:
                finish = int(value)

        if finish is None:
            continue

        horse_no = None

        for selector in [
            "td.Num",
            "td.Umaban",
            "td[class*='Umaban']",
            "td[class*='Num']",
        ]:
            node = row.select_one(selector)
            value = number(text_of(node))
            if value is not None and 1 <= value <= 18:
                horse_no = int(value)
                break

        if horse_no is None:
            continue

        if finish not in result:
            result[finish] = horse_no

    return [
        {"finish": f, "horse_no": result[f]}
        for f in sorted(result)
    ]


def parse_payouts(soup):
    payout_data = {
        "win": [],
        "place": [],
        "quinella": [],
        "wide": [],
        "exacta": [],
        "trio": [],
        "trifecta": [],
    }

    keywords = [
        ("trifecta", ["3連単", "三連単"]),
        ("trio", ["3連複", "三連複"]),
        ("quinella", ["馬連"]),
        ("wide", ["ワイド"]),
        ("exacta", ["馬単"]),
        ("place", ["複勝"]),
        ("win", ["単勝"]),
    ]

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue

        joined = " ".join(text_of(c) for c in cells)

        bet_type = None
        for kind, words in keywords:
            if any(word in joined for word in words):
                bet_type = kind
                break

        if bet_type is None:
            continue

        amounts = re.findall(r"(\d[\d,]*)\s*円", joined)
        if not amounts:
            continue

        amount = safe_int(amounts[-1].replace(",", ""), 0)
        if amount <= 0:
            continue

        combination = ""

        for cell in cells:
            value = text_of(cell)
            if re.search(r"\d{1,2}\s*[-＝=]\s*\d{1,2}", value):
                combination = value
                break

            if re.search(r"\d{1,2}\s*→\s*\d{1,2}", value):
                combination = value
                break

        if not combination:
            continue

        nums = [
            int(x) for x in re.findall(r"\d{1,2}", combination)
            if 1 <= int(x) <= 18
        ]

        required = {
            "win": 1, "place": 1,
            "quinella": 2, "wide": 2, "exacta": 2,
            "trio": 3, "trifecta": 3,
        }.get(bet_type, 99)

        if len(nums) != required:
            continue

        if bet_type in ("quinella", "wide", "trio"):
            nums = sorted(nums)

        payout_data[bet_type].append({
            "horses": nums,
            "payout_yen_per_100": amount,
            "source_text": joined[:250],
        })

    return payout_data


def get_result_data(base_url, race_id):
    url = f"{base_url}/race/result.html?race_id={race_id}"
    html = get_html(url)

    if not html:
        return {
            "finishes": [],
            "payouts": {},
            "result_available": False,
        }

    soup = soup_of(html)
    finishes = parse_finish_rows(soup)
    payouts = parse_payouts(soup)

    return {
        "finishes": finishes,
        "payouts": payouts,
        "result_available": bool(finishes),
    }


def normalize_combo(kind, horses):
    horses = list(horses)

    if kind in ("quinella", "wide", "trio"):
        return tuple(sorted(horses))

    return tuple(horses)


def settle_tickets(tickets, result_data):
    if not tickets:
        return {
            "race_cost": 0,
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "買い目未作成",
        }

    ticket = tickets[0]
    total_cost = safe_int(ticket.get("cost_yen"), 0)

    if not result_data or not result_data.get("result_available"):
        return {
            "race_cost": total_cost,
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "着順未取得・精算保留",
        }

    finishes = result_data.get("finishes", [])
    finish_order = [
        x["horse_no"] for x in sorted(finishes, key=lambda x: x["finish"])
    ]

    if not finish_order:
        return {
            "race_cost": total_cost,
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "着順を確認できず精算保留",
        }

    finish_pos = {horse_no: i + 1 for i, horse_no in enumerate(finish_order)}

    payout_lookup = {}
    for kind, entries in result_data.get("payouts", {}).items():
        payout_lookup[kind] = {
            normalize_combo(kind, e.get("horses", [])):
                safe_int(e.get("payout_yen_per_100"), 0)
            for e in entries
        }

    total_return = 0
    win_hit = False
    any_hit = False
    all_payouts_known = True
    settled_lines = []

    for line in ticket.get("line_items", []):
        kind = line.get("type")
        horses = line.get("horses", [])
        stake = safe_int(line.get("stake_yen"), 0)

        if kind == "win":
            hit = bool(horses and finish_order and horses[0] == finish_order[0])

        elif kind == "quinella":
            hit = (
                len(horses) == 2
                and all(h in finish_pos for h in horses)
                and all(finish_pos[h] <= 2 for h in horses)
            )

        elif kind == "wide":
            hit = (
                len(horses) == 2
                and all(h in finish_pos for h in horses)
                and all(finish_pos[h] <= 3 for h in horses)
            )

        elif kind == "trio":
            hit = (
                len(horses) == 3
                and all(h in finish_pos for h in horses)
                and all(finish_pos[h] <= 3 for h in horses)
            )

        elif kind == "trifecta":
            hit = len(horses) == 3 and horses == finish_order[:3]

        else:
            hit = False

        if kind == "win" and hit:
            win_hit = True

        if not hit:
            settled_lines.append({
                "type": kind,
                "horses": horses,
                "stake_yen": stake,
                "hit": False,
                "return_yen": 0,
                "status": "不的中",
            })
            continue

        any_hit = True
        key = normalize_combo(kind, horses)
        payout = payout_lookup.get(kind, {}).get(key)

        if payout is None or payout <= 0:
            all_payouts_known = False
            settled_lines.append({
                "type": kind,
                "horses": horses,
                "stake_yen": stake,
                "hit": True,
                "return_yen": None,
                "status": "的中条件該当・払戻未確認",
            })
            continue

        returned = int(round(payout * stake / 100))
        total_return += returned

        settled_lines.append({
            "type": kind,
            "horses": horses,
            "stake_yen": stake,
            "hit": True,
            "return_yen": returned,
            "status": "払戻確認済み",
        })

    win_return = sum(
        safe_int(x.get("return_yen"), 0)
        for x in settled_lines
        if x["type"] == "win" and x["hit"]
    )

    complete = all_payouts_known

    return {
        "race_cost": total_cost,
        "win_return": win_return,
        "all_bet_return": total_return if complete else None,
        "race_profit": total_return - total_cost if complete else None,
        "win_hit": win_hit,
        "any_bet_hit": any_hit,
        "settlement_complete": complete,
        "settlement_status": (
            "券種別精算完了"
            if complete
            else "一部払戻未確認・精算保留"
        ),
        "settled_lines": settled_lines,
    }


# ============================================================
# 9. レースページ解析
# ============================================================

def parse_race(html, race_id, kind, base_url, date_iso, is_tomorrow):
    soup = soup_of(html)

    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)

    meta_text = parse_meta(soup)
    post_time = parse_post_time(meta_text, soup)
    surface, distance = parse_surface_distance(meta_text, soup)
    weather, going = parse_weather_going(meta_text)

    race_name = first_text(soup, [
        ".RaceName",
        ".race_name",
        "h1.RaceName",
        "[class*='RaceName']",
    ])

    if not race_name or race_name in ["出馬表", "レース情報"]:
        race_name = (
            f"{venue}{race_no}R"
            if venue and race_no
            else "レース名未取得"
        )

    runners, runner_diagnostic = parse_runner_rows(
        soup, surface, venue
    )

    ranked = score_runners(runners, surface, venue)
    outsiders, longshots = select_outsiders(ranked)
    tickets = build_tickets(ranked, outsiders)

    # 頭数取得の品質チェック
    runner_count = len(runners)
    expected_numbers = [x["horse_no"] for x in runners]

    runner_data_valid = (
        runner_count >= 5
        and len(expected_numbers) == len(set(expected_numbers))
        and runner_diagnostic.get("table_found", False)
    )

    if not runner_data_valid:
        warn(
            f"{race_id}: 出走頭数の検証未通過 "
            f"(取得={runner_count}頭、行={runner_diagnostic.get('rows_found', 0)})"
        )

    is_finished = False
    if post_time and not is_tomorrow:
        try:
            hour, minute = map(int, post_time.split(":"))
            scheduled = NOW.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            is_finished = NOW >= scheduled + timedelta(minutes=10)
        except (ValueError, IndexError):
            pass

    result_data = {
        "finishes": [],
        "payouts": {},
        "result_available": False,
    }

    settlement = {
        "race_cost": tickets[0]["cost_yen"] if tickets else 0,
        "win_return": 0,
        "race_profit": None,
        "win_hit": None,
        "settlement_complete": False,
        "settlement_status": "発走前または結果待ち",
    }

    # 出走馬データが不完全なレースでは紙上精算を実行しない
    if is_finished and not is_tomorrow and runner_data_valid:
        result_data = get_result_data(base_url, race_id)
        settlement = settle_tickets(tickets, result_data)

    result_finishes = [
        x["horse_no"] for x in sorted(
            result_data.get("finishes", []),
            key=lambda x: x["finish"],
        )
    ]

    is_recommended = bool(
        runner_data_valid
        and (race_no == 11 or len(outsiders) >= 2 or len(longshots) >= 2)
    )

    return {
        "id": str(race_id),
        "date": date_iso,
        "kind": kind,
        "category": "local" if kind == "地方" else "central",
        "race_no": race_no,
        "name": race_name,
        "course": venue or "競馬場未取得",
        "post_time": post_time or "未取得",
        "surface": surface or "未取得",
        "distance_m": distance,
        "weather": weather or "未取得",
        "going": going or "未取得",
        "runner_count": runner_count,
        "runner_count_verified": runner_data_valid,
        "runner_diagnostic": runner_diagnostic,
        "horses": ranked,
        "top5": ranked[:5],
        "outsiders": outsiders,
        "longshots": longshots,
        "tickets": tickets if runner_data_valid else [],
        "is_finished": is_finished,
        "result_finishes": result_finishes,
        "payouts": result_data.get("payouts", {}),
        "win_hit": settlement.get("win_hit"),
        "win_return": settlement.get("win_return", 0),
        "all_bet_return": settlement.get("all_bet_return"),
        "race_cost": settlement.get("race_cost", 0),
        "race_profit": settlement.get("race_profit"),
        "settlement_complete": settlement.get("settlement_complete", False),
        "settled_lines": settlement.get("settled_lines", []),
        "settlement_status": settlement.get(
            "settlement_status", "結果未取得"
        ),
        "is_recommended": is_recommended,
        "prediction_status": (
            "未検証の簡易評価"
            if runner_data_valid
            else "出走頭数未検証・予想注意"
        ),
        "probability_note": (
            "表示順位・スコアは未検証の評価指標です。"
            "校正済み勝率や利益を保証しません。"
        ),
    }


# ============================================================
# 10. 履歴互換
# ============================================================

def load_history():
    if not HISTORY.exists():
        return {
            "schema_version": 27,
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

        value["schema_version"] = 27
        return value

    except Exception as exc:
        warn(
            "history.json 読み込み失敗。履歴保護のため処理を中止: "
            + exc.__class__.__name__
        )
        raise


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})

    if old.get("settlement_complete") is True:
        return

    ticket = race.get("tickets", [{}])
    ticket = ticket[0] if ticket else {}

    # 出走頭数が検証できなければ予測履歴を固定しない
    if not race.get("runner_count_verified"):
        if old:
            old["last_data_warning"] = "出走頭数未検証"
            old["updated_at"] = NOW.isoformat()
            snapshots[race_id] = old
        return

    snapshot = {
        "race_id": race_id,
        "date": race.get("date", TODAY_ISO),
        "kind": race.get("kind"),
        "course": race.get("course"),
        "race_no": race.get("race_no"),
        "name": race.get("name"),
        "cost": safe_int(
            race.get("race_cost"), ticket.get("cost_yen", 0)
        ),
        "is_finished": bool(race.get("is_finished")),
        "win_hit": race.get("win_hit"),
        "win_return": safe_int(race.get("win_return"), 0),
        "race_profit": race.get("race_profit"),
        "all_bet_return": race.get("all_bet_return"),
        "settlement_complete": bool(race.get("settlement_complete")),
        "settlement_status": race.get("settlement_status", ""),
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
    }

    snapshot["odds_snapshots"] = old.get("odds_snapshots", [])
    snapshot["prediction_created_at"] = (
        old.get("prediction_created_at") or NOW.isoformat()
    )

    snapshots[race_id] = snapshot


def calculate_stats(snapshots):
    all_items = list(snapshots.values())

    settled_win = [
        x for x in all_items
        if x.get("is_finished")
        and x.get("win_hit") is not None
        and x.get("settlement_status")
        in (
            "単勝のみ確定・他券種は組合せ検証未対応",
            "win_only_legacy",
        )
    ]

    settled_all = [
        x for x in all_items
        if x.get("settlement_complete") is True
        and x.get("all_bet_return") is not None
        and x.get("race_profit") is not None
    ]

    win_stake = sum(safe_int(x.get("cost"), 0) for x in settled_win)
    win_return = sum(safe_int(x.get("win_return"), 0) for x in settled_win)
    win_hits = sum(1 for x in settled_win if x.get("win_hit") is True)

    all_stake = sum(safe_int(x.get("cost"), 0) for x in settled_all)
    all_return = sum(
        safe_int(x.get("all_bet_return"), 0) for x in settled_all
    )

    all_hits = sum(
        1 for x in settled_all
        if safe_int(x.get("all_bet_return"), 0) > 0
    )

    return {
        "races_seen": len(all_items),
        "races_settled": len(settled_win) + len(settled_all),
        "win_bets": len(settled_win),
        "win_hits": win_hits,
        "total_stake_yen": win_stake,
        "total_return_yen": win_return,
        "roi_pct": round(win_return / win_stake * 100, 1)
        if win_stake else 0.0,
        "win_hit_rate_pct": round(win_hits / len(settled_win) * 100, 1)
        if settled_win else 0.0,
        "all_bet_settled_races": len(settled_all),
        "all_bet_stake_yen": all_stake,
        "all_bet_return_yen": all_return,
        "all_bet_roi_pct": round(all_return / all_stake * 100, 1)
        if all_stake else 0.0,
        "all_bet_hit_races": all_hits,
        "accounting_note": (
            "旧履歴の単勝成績と全券種精算成績は別集計。"
            "未取得・精算保留のレースは回収率に含めません。"
        ),
    }


# ============================================================
# 11. 日付別レース取得
# ============================================================

def fetch_races_for_date(date_str, is_tomorrow):
    all_races = []

    date_iso = (
        (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
        if is_tomorrow else TODAY_ISO
    )

    for source in SOURCES:
        list_url = source["list"] + date_str
        list_html = get_html(list_url)
        race_ids = extract_race_ids(list_html)

        if not race_ids:
            warn(
                f"{source['kind']} {date_str}: "
                "レース一覧からIDを取得できません。"
                "開催なし、ページ構造変更、アクセス制限の可能性があります。"
            )
            continue

        print(
            f"[INFO] {source['kind']} {date_str}: "
            f"{len(race_ids)} race IDs"
        )

        for race_id in race_ids:
            race_url = (
                f"{source['base']}/race/shutuba.html?race_id={race_id}"
            )
            html = get_html(race_url)

            if not html:
                warn(f"{source['kind']} {race_id}: 出馬表取得失敗")
                continue

            race = parse_race(
                html=html,
                race_id=race_id,
                kind=source["kind"],
                base_url=source["base"],
                date_iso=date_iso,
                is_tomorrow=is_tomorrow,
            )

            race["is_tomorrow"] = is_tomorrow

            # 1頭しか取れていないページなどは、レースデータとして掲載しない
            # ただし、少頭数レースを完全に排除しないよう、
            # 2頭以上なら警告付きでデータに残す。
            if race["runner_count"] >= 2:
                all_races.append(race)
            else:
                warn(
                    f"{source['kind']} {race_id}: "
                    f"有効な出走馬を{race['runner_count']}頭しか取得できません"
                )

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
# 12. メイン
# ============================================================

def main():
    print(f"=== {ENGINE_VERSION} START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")

    history_data = load_history()
    snapshots = history_data["snapshots"]

    today_races = fetch_races_for_date(TODAY, False)
    tomorrow_races = fetch_races_for_date(TOMORROW, True)

    for race in today_races:
        update_snapshot(snapshots, race)

    cutoff = (NOW - timedelta(days=HISTORY_RETENTION_DAYS)).date()

    for race_id, item in list(snapshots.items()):
        try:
            item_date = datetime.strptime(
                item.get("date", ""), "%Y-%m-%d"
            ).date()

            if item_date < cutoff:
                del snapshots[race_id]

        except (ValueError, TypeError):
            # 日付不明の既存履歴は削除しない
            continue

    stats = calculate_stats(snapshots)

    history_data["schema_version"] = 27
    history_data["updated_at"] = NOW.isoformat()
    history_data["stats"] = stats
    history_data["snapshots"] = snapshots

    # horse_form_cacheなど既存のトップレベルデータは保持
    save_json(HISTORY, history_data)

    tomorrow_recommended = [
        r for r in tomorrow_races if r.get("is_recommended")
    ]

    status = "OK" if today_races or tomorrow_races else "NO_RACES"

    verified_count = sum(
        1 for r in today_races if r.get("runner_count_verified")
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
            "note": (
                "出走頭数はHTMLから取得できた馬番の数です。"
                "公式の出走頭数と照合できない場合は未検証です。"
            ),
        },
        "prediction_notice": (
            "予想順位とスコアは未検証の簡易評価です。"
            "校正済み勝率ではなく、的中や利益を保証しません。"
        ),
        "paper_betting": {
            "mode": "paper_only",
            "real_betting_enabled": False,
            "stats": stats,
            "history": sorted(
                snapshots.values(),
                key=lambda x: (
                    x.get("date", ""),
                    x.get("race_id", ""),
                ),
                reverse=True,
            )[:100],
        },
    }

    save_json(OUT, data)

    print(
        f"{ENGINE_VERSION} | status={status}"
        f" | today={len(today_races)}"
        f" | today_verified={verified_count}"
        f" | tomorrow={len(tomorrow_races)}"
        f" | recommended={len(tomorrow_recommended)}"
        f" | history={len(snapshots)}"
        f" | settled={stats['races_settled']}"
    )

    if WARNINGS:
        print(f"[WARN] warnings={len(WARNINGS)}")
        print("[INFO] 詳細は docs/data.json の warnings を確認してください。")

    print("=== FINISHED ===")


if __name__ == "__main__":
    main()