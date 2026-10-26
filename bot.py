#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v26.0
中央・地方競馬のデータ取得 / 予想順位 / 穴馬分析 / 紙上検証

・無料 GitHub Actions 対応
・実際の馬券購入、決済、口座接続は一切行わない
・取得できないデータは推測で埋めず「未取得」
・予想スコアは未検証の評価指標であり、実証済み勝率ではない
・既存 history.json の snapshots / stats / horse_form_cache を可能な限り維持
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


# ============================================================
# 1. 基本設定
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

ENGINE_VERSION = "BAGEN_26.0"
REQUEST_TIMEOUT = (7, 18)
REQUEST_DELAY = 0.35
MAX_RACES_PER_SOURCE = 80
MAX_WARNINGS = 100
MIN_RUNNERS = 2
HISTORY_RETENTION_DAYS = 180
PAPER_BUDGET_YEN = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6",
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

NAR_CODES = {
    "30": "帯広", "35": "盛岡", "36": "水沢", "40": "浦和",
    "41": "船橋", "42": "大井", "43": "川崎", "44": "大井",
    "45": "川崎", "46": "金沢", "47": "笠松", "48": "名古屋",
    "50": "園田", "51": "姫路", "54": "姫路", "55": "高知",
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


def number(value):
    """テキストから数字を安全に取得。存在しない値は None。"""
    value = clean(value).replace(",", "").replace("．", ".")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (ValueError, TypeError):
        return None


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def get_html(url):
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except requests.RequestException as exc:
        warn(f"取得失敗: {url} ({exc.__class__.__name__})")
        return ""


def save_json(path, value):
    """一時ファイル経由で保存し、書き込み途中の破損を防ぐ。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def race_no_from_id(race_id):
    race_id = str(race_id)
    if not re.fullmatch(r"\d{12,14}", race_id):
        return None
    value = safe_int(race_id[-2:], 0)
    return value if 1 <= value <= 12 else None


def venue_from_id(race_id, kind):
    race_id = str(race_id)
    if not re.fullmatch(r"\d{12,14}", race_id):
        return ""
    code = race_id[4:6]
    return (JRA_CODES if kind == "中央" else NAR_CODES).get(code, "")


def first_text(soup, selectors):
    for selector in selectors:
        try:
            node = soup.select_one(selector)
        except Exception:
            continue
        value = text_of(node)
        if value and "netkeiba" not in value.lower():
            return value
    return ""


def parse_meta(soup):
    values = []
    selectors = [
        ".RaceData01", ".RaceData02", ".RaceData",
        ".race_data", "[class*='RaceData']",
        ".raceData01", ".raceData02",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            value = text_of(node)
            if value and value not in values:
                values.append(value)
    return " ".join(values)


def extract_race_ids(html):
    """一覧ページ内の race_id を抽出し、重複を除く。"""
    if not html:
        return []

    soup = soup_of(html)
    found = []
    seen = set()

    for anchor in soup.select('a[href*="race_id="], a[href*="shutuba.html"]'):
        href = anchor.get("href", "")
        match = re.search(r"race_id=(\d{12,14})", href)
        if not match:
            continue

        race_id = match.group(1)
        if race_id in seen or not race_no_from_id(race_id):
            continue

        seen.add(race_id)
        found.append(race_id)

    return found[:MAX_RACES_PER_SOURCE]


# ============================================================
# 3. 出走馬の読み取り
# ============================================================

def parse_runner_number(row):
    selectors = [
        "td.Umaban", ".Umaban", "[class*='Umaban']",
        "td.Num", "[class*='Num']",
    ]

    for selector in selectors:
        node = row.select_one(selector)
        value = number(text_of(node))
        if value is not None and 1 <= value <= 18:
            return int(value)

    for cell in row.find_all(["td", "th"], recursive=False)[:6]:
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


def parse_odds_popularity(row):
    odds = None
    popularity = None

    odds_selectors = [
        "td.Odds", ".Odds", "[class*='Odds']",
        ".odds", "td[class*='Odds']",
    ]
    popularity_selectors = [
        "td.Popular_Ninki", ".Popular_Ninki",
        "[class*='Ninki']", ".Popular", "td[class*='Popular']",
    ]

    for selector in odds_selectors:
        node = row.select_one(selector)
        value = number(text_of(node))
        if value is not None and 0 < value <= 9999:
            odds = value
            break

    for selector in popularity_selectors:
        node = row.select_one(selector)
        value = number(text_of(node))
        if value is not None and 1 <= value <= 18:
            popularity = int(value)
            break

    # クラス名が変わった場合の控えめな補助処理
    if odds is None or popularity is None:
        for cell in row.find_all(["td", "th"], recursive=False):
            cls = " ".join(cell.get("class", []))
            value = number(text_of(cell))
            if value is None:
                continue

            if odds is None and ("Odds" in cls or "オッズ" in text_of(cell)):
                if 0 < value <= 9999:
                    odds = value

            if popularity is None and ("Ninki" in cls or "Popular" in cls):
                if 1 <= value <= 18:
                    popularity = int(value)

    return odds, popularity


def parse_weight_change(row):
    selectors = [
        "td.Horse_Weight", ".Horse_Weight",
        "[class*='HorseWeight']", "[class*='Weight']",
    ]

    for selector in selectors:
        node = row.select_one(selector)
        value = text_of(node)
        if not value:
            continue

        match = re.search(r"\d{3}\s*\(([+-]?\d+)\)", value)
        if match:
            return int(match.group(1)), True

    return None, False


def parse_runner_rows(soup, surface, venue):
    selectors = (
        "tr.HorseList, tr[class*='Horse'], "
        "table.Shutuba_Table tr, table.ShutubaTable tr"
    )

    rows = soup.select(selectors)
    runners = []
    seen_numbers = set()

    for row in rows:
        horse_anchor = row.select_one('a[href*="/horse/"], a[href*="horse"]')
        horse_name = text_of(horse_anchor)

        if not horse_name or horse_name == "馬名" or horse_name.startswith("馬名 "):
            continue

        horse_no = parse_runner_number(row)
        if horse_no is None or horse_no in seen_numbers:
            continue

        seen_numbers.add(horse_no)

        row_text = text_of(row)
        frame_no = parse_frame(row)
        odds, popularity = parse_odds_popularity(row)
        weight_diff, has_weight_change = parse_weight_change(row)

        jockey = text_of(row.select_one(
            ".Jockey, td.Jockey, [class*='Jockey']"
        ))

        sire = ""
        sire_match = re.search(
            r"(?:父|種牡馬|Sire)[:：]?\s*([^\s（）()]+)",
            row_text,
        )
        if sire_match:
            sire = sire_match.group(1)

        is_dirt_blood = any(
            name in row_text or name in sire for name in DIRT_SIRES
        )
        is_power_blood = any(
            name in row_text or name in sire for name in POWER_SIRES
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
            reasons.append("登録騎手リストに該当（実績の保証ではない）")
        if surface == "ダート" and is_dirt_blood:
            reasons.append("掲載テキストにダート適性候補の血統名")
        if surface == "芝" and is_power_blood:
            reasons.append("掲載テキストに芝・持続力型候補の血統名")
        if has_weight_change and weight_diff is not None and abs(weight_diff) >= 6:
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
            "rank": None,
            "reasons": reasons,
            "caution": "過去走・調教・展開の十分な検証ができていない可能性あり",
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
        })

    return sorted(runners, key=lambda item: item["horse_no"])


# ============================================================
# 4. 評価スコア
# ============================================================

def score_runners(runners, surface, venue):
    """
    未検証の簡易評価スコア。
    確率・勝率・期待値として断定しない。
    オッズ未取得の場合は市場評価点を付けない。
    """
    for horse in runners:
        score = 0.0
        odds = horse.get("odds")
        popularity = horse.get("popularity")

        # オッズと人気は市場評価の参考値としてのみ使う
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
        horse["score_confidence"] = round(available / total * 100) if total else 0

        if odds is None:
            horse["reasons"].append("単勝オッズ未取得：市場評価を反映できていない")
        if horse["score_confidence"] < 60:
            horse["reasons"].append("取得項目が少なく、評価の不確実性が高い")

    ranked = sorted(
        runners,
        key=lambda item: (-item["score"], item["horse_no"]),
    )

    for rank, horse in enumerate(ranked, 1):
        horse["rank"] = rank

    return ranked


def select_outsiders(ranked):
    """
    穴馬：単勝10倍以上30倍未満
    大穴：単勝30倍以上
    どちらもオッズ取得時のみ判定。
    """
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
            "単勝10〜30倍の条件に該当。評価スコアは候補選別用で、"
            "実際の好走確率を証明するものではない。"
        )

    for horse in longshots:
        horse["outsider_reason"] = (
            "単勝30倍以上の条件に該当。高配当候補という意味であり、"
            "好走可能性が高いと確認されたわけではない。"
        )

    return outsiders[:5], longshots[:5]


# ============================================================
# 5. 紙上買い目
# ============================================================

def build_tickets(ranked, outsiders):
    """
    紙上シミュレーション用。
    購入実行は行わない。
    予算は最大2,000円、100円単位。
    """
    if len(ranked) < 3:
        return []

    top = ranked[:5]
    h1, h2, h3 = [item["horse_no"] for item in top[:3]]
    h4 = top[3]["horse_no"] if len(top) >= 4 else h3

    outsider = None
    for horse in outsiders:
        if horse["horse_no"] not in (h1, h2, h3):
            outsider = horse["horse_no"]
            break

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
        note = (
            "穴馬候補を含む紙上買い目。評価は未検証で、"
            "的中・利益・高配当を保証しません。"
        )
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
        note = "取得情報に基づく紙上シミュレーション。実際の購入は行いません。"

    # 2,000円以内に制限する
    lines = [
        line for line in lines
        if line["stake_yen"] > 0
        and line.get("horses")
        and all(isinstance(n, int) and 1 <= n <= 18 for n in line["horses"])
    ]

    total = sum(line["stake_yen"] for line in lines)

    while total > PAPER_BUDGET_YEN and lines:
        removed = lines.pop()
        total -= removed["stake_yen"]

    # 予算の余りを無理に埋めない。実際の買い目の総額を正しく表示。
    labels = []
    type_labels = {
        "win": "単勝",
        "quinella": "馬連",
        "trio": "3連複",
        "wide": "ワイド",
        "trifecta": "3連単",
    }

    for line in lines:
        horses = line["horses"]
        kind = line["type"]
        stake = line["stake_yen"]

        if kind == "trifecta":
            combo = "→".join(str(n) for n in horses)
        else:
            combo = "-".join(str(n) for n in horses)

        line["label"] = f"{type_labels.get(kind, kind)}: {combo} ({stake}円)"
        labels.append(line["label"])

    return [{
        "pattern_type": "B" if pattern_b else "A",
        "pattern": pattern,
        "cost_yen": total,
        "lines": labels,
        "line_items": lines,
        "note": note,
    }]


# ============================================================
# 6. レース結果・払戻取得
# ============================================================

def parse_finish_rows(soup):
    """
    着順と馬番を、クラス名が確認できるセルを優先して取得する。
    判定できない場合は不確かな値を無理に採用しない。
    """
    result = {}
    rows = soup.select(
        "table.RaceTable01 tr, table.ResultTable tr, "
        "tr.HorseList, table.RaceTable tr, table.race_table_01 tr"
    )

    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 3:
            continue

        row_text = text_of(row)
        if not row_text:
            continue

        finish = None
        for selector in [
            "td.Rank", ".Rank", "td[class*='Rank']",
            ".Finish", "td[class*='Finish']",
        ]:
            value = number(text_of(row.select_one(selector)))
            if value is not None and 1 <= value <= 18:
                finish = int(value)
                break

        if finish is None:
            first = text_of(cells[0])
            if re.fullmatch(r"\d{1,2}", first):
                finish = int(first)

        if finish is None or not 1 <= finish <= 18:
            continue

        horse_no = None
        for selector in [
            "td.Umaban", ".Umaban", "[class*='Umaban']",
            "td.Num", "[class*='Num']",
        ]:
            value = number(text_of(row.select_one(selector)))
            if value is not None and 1 <= value <= 18:
                horse_no = int(value)
                break

        if horse_no is None:
            # 着順セルを除外し、馬番セルのクラスが特定できる場合のみ採用
            for cell in cells[1:5]:
                cls = " ".join(cell.get("class", []))
                if "Umaban" not in cls and "Num" not in cls:
                    continue
                value = number(text_of(cell))
                if value is not None and 1 <= value <= 18:
                    horse_no = int(value)
                    break

        if horse_no is not None and finish not in result:
            result[finish] = horse_no

    return [
        {"finish": finish, "horse_no": result[finish]}
        for finish in sorted(result)
    ]


def parse_payouts(soup):
    """
    払戻金は券種別の行からのみ抽出。
    組み合わせと金額を関連付けられない場合は未確定のままにする。
    """
    payout_data = {
        "win": [],
        "quinella": [],
        "trio": [],
        "wide": [],
        "trifecta": [],
        "exacta": [],
        "place": [],
    }

    type_keywords = [
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

        joined = " ".join(text_of(cell) for cell in cells)
        if not joined:
            continue

        bet_type = None
        for kind, keywords in type_keywords:
            if any(keyword in joined for keyword in keywords):
                bet_type = kind
                break

        if bet_type is None:
            continue

        # 払戻額は「1,230円」の形式のみを受け付ける
        amounts = re.findall(r"(\d[\d,]*)\s*円", joined)
        if not amounts:
            continue

        amount = safe_int(amounts[-1].replace(",", ""), 0)
        if amount <= 0:
            continue

        # 馬番の抽出は券種・組み合わせセルを優先する
        combination = ""
        for cell in cells:
            cell_text = text_of(cell)
            cls = " ".join(cell.get("class", []))
            if any(word in cls.lower() for word in ["pay", "payout", "refund"]):
                continue
            if re.search(r"\d+\s*[-＝=]\s*\d+|\d+\s*→\s*\d+", cell_text):
                combination = cell_text
                break

        # 組み合わせが明確でない払戻は誤精算防止のため記録しない
        if not combination:
            continue

        nums = [int(x) for x in re.findall(r"\d{1,2}", combination)]
        nums = [n for n in nums if 1 <= n <= 18]

        required = {
            "win": 1,
            "place": 1,
            "quinella": 2,
            "wide": 2,
            "exacta": 2,
            "trio": 3,
            "trifecta": 3,
        }.get(bet_type, 99)

        if len(nums) < required:
            continue

        if bet_type in ("quinella", "wide", "trio"):
            nums = sorted(nums[:required])
        else:
            nums = nums[:required]

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


# ============================================================
# 7. 紙上精算
# ============================================================

def normalize_combo(kind, horses):
    horses = list(horses)

    if kind in ("quinella", "wide", "trio"):
        return tuple(sorted(horses))

    return tuple(horses)


def settle_tickets(tickets, result_data):
    """
    確認できた券種・組み合わせ・払戻だけを精算する。
    未取得の払戻は0円と決めつけず、精算保留として扱う。
    """
    if not tickets:
        return {
            "race_cost": 0,
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "買い目未作成",
        }

    if not result_data or not result_data.get("result_available"):
        return {
            "race_cost": tickets[0].get("cost_yen", 0),
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "着順未取得・精算保留",
        }

    finishes = result_data.get("finishes", [])
    payouts = result_data.get("payouts", {})
    finish_order = [
        item["horse_no"] for item in sorted(finishes, key=lambda x: x["finish"])
    ]

    if not finish_order:
        return {
            "race_cost": tickets[0].get("cost_yen", 0),
            "win_return": 0,
            "race_profit": None,
            "win_hit": None,
            "settlement_complete": False,
            "settlement_status": "着順を確認できず精算保留",
        }

    finish_pos = {horse_no: i + 1 for i, horse_no in enumerate(finish_order)}
    line_items = tickets[0].get("line_items", [])
    total_cost = safe_int(tickets[0].get("cost_yen"), 0)

    # 各券種の払戻情報を組み合わせキーに整理
    payout_lookup = {}
    for kind, entries in payouts.items():
        payout_lookup[kind] = {}
        for entry in entries:
            key = normalize_combo(kind, entry.get("horses", []))
            payout_lookup[kind][key] = safe_int(
                entry.get("payout_yen_per_100"), 0
            )

    total_return = 0
    win_hit = None
    all_payouts_known = True
    any_hit = False
    settled_lines = []

    for line in line_items:
        kind = line.get("type")
        horses = line.get("horses", [])
        stake = safe_int(line.get("stake_yen"), 0)

        hit = False

        if kind == "win":
            hit = bool(horses and finish_order and horses[0] == finish_order[0])
            if hit:
                win_hit = True
            elif win_hit is None:
                win_hit = False

        elif kind == "quinella":
            hit = len(horses) == 2 and all(h in finish_pos for h in horses)
            hit = hit and all(finish_pos[h] <= 2 for h in horses)

        elif kind == "wide":
            hit = len(horses) == 2 and all(h in finish_pos for h in horses)
            hit = hit and all(finish_pos[h] <= 3 for h in horses)

        elif kind == "trio":
            hit = len(horses) == 3 and all(h in finish_pos for h in horses)
            hit = hit and all(finish_pos[h] <= 3 for h in horses)

        elif kind == "trifecta":
            hit = (
                len(horses) == 3
                and len(finish_order) >= 3
                and list(horses) == finish_order[:3]
            )

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
        lookup_kind = "trifecta" if kind == "trifecta" else kind
        key = normalize_combo(lookup_kind, horses)
        payout_per_100 = payout_lookup.get(lookup_kind, {}).get(key)

        if payout_per_100 is None or payout_per_100 <= 0:
            all_payouts_known = False
            settled_lines.append({
                "type": kind,
                "horses": horses,
                "stake_yen": stake,
                "hit": True,
                "return_yen": None,
                "status": "的中条件に該当・払戻未確認",
            })
            continue

        # JRA/NARの表示払戻は通常100円あたり
        returned = int(round(payout_per_100 * stake / 100))
        total_return += returned

        settled_lines.append({
            "type": kind,
            "horses": horses,
            "stake_yen": stake,
            "hit": True,
            "return_yen": returned,
            "status": "払戻確認済み",
        })

    if win_hit is None:
        win_hit = False

    complete = all_payouts_known

    # 単勝の払戻のみを既存HTML互換フィールドへ表示する
    win_return = 0
    win_line = next((x for x in settled_lines if x["type"] == "win" and x["hit"]), None)
    if win_line and win_line.get("return_yen") is not None:
        win_return = win_line["return_yen"]

    if complete:
        status = "券種別精算完了"
        profit = total_return - total_cost
    elif any_hit:
        status = "的中候補あり・一部払戻未確認"
        profit = None
    else:
        status = "的中判定済み・払戻情報の一部未確認"
        profit = None

    return {
        "race_cost": total_cost,
        "win_return": win_return,
        "all_bet_return": total_return if complete else None,
        "race_profit": profit,
        "win_hit": win_hit,
        "any_bet_hit": any_hit,
        "settlement_complete": complete,
        "settlement_status": status,
        "settled_lines": settled_lines,
    }


# ============================================================
# 8. レースページ解析
# ============================================================

def parse_race(html, race_id, kind, base_url, date_iso, is_tomorrow):
    soup = soup_of(html)
    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)
    meta_text = parse_meta(soup)

    time_match = re.search(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)", meta_text)
    post_time = time_match.group(1) if time_match else ""

    race_name = first_text(soup, [
        ".RaceName", ".race_name", "h1",
        ".RaceList_ItemTitle", "[class*='RaceName']",
        "[class*='raceName']",
    ])

    if not race_name or race_name in ["出馬表", "レース情報"]:
        race_name = f"{venue}{race_no}R" if venue and race_no else "レース名未取得"

    surface = ""
    if re.search(r"ダート|ダ\s*\d{3,4}", meta_text):
        surface = "ダート"
    elif "芝" in meta_text:
        surface = "芝"

    distance_match = re.search(
        r"(?:芝|ダート|ダ)?\s*(\d{3,4})\s*m",
        meta_text,
        re.I,
    )
    if not distance_match:
        distance_match = re.search(r"(\d{3,4})\s*m", meta_text, re.I)

    distance = int(distance_match.group(1)) if distance_match else None

    runners = parse_runner_rows(soup, surface, venue)
    ranked = score_runners(runners, surface, venue)
    outsiders, longshots = select_outsiders(ranked)
    tickets = build_tickets(ranked, outsiders)

    # 発走時刻が取得できた場合のみ、発走後かどうかを判定
    is_finished = False
    if post_time and not is_tomorrow:
        try:
            hour, minute = [int(x) for x in post_time.split(":")]
            scheduled = NOW.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            is_finished = NOW >= scheduled + timedelta(minutes=10)
        except (ValueError, IndexError):
            is_finished = False

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

    if is_finished and not is_tomorrow:
        result_data = get_result_data(base_url, race_id)
        settlement = settle_tickets(tickets, result_data)

    result_finishes = [
        item["horse_no"]
        for item in sorted(
            result_data.get("finishes", []),
            key=lambda x: x["finish"],
        )
    ]

    payout_summary = {}
    for kind_key, entries in result_data.get("payouts", {}).items():
        payout_summary[kind_key] = entries

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
        "runner_count": len(runners),
        "horses": ranked,
        "top5": ranked[:5],
        "outsiders": outsiders,
        "longshots": longshots,
        "tickets": tickets,
        "is_finished": is_finished,
        "result_finishes": result_finishes,
        "payouts": payout_summary,
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
        "is_recommended": bool(
            race_no == 11 or len(outsiders) >= 2 or len(longshots) >= 2
        ),
        "prediction_status": "未検証の簡易評価",
        "probability_note": (
            "表示順位・スコアは未検証の評価指標です。"
            "校正済み勝率や利益を保証する数値ではありません。"
        ),
    }


# ============================================================
# 9. 履歴の読み込みと互換性維持
# ============================================================

def load_history():
    if not HISTORY.exists():
        return {
            "schema_version": 26,
            "snapshots": {},
            "stats": {},
            "horse_form_cache": {},
        }

    try:
        value = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("history root is not object")

        if not isinstance(value.get("snapshots"), dict):
            value["snapshots"] = {}

        if not isinstance(value.get("horse_form_cache"), dict):
            value["horse_form_cache"] = {}

        if not isinstance(value.get("stats"), dict):
            value["stats"] = {}

        # 既存の snapshots / horse_form_cache は消さずに維持
        value["schema_version"] = 26
        return value

    except (OSError, ValueError, json.JSONDecodeError) as exc:
        warn(
            "history.json の読み込みに失敗。履歴保護のため既存ファイルを"
            f"上書きしないでください。原因: {exc.__class__.__name__}"
        )
        raise


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})

    # 既に完全精算済みなら過去記録を上書きしない
    if old.get("settlement_complete") is True:
        return

    # 古い履歴には settlement_complete がないため、従来形式も尊重
    if old.get("is_finished") and old.get("win_hit") is not None:
        if old.get("settlement_status") in (
            "券種別精算完了",
            "単勝のみ確定・他券種は組合せ検証未対応",
        ):
            return

    ticket = race.get("tickets", [{}])
    ticket = ticket[0] if ticket else {}

    snapshot = {
        "race_id": race_id,
        "date": race.get("date", TODAY_ISO),
        "kind": race.get("kind"),
        "course": race.get("course"),
        "race_no": race.get("race_no"),
        "name": race.get("name"),
        "cost": safe_int(race.get("race_cost"), ticket.get("cost_yen", 0)),
        "is_finished": bool(race.get("is_finished")),
        "win_hit": race.get("win_hit"),
        "win_return": safe_int(race.get("win_return"), 0),
        "race_profit": race.get("race_profit"),
        "all_bet_return": race.get("all_bet_return"),
        "settlement_complete": bool(race.get("settlement_complete")),
        "settlement_status": race.get("settlement_status", ""),
        "updated_at": NOW.isoformat(),
        "frozen_prediction": {
            "top5": [
                {
                    "horse_no": horse.get("horse_no"),
                    "name": horse.get("name"),
                    "score": horse.get("score"),
                    "odds": horse.get("odds"),
                    "rank": horse.get("rank"),
                }
                for horse in race.get("top5", [])
            ],
            "tickets": ticket,
            "prediction_status": race.get("prediction_status"),
        },
        "last_odds": {
            str(horse.get("horse_no")): horse.get("odds")
            for horse in race.get("horses", [])
        },
    }

    # 古いスナップショットのオッズ履歴は引き継ぐ
    if isinstance(old.get("odds_snapshots"), list):
        snapshot["odds_snapshots"] = old["odds_snapshots"]
    else:
        snapshot["odds_snapshots"] = []

    # 初回予測の固定時刻を保存
    if old.get("prediction_created_at"):
        snapshot["prediction_created_at"] = old["prediction_created_at"]
    else:
        snapshot["prediction_created_at"] = NOW.isoformat()

    snapshots[race_id] = snapshot


def calculate_stats(snapshots):
    """
    完全精算済み記録だけで回収率を計算する。
    古い履歴で単勝のみ精算したものは、全券種回収率に混ぜない。
    """
    all_items = list(snapshots.values())

    settled_win = [
        item for item in all_items
        if item.get("is_finished")
        and item.get("win_hit") is not None
        and item.get("settlement_status")
        in (
            "単勝のみ確定・他券種は組合せ検証未対応",
            "win_only_legacy",
        )
    ]

    settled_all = [
        item for item in all_items
        if item.get("settlement_complete") is True
        and item.get("all_bet_return") is not None
        and item.get("race_profit") is not None
    ]

    win_stake = sum(safe_int(item.get("cost"), 0) for item in settled_win)
    win_return = sum(safe_int(item.get("win_return"), 0) for item in settled_win)
    win_hits = sum(1 for item in settled_win if item.get("win_hit") is True)

    all_stake = sum(safe_int(item.get("cost"), 0) for item in settled_all)
    all_return = sum(safe_int(item.get("all_bet_return"), 0) for item in settled_all)
    all_hits = sum(
        1 for item in settled_all
        if item.get("race_profit") is not None
        and safe_int(item.get("race_profit"), -1) > -safe_int(item.get("cost"), 0)
    )

    return {
        "races_seen": len(all_items),
        "races_settled": len(settled_win) + len(settled_all),
        "win_bets": len(settled_win),
        "win_hits": win_hits,
        "total_stake_yen": win_stake,
        "total_return_yen": win_return,
        "roi_pct": round(win_return / win_stake * 100, 1) if win_stake else 0.0,
        "win_hit_rate_pct": round(win_hits / len(settled_win) * 100, 1)
        if settled_win else 0.0,
        "all_bet_settled_races": len(settled_all),
        "all_bet_stake_yen": all_stake,
        "all_bet_return_yen": all_return,
        "all_bet_roi_pct": round(all_return / all_stake * 100, 1)
        if all_stake else 0.0,
        "all_bet_hit_races": all_hits,
        "accounting_note": (
            "旧履歴の単勝成績と、新方式の全券種精算成績は別集計。"
            "未取得・精算保留のレースは回収率計算に含めません。"
        ),
    }


# ============================================================
# 10. メイン処理
# ============================================================

def fetch_races_for_date(date_str, is_tomorrow):
    all_races = []

    date_iso = (
        (NOW + timedelta(days=1)).strftime("%Y-%m-%d")
        if is_tomorrow else TODAY_ISO
    )

    for source in SOURCES:
        list_html = get_html(source["list"] + date_str)
        race_ids = extract_race_ids(list_html)

        if not race_ids:
            warn(
                f"{source['kind']} {date_str}: レース一覧からIDを取得できません。"
                "サイト構造変更・開催なし・アクセス制限の可能性があります。"
            )
            continue

        print(f"[INFO] {source['kind']} {date_str}: {len(race_ids)} race IDs")

        for race_id in race_ids:
            race_url = f"{source['base']}/race/shutuba.html?race_id={race_id}"
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

            if race["runner_count"] >= MIN_RUNNERS:
                all_races.append(race)
            else:
                warn(
                    f"{source['kind']} {race_id}: 出走馬を"
                    f"{race['runner_count']}頭しか解析できませんでした"
                )

            time.sleep(REQUEST_DELAY)

    all_races.sort(
        key=lambda race: (
            race.get("post_time") == "未取得",
            race.get("post_time", ""),
            race.get("course", ""),
            race.get("race_no") or 0,
        )
    )
    return all_races


def main():
    print(f"=== {ENGINE_VERSION} START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")

    history_data = load_history()
    snapshots = history_data["snapshots"]

    today_races = fetch_races_for_date(TODAY, False)
    tomorrow_races = fetch_races_for_date(TOMORROW, True)

    for race in today_races:
        update_snapshot(snapshots, race)

    # 古い履歴だけを削除。直近180日分は維持
    cutoff = (NOW - timedelta(days=HISTORY_RETENTION_DAYS)).date()

    for race_id, item in list(snapshots.items()):
        try:
            item_date = datetime.strptime(
                item.get("date", ""), "%Y-%m-%d"
            ).date()
            if item_date < cutoff:
                del snapshots[race_id]
        except (ValueError, TypeError):
            # 日付不明の既存履歴は誤削除しない
            continue

    stats = calculate_stats(snapshots)

    history_data["schema_version"] = 26
    history_data["updated_at"] = NOW.isoformat()
    history_data["stats"] = stats
    history_data["snapshots"] = snapshots

    # horse_form_cache など、既存の他のトップレベルデータは保持する
    save_json(HISTORY, history_data)

    tomorrow_recommended = [
        race for race in tomorrow_races if race.get("is_recommended")
    ]

    if today_races or tomorrow_races:
        status = "OK"
    else:
        status = "NO_RACES"

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
                key=lambda item: (
                    item.get("date", ""),
                    item.get("race_id", ""),
                ),
                reverse=True,
            )[:100],
        },
    }

    save_json(OUT, data)

    print(
        f"{ENGINE_VERSION} | status={status} "
        f"| today={len(today_races)} "
        f"| tomorrow={len(tomorrow_races)} "
        f"| recommended={len(tomorrow_recommended)} "
        f"| history={len(snapshots)} "
        f"| settled={stats['races_settled']}"
    )

    if WARNINGS:
        print(f"[WARN] warnings={len(WARNINGS)}")
        print("[INFO] 詳細は docs/data.json の warnings を確認してください。")

    print("=== FINISHED ===")


if __name__ == "__main__":
    main()