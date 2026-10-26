#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v25.0
Paper-only horse racing analysis.
No real betting, wallet, payment, or account actions.
Predictions and EV are experimental and uncalibrated.
"""

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
TOMORROW_ISO = (NOW + timedelta(days=1)).strftime("%Y-%m-%d")

ENGINE_VERSION = "BAGEN_25.0"
REQUEST_TIMEOUT = (5, 10)
REQUEST_DELAY = 0.2
MAX_RUN_SECONDS = 480
MAX_RACES_PER_SOURCE = 80
MAX_WARNINGS = 100
MAX_FORM_CACHE = 1500
HISTORY_RETENTION_DAYS = 180
MAX_ODDS_SNAPSHOTS = 100
MIN_RUNNERS = 2
BET_BUDGET_YEN = 2000

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
    "50": "園田", "51": "姫路", "54": "姫路", "55": "高知", "56": "佐賀",
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
POSITIVE_WORDS = ["好気配", "一変", "立て直し", "上向き", "絶好", "シャープ", "好調", "順調"]
NEGATIVE_WORDS = ["太目", "硬い", "入れ込み", "不安", "モタれる"]
PAYOUT_TYPES = ["win", "quinella", "trio", "wide", "trifecta"]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAGEN-Keiba-PaperBot/25.0)",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
})

START_TIME = time.monotonic()
WARNINGS = []
FORM_CACHE = {}
STOP_REQUESTS = False


def warn(message):
    print(f"[WARN] {message}")
    if len(WARNINGS) < MAX_WARNINGS:
        WARNINGS.append(str(message))


def runtime_ok():
    global STOP_REQUESTS
    if time.monotonic() - START_TIME >= MAX_RUN_SECONDS:
        STOP_REQUESTS = True
        return False
    return not STOP_REQUESTS


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def number(value):
    text = clean(value).replace(",", "").replace("．", ".")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        result = float(match.group(1))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def safe_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def soup_of(html):
    return BeautifulSoup(html or "", "html.parser")


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def select(node, selector):
    try:
        return node.select(selector)
    except Exception:
        return []


def one(node, selector):
    try:
        return node.select_one(selector)
    except Exception:
        return None


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        warn(f"JSON read failed {path.name}: {exc}")
        return default


def get_html(url):
    """Single attempt per URL. Avoid repeated requests when a site errors."""
    if not runtime_ok():
        return ""
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        time.sleep(REQUEST_DELAY)
        return response.text
    except requests.HTTPError as exc:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else "unknown"
        warn(f"HTTP {status}: {url}")
    except requests.Timeout:
        warn(f"Request timeout: {url}")
    except requests.RequestException as exc:
        warn(f"Request error {type(exc).__name__}: {url}")
    return ""


def empty_payouts():
    return {kind: {} for kind in PAYOUT_TYPES}


def race_no_from_id(race_id):
    if not re.fullmatch(r"\d{12,14}", str(race_id)):
        return None
    value = int(str(race_id)[-2:])
    return value if 1 <= value <= 12 else None


def venue_from_id(race_id, kind):
    if not re.fullmatch(r"\d{12,14}", str(race_id)):
        return ""
    codes = JRA_CODES if kind == "中央" else NAR_CODES
    return codes.get(str(race_id)[4:6], "")


def extract_race_ids(html):
    if not html:
        return []
    found, seen = [], set()
    soup = soup_of(html)
    for anchor in select(soup, 'a[href*="race_id="], a[href*="shutuba.html"]'):
        match = re.search(r"race_id=(\d{12,14})", anchor.get("href", ""))
        if not match:
            continue
        rid = match.group(1)
        if rid not in seen and race_no_from_id(rid):
            seen.add(rid)
            found.append(rid)
    return found[:MAX_RACES_PER_SOURCE]


def parse_meta(soup):
    result = []
    for selector in [
        ".RaceData01", ".RaceData02", ".RaceData", ".race_data",
        "[class*='RaceData']", ".raceData01", ".raceData02",
    ]:
        for node in select(soup, selector):
            value = text_of(node)
            if value and value not in result:
                result.append(value)
    return " ".join(result)


def parse_race_time(text):
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""


def parse_distance(text):
    match = re.search(r"(?:芝|ダート|ダ)?\s*(\d{3,4})\s*m", text or "", re.I)
    if not match:
        match = re.search(r"(\d{3,4})\s*m", text or "", re.I)
    return int(match.group(1)) if match else None


def parse_surface(text):
    if re.search(r"ダート|ダ\s*\d{3,4}", text or ""):
        return "ダート"
    return "芝" if "芝" in (text or "") else ""


def scheduled_datetime(race):
    post, date_text = race.get("post_time"), race.get("date")
    if not post or not date_text or ":" not in post:
        return None
    try:
        return datetime.strptime(
            f"{date_text} {post}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=JST)
    except ValueError:
        return None


def parse_horse_id(anchor):
    if not anchor:
        return ""
    match = re.search(r"/horse/(\d+)", anchor.get("href", ""))
    return match.group(1) if match else ""


def previous_form_points(form, current_distance):
    points, reasons = 0.0, []
    if not form:
        return 0.0, ["前走データ未取得：前走補正なし"]

    finish = form.get("finish")
    if finish is not None:
        if finish == 1:
            points += 3
            reasons.append("前走1着")
        elif finish <= 3:
            points += 2
            reasons.append(f"前走{finish}着")
        elif finish <= 5:
            points += 0.8
            reasons.append(f"前走{finish}着")
        elif finish >= 10:
            points -= 0.8
            reasons.append(f"前走{finish}着：巻き返し要検証")

    margin = form.get("margin_estimate")
    if margin is not None:
        if margin <= 0.3:
            points += 1
            reasons.append("前走の着差が小さい")
        elif margin >= 1.5:
            points -= 0.5
            reasons.append("前走の着差が大きい")

    positions = form.get("passing_order") or []
    if positions:
        reasons.append("前走通過順 " + "-".join(map(str, positions)))

    if form.get("final_3f") is not None:
        reasons.append(f"前走上がり3F {form['final_3f']:g}秒")

    old_distance = form.get("distance_m")
    if current_distance and old_distance:
        diff = abs(current_distance - old_distance)
        if diff <= 200:
            points += 0.3
            reasons.append("前走と今回の距離差が小さい")
        elif diff >= 600:
            reasons.append("前走と今回の距離差が大きい")

    return points, reasons


def get_previous_race_form(horse_id, base_url):
    # v25 deliberately avoids fetching individual horse-profile pages.
    # Cached data from previous runs is still usable.
    if not horse_id:
        return None
    return FORM_CACHE.get(str(horse_id))


def parse_runner_number(row):
    for selector in [
        "td.Umaban", ".Umaban", "[class*='Umaban']",
        "td.Num", "[class*='Num']",
    ]:
        value = number(text_of(one(row, selector)))
        if value is not None and 1 <= value <= 18:
            return int(value)

    for cell in row.find_all(["td", "th"], recursive=False)[:5]:
        if "Waku" in " ".join(cell.get("class", [])):
            continue
        value = number(text_of(cell))
        if value is not None and 1 <= value <= 18:
            return int(value)
    return None


def parse_frame(row):
    for selector in ["td.Waku", ".Waku", "[class*='Waku']"]:
        value = number(text_of(one(row, selector)))
        if value is not None and 1 <= value <= 8:
            return int(value)
    return None


def parse_odds_popularity(row):
    odds = popularity = None
    for selector in [
        "td.Odds", ".Odds", "[class*='Odds']", ".odds", "td[class*='Odds']",
    ]:
        value = number(text_of(one(row, selector)))
        if value is not None and 0 < value <= 9999:
            odds = value
            break

    for selector in [
        "td.Popular_Ninki", ".Popular_Ninki", "[class*='Ninki']",
        ".Popular", "td[class*='Popular']",
    ]:
        value = number(text_of(one(row, selector)))
        if value is not None and 1 <= value <= 18:
            popularity = int(value)
            break
    return odds, popularity


def parse_weight(row):
    node = one(
        row,
        "td.Horse_Weight, .Horse_Weight, [class*='HorseWeight'], [class*='Weight']",
    )
    match = re.search(r"(\d{3})\s*\(([+-]?\d+)\)", text_of(node))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_runner_rows(soup, surface, venue, base_url, distance):
    rows = select(
        soup,
        "tr.HorseList, tr[class*='Horse'], "
        "table.Shutuba_Table tr, table.ShutubaTable tr",
    )
    runners, seen = [], set()

    for row in rows:
        anchor = one(row, 'a[href*="/horse/"]')
        horse_name = text_of(anchor)
        if not horse_name or "馬名" in horse_name:
            continue

        horse_no = parse_runner_number(row)
        if horse_no is None or horse_no in seen:
            continue
        seen.add(horse_no)

        row_text = text_of(row)
        frame = parse_frame(row)
        odds, popularity = parse_odds_popularity(row)
        jockey = text_of(one(
            row,
            ".Jockey, td.Jockey, [class*='Jockey'], .jockey, td[class*='jockey']",
        ))
        weight, weight_diff = parse_weight(row)
        horse_id = parse_horse_id(anchor)

        sire_match = re.search(
            r"(?:父|種牡馬|Sire)[:：]?\s*([^\s（）()]+)", row_text
        )
        sire = sire_match.group(1) if sire_match else ""
        dirt_blood = any(name in row_text or name in sire for name in DIRT_SIRES)
        power_blood = any(name in row_text or name in sire for name in POWER_SIRES)
        apprentice = any(mark in jockey for mark in ["▲", "△", "☆", "◇"])
        top_jockey = any(name in jockey for name in TOP_JOCKEYS)
        positive = any(word in row_text for word in POSITIVE_WORDS)
        negative = any(word in row_text for word in NEGATIVE_WORDS)

        form = get_previous_race_form(horse_id, base_url)
        form_points, form_reasons = previous_form_points(form, distance)
        reasons = []

        if odds is not None:
            reasons.append(f"取得単勝オッズ {odds:g}倍")
        if popularity is not None:
            reasons.append(f"取得人気順位 {popularity}番人気")
        if jockey:
            reasons.append(f"取得騎手情報：{jockey}")
        if apprentice:
            reasons.append("騎手欄に減量記号を検出")
        if top_jockey:
            reasons.append("登録騎手リストとの名前一致")
        if surface == "ダート" and dirt_blood:
            reasons.append("掲載テキスト内にダート血統候補を検出")
        if surface == "芝" and power_blood:
            reasons.append("掲載テキスト内に血統候補を検出")
        if weight_diff is not None and abs(weight_diff) >= 6:
            reasons.append(f"馬体重増減 {weight_diff:+d}kg")
        if positive:
            reasons.append("掲載テキストに好材料キーワード")
        if negative:
            reasons.append("掲載テキストに注意キーワード")
        reasons.extend(form_reasons)

        quality = {
            "odds": odds is not None,
            "popularity": popularity is not None,
            "jockey": bool(jockey),
            "frame": frame is not None,
            "weight_change": weight_diff is not None,
            "previous_race": bool(form),
        }

        runners.append({
            "horse_no": horse_no,
            "number": horse_no,
            "frame_no": frame,
            "horse": horse_name,
            "name": horse_name,
            "horse_id": horse_id or None,
            "jockey": jockey or "未取得",
            "odds": odds,
            "popularity": popularity,
            "score": 0.0,
            "rank": None,
            "reasons": reasons,
            "caution": "未検証のヒューリスティック評価です。勝率や利益を保証しません。",
            "is_apprentice": apprentice,
            "is_top_jockey": top_jockey,
            "is_inner": frame in (1, 2) if frame else False,
            "is_outer": frame in (7, 8) if frame else False,
            "is_dirt_blood": dirt_blood,
            "is_power_blood": power_blood,
            "is_positive_memo": positive,
            "is_negative_memo": negative,
            "weight": weight,
            "w_diff": weight_diff,
            "previous_race": form,
            "previous_race_points": round(form_points, 2),
            "data_quality": quality,
        })

    return sorted(runners, key=lambda x: x["horse_no"])


def market_points(odds):
    if odds is None or odds <= 0:
        return None
    return max(0.0, min(40.0, 40.0 - 10.0 * math.log(odds)))


def score_runners(runners, surface, venue, heavy=False):
    for horse in runners:
        odds = horse.get("odds")
        popularity = horse.get("popularity")
        market = market_points(odds)
        score = market if market is not None else 18.0

        if popularity is not None:
            score += max(0.0, 6.0 - (popularity - 1) * 0.45)
        if horse["is_top_jockey"]:
            score += 2
            horse["reasons"].append("騎手名一致による小幅補正")
        if horse["is_apprentice"]:
            horse["reasons"].append("減量記号を検出（自動加点なし）")

        multiplier = 1.25 if heavy else 1.0
        if surface == "ダート" and horse["is_dirt_blood"]:
            score += 2 * multiplier
            horse["reasons"].append("ダート血統候補による参考補正")
        if surface == "芝" and horse["is_power_blood"]:
            score += 1.5 * multiplier
            horse["reasons"].append("芝血統候補による参考補正")

        if venue in ["東京", "新潟"] and horse["is_outer"]:
            score += 0.5
            horse["reasons"].append("競馬場・外枠の仮説的な小幅補正")
        elif venue in ["中山", "小倉", "福島", "札幌"] and horse["is_inner"]:
            score += 0.5
            horse["reasons"].append("競馬場・内枠の仮説的な小幅補正")

        diff = horse.get("w_diff")
        if diff is not None and 8 <= diff <= 16:
            score += 0.5
            horse["reasons"].append("馬体重増加の小幅補正")
        elif diff is not None and diff <= -12:
            score -= 1
            horse["reasons"].append("大幅な馬体重減少に注意")

        score += float(horse.get("previous_race_points") or 0)
        if horse["is_positive_memo"]:
            score += 0.5
        if horse["is_negative_memo"]:
            score -= 1.5
            horse["reasons"].append("注意キーワードによる減点")
        if odds is not None and odds < 1.5:
            horse["reasons"].append("低オッズ：配当妙味は慎重に評価")
        if odds is None:
            horse["reasons"].append("オッズ未取得：市場比較は不完全")

        quality = horse.get("data_quality", {})
        confidence = sum(bool(v) for v in quality.values()) / max(1, len(quality))
        horse["score"] = round(max(0.0, score), 2)
        horse["score_confidence"] = round(confidence * 100)
        horse["market_points"] = round(market, 2) if market is not None else None
        if confidence < 0.6:
            horse["reasons"].append("取得項目不足：評価信頼度に制限")

    return sorted(runners, key=lambda x: (-x["score"], x["horse_no"]))


def estimate_probabilities(ranked):
    if not ranked:
        return

    scores = [float(x.get("score") or 0) for x in ranked]
    peak = max(scores)
    raw = [math.exp(max(-30, min(30, (s - peak) / 8.0))) for s in scores]
    total = sum(raw)
    probabilities = [v / total for v in raw] if total else [1 / len(ranked)] * len(ranked)

    for horse, probability in zip(ranked, probabilities):
        odds = horse.get("odds")
        horse["estimated_win_probability"] = round(probability, 6)
        horse["estimated_win_probability_pct"] = round(probability * 100, 2)
        horse["probability_method"] = "heuristic_softmax_unvalidated"

        if odds is not None and odds > 0:
            ev = probability * odds
            horse["ev"] = round(ev, 4)
            horse["ev_pct"] = round((ev - 1) * 100, 2)
            horse["ev_label"] = (
                "実験上の期待値候補" if ev >= 1.15
                else "期待値境界付近" if ev >= 1
                else "実験推定では割高"
            )
        else:
            horse["ev"] = None
            horse["ev_pct"] = None
            horse["ev_label"] = "オッズ未取得"

        horse["ev_warning"] = "未校正のスコア由来推定値。実証済みの期待値ではありません。"


def classify_value_horses(ranked):
    outsiders, longshots = [], []
    if not ranked:
        return outsiders, longshots

    cutoff = max(0.0, max(x["score"] for x in ranked) - 5.0)
    for horse in ranked:
        odds = horse.get("odds")
        if odds is None or odds < 10 or horse["score"] < cutoff:
            continue
        if odds < 30:
            horse["value_label"] = "穴馬候補"
            horse["value_reason"] = "単勝10〜30倍帯で評価点が比較的高い候補。推定値は未校正です。"
            outsiders.append(horse)
        else:
            horse["value_label"] = "大穴候補"
            horse["value_reason"] = "単勝30倍以上で評価点が比較的高い候補。好走を保証しません。"
            longshots.append(horse)

    key = lambda x: (-x["score"], x["horse_no"])
    return sorted(outsiders, key=key)[:3], sorted(longshots, key=key)[:3]


def ticket_item(kind, horses, stake, label):
    return {
        "type": kind,
        "horses": [int(x) for x in horses],
        "stake_yen": int(stake),
        "label": label,
    }


def build_tickets(ranked, outsiders):
    if len(ranked) < 3:
        return []

    top = ranked[:5]
    h1, h2, h3 = [x["horse_no"] for x in top[:3]]
    h4 = top[3]["horse_no"] if len(top) >= 4 else h3
    outsider = next(
        (x["horse_no"] for x in outsiders if x["horse_no"] not in {h1, h2, h3, h4}),
        None,
    )
    use_b = outsider is not None and (
        (top[0].get("odds") or 0) >= 2.8 or len(outsiders) >= 2
    )

    if use_b:
        lines = [
            ticket_item("win", [h1], 300, f"単勝: {h1}番 (300円)"),
            ticket_item("quinella", sorted([h1,h2]), 200, f"馬連: {h1}-{h2} (200円)"),
            ticket_item("quinella", sorted([h1,h3]), 200, f"馬連: {h1}-{h3} (200円)"),
            ticket_item("quinella", sorted([h1,outsider]), 200, f"馬連: {h1}-{outsider} (200円)"),
            ticket_item("trio", sorted([h1,h2,h3]), 100, f"3連複: {h1}-{h2}-{h3} (100円)"),
            ticket_item("trio", sorted([h1,h2,outsider]), 100, f"3連複: {h1}-{h2}-{outsider} (100円)"),
            ticket_item("trio", sorted([h1,h3,outsider]), 100, f"3連複: {h1}-{h3}-{outsider} (100円)"),
            ticket_item("wide", sorted([h1,outsider]), 100, f"ワイド: {h1}-{outsider} (100円)"),
            ticket_item("wide", sorted([h2,outsider]), 100, f"ワイド: {h2}-{outsider} (100円)"),
            ticket_item("wide", sorted([h3,outsider]), 100, f"ワイド: {h3}-{outsider} (100円)"),
            ticket_item("trifecta", [h1,outsider,h2], 100, f"3連単: {h1}→{outsider}→{h2} (100円)"),
            ticket_item("trifecta", [h1,outsider,h3], 100, f"3連単: {h1}→{outsider}→{h3} (100円)"),
            ticket_item("trifecta", [h1,outsider,h4], 100, f"3連単: {h1}→{outsider}→{h4} (100円)"),
        ]
        pattern = "パターンB（穴馬候補を含む）"
        note = "穴馬候補を含む紙上検証用買い目。利益を保証しません。"
    else:
        lines = [
            ticket_item("win", [h1], 500, f"単勝: {h1}番 (500円)"),
            ticket_item("quinella", sorted([h1,h2]), 300, f"馬連: {h1}-{h2} (300円)"),
            ticket_item("quinella", sorted([h1,h3]), 300, f"馬連: {h1}-{h3} (300円)"),
            ticket_item("trio", sorted([h1,h2,h3]), 600, f"3連複: {h1}-{h2}-{h3} (600円)"),
            ticket_item("wide", sorted([h1,h4]), 100, f"ワイド: {h1}-{h4} (100円)"),
            ticket_item("wide", sorted([h2,h4]), 100, f"ワイド: {h2}-{h4} (100円)"),
        ]
        pattern = "パターンA（上位評価中心）"
        note = "取得情報による紙上シミュレーション。利益を保証しません。"

    unique = {}
    for item in lines:
        key = (item["type"], tuple(item["horses"]))
        if key in unique:
            unique[key]["stake_yen"] += item["stake_yen"]
            unique[key]["label"] = (
                f"{item['type']} {'-'.join(map(str,item['horses']))} "
                f"({unique[key]['stake_yen']}円)"
            )
        else:
            unique[key] = dict(item)

    lines = list(unique.values())
    total = sum(x["stake_yen"] for x in lines)
    nums = [x["horse_no"] for x in top]
    candidates = []
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            pair = sorted([nums[i], nums[j]])
            if ("wide", tuple(pair)) not in unique:
                candidates.append(pair)

    while total + 100 <= BET_BUDGET_YEN and candidates:
        pair = candidates.pop(0)
        item = ticket_item("wide", pair, 100, f"ワイド: {pair[0]}-{pair[1]} (100円)")
        unique[("wide", tuple(pair))] = item
        lines.append(item)
        total += 100

    return [{
        "pattern_type": "B" if use_b else "A",
        "pattern": pattern,
        "cost_yen": total,
        "lines": [x["label"] for x in lines],
        "line_items": lines,
        "note": note,
    }]


def canonical_combo(kind, numbers):
    values = [int(x) for x in numbers]
    if kind == "win":
        return str(values[0]) if values else ""
    if kind in ("quinella", "wide", "trio"):
        return "-".join(map(str, sorted(values)))
    if kind == "trifecta":
        return "-".join(map(str, values))
    return ""


def detect_payout_type(text):
    text = clean(text)
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
    payouts = empty_payouts()
    rows = select(
        soup,
        "table.Payout_Detail_Table tr, table.PayoutTable tr, "
        "table.RacePayout tr, table[class*='Payout'] tr",
    )
    seen = set()

    for row in rows:
        row_text = text_of(row)
        if not row_text or row_text in seen:
            continue
        seen.add(row_text)
        kind = detect_payout_type(row_text)
        if not kind:
            continue

        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        needed = 1 if kind == "win" else 2 if kind in ("quinella", "wide") else 3
        combo, payout = "", None

        for cell in cells:
            value = text_of(cell)
            if re.search(r"\d+\s*[-－]\s*\d+", value):
                nums = re.findall(r"\d+", value)
                if len(nums) >= needed:
                    combo = canonical_combo(kind, nums[:needed])
                    break

        for cell in cells:
            match = re.search(r"([\d,]+)\s*円", text_of(cell))
            if match:
                try:
                    payout = int(match.group(1).replace(",", ""))
                except ValueError:
                    pass

        if combo and payout is not None:
            payouts[kind][combo] = payout

    return payouts


def parse_finish_rows(soup):
    finish_map = {}
    rows = select(
        soup,
        "table.RaceTable01 tr, table.ResultTable tr, table.RaceTable tr, "
        "table.race_table_01 tr, tr.HorseList",
    )

    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        finish = None

        for selector in ["td.Rank", ".Rank", "td.Result_Num", ".Result_Num", "td[class*='Rank']"]:
            value = number(text_of(one(row, selector)))
            if value is not None and 1 <= value <= 18:
                finish = int(value)
                break

        if finish is None:
            match = re.fullmatch(r"(\d{1,2})", text_of(cells[0]))
            if match and 1 <= int(match.group(1)) <= 18:
                finish = int(match.group(1))
        if finish is None:
            continue

        horse_no = None
        for selector in ["td.Umaban", ".Umaban", "[class*='Umaban']"]:
            value = number(text_of(one(row, selector)))
            if value is not None and 1 <= value <= 18:
                horse_no = int(value)
                break

        if horse_no is None:
            for cell in cells[1:5]:
                classes = " ".join(cell.get("class", []))
                if "Rank" in classes or "Result" in classes:
                    continue
                value = number(text_of(cell))
                if value is not None and 1 <= value <= 18:
                    horse_no = int(value)
                    break

        if horse_no is not None and finish not in finish_map:
            finish_map[finish] = horse_no

    return finish_map


def get_result_data(base_url, race_id):
    html = get_html(f"{base_url}/race/result.html?race_id={race_id}")
    if not html:
        return [], empty_payouts()
    soup = soup_of(html)
    finish_map = parse_finish_rows(soup)
    finishes = [finish_map[pos] for pos in sorted(finish_map) if pos in (1, 2, 3)]
    return finishes, parse_payouts(soup)


def settle_tickets(tickets, finishes, payouts):
    if not tickets or len(finishes) < 3:
        return {
            "race_cost": tickets[0].get("cost_yen", 0) if tickets else 0,
            "win_return": 0, "race_profit": 0, "win_hit": None,
            "settlement_complete": False, "settlement_status": "着順データ不足",
        }

    items = tickets[0].get("line_items", [])
    cost = int(tickets[0].get("cost_yen", 0))
    first = int(finishes[0])
    top2, top3 = set(map(int, finishes[:2])), set(map(int, finishes[:3]))
    returned, win_hit, missing = 0, False, False

    for item in items:
        kind = item.get("type")
        horses = list(map(int, item.get("horses", [])))
        stake = int(item.get("stake_yen", 0))
        if not horses or stake <= 0:
            continue

        if kind == "win":
            hit = len(horses) == 1 and horses[0] == first
            if hit:
                win_hit = True
        elif kind == "quinella":
            hit = len(horses) == 2 and set(horses) == top2
        elif kind == "trio":
            hit = len(horses) == 3 and set(horses) == top3
        elif kind == "wide":
            hit = len(horses) == 2 and set(horses).issubset(top3)
        elif kind == "trifecta":
            hit = len(horses) == 3 and horses == list(map(int, finishes[:3]))
        else:
            continue

        if not hit:
            continue
        combo = canonical_combo(kind, horses)
        payout = payouts.get(kind, {}).get(combo)
        if payout is None:
            missing = True
        else:
            returned += int(round(stake * payout / 100))

    if missing:
        return {
            "race_cost": cost, "win_return": 0, "race_profit": 0,
            "win_hit": win_hit, "settlement_complete": False,
            "settlement_status": "的中候補あり・払戻未確認のため未確定",
        }

    return {
        "race_cost": cost, "win_return": returned,
        "race_profit": returned - cost, "win_hit": win_hit,
        "settlement_complete": True, "settlement_status": "決済完了",
    }


def odds_snapshot(race):
    return {
        "captured_at": NOW.isoformat(),
        "minutes_to_post": race.get("minutes_to_post"),
        "odds": {
            str(h["horse_no"]): h.get("odds")
            for h in race.get("horses", [])
            if h.get("odds") is not None
        },
    }


def update_odds_history(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})
    history = old.get("odds_snapshots", [])
    current = odds_snapshot(race)

    if not history or history[-1].get("captured_at", "")[:16] != current["captured_at"][:16]:
        history.append(current)

    history = history[-MAX_ODDS_SNAPSHOTS:]
    old["odds_snapshots"] = history
    snapshots[race_id] = old

    post_dt = scheduled_datetime(race)
    comparison = {
        "ten_minutes": None, "one_minute": None,
        "available": False, "note": "必要な発走前スナップショットが未取得",
    }

    if post_dt:
        for target, key, tolerance in [(10, "ten_minutes", 4), (1, "one_minute", 2)]:
            candidates = []
            for snap in history:
                try:
                    captured = datetime.fromisoformat(snap["captured_at"])
                    mins = (post_dt - captured).total_seconds() / 60
                    if abs(mins - target) <= tolerance:
                        candidates.append((abs(mins - target), snap))
                except (ValueError, TypeError, KeyError):
                    pass
            if candidates:
                comparison[key] = min(candidates, key=lambda x: x[0])[1]

    comparison["available"] = bool(comparison["ten_minutes"] and comparison["one_minute"])
    if comparison["available"]:
        comparison["note"] = "10分前・1分前の近傍スナップショットを取得"

    trends = {}
    odds10 = (comparison.get("ten_minutes") or {}).get("odds", {})
    odds1 = (comparison.get("one_minute") or {}).get("odds", {})
    for horse_no in set(odds10) & set(odds1):
        a, b = safe_float(odds10.get(horse_no)), safe_float(odds1.get(horse_no))
        if a and b:
            trends[horse_no] = {
                "odds_10m": a, "odds_1m": b,
                "change_pct": round((b-a)/a*100, 2),
                "direction": "上昇" if b > a else "下降" if b < a else "変化なし",
            }

    race["odds_trend"] = {**comparison, "horses": trends}
    for horse in race.get("horses", []):
        trend = trends.get(str(horse["horse_no"]))
        horse["odds_trend"] = trend
        horse["odds_trend_reason"] = (
            f"10分前 {trend['odds_10m']:g}倍 → 1分前 {trend['odds_1m']:g}倍 "
            f"（{trend['change_pct']:+g}%）"
            if trend else "比較可能なオッズ履歴なし"
        )


def parse_race(html, race_id, kind, base_url):
    soup = soup_of(html)
    race_no = race_no_from_id(race_id)
    venue = venue_from_id(race_id, kind)
    meta = parse_meta(soup)
    post_time = parse_race_time(meta)
    surface = parse_surface(meta)
    distance = parse_distance(meta)
    heavy = bool(re.search(r"重|不良", meta))

    race_name = ""
    for selector in [".RaceName", ".race_name", "h1", ".RaceList_ItemTitle", "[class*='RaceName']", "[class*='raceName']"]:
        for node in select(soup, selector)[:3]:
            candidate = text_of(node)
            if candidate and "netkeiba" not in candidate.lower():
                race_name = candidate
                break
        if race_name:
            break
    if not race_name or race_name in ["出馬表", "レース情報"]:
        race_name = f"{venue}{race_no}R" if venue and race_no else "レース名未取得"

    runners = parse_runner_rows(soup, surface, venue, base_url, distance)
    ranked = score_runners(runners, surface, venue, heavy)
    estimate_probabilities(ranked)
    outsiders, longshots = classify_value_horses(ranked)
    tickets = build_tickets(ranked, outsiders)

    return {
        "id": str(race_id), "kind": kind,
        "category": "local" if kind == "地方" else "central",
        "race_no": race_no, "name": race_name,
        "course": venue or "競馬場未取得",
        "post_time": post_time or "未取得",
        "surface": surface or "未取得",
        "distance_m": distance, "runner_count": len(runners),
        "horses": ranked, "top5": ranked[:5],
        "outsiders": outsiders, "longshots": longshots, "tickets": tickets,
        "is_finished": False, "result_finishes": [],
        "win_hit": None, "win_return": 0,
        "race_cost": tickets[0]["cost_yen"] if tickets else 0,
        "race_profit": 0, "settlement_complete": False,
        "settlement_status": "発走前または結果待ち",
        "payouts": empty_payouts(),
        "is_recommended": bool(race_no == 11 or len(outsiders) >= 2 or len(longshots) >= 1),
        "prediction_method": "heuristic_v25_unvalidated",
        "prediction_warning": "推定勝率・EVは未校正。長期成績による検証が必要です。",
    }


def load_history():
    data = load_json(HISTORY, {
        "schema_version": 25,
        "snapshots": {},
        "horse_form_cache": {},
    })
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("snapshots"), dict):
        data["snapshots"] = {}
    if not isinstance(data.get("horse_form_cache"), dict):
        data["horse_form_cache"] = {}
    data["schema_version"] = 25
    return data


def freeze_prediction(race):
    return {
        "captured_at": NOW.isoformat(),
        "race_id": race["id"], "date": race.get("date", TODAY_ISO),
        "name": race.get("name"), "course": race.get("course"),
        "post_time": race.get("post_time"),
        "horses": [
            {
                "horse_no": h.get("horse_no"), "horse": h.get("horse"),
                "rank": h.get("rank"), "score": h.get("score"),
                "estimated_win_probability_pct": h.get("estimated_win_probability_pct"),
                "odds": h.get("odds"), "ev": h.get("ev"), "ev_label": h.get("ev_label"),
            }
            for h in race.get("horses", [])
        ],
        "tickets": race.get("tickets", []),
    }


def update_snapshot(snapshots, race):
    race_id = str(race["id"])
    old = snapshots.get(race_id, {})
    if old.get("settlement_complete") is True:
        return

    for key in ["race_id", "date", "kind", "course", "race_no", "name"]:
        default = TODAY_ISO if key == "date" else race.get(key)
        old.setdefault(key, default)

    if not old.get("frozen_prediction"):
        old["frozen_prediction"] = freeze_prediction(race)

    old["cost"] = int(race.get("race_cost") or 0)
    old["updated_at"] = NOW.isoformat()
    old["last_odds"] = {
        str(h["horse_no"]): h.get("odds") for h in race.get("horses", [])
    }
    update_odds_history(snapshots, race)

    post_dt = scheduled_datetime(race)
    finished = bool(post_dt and NOW >= post_dt + timedelta(minutes=10))
    race["is_finished"] = finished
    old["is_finished"] = finished

    if finished and not old.get("settlement_complete") and runtime_ok():
        base = "https://nar.netkeiba.com" if race.get("kind") == "地方" else "https://race.netkeiba.com"
        finishes, payouts = get_result_data(base, race_id)
        race["result_finishes"], race["payouts"] = finishes, payouts

        if len(finishes) >= 3 and race.get("tickets"):
            settlement = settle_tickets(race["tickets"], finishes, payouts)
        else:
            settlement = {
                "race_cost": race.get("race_cost", 0), "win_return": 0,
                "race_profit": 0, "win_hit": None,
                "settlement_complete": False,
                "settlement_status": "着順または買い目データ未確定",
            }

        race.update(settlement)
        old.update({
            "win_hit": settlement["win_hit"],
            "win_return": settlement["win_return"],
            "race_profit": settlement["race_profit"],
            "settlement_complete": settlement["settlement_complete"],
            "settlement_status": settlement["settlement_status"],
            "result_finishes": finishes, "payouts": payouts,
        })

    race["settlement_complete"] = bool(old.get("settlement_complete"))
    race["settlement_status"] = old.get("settlement_status", "発走前または結果待ち")
    race["win_hit"] = old.get("win_hit")
    race["win_return"] = int(old.get("win_return") or 0)
    race["race_profit"] = int(old.get("race_profit") or 0)


def calculate_stats(snapshots):
    settled = [
        x for x in snapshots.values()
        if x.get("settlement_complete") is True
        and x.get("is_finished") is True
        and x.get("win_hit") is not None
    ]
    stake = sum(int(x.get("cost") or 0) for x in settled)
    returned = sum(int(x.get("win_return") or 0) for x in settled)
    wins = sum(1 for x in settled if x.get("win_hit") is True)
    count = len(settled)

    return {
        "races_settled": count, "win_bets": count, "win_hits": wins,
        "total_stake_yen": stake, "total_return_yen": returned,
        "roi_pct": round(returned / stake * 100, 1) if stake else 0.0,
        "win_hit_rate_pct": round(wins / count * 100, 1) if count else 0.0,
        "accounting_note": "紙上シミュレーション。確認できた払戻だけ集計。実際の利益・勝率を保証しません。",
    }


def main():
    global FORM_CACHE

    history_data = load_history()
    snapshots = history_data["snapshots"]
    FORM_CACHE = history_data.get("horse_form_cache", {})
    if not isinstance(FORM_CACHE, dict):
        FORM_CACHE = {}

    today_races, tomorrow_races, errors = [], [], []
    targets = [
        (TODAY, TODAY_ISO, today_races, False),
        (TOMORROW, TOMORROW_ISO, tomorrow_races, True),
    ]

    for date_text, iso_date, target, is_tomorrow in targets:
        for source in SOURCES:
            if not runtime_ok():
                break

            print(f"[INFO] Race list: {source['kind']} {date_text}")
            list_html = get_html(source["list"] + date_text)
            race_ids = extract_race_ids(list_html)

            if not race_ids:
                message = f"{source['kind']} {date_text}: レース一覧からIDを取得できませんでした"
                errors.append(message)
                warn(message)
                continue

            print(f"[INFO] {source['kind']} {date_text}: {len(race_ids)} race IDs")

            for race_id in race_ids:
                if not runtime_ok():
                    break

                html = get_html(
                    f"{source['base']}/race/shutuba.html?race_id={race_id}"
                )
                if not html:
                    errors.append(f"{source['kind']} {race_id}: 出馬表取得失敗")
                    continue

                try:
                    race = parse_race(html, race_id, source["kind"], source["base"])
                    race["date"] = iso_date
                    race["is_tomorrow"] = is_tomorrow
                    post_dt = scheduled_datetime(race)
                    race["minutes_to_post"] = (
                        round((post_dt - NOW).total_seconds() / 60, 2)
                        if post_dt else None
                    )

                    for rank, horse in enumerate(race["horses"], 1):
                        horse["rank"] = rank
                    race["top5"] = race["horses"][:5]

                    if race["runner_count"] >= MIN_RUNNERS:
                        target.append(race)
                        if not is_tomorrow:
                            update_snapshot(snapshots, race)
                    else:
                        errors.append(
                            f"{source['kind']} {race_id}: "
                            f"出走馬の解析数が{race['runner_count']}頭"
                        )
                except Exception as exc:
                    message = f"{source['kind']} {race_id}: 解析エラー {type(exc).__name__}: {exc}"
                    errors.append(message)
                    warn(message)

    previous_data = load_json(OUT, {})
    if (
        not today_races and not tomorrow_races
        and isinstance(previous_data, dict)
        and (previous_data.get("races") or previous_data.get("tomorrow_races"))
    ):
        print("[ERROR] No races parsed; preserving existing data.json.")
        raise RuntimeError(
            "レース取得に失敗したため既存データを保護しました。"
            "Actionsログと通信エラーを確認してください。"
        )

    cutoff = (NOW - timedelta(days=HISTORY_RETENTION_DAYS)).date()
    for race_id, item in list(snapshots.items()):
        try:
            old_date = datetime.strptime(item.get("date", ""), "%Y-%m-%d").date()
            if old_date < cutoff:
                del snapshots[race_id]
        except (ValueError, TypeError):
            pass

    if len(FORM_CACHE) > MAX_FORM_CACHE:
        FORM_CACHE = dict(list(FORM_CACHE.items())[-MAX_FORM_CACHE:])

    stats = calculate_stats(snapshots)
    history_data.update({
        "schema_version": 25,
        "updated_at": NOW.isoformat(),
        "stats": stats,
        "snapshots": snapshots,
        "horse_form_cache": FORM_CACHE,
    })
    save_json(HISTORY, history_data)

    tomorrow_recommended = [r for r in tomorrow_races if r.get("is_recommended")]
    output = {
        "site": "BAGEN KEIBA",
        "engine_version": ENGINE_VERSION,
        "generated_at": NOW.isoformat(),
        "race_date": TODAY_ISO,
        "status": "OK" if today_races or tomorrow_races else "NO_RACES",
        "warnings": (errors + WARNINGS)[:MAX_WARNINGS],
        "races": today_races,
        "tomorrow_races": tomorrow_recommended,
        "tomorrow_race_count": len(tomorrow_races),
        "paper_betting": {
            "mode": "paper_only",
            "stats": stats,
            "history": sorted(
                snapshots.values(),
                key=lambda x: (x.get("date", ""), x.get("race_id", "")),
                reverse=True,
            )[:100],
        },
    }
    save_json(OUT, output)

    elapsed = round(time.monotonic() - START_TIME, 1)
    print(
        f"BAGEN KEIBA v25.0 | status={output['status']} | "
        f"today={len(today_races)} | tomorrow={len(tomorrow_races)} | "
        f"recommended={len(tomorrow_recommended)} | settled={stats['races_settled']} | "
        f"ROI={stats['roi_pct']}% | elapsed={elapsed}s"
    )
    if STOP_REQUESTS:
        print("[WARN] Runtime budget reached; partial data saved.")
    if errors or WARNINGS:
        print(f"[WARN] {len(errors) + len(WARNINGS)} warning(s); see docs/data.json -> warnings.")


if __name__ == "__main__":
    main()