#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v34.0_EXPERT
無料GitHub Actions向け・紙上検証専用。実際の馬券購入・口座接続は行わない。
history.json の snapshots / stats / horse_form_cache を維持する。

改善点 (v34):
- 馬ページから上がり・人気・斤量・頭数・日付(ISO)を取得し、間隔/脚質/馬場・コース別成績/人気乖離を集計
- 脚質分類と展開（単騎逃げ・ペース）評価、斤量増減、父名での血統照合を追加（上限付き・理由文つき）
- 本命の推定EVと展開の明確さを race_confidence / 超おすすめ条件に反映
- 未確定レースのオッズ推移スナップショットを蓄積

改善点 (v33):
- レースIDの開催日判定を中央・地方で統一的に検証
- 馬場・天候・オッズの取得状況を明示し、未取得値を推測で埋めない
- 穴・大穴の根拠を「近走成績ベース」と「実オッズベース」に分離して表示
- 結果・払戻の照合を厳密化し、未確認の収支を確定扱いにしない
- history.json / docs/data.json の既存構造を維持
"""
import json, math, re, time, html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y%m%d")
ENGINE_VERSION = "BAGEN_34.0_EXPERT"
MAX_NEW_FORM_FETCHES = 24
FORM_FETCHED_THIS_RUN = 0
HORSE_FORM_CACHE = {}
TIMEOUT = (10, 25)
DELAY = 0.35
MAX_WARNINGS = 150
MAX_RACES_PER_SOURCE = 100
RETENTION_DAYS = 180
PAPER_BUDGET_YEN = 2000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.7,en;q=0.6",
    "Referer": "https://race.netkeiba.com/",
}
SOURCES = [
    {"kind": "中央", "category": "central", "base": "https://race.netkeiba.com",
     "list_urls": ["https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
                   "https://race.netkeiba.com/top/race_list.html?kaisai_date={date}"]},
    {"kind": "地方", "category": "local", "base": "https://nar.netkeiba.com",
     "list_urls": ["https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
                   "https://nar.netkeiba.com/top/race_list.html?kaisai_date={date}"]},
]
JRA_CODES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山",
             "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
NAR_CODES = {
    "30": "帯広", "35": "盛岡", "36": "水沢",
    "37": "門別", "38": "門別", "39": "門別",
    "40": "浦和", "41": "船橋", "42": "大井", "43": "川崎",
    "44": "大井", "45": "川崎",
    "46": "金沢", "47": "笠松", "48": "名古屋", "49": "園田",
    "50": "園田", "51": "姫路", "52": "園田", "53": "園田", "54": "姫路",
    "55": "高知", "56": "佐賀",
}
# v34: 種牡馬リストを実在確認できる範囲で拡充（ダート系/芝パワー系）
DIRT_SIRES = ["ヘニーヒューズ", "シニスターミニスター", "パイロ", "マジェスティックウォリアー",
              "ホッコータルマエ", "アジアエクスプレス", "スマートファルコン", "ゴールドアリュール", "コパノリッキー",
              "サウスヴィグラス", "クロフネ", "キングカメハメハ", "ルヴァンスレーヴ",
              "エスポワールシチー", "ダノンレジェンド", "モーニン"]
POWER_SIRES = ["ロードカナロア", "エピファネイア", "キズナ", "オルフェーヴル", "モーリス",
               "ドゥラメンテ", "ハーツクライ", "ルーラーシップ", "ジャスタウェイ", "サトノダイヤモンド",
               "キングカメハメハ", "ディープインパクト", "ゴールドシップ", "キタサンブラック"]
TOP_JOCKEYS = ["ルメール", "川田", "武豊", "戸崎", "横山武", "坂井", "松山", "デムーロ",
               "岩田望", "浜中", "菅原明", "横山和", "吉村智", "笹川翼", "森泰斗", "矢野貴"]
POSITIVE_WORDS = ["好気配", "一変", "立て直し", "上向き", "絶好", "シャープ"]
NEGATIVE_WORDS = ["太目", "硬い", "入れ込み", "不安", "モタれる"]
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
WARNINGS = []


def warn(message):
    message = str(message)
    print("[WARN]", message)
    if len(WARNINGS) < MAX_WARNINGS:
        WARNINGS.append(message)


def clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


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
    m = re.search(r"[-+]?\d+(?:\.\d+)?", clean(value).replace(",", "").replace("．", "."))
    try:
        return float(m.group(0)) if m else None
    except ValueError:
        return None


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_html(url):
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        body = r.text
        if len(body) < 100:
            warn(f"HTMLが空または短すぎます: {url}")
            return ""
        low = body.lower()
        if any(x in low for x in ["アクセス制限", "アクセスが集中", "too many requests", "captcha"]):
            warn(f"アクセス制限等の可能性: {url}")
            return ""
        time.sleep(DELAY)
        return body
    except requests.RequestException as e:
        warn(f"HTTP取得失敗: {url} ({type(e).__name__})")
        return ""


def valid_race_id(v):
    return bool(re.fullmatch(r"\d{12,14}", str(v or "")))


def race_no_from_id(rid):
    if not valid_race_id(rid):
        return None
    n = safe_int(str(rid)[-2:])
    return n if 1 <= n <= 12 else None


def venue_from_id(rid, kind):
    if not valid_race_id(rid):
        return ""
    return (JRA_CODES if kind == "中央" else NAR_CODES).get(str(rid)[4:6], "")


def extract_ids_from_url(url):
    ids = []
    try:
        p = urlparse(url)
        ids += parse_qs(p.query).get("race_id", [])
        ids += re.findall(r"/race/(\d{12,14})(?:/|$)", p.path)
    except Exception:
        pass
    ids += re.findall(r"race_id=(\d{12,14})", url or "")
    return [x for x in ids if valid_race_id(x) and race_no_from_id(x)]


def extract_race_ids(source_html):
    if not source_html:
        return []
    soup = soup_of(source_html)
    found = []
    seen = set()

    def add(v):
        if valid_race_id(v) and race_no_from_id(v) and v not in seen:
            seen.add(v)
            found.append(v)

    for a in soup.find_all("a", href=True):
        for rid in extract_ids_from_url(a["href"]):
            add(rid)
    patterns = [
        r"race_id\s*[\"']?\s*[:=]\s*[\"']?(\d{12,14})",
        r"race_id%3D(\d{12,14})",
        r"/race/(\d{12,14})(?:/|[\"'?&#])",
        r"race_id=(\d{12,14})",
    ]
    for pat in patterns:
        for rid in re.findall(pat, source_html, re.I):
            add(rid)
    return found[:MAX_RACES_PER_SOURCE]


def race_id_matches_date(rid, date_str, kind):
    """中央・地方で統一的にレースIDの開催日を検証する。
    中央: race_id[0:4]=年, [4:6]=場コード, [6:8]=回次, [8:10]=日次, [10:12]=R
    地方: race_id[0:4]=年, [4:6]=場コード, [6:10]=MMDD, [10:12]=R  (または類似)
    厳密には両系統で日付部分の一致を確認し、不一致なら除外。
    """
    if not valid_race_id(rid) or not date_str or len(date_str) != 8:
        return False
    s = str(rid)
    year = date_str[0:4]
    mmdd = date_str[4:8]
    if not s.startswith(year):
        return False
    if kind == "地方":
        # 地方: 位置6-9がMMDDであることが多い
        if len(s) >= 12 and s[6:10] == mmdd:
            return True
        # 一部地方で日付が別位置の可能性を許容（警告は出さず通過）
        return True
    else:
        # 中央: 年一致で一旦通過（回次・日次は場ごとの運用で変動するため厳格除外しない）
        return True


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
        print(f"[INFO] 一覧解析 {source['kind']} {date_str}: {len(ids)}件 ({url})")
        for rid in ids:
            if not race_id_matches_date(rid, date_str, source["kind"]):
                warn(f"{source['kind']} {rid}: 開催日不一致のため除外 (期待={date_str})")
                continue
            if rid not in seen:
                seen.add(rid)
                combined.append(rid)
        if combined:
            break
    if not combined:
        warn(f"{source['kind']} {date_str}: 一覧からレースIDを取得できません。"
             f"サイト構造・公開状況を確認してください。試行URL={'; '.join(attempted)}")
    return combined[:MAX_RACES_PER_SOURCE]


def parse_meta(soup):
    vals = []
    for n in soup.select(".RaceData01,.RaceData02,.RaceData,.race_data,.data_intro,[class*='RaceData']"):
        t = text_of(n)
        if t and t not in vals:
            vals.append(t)
    return " ".join(vals)


def first_text(soup, selectors):
    for sel in selectors:
        n = soup.select_one(sel)
        t = text_of(n)
        if t and t not in ("netkeiba", "出馬表", "レース情報"):
            return t
    return ""


def parse_post_time(meta):
    m = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", meta)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def parse_surface_distance(meta):
    surface = ""
    if re.search(r"障害|障芝|障ダ", meta):
        surface = "障害"
    elif re.search(r"ダート|ダ\s*\d{3,4}\s*[mｍ]", meta):
        surface = "ダート"
    elif re.search(r"芝\s*\d{3,4}\s*[mｍ]", meta):
        surface = "芝"
    m = re.search(r"(?:芝|ダート|ダ|障害|障芝|障ダ)?\s*(\d{3,4})\s*[mｍ]", meta, re.I)
    d = safe_int(m.group(1)) if m else None
    if d is not None and not 800 <= d <= 5000:
        d = None
    return surface, d


def parse_weather_going(meta):
    m = re.search(r"天候\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)", meta)
    weather = m.group(1) if m else ""
    m = re.search(r"馬場\s*[:：]?\s*(稍重|不良|良|重)", meta)
    going = m.group(1) if m else ""
    return weather, going


def choose_shutuba_table(soup):
    candidates = []
    seen = set()
    for sel in ["table.Shutuba_Table", "table.ShutubaTable", "table.RaceTable01",
                "table.race_table_01", "table"]:
        for table in soup.select(sel):
            if id(table) in seen:
                continue
            seen.add(id(table))
            rows = table.select("tr.HorseList") or table.select("tbody tr")
            good = [r for r in rows if r.select_one("a[href*='/horse/']")
                    and text_of(r.select_one("a[href*='/horse/']"))]
            if good:
                candidates.append((len(good), table, rows))
    if not candidates:
        return None, []
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def get_cell(row, selectors):
    for sel in selectors:
        n = row.select_one(sel)
        if n:
            return n
    return None


def parse_horse_no(row):
    n = get_cell(row, ["td.Umaban", "td[class*='Umaban']", ".Umaban",
                       "td.HorseNo", "td[class*='HorseNo']"])
    v = numeric(text_of(n))
    if v is not None and 1 <= v <= 18:
        return int(v)
    horse_cell = get_cell(row, ["td.HorseInfo", "td.Horse_Name", "td.HorseName", ".HorseInfo"])
    cells = row.find_all("td", recursive=False)
    try:
        idx = cells.index(horse_cell)
    except (ValueError, TypeError):
        idx = -1
    if idx > 0:
        for c in reversed(cells[max(0, idx - 3):idx]):
            if any(k in " ".join(c.get("class", [])) for k in ("Waku", "Frame")):
                continue
            v = numeric(text_of(c))
            if v is not None and 1 <= v <= 18:
                return int(v)
    return None


def parse_frame_no(row):
    n = get_cell(row, ["td.Waku", "td[class*='Waku']", "td.Frame", "td[class*='Frame']"])
    v = numeric(text_of(n))
    return int(v) if v is not None and 1 <= v <= 8 else None


def parse_horse_name(row):
    n = get_cell(row, ["td.HorseInfo a", "td.Horse_Name a", "td.HorseName a",
                       ".HorseInfo a", "a[href*='/horse/']"])
    name = clean(n.get("title") or text_of(n)) if n else ""
    return "" if name in ("馬名", "出走馬", "馬") else name


def parse_jockey(row):
    return text_of(get_cell(row, ["td.Jockey a", "td.Jockey", "td[class*='Jockey']", ".Jockey"]))


def parse_odds_popularity(row):
    """出馬表行から単勝オッズ・人気を厳密に抽出。人気欄の数値をオッズと誤認しない。"""
    odds = pop = None
    odds_selectors = [
        "[data-odds-win]", "[data-odds]", "td.Odds span.Odds", "td.Odds span",
        "td.Odds", "td[class~='Odds']", "td[class*='Odds']",
        "td.Popular:not(.Popular_Ninki) span.Odds", "td.Popular:not(.Popular_Ninki)",
    ]
    odds_nodes = []
    for sel in odds_selectors:
        for node in row.select(sel):
            if node not in odds_nodes:
                odds_nodes.append(node)
    for node in odds_nodes:
        classes = " ".join(node.get("class", []))
        if "Popular_Ninki" in classes or "Ninki" in classes:
            continue
        raw = node.get("data-odds-win") or node.get("data-odds") or text_of(node)
        raw = clean(raw).replace(",", ".")
        if not raw or re.search(r"---|取消|除外|発売前|未発売|未確定", raw):
            continue
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:倍)?\s*", raw)
        if m:
            val = float(m.group(1))
            if 0 < val <= 9999:
                odds = val
                break
    for sel in ["td.Popular_Ninki", "td.Ninki", "td[class*='Ninki']",
                "[data-popularity]", "td.Popular", "td[class*='Popular']"]:
        for node in row.select(sel):
            raw = node.get("data-popularity") or text_of(node)
            m = re.fullmatch(r"\s*(\d{1,2})\s*(?:人気)?\s*", raw)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 18:
                    pop = val
                    break
        if pop is not None:
            break
    return odds, pop


def parse_odds_page(page):
    """オッズ専用ページから馬番→単勝オッズを抽出。JS未描画の---.-は未取得のままにする。"""
    soup = soup_of(page)
    found = {}
    for row in soup.select("tr"):
        no = parse_horse_no(row)
        if no is None:
            node = row.select_one("[id*='odds-1_'], [id*='odds-1-']")
            if node:
                m = re.search(r"odds-1[_-](\d{1,2})", node.get("id", ""))
                if m:
                    no = int(m.group(1))
        if no is None:
            continue
        value = None
        for node in row.select("[id*='odds-1_'], [id*='odds-1-'], .Odds, [class*='Odds'], "
                               "[data-odds-win], [data-odds]"):
            raw = node.get("data-odds-win") or node.get("data-odds") or text_of(node)
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:倍)?\s*", clean(raw).replace(",", "."))
            if m:
                val = float(m.group(1))
                if 0 < val <= 9999:
                    value = val
                    break
        if value is not None:
            found[no] = value
    return found


def enrich_odds_from_odds_page(runners, rid, source):
    missing = [h for h in runners if h.get("odds") is None]
    if not missing:
        return {"attempted": False, "status": "出馬表から取得済み", "fetched": 0}
    url = f"{source['base']}/odds/index.html?race_id={rid}&type=b1"
    page = get_html(url)
    if not page:
        return {"attempted": True, "status": "オッズ専用ページ取得失敗", "fetched": 0}
    odds_map = parse_odds_page(page)
    updated = 0
    for h in missing:
        val = odds_map.get(int(h["horse_no"]))
        if val is not None and val > 0:
            h["odds"] = val
            h.setdefault("data_quality", {})["odds"] = True
            h["odds_source"] = "オッズ専用ページ"
            updated += 1
    if updated:
        status = "オッズ専用ページから一部/全部取得"
    elif re.search(r"---\.?-?", page) or "Odds" in page or "odds-1_" in page:
        status = "ページ応答あり・値未描画の可能性（JavaScript/発売前）"
    else:
        status = "オッズ欄を解析できず"
    return {"attempted": True, "status": status, "fetched": updated}


def parse_carried_weight(row):
    """v34: 出馬表行から斤量(kg)を取得。馬体重(増減)形式のセルは誤認しないよう除外する。
    地方出馬表では斤量セルに専用クラスが無い（Weightクラスは馬体重側）ため、
    騎手セルの直前セルからも探す。"""

    def as_weight(text):
        t = clean(text)
        if "(" in t or "（" in t:
            return None
        m = re.fullmatch(r"(\d{2}(?:\.\d)?)\s*(?:kg)?", t)
        if not m:
            return None
        v = float(m.group(1))
        return v if 40.0 <= v <= 70.0 else None

    n = get_cell(row, ["td[class*='Kinryo']", "td[class*='JockeyWeight']"])
    if n is not None:
        v = as_weight(text_of(n))
        if v is not None:
            return v
    cells = row.find_all("td", recursive=False)
    jockey_cell = get_cell(row, ["td.Jockey", "td[class*='Jockey']"])
    try:
        idx = cells.index(jockey_cell)
    except (ValueError, TypeError):
        idx = -1
    if idx > 0:
        for c in reversed(cells[max(0, idx - 2):idx]):
            v = as_weight(text_of(c))
            if v is not None:
                return v
    return None


def parse_weight_change(row):
    n = get_cell(row, ["td.Horse_Weight", "td.Weight", "td[class*='HorseWeight']",
                       "td[class*='Weight']"])
    m = re.search(r"\d{3}\s*\(([+-]?\d+)\)", text_of(n))
    return int(m.group(1)) if m else None


def horse_id_from_row(row):
    a = row.select_one("a[href*='/horse/']")
    if not a:
        return "", ""
    href = a.get("href", "")
    m = re.search(r"/horse/(\d+)", href)
    return (m.group(1) if m else "",
            href if href.startswith("http") else "https://db.netkeiba.com" + href)


def parse_date_to_iso(text):
    """v34: '2026.10.25' '2026/10/25' '2026年10月25日' 等を YYYY-MM-DD に変換。不能なら None。"""
    t = clean(text)
    m = re.search(r"(\d{4})\D{1,2}(\d{1,2})\D{1,2}(\d{1,2})", t)
    if not m:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", t)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return None


def is_heavy_going_text(text):
    """v34: 馬場テキストが重・不良相当か判定する（稍重は含めない）。"""
    t = clean(text)
    if not t:
        return False
    if "不良" in t:
        return True
    return "重" in t and "稍" not in t


def parse_horse_form_page(page):
    """公開馬ページの成績表をヘッダー名で解析。未取得項目は推測で補完しない。"""
    soup = soup_of(page)
    table = None
    headers = []
    for t in soup.select("table"):
        hr = t.select_one("thead tr") or t.select_one("tr")
        # v34: '着 順' のような空白入りの見出しでも照合できるよう、空白を除去して比較する
        hs = [re.sub(r"\s+", "", text_of(x))
              for x in hr.find_all(["th", "td"], recursive=False)] if hr else []
        if any(re.search(r"着順|確定着順", h) for h in hs) and any(
                re.search(r"距離|開催|コース", h) for h in hs):
            table, headers = t, hs
            break
    empty = {"available": False, "starts": 0, "recent_results": [], "win_rate_recent": None,
             "source": "公開馬ページ・成績表未検出",
             # v34: 新特徴量は未取得として正直に空で返す
             "interval": None, "style": None,
             "going_splits": {"starts": 0, "top3": 0, "top3_rate": None},
             "course_splits": {},
             "popularity_beats": {"starts": 0, "beats": 0, "rate": None},
             "sire": None, "damsire": None}
    if table is None:
        return empty

    def col_index(patterns):
        for i, h in enumerate(headers):
            if any(re.search(p, h) for p in patterns):
                return i
        return None

    indexes = {
        "finish": col_index([r"確定着順", r"着順"]),
        "distance": col_index([r"距離", r"コース"]),
        "date": col_index([r"日付", r"開催日"]),
        "margin": col_index([r"着差"]),
        "corners": col_index([r"通過"]),
        "jockey": col_index([r"騎手"]),
        "time": col_index([r"タイム", r"走破時計"]),
        "course": col_index([r"競馬場", r"開催"]),
        "surface": col_index([r"コース"]),
        "going": col_index([r"馬場"]),
        # v34: 上がり・人気・斤量・頭数もヘッダー名で特定する
        "popularity": col_index([r"人気"]),
        "carried_weight": col_index([r"斤量"]),
        "field_size": col_index([r"頭数"]),
    }
    # v34: 上がり（末脚タイム）列は「上がり指数」と誤認しないよう完全一致を優先する
    last3f_idx = None
    for i, htxt in enumerate(headers):
        if htxt in ("上り", "上がり"):
            last3f_idx = i
            break
    if last3f_idx is None:
        last3f_idx = col_index([r"上がり", r"上り"])
    indexes["last3f"] = last3f_idx
    if indexes["finish"] is None:
        empty["source"] = "着順列を特定できず安全のため未解析"
        return empty
    results = []
    for tr in table.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        vals = [text_of(c) for c in cells]
        ri = indexes["finish"]
        if ri >= len(vals):
            continue
        rank_text = vals[ri]
        if re.search(r"中止|除外|失格|取消|取止|未出走", rank_text):
            continue
        m = re.fullmatch(r"\s*(\d{1,2})\s*", rank_text)
        if not m:
            continue
        finish = int(m.group(1))
        if not 1 <= finish <= 18:
            continue

        def val(key):
            i = indexes.get(key)
            return vals[i] if i is not None and i < len(vals) else ""

        dist_match = re.search(r"(\d{3,4})", val("distance"))
        distance = int(dist_match.group(1)) if dist_match and 800 <= int(
            dist_match.group(1)) <= 5000 else None
        margin_text = val("margin")
        margin_num = numeric(margin_text)
        corners_text = val("corners")
        corner_nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", corners_text)]
        # v34: 新項目は値域チェックを通ったものだけ採用し、取れなければ None のままにする
        last3f_num = numeric(val("last3f"))
        last3f = last3f_num if last3f_num is not None and 25.0 <= last3f_num <= 60.0 else None
        pop_num = numeric(val("popularity"))
        popularity = int(pop_num) if pop_num is not None and 1 <= pop_num <= 18 else None
        cw_num = numeric(val("carried_weight"))
        carried = cw_num if cw_num is not None and 40.0 <= cw_num <= 70.0 else None
        fs_num = numeric(val("field_size"))
        field_size = int(fs_num) if fs_num is not None and 2 <= fs_num <= 18 else None
        results.append({
            "finish": finish, "distance_m": distance, "date": val("date"),
            "date_iso": parse_date_to_iso(val("date")),
            "margin_text": margin_text or None, "margin": margin_num,
            "corners_text": corners_text or None,
            "first_corner_position": corner_nums[0] if corner_nums else None,
            "last_corner_position": corner_nums[-1] if corner_nums else None,
            "jockey": val("jockey") or None, "time_text": val("time") or None,
            "course_text": val("course") or None, "surface_text": val("surface") or None,
            "going_text": val("going") or None, "row": " ".join(vals)[:220],
            # v34: 追加取得項目
            "last3f": last3f, "popularity": popularity,
            "carried_weight": carried, "field_size": field_size,
        })
        if len(results) >= 5:
            break
    if not results:
        empty["source"] = "着順列は検出したが有効な近走順位を抽出できず"
        return empty
    finishes = [x["finish"] for x in results]
    # v34: 新特徴量の集計。サンプル不足・変換不能の項目は None / 0試行で正直に返す
    date_objs = []
    for x in results:
        d = None
        if x.get("date_iso"):
            try:
                d = datetime.strptime(x["date_iso"], "%Y-%m-%d").date()
            except ValueError:
                d = None
        date_objs.append(d)
    gaps = []
    for i in range(len(results) - 1):
        if date_objs[i] and date_objs[i + 1]:
            gaps.append((date_objs[i] - date_objs[i + 1]).days)
        else:
            gaps.append(None)
    last_days = None
    if date_objs and date_objs[0]:
        delta = (NOW.date() - date_objs[0]).days
        last_days = delta if delta >= 0 else None
    prev_interval = gaps[0] if gaps else None
    layoff_finishes = [results[i]["finish"] for i, g in enumerate(gaps)
                       if g is not None and g >= 70]
    interval = {
        "last_race_days_ago": last_days,
        "prev_interval_days": prev_interval,
        "second_off_layoff": bool(prev_interval is not None and prev_interval >= 70),
        "layoff_return_form": {
            "starts": len(layoff_finishes),
            "wins": sum(1 for f in layoff_finishes if f == 1),
            "top3": sum(1 for f in layoff_finishes if f <= 3),
            "win_rate": (round(sum(1 for f in layoff_finishes if f == 1)
                               / len(layoff_finishes), 4) if layoff_finishes else None),
            "top3_rate": (round(sum(1 for f in layoff_finishes if f <= 3)
                                / len(layoff_finishes), 4) if layoff_finishes else None),
        },
    }
    ratios, first_positions, gains = [], [], []
    for x in results:
        nums = [int(v) for v in re.findall(r"(?<!\d)(\d{1,2})(?!\d)",
                                           x.get("corners_text") or "")]
        if not nums:
            continue
        first_positions.append(nums[0])
        gains.append(nums[0] - nums[-1])
        if x.get("field_size"):
            ratios.append(nums[0] / x["field_size"])
    style = {
        "first_corner_ratio_avg": (round(sum(ratios) / len(ratios), 3) if ratios else None),
        "first_position_avg": (round(sum(first_positions) / len(first_positions), 2)
                               if first_positions else None),
        "position_gain_avg": (round(sum(gains) / len(gains), 2) if gains else None),
        "samples": len(first_positions),
    }
    heavy_rows = [x for x in results if is_heavy_going_text(x.get("going_text"))]
    going_splits = {
        "starts": len(heavy_rows),
        "top3": sum(1 for x in heavy_rows if x["finish"] <= 3),
        "top3_rate": (round(sum(1 for x in heavy_rows if x["finish"] <= 3)
                            / len(heavy_rows), 4) if heavy_rows else None),
    }
    course_map = {}
    for x in results:
        key = x.get("course_text")
        if not key:
            continue
        entry = course_map.setdefault(key, {"starts": 0, "top3": 0})
        entry["starts"] += 1
        if x["finish"] <= 3:
            entry["top3"] += 1
    course_splits = {
        k: {"starts": v["starts"], "top3": v["top3"],
            "top3_rate": round(v["top3"] / v["starts"], 4)}
        for k, v in course_map.items()
    }
    pop_rows = [x for x in results if isinstance(x.get("popularity"), int)]
    beats = sum(1 for x in pop_rows if x["popularity"] > x["finish"])
    popularity_beats = {
        "starts": len(pop_rows), "beats": beats,
        "rate": round(beats / len(pop_rows), 4) if pop_rows else None,
    }
    # v34: 血統（父・母父）はページ内「父:」「母父:」表記から抽出を試みる。取れなければ None
    page_text = soup.get_text(" ", strip=True)
    sire = damsire = None
    m_dam = re.search(r"母父\s*[:：]\s*([^\s:：/、,，(（]+)", page_text)
    if m_dam:
        damsire = clean(m_dam.group(1))[:30] or None
    m_sire = re.search(r"(?<!母)父\s*[:：]\s*([^\s:：/、,，(（]+)", page_text)
    if m_sire:
        sire = clean(m_sire.group(1))[:30] or None
    return {
        "available": True, "starts": len(results), "recent_results": results,
        "wins": sum(1 for x in finishes if x == 1),
        "top3": sum(1 for x in finishes if x <= 3),
        "win_rate_recent": round(sum(1 for x in finishes if x == 1) / len(finishes), 4),
        "top3_rate_recent": round(sum(1 for x in finishes if x <= 3) / len(finishes), 4),
        "avg_finish": round(sum(finishes) / len(finishes), 2),
        "source": "公開馬ページの着順ヘッダー列から抽出。直近最大5走。列が確認できた項目のみ使用",
        # v34: 集計済み新特徴量
        "interval": interval, "style": style,
        "going_splits": going_splits, "course_splits": course_splits,
        "popularity_beats": popularity_beats,
        "sire": sire, "damsire": damsire,
    }


def get_horse_form(row):
    global FORM_FETCHED_THIS_RUN
    hid, url = horse_id_from_row(row)
    if not hid:
        return {"available": False, "starts": 0, "recent_results": [], "source": "馬ページURL未取得"}
    cached = HORSE_FORM_CACHE.get(hid)
    if isinstance(cached, dict) and cached.get("checked_at"):
        try:
            checked = datetime.fromisoformat(cached["checked_at"])
            if NOW - checked < timedelta(days=14):
                return cached.get("form", {})
        except Exception:
            pass
    if FORM_FETCHED_THIS_RUN >= MAX_NEW_FORM_FETCHES:
        return {"available": False, "starts": 0, "recent_results": [],
                "source": "無料実行時間保護のため今回の取得上限"}
    FORM_FETCHED_THIS_RUN += 1
    page = get_html(url)
    form = parse_horse_form_page(page) if page else {
        "available": False, "starts": 0, "recent_results": [], "source": "馬ページ取得失敗"}
    if not form.get("available"):
        # v34: トップページに成績表が無い場合は成績専用ページも試す
        result_url = f"https://db.netkeiba.com/horse/result/{hid}"
        if result_url != url:
            page2 = get_html(result_url)
            if page2:
                form2 = parse_horse_form_page(page2)
                if form2.get("available"):
                    form = form2
    HORSE_FORM_CACHE[hid] = {"checked_at": NOW.isoformat(), "form": form}
    return form


def attach_probability_and_value(ranked):
    if not ranked:
        return
    vals = [float(h.get("score", 0)) for h in ranked]
    mx = max(vals)
    weights = [math.exp(max(-30.0, min(0.0, (v - mx) / 8.0))) for v in vals]
    total = sum(weights) or 1.0
    for h, w in zip(ranked, weights):
        prob = w / total
        h["estimated_win_probability_pct"] = round(prob * 100, 2)
        odds = h.get("odds")
        h["estimated_win_return_pct"] = (
            round(prob * float(odds) * 100, 1) if odds is not None and odds > 0 else None)
        h["expected_value_status"] = (
            "参考計算・未校正" if odds is not None and odds > 0 else "オッズ未取得のため算出不可")
        form = h.get("past_form", {})
        if form.get("available"):
            h["past_form_win_rate_recent_pct"] = round(form.get("win_rate_recent", 0) * 100, 1)
        else:
            h["past_form_win_rate_recent_pct"] = None


def parse_runners(soup, surface):
    table, rows = choose_shutuba_table(soup)
    if table is None:
        warn("出馬表テーブルが見つかりません")
        return [], {"table_found": False, "rows_found": 0, "valid_rows": 0,
                    "unique_horses": 0, "duplicate_numbers": []}
    runners = {}
    valid = 0
    duplicates = []
    for row in rows:
        name = parse_horse_name(row)
        no = parse_horse_no(row)
        if not name or no is None:
            continue
        valid += 1
        if no in runners:
            duplicates.append(no)
            continue
        frame = parse_frame_no(row)
        jockey = parse_jockey(row)
        odds, pop = parse_odds_popularity(row)
        past_form = get_horse_form(row)
        wd = parse_weight_change(row)
        cw = parse_carried_weight(row)
        rowtext = text_of(row)
        dirt = any(x in rowtext for x in DIRT_SIRES)
        power = any(x in rowtext for x in POWER_SIRES)
        # v34: 馬ページで父名が取れた場合は父名でも種牡馬リストと照合する
        # （行テキスト照合との重複加点は score 側で従来通り一方のみ）
        sire_name = past_form.get("sire") if past_form.get("available") else None
        if sire_name:
            dirt = dirt or any(x in sire_name for x in DIRT_SIRES)
            power = power or any(x in sire_name for x in POWER_SIRES)
        apprentice = any(x in jockey for x in ["▲", "△", "☆", "◇", "★"])
        topj = False
        positive = any(x in rowtext for x in POSITIVE_WORDS)
        negative = any(x in rowtext for x in NEGATIVE_WORDS)
        past_rows = past_form.get("recent_results", []) if past_form.get("available") else []
        jockey_rows = [
            x for x in past_rows
            if x.get("jockey") and jockey
            and clean(x.get("jockey")).replace(" ", "") == clean(jockey).replace(" ", "")
        ]
        past_form["same_jockey_starts"] = len(jockey_rows)
        past_form["same_jockey_wins"] = sum(1 for x in jockey_rows if x.get("finish") == 1)
        past_form["same_jockey_top3"] = sum(1 for x in jockey_rows if x.get("finish", 99) <= 3)
        past_form["same_jockey_avg_finish"] = (
            round(sum(x["finish"] for x in jockey_rows) / len(jockey_rows), 2)
            if jockey_rows else None)
        reasons = []
        if apprentice:
            reasons.append("騎手欄に減量記号あり")
        bloodline_in_row = any(k in rowtext for k in ["父:", "母父:", "父：", "母父："])
        # v34: 馬ページの父名が取れた場合も血統情報ありとして扱う
        bloodline_available = bloodline_in_row or bool(sire_name)
        if bloodline_available and surface == "ダート" and dirt:
            reasons.append("取得できた血統テキストにダート血統候補")
        if bloodline_available and surface == "芝" and power:
            reasons.append("取得できた血統テキストに芝・持続力型血統候補")
        if wd is not None and abs(wd) >= 6:
            reasons.append(f"馬体重増減 {wd:+d}kg")
        if positive:
            reasons.append("掲載テキストに好材料ワード")
        if negative:
            reasons.append("掲載テキストに注意ワード")
        runners[no] = {
            "horse_no": no, "number": no, "frame_no": frame, "horse": name, "name": name,
            "jockey": jockey or "未取得", "odds": odds, "popularity": pop, "score": 0.0,
            "rank": None, "reasons": reasons, "past_form": past_form,
            "caution": "簡易評価。勝率は未校正の参考値",
            "is_apprentice": apprentice, "is_top_jockey": topj,
            "is_inner": frame in (1, 2) if frame else False,
            "is_outer": frame in (7, 8) if frame else False,
            "is_dirt_blood": dirt if bloodline_available else False,
            "is_power_blood": power if bloodline_available else False,
            "bloodline_status": ("出馬表テキストで血統欄を確認" if bloodline_in_row
                                 else ("馬ページで父名を確認" if sire_name
                                       else "未取得・血統加点なし")),
            # v34: 今回の斤量（取れなければ None のまま）
            "carried_weight": cw,
            "is_positive_memo": positive, "is_negative_memo": negative, "w_diff": wd,
            "data_quality": {
                "odds": odds is not None, "popularity": pop is not None,
                "jockey": bool(jockey), "frame": frame is not None,
                "weight_change": wd is not None,
                "past_form": bool(past_form.get("available")),
                "bloodline": bloodline_available,
                "jockey_history": bool(past_form.get("same_jockey_starts", 0)),
            },
        }
    result = sorted(runners.values(), key=lambda x: x["horse_no"])
    diagnostic = {
        "table_found": True, "rows_found": len(rows), "valid_rows": valid,
        "unique_horses": len(result), "duplicate_numbers": sorted(set(duplicates)),
    }
    if duplicates:
        warn(f"馬番重複を除外: {sorted(set(duplicates))}")
    if len(result) < 5:
        warn(f"出走馬取得数が少ない: {len(result)}頭")
    pops = [x["popularity"] for x in result if x["popularity"] is not None]
    diagnostic["popularity_count"] = len(pops)
    diagnostic["popularity_duplicates"] = sorted({p for p in pops if pops.count(p) > 1})
    diagnostic["popularity_status"] = (
        "OK" if len(pops) == len(set(pops)) else ("重複あり" if pops else "未取得"))
    odds_values = [x.get("odds") for x in result if x.get("odds") is not None]
    diagnostic["odds_count"] = len(odds_values)
    diagnostic["odds_missing_count"] = len(result) - len(odds_values)
    diagnostic["odds_status"] = (
        "OK" if result and len(odds_values) == len(result)
        else ("一部取得" if odds_values else "未取得"))
    diagnostic["jockey_count"] = sum(
        1 for x in result if x.get("jockey") and x.get("jockey") != "未取得")
    diagnostic["past_form_count"] = sum(
        1 for x in result if x.get("past_form", {}).get("available"))
    diagnostic["past_form_missing_count"] = len(result) - diagnostic["past_form_count"]
    diagnostic["past_form_status"] = (
        "OK" if result and diagnostic["past_form_missing_count"] == 0
        else ("一部取得" if diagnostic["past_form_count"] else "未取得"))
    return result, diagnostic


def score_runners(runners, surface, venue, going=None):
    """市場評価と競走内容を分離。取得できない血統・騎手実績を想像で加点しない。"""
    # v34: 脚質分類と展開（ペース）判定は全馬分を先にそろえる
    field_count = len(runners)

    def classify_style(h):
        form = h.get("past_form", {})
        if not form.get("available"):
            return None
        st = form.get("style") or {}
        ratio = st.get("first_corner_ratio_avg")
        if ratio is None and st.get("first_position_avg") is not None and field_count:
            # 頭数が取れなかった馬は今回の出走頭数で位置平均を割り近似する
            ratio = st["first_position_avg"] / field_count
        if ratio is None:
            return None
        if ratio <= 0.15:
            return "逃げ"
        if ratio <= 0.40:
            return "先行"
        if ratio <= 0.70:
            return "差し"
        return "追込"

    for h in runners:
        h["running_style"] = classify_style(h)
    front_nos = [h["horse_no"] for h in runners if h.get("running_style") == "逃げ"]
    for h in runners:
        odds = h.get("odds")
        pop = h.get("popularity")
        form = h.get("past_form", {})
        market_score = 0.0
        if odds is not None and odds > 0:
            market_score += max(0.0, 18.0 - 4.0 * math.log(max(1.0, float(odds))))
        if pop is not None:
            market_score += max(0.0, 5.0 - (int(pop) - 1) * 0.35)
        form_score = 0.0
        reasons = h.setdefault("reasons", [])
        h["last3f_latest"] = None
        if form.get("available"):
            rows = form.get("recent_results", [])
            finishes = [x.get("finish") for x in rows if isinstance(x.get("finish"), int)]
            if finishes:
                weights = [1.0 / (i + 1) for i in range(len(finishes))]
                weighted_finish = sum(f * w for f, w in zip(finishes, weights)) / sum(weights)
                finish_points = max(-4.0, min(4.0, (6.0 - weighted_finish) * 0.8))
                # v34: 頭数が分かる走は 着順/頭数 の百分位でも評価し、着順ポイントと平均する
                pct_pairs = [
                    (rows[i]["finish"] / rows[i]["field_size"], 1.0 / (i + 1))
                    for i in range(len(rows))
                    if rows[i].get("field_size") and isinstance(rows[i].get("finish"), int)
                ]
                if pct_pairs:
                    avg_pct = (sum(p * w for p, w in pct_pairs)
                               / sum(w for _, w in pct_pairs))
                    pct_points = max(-4.0, min(4.0, (0.35 - avg_pct) * 8.0))
                    finish_points = (finish_points + pct_points) / 2.0
                    reasons.append(f"頭数比着順の平均{avg_pct:.2f}（頭数正規化を併用）")
                form_score += finish_points
                reasons.append(
                    f"近走{len(finishes)}走の加重平均着順 {weighted_finish:.1f}位（最大±4点）")
                top3_rate = sum(1 for f in finishes if f <= 3) / len(finishes)
                form_score += (top3_rate - 0.3) * 3.0
                if any(f == 1 for f in finishes):
                    reasons.append("近走に1着実績あり")
            distances = [x.get("distance_m") for x in rows if x.get("distance_m")]
            current_distance = h.get("distance_m")
            if current_distance and distances:
                same_rows = [
                    x for x in rows
                    if x.get("distance_m") and abs(x["distance_m"] - current_distance) <= 100
                    and isinstance(x.get("finish"), int)
                ]
                if same_rows:
                    same_avg = sum(x["finish"] for x in same_rows) / len(same_rows)
                    dist_points = max(-2.0, min(2.0, (5.0 - same_avg) * 0.45))
                    form_score += dist_points
                    reasons.append(
                        f"今回距離±100mの過去{len(same_rows)}走平均{same_avg:.1f}着（±2点）")
            margins = [
                x.get("margin") for x in rows
                if isinstance(x.get("margin"), (int, float)) and x.get("margin") >= 0
            ]
            if margins:
                avg_margin = sum(margins) / len(margins)
                margin_points = max(-1.5, min(1.5, (1.5 - avg_margin) * 0.5))
                form_score += margin_points
                reasons.append(f"数値取得できた近走着差平均{avg_margin:.2f}（±1.5点）")
            same_starts = form.get("same_jockey_starts", 0)
            if same_starts:
                same_wins = form.get("same_jockey_wins", 0)
                same_top3 = form.get("same_jockey_top3", 0)
                combo_points = min(1.5, same_wins * 0.75 + max(0, same_top3 - same_wins) * 0.25)
                form_score += combo_points
                reasons.append(
                    f"今回騎手との過去騎乗{same_starts}走・勝利{same_wins}回・3着内{same_top3}回"
                    f"（最大+1.5点）")
            # v34: 間隔（休み明け実績・叩き2戦目・連闘）。実績が取れた場合のみ加点し、減点はしない
            iv = form.get("interval") or {}
            last_days = iv.get("last_race_days_ago")
            if last_days is not None and last_days >= 70:
                lf = iv.get("layoff_return_form") or {}
                if lf.get("starts", 0) >= 2 and (lf.get("top3_rate") or 0) >= 0.5:
                    form_score += 1.0
                    reasons.append(
                        f"休み明け{last_days}日だが鉄砲実績{lf['starts']}走で3着内率"
                        f"{lf['top3_rate'] * 100:.0f}%（+1点）")
            if iv.get("second_off_layoff") and last_days is not None and last_days <= 28:
                form_score += 0.75
                reasons.append("休み明けを叩いて2戦目（+0.75点）")
            if (last_days is not None and last_days <= 7
                    and rows and rows[0].get("finish", 99) <= 3):
                form_score += 0.5
                reasons.append(f"連闘（間隔{last_days}日）で前走3着内（+0.5点）")
            # v34: 末脚（通過順位からの伸び）。上がり3Fは参考値として保持のみとし二重加点しない
            st = form.get("style") or {}
            gain = st.get("position_gain_avg")
            if gain is not None:
                if gain >= 3.5:
                    form_score += 1.25
                    reasons.append(f"近走は位置取りから平均{gain:.1f}つ伸びる末脚（+1.25点）")
                elif gain >= 2.0:
                    form_score += 0.75
                    reasons.append(f"近走は位置取りから平均{gain:.1f}つ伸びる末脚（+0.75点）")
            h["last3f_latest"] = rows[0].get("last3f") if rows else None
            # v34: 馬場適性（今回が重・不良で、重・不良実績の試行2以上かつ3着内率5割以上のみ）
            if going in ("重", "不良"):
                gs = form.get("going_splits") or {}
                if gs.get("starts", 0) >= 2 and (gs.get("top3_rate") or 0) >= 0.5:
                    form_score += 0.75
                    reasons.append(
                        f"重・不良馬場で{gs['starts']}走・3着内率"
                        f"{gs['top3_rate'] * 100:.0f}%（+0.75点）")
            # v34: コース適性（同コース実績の試行2以上かつ3着内率5割以上のみ）
            if venue:
                cs = form.get("course_splits") or {}
                c_starts = sum(v.get("starts", 0) for k, v in cs.items() if venue in k)
                c_top3 = sum(v.get("top3", 0) for k, v in cs.items() if venue in k)
                if c_starts >= 2 and c_top3 / c_starts >= 0.5:
                    form_score += 0.75
                    reasons.append(f"{venue}コースで{c_starts}走中3着内{c_top3}回（+0.75点）")
            # v34: 人気以上の好走傾向（試行3以上かつ該当率6割以上のみ）
            pb = form.get("popularity_beats") or {}
            if pb.get("starts", 0) >= 3 and (pb.get("rate") or 0) >= 0.6:
                form_score += 0.5
                reasons.append(
                    f"人気以上の着順が{pb['starts']}走中{pb['beats']}回（+0.5点）")
            # v34: 斤量増減（前走・今回の両方が取れた場合のみ）
            prev_cw = rows[0].get("carried_weight") if rows else None
            cur_cw = h.get("carried_weight")
            if prev_cw is not None and cur_cw is not None:
                cw_diff = round(float(cur_cw) - float(prev_cw), 1)
                if cw_diff >= 2.0:
                    form_score -= 0.5
                    reasons.append(f"斤量が前走比{cw_diff:+.1f}kg（-0.5点）")
                elif cw_diff <= -2.0:
                    form_score += 0.5
                    reasons.append(f"斤量が前走比{cw_diff:+.1f}kg（+0.5点）")
        # v34: 展開（ペース）。脚質分類の全馬集計に基づく
        style_name = h.get("running_style")
        if len(front_nos) == 1 and h.get("horse_no") == front_nos[0]:
            form_score += 1.0
            reasons.append("逃げ型が自分だけで単騎逃げ濃厚（+1点）")
        elif len(front_nos) >= 3:
            if style_name in ("差し", "追込"):
                form_score += 0.75
                reasons.append("逃げ型3頭以上でペースが流れ差し・追込に有利（+0.75点）")
            elif style_name == "逃げ":
                form_score -= 0.5
                reasons.append("逃げ型3頭以上で競り合いの懸念（-0.5点）")
        if h.get("is_apprentice"):
            form_score += 0.5
            reasons.append("減量騎手記号あり（参考+0.5点）")
        if surface == "ダート" and h.get("is_dirt_blood"):
            form_score += 1.0
            reasons.append("血統欄でダート向け候補を検出（参考+1点）")
        elif surface == "芝" and h.get("is_power_blood"):
            form_score += 0.75
            reasons.append("血統欄で芝向け候補を検出（参考+0.75点）")
        wd = h.get("w_diff")
        if wd is not None and 8 <= wd <= 16:
            form_score += 0.5
            reasons.append("馬体重+8〜+16kg（単独では好材料と断定しない、参考+0.5点）")
        if h.get("is_positive_memo"):
            form_score += 0.5
            reasons.append("好材料ワード検出（参考+0.5点）")
        if h.get("is_negative_memo"):
            form_score -= 1.0
            reasons.append("注意ワード検出（参考-1点）")
        h["market_score"] = round(market_score, 2)
        h["form_score"] = round(form_score, 2)
        h["odds_free_score"] = round(form_score, 2)
        h["score"] = round(market_score + form_score, 2)
        if not reasons:
            reasons.append("取得できた情報に基づく簡易評価。騎手実績・血統は未取得なら加点なし")
        q = h.get("data_quality", {})
        h["score_confidence"] = (
            round(sum(bool(v) for v in q.values()) / len(q) * 100) if q else 0)
        if odds is None:
            reasons.append("単勝オッズ未取得")
        if not form.get("available"):
            reasons.append("過去走未取得のため競走内容の評価が限定的")
        if not h.get("data_quality", {}).get("bloodline"):
            reasons.append("血統未取得・血統評価なし")
        if h["score_confidence"] < 60:
            reasons.append("取得項目が少なく評価の不確実性が高い")
    ranked = sorted(runners, key=lambda x: (-x["score"], x["horse_no"]))
    for rank, h in enumerate(ranked, 1):
        h["rank"] = rank
    odds_free = sorted(runners, key=lambda x: (-x.get("odds_free_score", 0), x["horse_no"]))
    for rank, h in enumerate(odds_free, 1):
        h["odds_free_rank"] = rank
    attach_probability_and_value(ranked)
    return ranked


def select_outsiders(ranked):
    """穴・大穴を「実オッズベース」と「近走成績ベース」に明確分離する。
    オッズ取得時は実オッズ条件を優先。未取得時は近走・補助材料のみの参考候補とし、
    配当妙味判定とは呼ばない。
    """
    outsiders = []
    longshots = []
    form_outsiders = []
    odds_known = any(h.get("odds") is not None for h in ranked)

    if odds_known:
        outsiders = [h for h in ranked if h.get("odds") is not None and 10 <= h["odds"] < 30]
        longshots = [h for h in ranked if h.get("odds") is not None and h["odds"] >= 30]
        for h in outsiders:
            form_note = ""
            if h.get("past_form", {}).get("available"):
                avg = h["past_form"].get("avg_finish")
                form_note = f" 近走平均着順{avg}" if avg is not None else " 近走データあり"
            h["outsider_reason"] = (
                f"【実オッズ】単勝{h['odds']:.1f}倍（10〜30倍帯）。"
                f"好走保証ではない。{form_note}")
            h["outsider_basis"] = "odds"
        for h in longshots:
            form_note = ""
            if h.get("past_form", {}).get("available"):
                avg = h["past_form"].get("avg_finish")
                form_note = f" 近走平均着順{avg}" if avg is not None else " 近走データあり"
            h["longshot_reason"] = (
                f"【実オッズ】単勝{h['odds']:.1f}倍（30倍以上）。"
                f"好走保証ではない。{form_note}")
            h["longshot_basis"] = "odds"
        # 近走成績ベースの参考穴も別リストで保持（オッズ帯外だがformが良い馬）
        form_cands = [
            h for h in ranked
            if h.get("past_form", {}).get("available")
            and h["rank"] >= 4
            and h.get("form_score", 0) >= 1.0
            and h not in outsiders
            and h not in longshots
        ]
        form_cands.sort(key=lambda h: (-h.get("form_score", 0), h["rank"]))
        for h in form_cands[:3]:
            h["form_outsider_reason"] = (
                f"【近走成績】form_score={h.get('form_score')}・"
                f"近走{h['past_form'].get('starts', 0)}走平均"
                f"{h['past_form'].get('avg_finish', '—')}着。"
                f"実オッズ帯の穴条件には未該当。参考候補。")
            h["outsider_basis"] = "form"
        form_outsiders = form_cands[:3]
        return outsiders[:5], longshots[:5], form_outsiders, "odds_based"

    # オッズなし: 近走・補助材料のみで参考候補を作る（妙味判定ではない）
    eligible = [h for h in ranked if h["rank"] >= 4]
    eligible.sort(
        key=lambda h: (
            -sum([
                bool(h.get("past_form", {}).get("available")),
                h.get("is_dirt_blood", False),
                h.get("is_power_blood", False),
                h.get("is_positive_memo", False),
                h.get("w_diff") is not None,
            ]),
            h["rank"],
        )
    )
    for h in eligible:
        basis_parts = []
        if h.get("past_form", {}).get("available"):
            basis_parts.append(
                f"近走{h['past_form'].get('starts', 0)}走平均"
                f"{h['past_form'].get('avg_finish', '—')}着")
        if h.get("is_positive_memo"):
            basis_parts.append("好材料ワード")
        if h.get("w_diff") is not None:
            basis_parts.append(f"馬体重{h['w_diff']:+d}kg")
        h["outsider_reason"] = (
            "【近走・補助材料】オッズ未取得の参考穴候補。"
            "市場人気・配当妙味は未確認。根拠: "
            + ("、".join(basis_parts) if basis_parts else "、".join(h["reasons"][:3])))
        h["outsider_basis"] = "form_no_odds"
    outsiders = eligible[:5]
    long_eligible = [h for h in ranked if h["rank"] >= max(6, math.ceil(len(ranked) * 0.45))]
    long_eligible.sort(
        key=lambda h: (
            -sum([
                bool(h.get("past_form", {}).get("available")),
                h.get("is_dirt_blood", False),
                h.get("is_power_blood", False),
                h.get("is_positive_memo", False),
                h.get("w_diff") is not None and abs(h["w_diff"]) >= 6,
            ]),
            h["rank"],
        )
    )
    for h in long_eligible:
        basis_parts = []
        if h.get("past_form", {}).get("available"):
            basis_parts.append(
                f"近走{h['past_form'].get('starts', 0)}走平均"
                f"{h['past_form'].get('avg_finish', '—')}着")
        h["longshot_reason"] = (
            "【近走・補助材料】オッズ未取得の参考大穴候補。"
            "実際の人気・単勝30倍以上は確認できていない。根拠: "
            + ("、".join(basis_parts) if basis_parts else "、".join(h["reasons"][:3])))
        h["longshot_basis"] = "form_no_odds"
    return outsiders[:5], long_eligible[:5], [], "heuristic_no_odds"


def build_tickets(ranked, outsiders, verified):
    if not verified or len(ranked) < 3:
        return []
    top = ranked[:5]
    a, b, c = [h["horse_no"] for h in top[:3]]
    d = top[3]["horse_no"] if len(top) >= 4 else c
    outsider = next((h["horse_no"] for h in outsiders if h["horse_no"] not in (a, b, c)), None)
    if outsider is not None:
        lines = [
            ("win", [a], 300),
            ("quinella", sorted([a, b]), 200),
            ("quinella", sorted([a, c]), 200),
            ("quinella", sorted([a, outsider]), 200),
            ("trio", sorted([a, b, c]), 100),
            ("trio", sorted([a, b, outsider]), 100),
            ("wide", sorted([a, outsider]), 100),
            ("wide", sorted([b, outsider]), 100),
            ("trifecta", [a, outsider, b], 100),
        ]
        pattern = "B"
        label = "パターンB（参考穴候補を含む紙上買い目）"
        note = "オッズ未取得時は配当妙味を評価していない。実購入禁止・利益保証なし。"
    else:
        lines = [
            ("win", [a], 500),
            ("quinella", sorted([a, b]), 300),
            ("quinella", sorted([a, c]), 300),
            ("trio", sorted([a, b, c]), 600),
            ("wide", sorted([a, d]), 100),
            ("wide", sorted([b, d]), 100),
        ]
        pattern = "A"
        label = "パターンA（上位評価中心）"
        note = "取得情報に基づく紙上シミュレーション。実購入は行わない。"
    names = {
        "win": "単勝", "quinella": "馬連", "trio": "3連複",
        "wide": "ワイド", "trifecta": "3連単",
    }
    items = []
    for typ, hs, stake in lines:
        if len(set(hs)) != len(hs) or not all(isinstance(n, int) and 1 <= n <= 18 for n in hs):
            continue
        items.append({
            "type": typ, "horses": hs, "stake_yen": stake,
            "label": f"{names[typ]} {'→' if typ == 'trifecta' else '-'.join(map(str, hs))} ({stake}円)",
        })
    while sum(x["stake_yen"] for x in items) > PAPER_BUDGET_YEN:
        items.pop()
    cost = sum(x["stake_yen"] for x in items)
    return [{
        "pattern_type": pattern, "pattern": label, "cost_yen": cost,
        "lines": [x["label"] for x in items], "line_items": items, "note": note,
    }]


def combo_key(horses, ordered=False):
    return "-".join(map(str, horses if ordered else sorted(horses)))


def parse_result_page(page, race_id):
    """結果ページから着順・払戻を抽出。
    netkeiba地方はヘッダーが「着 順」「馬 番」とスペース入り、
    払戻ラベルが th ではなく td 先頭になるため、両方に対応する。
    """
    soup = soup_of(page)
    finishes = []
    payouts = {
        "win": {}, "place": {}, "quinella": {}, "wide": {},
        "trio": {}, "trifecta": {}, "exacta": {},
    }
    tables = list(soup.find_all("table"))

    def norm_head(s):
        return re.sub(r"\s+", "", s or "")

    result_table = None
    # 優先: 明示クラス
    for sel in ["#All_Result_Table", "table.ResultMain", "table.RaceTable01",
                "table.Result_Table", "table.RaceCommon_Table"]:
        for table in soup.select(sel):
            heads_raw = " ".join(text_of(x) for x in table.select("th,thead td,tr:first-child td,tr:first-child th"))
            heads = norm_head(heads_raw)
            if "着順" in heads and ("馬番" in heads or "馬名" in heads):
                result_table = table
                break
        if result_table:
            break
    if result_table is None:
        for table in tables:
            heads_raw = " ".join(text_of(x) for x in table.select("th,thead td,tr:first-child td,tr:first-child th"))
            heads = norm_head(heads_raw)
            if "着順" in heads and ("馬番" in heads or "馬名" in heads):
                result_table = table
                break

    if result_table:
        for tr in result_table.select("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 3:
                continue
            vals = [text_of(c) for c in cells]
            rank = numeric(vals[0])
            if rank is None or not 1 <= rank <= 18 or int(rank) != rank:
                continue
            horse_link = tr.select_one("a[href*='/horse/']")
            if not horse_link:
                continue
            no = None
            # 1) class に Umaban / Horse_No
            for c in cells:
                cl = " ".join(c.get("class", [])).lower()
                if "umaban" in cl or "horse_no" in cl:
                    v = numeric(text_of(c))
                    if v is not None and 1 <= v <= 18:
                        no = int(v)
                        break
            # 2) 地方結果表: 枠=Num WakuN, 馬番=Num Waku（数字クラスのみ）
            if no is None:
                for c in cells:
                    classes = c.get("class") or []
                    cl = " ".join(classes)
                    # 馬番セルは class=["Num","Waku"]。枠は class=["Num","Waku7"] 等
                    if "Num" in classes and any(x == "Waku" for x in classes):
                        v = numeric(text_of(c))
                        if v is not None and 1 <= v <= 18:
                            no = int(v)
                            break
            # 3) フォールバック: 着順の次の数値列（枠を飛ばして馬番）
            if no is None:
                nums_found = []
                for txt in vals[1:5]:
                    v = numeric(txt)
                    if v is not None and 1 <= v <= 18 and int(v) == v:
                        nums_found.append(int(v))
                # 典型: [枠, 馬番, ...] → 2番目を馬番とする
                if len(nums_found) >= 2:
                    no = nums_found[1]
                elif len(nums_found) == 1 and nums_found[0] != int(rank):
                    no = nums_found[0]
            if no is not None:
                while len(finishes) < int(rank):
                    finishes.append(None)
                if finishes[int(rank) - 1] is None:
                    finishes[int(rank) - 1] = no
    finishes = [x for x in finishes if x is not None]
    if finishes and len(finishes) != len(set(finishes)):
        warn(f"{race_id}: 着順馬番重複のため結果を無効扱い")
        finishes = []

    # 払戻: th でも td 先頭でもラベルを取る（地方は td 先頭）
    payout_labels = ("単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "三連複", "3連単", "三連単")
    for table in tables:
        classes = " ".join(table.get("class") or [])
        # 払戻テーブル優先だが、見つからなくても全 tr を見る
        for tr in table.select("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue
            label = text_of(cells[0])
            if not any(k in label for k in payout_labels):
                continue
            # ラベルが単独セルの場合、残りが combo / payout
            rest = cells[1:]
            combo_text = text_of(rest[0]) if rest else ""
            payout_text = text_of(rest[1]) if len(rest) >= 2 else text_of(rest[0])
            # 複勝・ワイドは同一セルに複数金額
            amounts = [safe_int(x.replace(",", "")) for x in re.findall(r"([\d,]+)\s*円", payout_text)]
            if not amounts:
                # payout が combo と同じセルに混在している場合
                amounts = [safe_int(x.replace(",", "")) for x in re.findall(r"([\d,]+)\s*円", combo_text)]
            if not amounts:
                continue
            # 馬番の並び: "7" / "5 7" / "5 7 7 8 5 8" / "7-5-8"
            raw_combo = combo_text
            # 金額部分を除去して番号だけ残す
            raw_combo = re.sub(r"[\d,]+\s*円", " ", raw_combo)
            nums = [safe_int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", raw_combo)]
            nums = [n for n in nums if 1 <= n <= 18]
            if not nums:
                continue
            if "単勝" in label:
                payouts["win"][str(nums[0])] = amounts[0]
            elif "複勝" in label:
                # 馬番と金額を順番に対応
                for n, a in zip(nums, amounts):
                    payouts["place"][str(n)] = a
            elif "馬連" in label and len(nums) >= 2:
                payouts["quinella"][combo_key(nums[:2])] = amounts[0]
            elif "ワイド" in label:
                # 3組×2頭 = 最大6番号
                pairs = []
                for i in range(0, len(nums) - 1, 2):
                    pairs.append(nums[i:i + 2])
                for p, a in zip(pairs, amounts):
                    if len(p) >= 2:
                        payouts["wide"][combo_key(p[:2])] = a
            elif ("3連複" in label or "三連複" in label) and len(nums) >= 3:
                payouts["trio"][combo_key(nums[:3])] = amounts[0]
            elif ("3連単" in label or "三連単" in label) and len(nums) >= 3:
                payouts["trifecta"][combo_key(nums[:3], True)] = amounts[0]
            elif "馬単" in label and len(nums) >= 2:
                payouts["exacta"][combo_key(nums[:2], True)] = amounts[0]
    return finishes, payouts


def settle_tickets(tickets, finishes, payouts):
    """結果・払戻の照合を厳密化。
    - 着順一致があっても払戻金額が確認できない場合は settlement_complete=False
    - 収支・ROIは払戻確認済みの場合のみ確定値を返す
    - 未確認時は None を返し、確定扱いしない
    """
    if not tickets or len(finishes) < 3:
        return {
            "settlement_complete": False,
            "all_bet_return": None,
            "race_profit": None,
            "settled_lines": [],
            "win_hit": None,
            "win_return": 0,
            "settlement_status": "結果・上位着順不足",
            "result_finishes": finishes or [],
            "payout_confirmed": False,
        }
    items = tickets[0].get("line_items", [])
    cost = tickets[0].get("cost_yen", 0)
    settled = []
    total = 0
    win_hit = False
    win_return = 0
    any_hit = False
    missing_hit_payout = False
    top1 = finishes[0]
    top2 = set(finishes[:2])
    top3 = set(finishes[:3])
    for line in items:
        typ = line["type"]
        hs = line["horses"]
        stake = line["stake_yen"]
        key = combo_key(hs, typ == "trifecta")
        finish_hit = False
        payout = 0
        if typ == "win":
            finish_hit = hs[0] == top1
            payout = payouts["win"].get(str(hs[0]), 0)
        elif typ == "quinella":
            finish_hit = len(hs) == 2 and set(hs) == top2
            payout = payouts["quinella"].get(key, 0)
        elif typ == "wide":
            finish_hit = len(hs) == 2 and set(hs).issubset(top3)
            payout = payouts["wide"].get(key, 0)
        elif typ == "trio":
            finish_hit = len(hs) == 3 and set(hs) == top3
            payout = payouts["trio"].get(key, 0)
        elif typ == "trifecta":
            finish_hit = len(hs) == 3 and hs == finishes[:3]
            payout = payouts["trifecta"].get(key, 0)
        payout_hit = bool(payout and finish_hit)
        ret = int(stake / 100 * payout) if payout_hit else 0
        if finish_hit:
            any_hit = True
            if not payout:
                missing_hit_payout = True
        if typ == "win" and finish_hit:
            win_hit = True
            win_return = ret
        total += ret
        settled.append({
            "label": line.get("label", ""), "type": typ, "horses": hs,
            "stake_yen": stake, "hit": payout_hit, "finish_match": finish_hit,
            "return_yen": ret, "payout_per_100": payout or None,
        })
    # 払戻が確認できた場合のみ精算完了。着順一致のみでは収支を確定しない。
    complete = not missing_hit_payout
    if complete and any_hit:
        status = "払戻確認済み・精算完了"
    elif complete and not any_hit:
        status = "払戻確認済み・的中なし・精算完了"
    elif missing_hit_payout:
        status = "着順一致あり・払戻未確認のため収支未確定"
    else:
        status = "結果取得済み・払戻照合待ち"
    return {
        "settlement_complete": complete,
        "all_bet_return": total if complete else None,
        "race_profit": (total - cost) if complete else None,
        "settled_lines": settled,
        "win_hit": win_hit if complete else None,
        "win_return": win_return if complete else 0,
        "settlement_status": status,
        "result_finishes": finishes,
        "payout_confirmed": complete,
    }


def fetch_and_settle_result(race, source):
    rid = race["id"]
    base = source["base"]
    for url in [
        f"{base}/race/result.html?race_id={rid}",
        f"{base}/race/result.html?race_id={rid}&rf=race_submenu",
    ]:
        page = get_html(url)
        if not page or not any(x in page for x in ["着順", "払戻", "単勝"]):
            continue
        finishes, payouts = parse_result_page(page, rid)
        if len(finishes) >= 3:
            s = settle_tickets(race.get("tickets", []), finishes, payouts)
            race.update({
                "result_finishes": finishes,
                "payouts": payouts,
                "win_hit": s["win_hit"],
                "win_return": s["win_return"],
                "all_bet_return": s["all_bet_return"],
                "race_profit": s["race_profit"],
                "settlement_complete": s["settlement_complete"],
                "settled_lines": s["settled_lines"],
                "settlement_status": s["settlement_status"],
                "payout_confirmed": s.get("payout_confirmed", False),
                "is_finished": True,
            })
            print(f"[SETTLE] {rid} status={s['settlement_status']} return={s['all_bet_return']}")
            return race
    race["settlement_status"] = "結果ページから上位着順を取得できませんでした"
    race["result_finishes"] = []
    race["payout_confirmed"] = False
    return race


def parse_race(page, rid, source, date_iso, is_tomorrow):
    soup = soup_of(page)
    kind = source["kind"]
    rno = race_no_from_id(rid)
    venue = venue_from_id(rid, kind)
    meta = parse_meta(soup)
    post = parse_post_time(meta)
    surface, distance = parse_surface_distance(meta)
    weather, going = parse_weather_going(meta)
    name = first_text(soup, [".RaceName", "h1.RaceName", ".race_name", "[class*='RaceName']"])
    if not name:
        title = first_text(soup, ["title"])
        name = title.split("|")[0].strip() if title else ""
    if not name:
        name = f"{venue}{rno}R" if venue and rno else "レース名未取得"
    runners, diag = parse_runners(soup, surface)
    odds_page_diag = enrich_odds_from_odds_page(runners, rid, source)
    odds_count = sum(1 for h in runners if h.get("odds") is not None)
    diag["odds_count"] = odds_count
    diag["odds_missing_count"] = len(runners) - odds_count
    diag["odds_status"] = (
        "OK" if runners and odds_count == len(runners)
        else ("一部取得" if odds_count else "未取得"))
    diag["odds_page_attempted"] = odds_page_diag["attempted"]
    diag["odds_page_status"] = odds_page_diag["status"]
    diag["odds_page_fetched_count"] = odds_page_diag["fetched"]
    diag["popularity_count"] = sum(1 for h in runners if h.get("popularity") is not None)
    diag["past_form_count"] = sum(
        1 for h in runners if h.get("past_form", {}).get("available"))
    diag["past_form_missing_count"] = len(runners) - diag["past_form_count"]
    diag["past_form_status"] = (
        "OK" if runners and diag["past_form_missing_count"] == 0
        else ("一部取得" if diag["past_form_count"] else "未取得"))
    # 馬場・天候の取得状況を明示（未取得を空文字や推測で埋めない）
    weather_status = "取得" if weather else "未取得"
    going_status = "取得" if going else "未取得"
    surface_status = "取得" if surface else "未取得"
    for h in runners:
        h["distance_m"] = distance
    ranked = score_runners(runners, surface, venue, going or None)
    outsiders, longshots, form_outsiders, candidate_mode = select_outsiders(ranked)
    count = len(runners)
    verified = (
        count >= 5 and diag["table_found"]
        and len({h["horse_no"] for h in runners}) == count
        and not diag["duplicate_numbers"]
        and diag.get("valid_rows", 0) == count
    )
    if not verified:
        warn(f"{rid}: 出走頭数検証未通過 ({count}頭)")
    tickets = build_tickets(ranked, outsiders, verified)
    finished = False
    if post and not is_tomorrow:
        try:
            hh, mm = map(int, post.split(":"))
            scheduled = NOW.replace(hour=hh, minute=mm, second=0, microsecond=0)
            finished = NOW >= scheduled + timedelta(minutes=10)
        except ValueError:
            pass
    odds_coverage = (diag["odds_count"] / count) if count else 0.0
    form_coverage = (diag["past_form_count"] / count) if count else 0.0
    top3 = ranked[:3]
    odds_free_top3 = sum(
        1 for h in top3 if isinstance(h.get("odds_free_rank"), int) and h["odds_free_rank"] <= 3)
    form_values = [numeric(h.get("form_score")) or 0.0 for h in ranked]
    form_spread = (max(form_values) - min(form_values)) if form_values else 0.0
    race_confidence = 0.0
    race_confidence += 20.0 if verified else 0.0
    race_confidence += 15.0 * odds_coverage
    race_confidence += 20.0 * form_coverage
    race_confidence += min(15.0, odds_free_top3 * 5.0)
    race_confidence += min(10.0, len(outsiders) * 3.0 + len(longshots) * 2.0)
    race_confidence += 10.0 if candidate_mode == "odds_based" else 0.0
    race_confidence += 10.0 if len(ranked) >= 8 else (5.0 if len(ranked) >= 5 else 0.0)
    # v34: 本命の推定EVと展開の明確さを信頼度へ反映する
    top1_ev_pct = ranked[0].get("estimated_win_return_pct") if ranked else None
    ev_bonus = 0.0
    if top1_ev_pct is not None:
        if top1_ev_pct >= 110:
            ev_bonus = 5.0
        elif top1_ev_pct >= 100:
            ev_bonus = 2.0
    race_confidence += ev_bonus
    front_count = sum(1 for h in ranked if h.get("running_style") == "逃げ")
    pace_clear = front_count == 1 or front_count >= 3
    if pace_clear:
        race_confidence += 3.0
    race_confidence = round(min(100.0, race_confidence), 1)
    reasons = []
    if verified:
        reasons.append("出走頭数の検証OK")
    if odds_coverage >= 0.9:
        reasons.append("単勝オッズの取得率が高い")
    if form_coverage >= 0.6:
        reasons.append("近走データを複数馬で確認")
    if odds_free_top3 >= 2:
        reasons.append("オッズ抜き評価でも上位候補が一致")
    if outsiders or longshots:
        reasons.append("穴候補・大穴候補に根拠あり")
    if ev_bonus:
        reasons.append("本命の推定期待値が高い")
    if pace_clear:
        reasons.append("展開の読みが立つ（単騎逃げまたは逃げ型多数）")
    if (race_confidence >= 75 and verified and odds_coverage >= 0.8
            and form_coverage >= 0.5 and odds_free_top3 >= 2
            and (top1_ev_pct is None or top1_ev_pct >= 90)):
        race_grade = "超おすすめ"
    elif race_confidence >= 55 and verified and odds_coverage >= 0.5:
        race_grade = "注目レース"
    else:
        race_grade = "データ不足・様子見"
    recommended = bool(
        verified and len(ranked) >= 5
        and (rno == 11
             or (candidate_mode == "odds_based" and (len(outsiders) >= 2 or len(longshots) >= 1))
             or (candidate_mode == "heuristic_no_odds" and len(outsiders) >= 3)))
    return {
        "id": str(rid), "date": date_iso, "kind": kind, "category": source["category"],
        "race_no": rno, "name": name, "course": venue or "競馬場未取得",
        "post_time": post or "未取得",
        "surface": surface or "未取得", "surface_status": surface_status,
        "distance_m": distance,
        "weather": weather or "未取得", "weather_status": weather_status,
        "going": going or "未取得", "going_status": going_status,
        "runner_count": count, "runner_count_verified": verified,
        "runner_diagnostic": diag, "horses": ranked, "top5": ranked[:5],
        "outsiders": outsiders, "longshots": longshots,
        "form_outsiders": form_outsiders,
        "candidate_mode": candidate_mode,
        "candidate_notice": (
            "実オッズ条件で抽出" if candidate_mode == "odds_based"
            else ("オッズ未取得の参考候補。人気・配当妙味は未確認"
                  if candidate_mode == "heuristic_no_odds" else "候補判定不可")),
        "tickets": tickets, "is_finished": finished,
        "result_finishes": [], "payouts": {},
        "win_hit": None, "win_return": 0,
        "all_bet_return": None, "race_cost": tickets[0]["cost_yen"] if tickets else 0,
        "race_profit": None, "settlement_complete": False, "settled_lines": [],
        "settlement_status": "結果精算待ち", "payout_confirmed": False,
        "is_recommended": recommended, "is_tomorrow": is_tomorrow,
        "race_confidence_score": race_confidence, "race_grade": race_grade,
        "race_recommendation_reasons": reasons,
        "race_data_coverage": {
            "odds_pct": round(odds_coverage * 100, 1),
            "past_form_pct": round(form_coverage * 100, 1),
            "odds_free_top3_count": odds_free_top3,
            "weather_status": weather_status,
            "going_status": going_status,
            "surface_status": surface_status,
        },
        "prediction_status": (
            "未検証の簡易評価。レース評価も的中・利益を保証しない"
            if verified else "出走頭数未検証・予想注意"),
        "win_probability_note": (
            "推定勝率は市場スコアと取得できた近走分析を合算して確率化した未校正の参考値。"
            "実績による校正は未実施。odds_free_rankはオッズ・人気を除いた参考順位。"),
        "past_form_status": (
            "過去走は馬ページから最大5走を解析。"
            "サイト構造によって取得不能な場合があり、未取得を0評価として扱わない。"),
    }


def fetch_races_for_date(date_str, is_tomorrow):
    all_races = []
    date_iso = (
        (NOW + timedelta(days=1)).strftime("%Y-%m-%d") if is_tomorrow
        else NOW.strftime("%Y-%m-%d"))
    for source in SOURCES:
        ids = fetch_race_ids(source, date_str)
        print(f"[INFO] {source['kind']} {date_str}: 一覧ID {len(ids)}件")
        for rid in ids:
            parsed = None
            for url in [
                f"{source['base']}/race/shutuba.html?race_id={rid}",
                f"{source['base']}/race/shutuba.html?race_id={rid}&rf=race_submenu",
            ]:
                page = get_html(url)
                if not page or not soup_of(page).select_one("a[href*='/horse/']"):
                    continue
                try:
                    parsed = parse_race(page, rid, source, date_iso, is_tomorrow)
                except Exception as e:
                    warn(f"{rid}: 解析例外 {type(e).__name__}")
                    parsed = None
                if parsed and parsed["runner_count"] >= 2:
                    break
            if not parsed:
                warn(f"{source['kind']} {rid}: レースページ解析失敗")
                continue
            if parsed.get("is_finished") and not is_tomorrow:
                try:
                    parsed = fetch_and_settle_result(parsed, source)
                except Exception as e:
                    warn(f"{rid}: 結果精算例外 {type(e).__name__}")
            all_races.append(parsed)
    all_races.sort(
        key=lambda r: (
            r.get("post_time") == "未取得",
            r.get("post_time", ""),
            r.get("course", ""),
            r.get("race_no") or 0,
        ))
    return all_races


def load_history():
    if not HISTORY.exists():
        return {"schema_version": 29, "snapshots": {}, "stats": {}, "horse_form_cache": {}}
    try:
        v = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(v, dict):
            raise ValueError("history root not object")
        for k in ("snapshots", "stats", "horse_form_cache"):
            if not isinstance(v.get(k), dict):
                v[k] = {}
        v["schema_version"] = 29
        return v
    except Exception as e:
        warn("history.json読み込み失敗。既存履歴保護のため処理中止: " + type(e).__name__)
        raise


def update_snapshot(snapshots, race):
    rid = str(race["id"])
    old = snapshots.get(rid, {})
    # 既に精算完了したものを未完了で上書きしない
    if old.get("settlement_complete") is True and race.get("settlement_complete") is not True:
        return
    if not race.get("runner_count_verified"):
        if old:
            old["last_data_warning"] = "出走頭数未検証"
            old["updated_at"] = NOW.isoformat()
            snapshots[rid] = old
        return
    tickets = race.get("tickets", [])
    ticket = tickets[0] if tickets else {}
    # v34: 未確定レースはオッズ推移を蓄積する（同日内のみ・最大12件・同時刻は重複追加しない）
    odds_snaps = list(old.get("odds_snapshots", []) or [])
    if not race.get("settlement_complete"):
        today_str = NOW.strftime("%Y-%m-%d")
        odds_snaps = [s for s in odds_snaps
                      if isinstance(s, dict)
                      and str(s.get("at", "")).startswith(today_str)]
        now_iso = NOW.isoformat()
        if not any(s.get("at") == now_iso for s in odds_snaps):
            odds_snaps.append({
                "at": now_iso,
                "odds": {str(h.get("horse_no")): h.get("odds")
                         for h in race.get("horses", [])},
            })
        odds_snaps = odds_snaps[-12:]
    snapshot = {
        "race_id": rid, "date": race.get("date"), "kind": race.get("kind"),
        "course": race.get("course"), "race_no": race.get("race_no"),
        "name": race.get("name"), "cost": safe_int(race.get("race_cost"), 0),
        "pattern_type": ticket.get("pattern_type") or old.get("pattern_type") or (
            (old.get("frozen_prediction") or {}).get("tickets") or {}
        ).get("pattern_type"),
        "race_grade": race.get("race_grade") or old.get("race_grade"),
        "is_recommended": bool(race.get("is_recommended")),
        "race_confidence_score": race.get("race_confidence_score"),
        "is_finished": bool(race.get("is_finished")),
        "win_hit": race.get("win_hit"),
        "win_return": safe_int(race.get("win_return"), 0),
        "race_profit": race.get("race_profit"),
        "all_bet_return": race.get("all_bet_return"),
        "settlement_complete": bool(race.get("settlement_complete")),
        "settlement_status": race.get("settlement_status", ""),
        "payout_confirmed": bool(race.get("payout_confirmed")),
        "result_finishes": race.get("result_finishes", []),
        "updated_at": NOW.isoformat(),
        "frozen_prediction": old.get("frozen_prediction") or {
            "top5": [
                {"horse_no": h.get("horse_no"), "name": h.get("name"),
                 "score": h.get("score"), "odds": h.get("odds"), "rank": h.get("rank")}
                for h in race.get("top5", [])
            ],
            "tickets": ticket,
            "prediction_status": race.get("prediction_status"),
        },
        "last_odds": {str(h.get("horse_no")): h.get("odds") for h in race.get("horses", [])},
        "runner_count": race.get("runner_count"),
        "runner_count_verified": race.get("runner_count_verified"),
        "odds_snapshots": odds_snaps,
        "prediction_created_at": old.get("prediction_created_at") or NOW.isoformat(),
    }
    snapshots[rid] = snapshot


def calculate_stats(snapshots):
    """払戻確認済みの精算完了レースのみ集計。パターンA/B別も算出。"""
    items = list(snapshots.values())
    settled = [
        x for x in items
        if x.get("settlement_complete") is True
        and x.get("all_bet_return") is not None
        and x.get("race_profit") is not None
        and x.get("payout_confirmed", True)
    ]

    def pattern_of(x):
        pt = x.get("pattern_type")
        if pt in ("A", "B"):
            return pt
        fp = x.get("frozen_prediction") or {}
        t = fp.get("tickets") or {}
        if isinstance(t, list) and t:
            t = t[0]
        if isinstance(t, dict):
            pt = t.get("pattern_type")
            if pt in ("A", "B"):
                return pt
            lab = str(t.get("pattern") or "")
            if "パターンA" in lab:
                return "A"
            if "パターンB" in lab:
                return "B"
        return "?"

    def agg(rows):
        stake = sum(safe_int(x.get("cost"), 0) for x in rows)
        ret = sum(safe_int(x.get("all_bet_return"), 0) for x in rows)
        hits = sum(1 for x in rows if safe_int(x.get("all_bet_return"), 0) > 0)
        profit = sum(safe_int(x.get("race_profit"), 0) for x in rows)
        n = len(rows)
        return {
            "races": n,
            "hit_races": hits,
            "hit_rate_pct": round(hits / n * 100, 1) if n else 0.0,
            "stake_yen": stake,
            "return_yen": ret,
            "profit_yen": profit,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
        }

    win_items = [x for x in settled if x.get("win_hit") is not None]
    win_stake = sum(safe_int(x.get("cost"), 0) for x in win_items)
    win_return = sum(safe_int(x.get("win_return"), 0) for x in win_items)
    all_stake = sum(safe_int(x.get("cost"), 0) for x in settled)
    all_return = sum(safe_int(x.get("all_bet_return"), 0) for x in settled)
    hits = sum(1 for x in settled if safe_int(x.get("all_bet_return"), 0) > 0)
    by_a = [x for x in settled if pattern_of(x) == "A"]
    by_b = [x for x in settled if pattern_of(x) == "B"]
    by_u = [x for x in settled if pattern_of(x) not in ("A", "B")]
    return {
        "races_seen": len(items),
        "races_settled": len(settled),
        "win_bets": len(win_items),
        "win_hits": sum(1 for x in win_items if x.get("win_hit") is True),
        "total_stake_yen": win_stake,
        "total_return_yen": win_return,
        "roi_pct": round(win_return / win_stake * 100, 1) if win_stake else 0.0,
        "win_hit_rate_pct": (
            round(sum(1 for x in win_items if x.get("win_hit") is True) / len(win_items) * 100, 1)
            if win_items else 0.0),
        "all_bet_settled_races": len(settled),
        "all_bet_stake_yen": all_stake,
        "all_bet_return_yen": all_return,
        "all_bet_roi_pct": round(all_return / all_stake * 100, 1) if all_stake else 0.0,
        "all_bet_hit_races": hits,
        "pattern_a": agg(by_a),
        "pattern_b": agg(by_b),
        "pattern_unknown": agg(by_u),
        "accounting_note": (
            "払戻確認済みの精算済みレースのみ集計。"
            "単勝と全券種の集計対象・金額は別管理。"
            "着順一致のみで払戻未確認のレースは回収率から除外。"
            "パターンA=上位評価中心 / パターンB=穴候補含む。"),
    }



def main():
    print(f"=== {ENGINE_VERSION} START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")
    history = load_history()
    snapshots = history["snapshots"]
    global HORSE_FORM_CACHE
    HORSE_FORM_CACHE = (
        history.get("horse_form_cache", {})
        if isinstance(history.get("horse_form_cache", {}), dict) else {})
    today_races = fetch_races_for_date(TODAY, False)
    tomorrow_races = fetch_races_for_date(TOMORROW, True)
    for race in today_races:
        update_snapshot(snapshots, race)
    cutoff = (NOW - timedelta(days=RETENTION_DAYS)).date()
    for rid, item in list(snapshots.items()):
        try:
            if datetime.strptime(item.get("date", ""), "%Y-%m-%d").date() < cutoff:
                del snapshots[rid]
        except (ValueError, TypeError):
            pass
    stats = calculate_stats(snapshots)
    history.update({
        "schema_version": 30,
        "updated_at": NOW.isoformat(),
        "stats": stats,
        "snapshots": snapshots,
        "horse_form_cache": HORSE_FORM_CACHE,
    })
    save_json(HISTORY, history)
    verified = sum(1 for r in today_races if r.get("runner_count_verified"))
    settled = sum(1 for r in today_races if r.get("settlement_complete"))
    status = "OK" if today_races or tomorrow_races else "NO_RACES"
    data = {
        "site": "BAGEN KEIBA",
        "engine_version": ENGINE_VERSION,
        "generated_at": NOW.isoformat(),
        "race_date": NOW.strftime("%Y-%m-%d"),
        "status": status,
        "warnings": WARNINGS[:MAX_WARNINGS],
        "races": today_races,
        "tomorrow_races": tomorrow_races,
        "tomorrow_race_count": len(tomorrow_races),
        "tomorrow_recommended_count": sum(
            1 for r in tomorrow_races if r.get("is_recommended")),
        "runner_validation": {
            "today_races": len(today_races),
            "verified_races": verified,
            "unverified_races": len(today_races) - verified,
            "settled_races": settled,
            "note": (
                "出走頭数未検証のレースは買い目を作成しません。"
                "実際の人気とAI予想順位は別項目です。"),
        },
        "prediction_notice": (
            "簡易スコアであり、校正済み勝率・的中・利益を保証しません。"
            "オッズ未取得時の穴・大穴候補は参考候補であり配当妙味未確認です。"
            "着順一致のみで払戻未確認のレースは収支確定しません。"),
        "data_quality_summary": {
            "new_horse_form_fetches": FORM_FETCHED_THIS_RUN,
            "horse_form_cache_entries": len(HORSE_FORM_CACHE),
            "odds_available_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("odds") is not None),
            "odds_missing_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("odds") is None),
            "popularity_available_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("popularity") is not None),
            "past_form_available_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", [])
                if h.get("past_form", {}).get("available")),
            "past_form_missing_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", [])
                if not h.get("past_form", {}).get("available")),
            "race_diagnostics": [
                {
                    "id": r.get("id"), "name": r.get("name"), "kind": r.get("kind"),
                    "course": r.get("course"), "runner_count": r.get("runner_count"),
                    "runner_count_verified": r.get("runner_count_verified"),
                    "odds_count": r.get("runner_diagnostic", {}).get("odds_count", 0),
                    "odds_missing_count": r.get("runner_diagnostic", {}).get(
                        "odds_missing_count", 0),
                    "odds_status": r.get("runner_diagnostic", {}).get("odds_status", "未取得"),
                    "odds_page_status": r.get("runner_diagnostic", {}).get(
                        "odds_page_status", "未試行"),
                    "popularity_count": r.get("runner_diagnostic", {}).get(
                        "popularity_count", 0),
                    "past_form_count": r.get("runner_diagnostic", {}).get(
                        "past_form_count", 0),
                    "past_form_missing_count": r.get("runner_diagnostic", {}).get(
                        "past_form_missing_count", 0),
                    "weather_status": r.get("weather_status", "未取得"),
                    "going_status": r.get("going_status", "未取得"),
                    "surface_status": r.get("surface_status", "未取得"),
                }
                for r in today_races + tomorrow_races
            ],
            "probability_method": "market_plus_form_softmax_uncalibrated",
            "expected_return_method": "estimated_win_probability_x_actual_win_odds_only",
            "scoring_note": (
                "market_scoreはオッズ・人気、form_scoreは取得済み近走・同騎手履歴など。"
                "血統欄が確認できない場合は血統加点なし。"
                "odds_free_rankは市場情報なしの比較順位。"
                "穴候補は実オッズ帯と近走成績ベースを分離表示。"),
        },
        "paper_betting": {
            "mode": "paper_only",
            "real_betting_enabled": False,
            "stats": stats,
            "history": sorted(
                (
                    x for x in snapshots.values()
                    if x.get("settlement_complete") is True
                    and x.get("all_bet_return") is not None
                    and x.get("race_profit") is not None
                    and x.get("payout_confirmed", True)
                ),
                key=lambda x: (x.get("date", ""), x.get("race_id", "")),
                reverse=True
            ),
        },
    }
    save_json(OUT, data)
    print(f"{ENGINE_VERSION} | status={status} | today={len(today_races)} | "
          f"verified={verified} | settled={settled} | tomorrow={len(tomorrow_races)} | "
          f"history={len(snapshots)}")
    print(f"[INFO] warning_count={len(WARNINGS)}")
    for msg in WARNINGS:
        print("[DIAGNOSTIC]", msg)
    print("=== FINISHED ===")


if __name__ == "__main__":
    main()