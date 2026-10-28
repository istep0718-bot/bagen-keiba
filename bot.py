#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v29.0
無料GitHub Actions向け・紙上検証専用。実際の馬券購入・口座接続は行わない。
history.json の snapshots / stats / horse_form_cache を維持する。
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
ENGINE_VERSION = "BAGEN_30.0"
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
    {"kind":"中央","category":"central","base":"https://race.netkeiba.com",
     "list_urls":["https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
                  "https://race.netkeiba.com/top/race_list.html?kaisai_date={date}"]},
    {"kind":"地方","category":"local","base":"https://nar.netkeiba.com",
     "list_urls":["https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={date}",
                  "https://nar.netkeiba.com/top/race_list.html?kaisai_date={date}"]},
]
JRA_CODES = {"01":"札幌","02":"函館","03":"福島","04":"新潟","05":"東京","06":"中山","07":"中京","08":"京都","09":"阪神","10":"小倉"}
NAR_CODES = {"30":"帯広","35":"盛岡","36":"水沢","37":"門別","38":"門別","39":"門別","40":"浦和","41":"船橋","42":"大井","43":"川崎","44":"大井","45":"川崎","46":"金沢","47":"笠松","48":"名古屋","50":"園田","51":"姫路","54":"姫路","55":"高知","56":"佐賀"}
DIRT_SIRES = ["ヘニーヒューズ","シニスターミニスター","パイロ","マジェスティックウォリアー","ホッコータルマエ","アジアエクスプレス","スマートファルコン","ゴールドアリュール","コパノリッキー"]
POWER_SIRES = ["ロードカナロア","エピファネイア","キズナ","オルフェーヴル","モーリス","ドゥラメンテ","ハーツクライ","ルーラーシップ","ジャスタウェイ","サトノダイヤモンド"]
TOP_JOCKEYS = ["ルメール","川田","武豊","戸崎","横山武","坂井","松山","デムーロ","岩田望","浜中","菅原明","横山和","吉村智","笹川翼","森泰斗","矢野貴"]
POSITIVE_WORDS = ["好気配","一変","立て直し","上向き","絶好","シャープ"]
NEGATIVE_WORDS = ["太目","硬い","入れ込み","不安","モタれる"]
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
    try: return int(value)
    except (ValueError, TypeError, OverflowError): return default

def numeric(value):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", clean(value).replace(",","").replace("．","."))
    try: return float(m.group(0)) if m else None
    except ValueError: return None

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
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
        if any(x in low for x in ["アクセス制限","アクセスが集中","too many requests","captcha"]):
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
    if not valid_race_id(rid): return None
    n = safe_int(str(rid)[-2:])
    return n if 1 <= n <= 12 else None

def venue_from_id(rid, kind):
    if not valid_race_id(rid): return ""
    return (JRA_CODES if kind=="中央" else NAR_CODES).get(str(rid)[4:6], "")

def extract_ids_from_url(url):
    ids=[]
    try:
        p=urlparse(url)
        ids += parse_qs(p.query).get("race_id", [])
        ids += re.findall(r"/race/(\d{12,14})(?:/|$)",p.path)
    except Exception: pass
    ids += re.findall(r"race_id=(\d{12,14})",url or "")
    return [x for x in ids if valid_race_id(x) and race_no_from_id(x)]

def extract_race_ids(source_html):
    if not source_html: return []
    soup=soup_of(source_html); found=[]; seen=set()
    def add(v):
        if valid_race_id(v) and race_no_from_id(v) and v not in seen:
            seen.add(v); found.append(v)
    for a in soup.find_all("a",href=True):
        for rid in extract_ids_from_url(a["href"]): add(rid)
    patterns=[r"race_id\s*[\"']?\s*[:=]\s*[\"']?(\d{12,14})",
              r'race_id%3D(\d{12,14})',r"/race/(\d{12,14})(?:/|[\"'?&#])",
              r'race_id=(\d{12,14})']
    for pat in patterns:
        for rid in re.findall(pat,source_html,re.I): add(rid)
    return found[:MAX_RACES_PER_SOURCE]

def fetch_race_ids(source,date_str):
    combined=[]; seen=set(); attempted=[]
    for template in source["list_urls"]:
        url=template.format(date=date_str); attempted.append(url)
        page=get_html(url)
        if not page: continue
        ids=extract_race_ids(page)
        print(f"[INFO] 一覧解析 {source['kind']} {date_str}: {len(ids)}件 ({url})")
        for rid in ids:
            if source["kind"]=="地方" and str(rid)[6:10] != date_str[4:8]: continue
            if rid not in seen: seen.add(rid); combined.append(rid)
        if combined: break
    if not combined:
        warn(f"{source['kind']} {date_str}: 一覧からレースIDを取得できません。サイト構造・公開状況を確認してください。試行URL={'; '.join(attempted)}")
    return combined[:MAX_RACES_PER_SOURCE]

def parse_meta(soup):
    vals=[]
    for n in soup.select(".RaceData01,.RaceData02,.RaceData,.race_data,.data_intro,[class*='RaceData']"):
        t=text_of(n)
        if t and t not in vals: vals.append(t)
    return " ".join(vals)

def first_text(soup,selectors):
    for sel in selectors:
        n=soup.select_one(sel); t=text_of(n)
        if t and t not in ("netkeiba","出馬表","レース情報"): return t
    return ""

def parse_post_time(meta):
    m=re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",meta)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""

def parse_surface_distance(meta):
    surface="障害" if re.search(r"障害|障芝|障ダ",meta) else ("ダート" if re.search(r"ダート|ダ\s*\d{3,4}\s*[mｍ]",meta) else ("芝" if re.search(r"芝\s*\d{3,4}\s*[mｍ]",meta) else ""))
    m=re.search(r"(?:芝|ダート|ダ|障害|障芝|障ダ)?\s*(\d{3,4})\s*[mｍ]",meta,re.I)
    d=safe_int(m.group(1)) if m else None
    if d is not None and not 800<=d<=5000: d=None
    return surface,d

def parse_weather_going(meta):
    m=re.search(r"天候\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)",meta); weather=m.group(1) if m else ""
    m=re.search(r"馬場\s*[:：]?\s*(稍重|不良|良|重)",meta); going=m.group(1) if m else ""
    return weather,going

def choose_shutuba_table(soup):
    candidates=[]; seen=set()
    for sel in ["table.Shutuba_Table","table.ShutubaTable","table.RaceTable01","table.race_table_01","table"]:
        for table in soup.select(sel):
            if id(table) in seen: continue
            seen.add(id(table))
            rows=table.select("tr.HorseList") or table.select("tbody tr")
            good=[r for r in rows if r.select_one("a[href*='/horse/']") and text_of(r.select_one("a[href*='/horse/']"))]
            if good: candidates.append((len(good),table,rows))
    if not candidates: return None,[]
    candidates.sort(key=lambda x:x[0],reverse=True)
    return candidates[0][1],candidates[0][2]

def get_cell(row,selectors):
    for sel in selectors:
        n=row.select_one(sel)
        if n: return n
    return None

def parse_horse_no(row):
    n=get_cell(row,["td.Umaban","td[class*='Umaban']",".Umaban","td.HorseNo","td[class*='HorseNo']"])
    v=numeric(text_of(n))
    if v is not None and 1<=v<=18: return int(v)
    horse_cell=get_cell(row,["td.HorseInfo","td.Horse_Name","td.HorseName",".HorseInfo"])
    cells=row.find_all("td",recursive=False)
    try: idx=cells.index(horse_cell)
    except (ValueError,TypeError): idx=-1
    if idx>0:
        for c in reversed(cells[max(0,idx-3):idx]):
            if any(k in " ".join(c.get("class",[])) for k in ("Waku","Frame")): continue
            v=numeric(text_of(c))
            if v is not None and 1<=v<=18: return int(v)
    return None

def parse_frame_no(row):
    n=get_cell(row,["td.Waku","td[class*='Waku']","td.Frame","td[class*='Frame']"])
    v=numeric(text_of(n))
    return int(v) if v is not None and 1<=v<=8 else None

def parse_horse_name(row):
    n=get_cell(row,["td.HorseInfo a","td.Horse_Name a","td.HorseName a",".HorseInfo a","a[href*='/horse/']"])
    name=clean(n.get("title") or text_of(n)) if n else ""
    return "" if name in ("馬名","出走馬","馬") else name

def parse_jockey(row):
    return text_of(get_cell(row,["td.Jockey a","td.Jockey","td[class*='Jockey']",".Jockey"]))

def parse_odds_popularity(row):
    odds=pop=None
    for sel in ["td.Odds span", "td.Odds", "td[class*='Odds']", ".Odds", "[class*='Odds']", "[data-odds]", "[data-odds-win]"]:
        for n in row.select(sel):
            t=text_of(n)
            if not t or "---" in t or "取消" in t: continue
            raw=n.get("data-odds") or n.get("data-odds-win") or t
            m=re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)",clean(raw).replace(",","."))
            if m and 0<float(m.group(1))<=9999: odds=float(m.group(1)); break
        if odds is not None: break
    for sel in ["td.Popular_Ninki","td.Popular","td[class*='Ninki']","td[class*='Popular']"]:
        for n in row.select(sel):
            v=numeric(text_of(n))
            if v is not None and 1<=v<=18: pop=int(v); break
        if pop is not None: break
    return odds,pop

def parse_weight_change(row):
    n=get_cell(row,["td.Horse_Weight","td.Weight","td[class*='HorseWeight']","td[class*='Weight']"])
    m=re.search(r"\d{3}\s*\(([+-]?\d+)\)",text_of(n))
    return int(m.group(1)) if m else None

def horse_id_from_row(row):
    a=row.select_one("a[href*='/horse/']")
    if not a: return "", ""
    href=a.get("href","")
    m=re.search(r"/horse/(\d+)",href)
    return (m.group(1) if m else "", href if href.startswith("http") else "https://db.netkeiba.com"+href)

def parse_horse_form_page(page):
    soup=soup_of(page); table=None
    for sel in ["table.db_h_race_results", "table.race_table_01", "table"]:
        for t in soup.select(sel):
            headers=" ".join(text_of(x) for x in t.select("th"))
            if ("着順" in headers or "確定着順" in headers) and ("距離" in headers or "開催" in headers):
                table=t; break
        if table: break
    if not table: return {"available":False,"starts":0,"recent_results":[],"win_rate_recent":None,"source":"公開馬ページ・成績表未検出"}
    headers=[text_of(x) for x in table.select("tr th")]
    results=[]
    for tr in table.select("tr"):
        cells=tr.find_all(["td","th"],recursive=False)
        if not cells or cells[0].name=="th": continue
        vals=[text_of(c) for c in cells]
        if len(vals)<4: continue
        rowtext=" ".join(vals)
        # 近走らしい行のみ。未来の出走表や空行は除外。
        rank=None
        for val in vals[:5]:
            n=numeric(val)
            if n is not None and 1<=n<=18 and float(n).is_integer(): rank=int(n); break
        if rank is None: continue
        dist=None
        for val in vals:
            m=re.search(r"(?:芝|ダ|障)?\s*(\d{3,4})",val)
            if m and 800<=int(m.group(1))<=5000: dist=int(m.group(1)); break
        results.append({"finish":rank,"distance_m":dist,"row":rowtext[:220]})
        if len(results)>=5: break
    if not results: return {"available":False,"starts":0,"recent_results":[],"win_rate_recent":None,"source":"公開馬ページ・近走解析不可"}
    return {"available":True,"starts":len(results),"recent_results":results,
            "wins":sum(1 for x in results if x["finish"]==1),
            "win_rate_recent":round(sum(1 for x in results if x["finish"]==1)/len(results),4),
            "avg_finish":round(sum(x["finish"] for x in results)/len(results),2),
            "source":"公開馬ページから抽出。列構造の自動解析のため要検証"}

def get_horse_form(row):
    global FORM_FETCHED_THIS_RUN
    hid,url=horse_id_from_row(row)
    if not hid: return {"available":False,"starts":0,"recent_results":[],"source":"馬ページURL未取得"}
    cached=HORSE_FORM_CACHE.get(hid)
    if isinstance(cached,dict) and cached.get("checked_at"):
        try:
            checked=datetime.fromisoformat(cached["checked_at"])
            if NOW-checked < timedelta(days=14): return cached.get("form",{})
        except Exception: pass
    if FORM_FETCHED_THIS_RUN>=MAX_NEW_FORM_FETCHES:
        return {"available":False,"starts":0,"recent_results":[],"source":"無料実行時間保護のため今回の取得上限"}
    FORM_FETCHED_THIS_RUN+=1
    page=get_html(url)
    form=parse_horse_form_page(page) if page else {"available":False,"starts":0,"recent_results":[],"source":"馬ページ取得失敗"}
    HORSE_FORM_CACHE[hid]={"checked_at":NOW.isoformat(),"form":form}
    return form

def attach_probability_and_value(ranked):
    if not ranked: return
    # softmax風の参考確率。過去実績で校正された勝率ではない。
    vals=[float(h.get("score",0)) for h in ranked]
    mx=max(vals); weights=[math.exp(max(-30.0,min(0.0,(v-mx)/8.0))) for v in vals]
    total=sum(weights) or 1.0
    for h,w in zip(ranked,weights):
        prob=w/total
        h["estimated_win_probability_pct"]=round(prob*100,2)
        odds=h.get("odds")
        h["estimated_win_return_pct"] = round(prob*float(odds)*100,1) if odds is not None and odds>0 else None
        h["expected_value_status"] = "参考計算・未校正" if odds is not None and odds>0 else "オッズ未取得のため算出不可"
        form=h.get("past_form",{})
        if form.get("available"):
            h["past_form_win_rate_recent_pct"]=round(form.get("win_rate_recent",0)*100,1)
        else: h["past_form_win_rate_recent_pct"]=None

def parse_runners(soup,surface):
    table,rows=choose_shutuba_table(soup)
    if table is None:
        warn("出馬表テーブルが見つかりません")
        return [],{"table_found":False,"rows_found":0,"valid_rows":0,"unique_horses":0,"duplicate_numbers":[]}
    runners={}; valid=0; duplicates=[]
    for row in rows:
        name=parse_horse_name(row); no=parse_horse_no(row)
        if not name or no is None: continue
        valid+=1
        if no in runners: duplicates.append(no); continue
        frame=parse_frame_no(row); jockey=parse_jockey(row); odds,pop=parse_odds_popularity(row)
        past_form=get_horse_form(row)
        wd=parse_weight_change(row); rowtext=text_of(row)
        dirt=any(x in rowtext for x in DIRT_SIRES); power=any(x in rowtext for x in POWER_SIRES)
        apprentice=any(x in jockey for x in ["▲","△","☆","◇","★"])
        topj=any(x in jockey for x in TOP_JOCKEYS)
        positive=any(x in rowtext for x in POSITIVE_WORDS); negative=any(x in rowtext for x in NEGATIVE_WORDS)
        reasons=[]
        if topj: reasons.append("登録騎手リストに該当（実績保証ではない）")
        if apprentice: reasons.append("騎手欄に減量記号あり")
        if surface=="ダート" and dirt: reasons.append("掲載テキストにダート血統候補")
        if surface=="芝" and power: reasons.append("掲載テキストに芝・持続力型血統候補")
        if wd is not None and abs(wd)>=6: reasons.append(f"馬体重増減 {wd:+d}kg")
        if positive: reasons.append("掲載テキストに好材料ワード")
        if negative: reasons.append("掲載テキストに注意ワード")
        runners[no]={"horse_no":no,"number":no,"frame_no":frame,"horse":name,"name":name,
          "jockey":jockey or "未取得","odds":odds,"popularity":pop,"score":0.0,"rank":None,
          "reasons":reasons,"past_form":past_form,"caution":"簡易評価。勝率は未校正の参考値",
          "is_apprentice":apprentice,"is_top_jockey":topj,"is_inner":frame in (1,2) if frame else False,
          "is_outer":frame in (7,8) if frame else False,"is_dirt_blood":dirt,"is_power_blood":power,
          "is_positive_memo":positive,"is_negative_memo":negative,"w_diff":wd,
          "data_quality":{"odds":odds is not None,"popularity":pop is not None,"jockey":bool(jockey),
                          "frame":frame is not None,"weight_change":wd is not None,"past_form":bool(past_form.get("available"))}}
    result=sorted(runners.values(),key=lambda x:x["horse_no"])
    diagnostic={"table_found":True,"rows_found":len(rows),"valid_rows":valid,"unique_horses":len(result),"duplicate_numbers":sorted(set(duplicates))}
    if duplicates: warn(f"馬番重複を除外: {sorted(set(duplicates))}")
    if len(result)<5: warn(f"出走馬取得数が少ない: {len(result)}頭")
    # 実際の人気順位は取得値をそのまま保持。重複を勝手に修正しない。
    pops=[x["popularity"] for x in result if x["popularity"] is not None]
    diagnostic["popularity_count"]=len(pops)
    diagnostic["popularity_duplicates"]=sorted({p for p in pops if pops.count(p)>1})
    diagnostic["popularity_status"]="OK" if len(pops)==len(set(pops)) else ("重複あり" if pops else "未取得")
    return result,diagnostic

def score_runners(runners,surface,venue):
    for h in runners:
        score=0.0; odds=h["odds"]; pop=h["popularity"]
        if odds is not None and odds>0: score+=max(0.0,42.0-8.0*math.log(max(1.0,odds)))
        if pop is not None: score+=max(0.0,16.0-(pop-1)*1.1)
        if h["is_top_jockey"]: score+=3
        if h["is_apprentice"]: score+=1.5
        if surface=="ダート" and h["is_dirt_blood"]: score+=2
        elif surface=="芝" and h["is_power_blood"]: score+=1.5
        if venue in ("東京","新潟") and h["is_outer"]: score+=1; h["reasons"].append("外枠の簡易補正（未検証）")
        elif venue in ("中山","小倉","福島","札幌") and h["is_inner"]: score+=1; h["reasons"].append("内枠の簡易補正（未検証）")
        wd=h["w_diff"]
        if wd is not None and 8<=wd<=16: score+=1
        if h["is_positive_memo"]: score+=1
        form=h.get("past_form",{})
        if form.get("available"):
            avg=form.get("avg_finish")
            if avg is not None: score += max(-2.0, min(2.0, (6.0-float(avg))*0.35)); h["reasons"].append(f"取得できた近走{form.get('starts',0)}走の平均着順 {avg}位（参考）")
        if h["is_negative_memo"]: score-=2; h["reasons"].append("注意ワード検出による簡易減点")
        if pop==1 and odds is not None and odds<1.8: score-=1; h["reasons"].append("低オッズのため妙味を控えめ評価")
        h["score"]=round(score,2)
        if not h["reasons"]: h["reasons"].append("取得できた情報に基づく簡易評価")
        q=h["data_quality"]; h["score_confidence"]=round(sum(bool(v) for v in q.values())/len(q)*100) if q else 0
        if odds is None: h["reasons"].append("単勝オッズ未取得")
        if h["score_confidence"]<60: h["reasons"].append("取得項目が少なく評価の不確実性が高い")
    ranked=sorted(runners,key=lambda x:(-x["score"],x["horse_no"]))
    for rank,h in enumerate(ranked,1): h["rank"]=rank
    attach_probability_and_value(ranked)
    return ranked

def select_outsiders(ranked):
    # オッズ取得時は実オッズ条件。未取得時は「参考候補」として分離し、妙味判定とは呼ばない。
    outsiders=[]; longshots=[]; odds_known=any(h.get("odds") is not None for h in ranked)
    if odds_known:
        outsiders=[h for h in ranked if h.get("odds") is not None and 10<=h["odds"]<30]
        longshots=[h for h in ranked if h.get("odds") is not None and h["odds"]>=30]
        for h in outsiders: h["outsider_reason"]="単勝10〜30倍の実オッズ条件。好走保証ではない。"
        for h in longshots: h["longshot_reason"]="単勝30倍以上の実オッズ条件。好走保証ではない。"
        return outsiders[:5],longshots[:5],("odds_based" if odds_known else "unavailable")
    # オッズなしの場合、スコアだけで市場妙味を判断せず、順位帯と補助材料で参考候補を作る。
    eligible=[h for h in ranked if h["rank"]>=4]
    eligible.sort(key=lambda h:(-sum([bool(h.get("past_form",{}).get("available")),h.get("is_top_jockey",False),h.get("is_dirt_blood",False),h.get("is_power_blood",False),h.get("is_positive_memo",False),h.get("w_diff") is not None]), h["rank"]))
    for h in eligible:
        h["outsider_reason"]="オッズ未取得の参考穴候補。市場人気・配当妙味は未確認。根拠: "+"、".join(h["reasons"][:3])
    outsiders=eligible[:5]
    long_eligible=[h for h in ranked if h["rank"]>=max(6,math.ceil(len(ranked)*0.45))]
    long_eligible.sort(key=lambda h:(-sum([bool(h.get("past_form",{}).get("available")),h.get("is_top_jockey",False),h.get("is_dirt_blood",False),h.get("is_power_blood",False),h.get("is_positive_memo",False),h.get("w_diff") is not None and abs(h["w_diff"])>=6]), h["rank"]))
    for h in long_eligible:
        h["longshot_reason"]="オッズ未取得の参考大穴候補。実際の人気・単勝30倍以上は確認できていない。根拠: "+"、".join(h["reasons"][:3])
    return outsiders[:5],long_eligible[:5],"heuristic_no_odds"

def build_tickets(ranked,outsiders,verified):
    if not verified or len(ranked)<3: return []
    top=ranked[:5]; a,b,c=[h["horse_no"] for h in top[:3]]
    d=top[3]["horse_no"] if len(top)>=4 else c
    outsider=next((h["horse_no"] for h in outsiders if h["horse_no"] not in (a,b,c)),None)
    if outsider is not None:
        lines=[("win",[a],300),("quinella",sorted([a,b]),200),("quinella",sorted([a,c]),200),
               ("quinella",sorted([a,outsider]),200),("trio",sorted([a,b,c]),100),
               ("trio",sorted([a,b,outsider]),100),("wide",sorted([a,outsider]),100),
               ("wide",sorted([b,outsider]),100),("trifecta",[a,outsider,b],100)]
        pattern="B"; label="パターンB（参考穴候補を含む紙上買い目）"
        note="オッズ未取得時は配当妙味を評価していない。実購入禁止・利益保証なし。"
    else:
        lines=[("win",[a],500),("quinella",sorted([a,b]),300),("quinella",sorted([a,c]),300),
               ("trio",sorted([a,b,c]),600),("wide",sorted([a,d]),100),("wide",sorted([b,d]),100)]
        pattern="A"; label="パターンA（上位評価中心）"
        note="取得情報に基づく紙上シミュレーション。実購入は行わない。"
    names={"win":"単勝","quinella":"馬連","trio":"3連複","wide":"ワイド","trifecta":"3連単"}
    items=[]
    for typ,hs,stake in lines:
        if len(set(hs))!=len(hs) or not all(isinstance(n,int) and 1<=n<=18 for n in hs): continue
        items.append({"type":typ,"horses":hs,"stake_yen":stake,"label":f"{names[typ]} {'→' if typ=='trifecta' else '-'.join(map(str,hs))} ({stake}円)"})
    while sum(x["stake_yen"] for x in items)>PAPER_BUDGET_YEN: items.pop()
    cost=sum(x["stake_yen"] for x in items)
    return [{"pattern_type":pattern,"pattern":label,"cost_yen":cost,"lines":[x["label"] for x in items],"line_items":items,"note":note}]

def combo_key(horses,ordered=False):
    return "-".join(map(str,horses if ordered else sorted(horses)))

def parse_result_page(page,race_id):
    soup=soup_of(page); finishes=[]; payouts={"win":{},"place":{},"quinella":{},"wide":{},"trio":{},"trifecta":{},"exacta":{}}
    # 着順は「着順」ヘッダーと馬番列の両方が明示された表のみを優先
    tables=list(soup.find_all("table")); result_table=None
    for table in tables:
        heads=" ".join(text_of(x) for x in table.select("th,thead td,tr:first-child td"))
        if "着順" in heads and ("馬番" in heads or "馬名" in heads):
            result_table=table; break
    if result_table:
        for tr in result_table.select("tr"):
            cells=tr.find_all(["td","th"],recursive=False)
            if len(cells)<3: continue
            vals=[text_of(c) for c in cells]
            rank=numeric(vals[0])
            if rank is None or not 1<=rank<=18 or int(rank)!=rank: continue
            # 馬番は、馬名リンクを含む行の近くにある列から特定
            horse_link=tr.select_one("a[href*='/horse/']")
            if not horse_link: continue
            no=None
            for c in cells:
                cl=" ".join(c.get("class",[])).lower()
                if "umaban" in cl or "horse_no" in cl:
                    v=numeric(text_of(c))
                    if v is not None and 1<=v<=18: no=int(v); break
            if no is None:
                # 標準結果表: 着順、枠、馬番、馬名
                for txt in vals[1:4]:
                    v=numeric(txt)
                    if v is not None and 1<=v<=18 and int(v)!=int(rank):
                        no=int(v); break
            if no is not None:
                while len(finishes)<int(rank): finishes.append(None)
                if finishes[int(rank)-1] is None: finishes[int(rank)-1]=no
    finishes=[x for x in finishes if x is not None]
    if finishes and len(finishes)!=len(set(finishes)): warn(f"{race_id}: 着順馬番重複のため結果を無効扱い"); finishes=[]
    # 払戻: ラベル・組み合わせ・金額を過剰推測しない
    for table in tables:
        for tr in table.select("tr"):
            th=tr.select_one("th")
            if not th: continue
            label=text_of(th); tds=tr.find_all("td",recursive=False)
            if len(tds)<2: continue
            combo_text=text_of(tds[0]); payout_text=text_of(tds[1])
            amounts=[safe_int(x.replace(",","")) for x in re.findall(r"([\d,]+)\s*円",payout_text)]
            if not amounts: continue
            groups=re.findall(r"(?<!\d)(\d{1,2})(?:\s*[-－ー]\s*(\d{1,2}))?(?:\s*[-－ー]\s*(\d{1,2}))?",combo_text)
            combos=[]
            for g in groups:
                nums=[safe_int(x) for x in g if x]
                if nums and all(1<=x<=18 for x in nums): combos.append(nums)
            if not combos: continue
            if "単勝" in label: payouts["win"][str(combos[0][0])]=amounts[0]
            elif "複勝" in label:
                for c,a in zip(combos,amounts): payouts["place"][str(c[0])]=a
            elif "馬連" in label and len(combos[0])>=2: payouts["quinella"][combo_key(combos[0][:2])]=amounts[0]
            elif "ワイド" in label:
                for c,a in zip(combos,amounts):
                    if len(c)>=2: payouts["wide"][combo_key(c[:2])]=a
            elif "3連複" in label or "三連複" in label:
                if len(combos[0])>=3: payouts["trio"][combo_key(combos[0][:3])]=amounts[0]
            elif "3連単" in label or "三連単" in label:
                if len(combos[0])>=3: payouts["trifecta"][combo_key(combos[0][:3],True)]=amounts[0]
            elif "馬単" in label and len(combos[0])>=2: payouts["exacta"][combo_key(combos[0][:2],True)]=amounts[0]
    return finishes,payouts

def settle_tickets(tickets,finishes,payouts):
    if not tickets or len(finishes)<3:
        return {"settlement_complete":False,"all_bet_return":None,"race_profit":None,"settled_lines":[],"win_hit":None,"win_return":0,"settlement_status":"結果・上位着順不足"}
    items=tickets[0].get("line_items",[]); cost=tickets[0].get("cost_yen",0)
    settled=[]; total=0; win_hit=False; win_return=0; any_hit=False; missing_hit_payout=False
    top1=finishes[0]; top2=set(finishes[:2]); top3=set(finishes[:3])
    for line in items:
        typ=line["type"]; hs=line["horses"]; stake=line["stake_yen"]; key=combo_key(hs,typ=="trifecta")
        finish_hit=False
        if typ=="win": finish_hit=hs[0]==top1; payout=payouts["win"].get(str(hs[0]),0)
        elif typ=="quinella": finish_hit=len(hs)==2 and set(hs)==top2; payout=payouts["quinella"].get(key,0)
        elif typ=="wide": finish_hit=len(hs)==2 and set(hs).issubset(top3); payout=payouts["wide"].get(key,0)
        elif typ=="trio": finish_hit=len(hs)==3 and set(hs)==top3; payout=payouts["trio"].get(key,0)
        elif typ=="trifecta": finish_hit=len(hs)==3 and hs==finishes[:3]; payout=payouts["trifecta"].get(key,0)
        else: payout=0
        payout_hit=bool(payout and finish_hit)
        ret=int(stake/100*payout) if payout_hit else 0
        if finish_hit:
            any_hit=True
            if not payout: missing_hit_payout=True
        if typ=="win" and finish_hit:
            win_hit=True; win_return=ret
        total+=ret
        settled.append({"label":line.get("label",""),"type":typ,"horses":hs,"stake_yen":stake,
                        "hit":payout_hit,"finish_match":finish_hit,"return_yen":ret,
                        "payout_per_100":payout or None})
    # 結果着順だけでは利益を確定しない。的中組み合わせの払戻が確認できた時のみ精算完了。
    complete=not missing_hit_payout
    status=("払戻確認済み・精算完了" if complete else "着順一致あり・払戻未確認のため収支未確定")
    return {"settlement_complete":complete,"all_bet_return":total if complete else None,
            "race_profit":total-cost if complete else None,"settled_lines":settled,
            "win_hit":win_hit if complete else None,"win_return":win_return if complete else 0,
            "settlement_status":status,"result_finishes":finishes}

def fetch_and_settle_result(race,source):
    rid=race["id"]; base=source["base"]
    for url in [f"{base}/race/result.html?race_id={rid}",f"{base}/race/result.html?race_id={rid}&rf=race_submenu"]:
        page=get_html(url)
        if not page or not any(x in page for x in ["着順","払戻","単勝"]): continue
        finishes,payouts=parse_result_page(page,rid)
        if len(finishes)>=3:
            s=settle_tickets(race.get("tickets",[]),finishes,payouts)
            race.update({"result_finishes":finishes,"payouts":payouts,"win_hit":s["win_hit"],
              "win_return":s["win_return"],"all_bet_return":s["all_bet_return"],"race_profit":s["race_profit"],
              "settlement_complete":s["settlement_complete"],"settled_lines":s["settled_lines"],
              "settlement_status":s["settlement_status"],"is_finished":True})
            print(f"[SETTLE] {rid} status={s['settlement_status']} return={s['all_bet_return']}")
            return race
    race["settlement_status"]="結果ページから上位着順を取得できませんでした"
    race["result_finishes"]=[]
    return race

def parse_race(page,rid,source,date_iso,is_tomorrow):
    soup=soup_of(page); kind=source["kind"]; rno=race_no_from_id(rid); venue=venue_from_id(rid,kind)
    meta=parse_meta(soup); post=parse_post_time(meta); surface,distance=parse_surface_distance(meta); weather,going=parse_weather_going(meta)
    name=first_text(soup,[".RaceName","h1.RaceName",".race_name","[class*='RaceName']"])
    if not name:
        title=first_text(soup,["title"]); name=title.split("|")[0].strip() if title else ""
    if not name: name=f"{venue}{rno}R" if venue and rno else "レース名未取得"
    runners,diag=parse_runners(soup,surface); ranked=score_runners(runners,surface,venue)
    outsiders,longshots,candidate_mode=select_outsiders(ranked)
    count=len(runners); verified=count>=5 and diag["table_found"] and len({h["horse_no"] for h in runners})==count and not diag["duplicate_numbers"]
    if not verified: warn(f"{rid}: 出走頭数検証未通過 ({count}頭)")
    tickets=build_tickets(ranked,outsiders,verified)
    finished=False
    if post and not is_tomorrow:
        try:
            hh,mm=map(int,post.split(":")); scheduled=NOW.replace(hour=hh,minute=mm,second=0,microsecond=0)
            finished=NOW>=scheduled+timedelta(minutes=10)
        except ValueError: pass
    recommended=bool(verified and (rno==11 or len(outsiders)>=2 or len(longshots)>=2))
    return {"id":str(rid),"date":date_iso,"kind":kind,"category":source["category"],"race_no":rno,"name":name,
      "course":venue or "競馬場未取得","post_time":post or "未取得","surface":surface or "未取得",
      "distance_m":distance,"weather":weather or "未取得","going":going or "未取得","runner_count":count,
      "runner_count_verified":verified,"runner_diagnostic":diag,"horses":ranked,"top5":ranked[:5],
      "outsiders":outsiders,"longshots":longshots,"candidate_mode":candidate_mode,
      "candidate_notice":("実オッズ条件で抽出" if candidate_mode=="odds_based" else "オッズ未取得の参考候補。人気・配当妙味は未確認" if candidate_mode=="heuristic_no_odds" else "候補判定不可"),
      "tickets":tickets,"is_finished":finished,"result_finishes":[],"payouts":{},"win_hit":None,"win_return":0,
      "all_bet_return":None,"race_cost":tickets[0]["cost_yen"] if tickets else 0,"race_profit":None,
      "settlement_complete":False,"settled_lines":[],"settlement_status":"結果精算待ち",
      "is_recommended":recommended,"is_tomorrow":is_tomorrow,
      "prediction_status":"未検証の簡易評価" if verified else "出走頭数未検証・予想注意",
      "win_probability_note":"推定勝率はスコアを確率化した未校正の参考値。実績による校正は未実施。期待回収率は単勝オッズが取得できた場合のみ参考計算。",
      "past_form_status":"過去走は馬ページから最大5走を解析。サイト構造によって取得不能な場合があり、未取得を0評価として扱わない。"}

def fetch_races_for_date(date_str,is_tomorrow):
    all_races=[]; date_iso=(NOW+timedelta(days=1)).strftime("%Y-%m-%d") if is_tomorrow else NOW.strftime("%Y-%m-%d")
    for source in SOURCES:
        ids=fetch_race_ids(source,date_str)
        print(f"[INFO] {source['kind']} {date_str}: 一覧ID {len(ids)}件")
        for rid in ids:
            parsed=None
            for url in [f"{source['base']}/race/shutuba.html?race_id={rid}",f"{source['base']}/race/shutuba.html?race_id={rid}&rf=race_submenu"]:
                page=get_html(url)
                if not page or not soup_of(page).select_one("a[href*='/horse/']"): continue
                try: parsed=parse_race(page,rid,source,date_iso,is_tomorrow)
                except Exception as e: warn(f"{rid}: 解析例外 {type(e).__name__}"); parsed=None
                if parsed and parsed["runner_count"]>=2: break
            if not parsed:
                warn(f"{source['kind']} {rid}: レースページ解析失敗"); continue
            if parsed.get("is_finished") and not is_tomorrow:
                try: parsed=fetch_and_settle_result(parsed,source)
                except Exception as e: warn(f"{rid}: 結果精算例外 {type(e).__name__}")
            all_races.append(parsed)
    all_races.sort(key=lambda r:(r.get("post_time")=="未取得",r.get("post_time",""),r.get("course",""),r.get("race_no") or 0))
    return all_races

def load_history():
    if not HISTORY.exists(): return {"schema_version":29,"snapshots":{},"stats":{},"horse_form_cache":{}}
    try:
        v=json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(v,dict): raise ValueError("history root not object")
        for k in ("snapshots","stats","horse_form_cache"):
            if not isinstance(v.get(k),dict): v[k]={}
        v["schema_version"]=29
        return v
    except Exception as e:
        warn("history.json読み込み失敗。既存履歴保護のため処理中止: "+type(e).__name__)
        raise

def update_snapshot(snapshots,race):
    rid=str(race["id"]); old=snapshots.get(rid,{})
    if old.get("settlement_complete") is True and race.get("settlement_complete") is not True: return
    if not race.get("runner_count_verified"):
        if old: old["last_data_warning"]="出走頭数未検証"; old["updated_at"]=NOW.isoformat(); snapshots[rid]=old
        return
    tickets=race.get("tickets",[]); ticket=tickets[0] if tickets else {}
    snapshot={"race_id":rid,"date":race.get("date"),"kind":race.get("kind"),"course":race.get("course"),
      "race_no":race.get("race_no"),"name":race.get("name"),"cost":safe_int(race.get("race_cost"),0),
      "is_finished":bool(race.get("is_finished")),"win_hit":race.get("win_hit"),"win_return":safe_int(race.get("win_return"),0),
      "race_profit":race.get("race_profit"),"all_bet_return":race.get("all_bet_return"),
      "settlement_complete":bool(race.get("settlement_complete")),"settlement_status":race.get("settlement_status",""),
      "result_finishes":race.get("result_finishes",[]),"updated_at":NOW.isoformat(),
      "frozen_prediction":old.get("frozen_prediction") or {"top5":[{"horse_no":h.get("horse_no"),"name":h.get("name"),
        "score":h.get("score"),"odds":h.get("odds"),"rank":h.get("rank")} for h in race.get("top5",[])],
        "tickets":ticket,"prediction_status":race.get("prediction_status")},
      "last_odds":{str(h.get("horse_no")):h.get("odds") for h in race.get("horses",[])},
      "runner_count":race.get("runner_count"),"runner_count_verified":race.get("runner_count_verified"),
      "odds_snapshots":old.get("odds_snapshots",[]),"prediction_created_at":old.get("prediction_created_at") or NOW.isoformat()}
    snapshots[rid]=snapshot

def calculate_stats(snapshots):
    items=list(snapshots.values())
    settled=[x for x in items if x.get("settlement_complete") is True and x.get("all_bet_return") is not None and x.get("race_profit") is not None]
    # 単勝の払戻と全券種の収支を混ぜない。精算未確定は除外。
    win_items=[x for x in settled if x.get("win_hit") is not None]
    win_stake=sum(safe_int(x.get("cost"),0) for x in win_items)
    win_return=sum(safe_int(x.get("win_return"),0) for x in win_items)
    all_stake=sum(safe_int(x.get("cost"),0) for x in settled)
    all_return=sum(safe_int(x.get("all_bet_return"),0) for x in settled)
    hits=sum(1 for x in settled if safe_int(x.get("all_bet_return"),0)>0)
    return {"races_seen":len(items),"races_settled":len(settled),"win_bets":len(win_items),
      "win_hits":sum(1 for x in win_items if x.get("win_hit") is True),"total_stake_yen":win_stake,
      "total_return_yen":win_return,"roi_pct":round(win_return/win_stake*100,1) if win_stake else 0.0,
      "win_hit_rate_pct":round(sum(1 for x in win_items if x.get("win_hit") is True)/len(win_items)*100,1) if win_items else 0.0,
      "all_bet_settled_races":len(settled),"all_bet_stake_yen":all_stake,"all_bet_return_yen":all_return,
      "all_bet_roi_pct":round(all_return/all_stake*100,1) if all_stake else 0.0,"all_bet_hit_races":hits,
      "accounting_note":"払戻確認済みの精算済みレースのみ集計。単勝と全券種の集計対象・金額は別管理。未確定レースは回収率から除外。"}

def main():
    print(f"=== {ENGINE_VERSION} START ==="); print(f"[INFO] JST now: {NOW.isoformat()}")
    history=load_history(); snapshots=history["snapshots"]
    global HORSE_FORM_CACHE
    HORSE_FORM_CACHE=history.get("horse_form_cache",{}) if isinstance(history.get("horse_form_cache",{}),dict) else {}
    today_races=fetch_races_for_date(TODAY,False)
    tomorrow_races=fetch_races_for_date(TOMORROW,True)
    for race in today_races: update_snapshot(snapshots,race)
    cutoff=(NOW-timedelta(days=RETENTION_DAYS)).date()
    for rid,item in list(snapshots.items()):
        try:
            if datetime.strptime(item.get("date",""),"%Y-%m-%d").date()<cutoff: del snapshots[rid]
        except (ValueError,TypeError): pass
    stats=calculate_stats(snapshots)
    history.update({"schema_version":30,"updated_at":NOW.isoformat(),"stats":stats,"snapshots":snapshots,"horse_form_cache":HORSE_FORM_CACHE})
    save_json(HISTORY,history)
    verified=sum(1 for r in today_races if r.get("runner_count_verified"))
    settled=sum(1 for r in today_races if r.get("settlement_complete"))
    status="OK" if today_races or tomorrow_races else "NO_RACES"
    data={"site":"BAGEN KEIBA","engine_version":ENGINE_VERSION,"generated_at":NOW.isoformat(),
      "race_date":NOW.strftime("%Y-%m-%d"),"status":status,"warnings":WARNINGS[:MAX_WARNINGS],
      "races":today_races,"tomorrow_races":tomorrow_races,"tomorrow_race_count":len(tomorrow_races),
      "tomorrow_recommended_count":sum(1 for r in tomorrow_races if r.get("is_recommended")),
      "runner_validation":{"today_races":len(today_races),"verified_races":verified,
        "unverified_races":len(today_races)-verified,"settled_races":settled,
        "note":"出走頭数未検証のレースは買い目を作成しません。実際の人気とAI予想順位は別項目です。"},
      "prediction_notice":"簡易スコアであり、校正済み勝率・的中・利益を保証しません。オッズ未取得時の穴・大穴候補は参考候補であり配当妙味未確認です。",
      "data_quality_summary":{"new_horse_form_fetches":FORM_FETCHED_THIS_RUN,"horse_form_cache_entries":len(HORSE_FORM_CACHE),"odds_available_runners":sum(1 for r in today_races+tomorrow_races for h in r.get("horses",[]) if h.get("odds") is not None),"probability_method":"score_softmax_uncalibrated","expected_return_method":"estimated_win_probability_x_actual_win_odds_only"},
      "paper_betting":{"mode":"paper_only","real_betting_enabled":False,"stats":stats,
        "history":sorted(snapshots.values(),key=lambda x:(x.get("date",""),x.get("race_id","")),reverse=True)[:100]}}
    save_json(OUT,data)
    print(f"{ENGINE_VERSION} | status={status} | today={len(today_races)} | verified={verified} | settled={settled} | tomorrow={len(tomorrow_races)} | history={len(snapshots)}")
    print(f"[INFO] warning_count={len(WARNINGS)}")
    for msg in WARNINGS: print("[DIAGNOSTIC]",msg)
    print("=== FINISHED ===")

if __name__=="__main__": main()
