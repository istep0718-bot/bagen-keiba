#!/usr/bin/env python3
"""BAGEN KEIBA — free, paper-only racing data and prediction engine.
No real-money betting. Public-page scraping may fail when source pages change.
"""
from __future__ import annotations
import json, re, time, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "data.json"
HISTORY = DOCS / "history.json"
JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y%m%d")
UNIT_YEN = 100
INITIAL_BANKROLL_YEN = 10_000
MAX_RACES_PER_SOURCE = 60
REQUEST_DELAY_SECONDS = 0.7

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}
SOURCES = [
    {"kind": "中央", "category": "central", "base": "https://race.netkeiba.com", "list": "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date="},
    {"kind": "地方", "category": "local", "base": "https://nar.netkeiba.com", "list": "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date="},
]
VENUES = ["札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉","門別","盛岡","水沢","浦和","船橋","大井","川崎","金沢","笠松","名古屋","園田","姫路","高知","佐賀","帯広"]
JRA_CODES = {"01":"札幌","02":"函館","03":"福島","04":"新潟","05":"東京","06":"中山","07":"中京","08":"京都","09":"阪神","10":"小倉"}
NAR_CODES = {"30":"門別","35":"盛岡","36":"水沢","42":"浦和","43":"船橋","44":"大井","45":"川崎","46":"金沢","47":"笠松","48":"名古屋","50":"園田","51":"姫路","54":"高知","55":"佐賀","65":"帯広"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def num(v: Any) -> float | None:
    if v is None: return None
    s = clean(v).replace(",", "")
    if s in {"", "--", "-", "取消", "除外", "未発表", "発売前"}: return None
    m = re.search(r"\d+(?:\.\d+)?", s)
    try: return float(m.group()) if m else None
    except (ValueError, AttributeError): return None


def get(url: str) -> str:
    r = SESSION.get(url, timeout=(10, 25))
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def load_json(path: Path, default: Any) -> Any:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError): return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def soup_of(html: str) -> BeautifulSoup: return BeautifulSoup(html, "html.parser")
def text_of(soup: BeautifulSoup) -> str: return clean(soup.get_text(" ", strip=True))


def first_text(node: Any, selectors: list[str]) -> str:
    for sel in selectors:
        try: el = node.select_one(sel)
        except Exception: el = None
        if el:
            t = clean(el.get_text(" ", strip=True))
            if t: return t
    return ""


def first_group(patterns: list[str], text: str) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m: return clean(m.group(1))
    return ""


def venue_from_id(race_id: str, kind: str) -> str:
    # For common Netkeiba IDs, venue code is usually positions 8–9.
    if len(race_id) >= 10:
        return (JRA_CODES if kind == "中央" else NAR_CODES).get(race_id[8:10], "")
    return ""


def find_venue(text: str, title: str, race_id: str, kind: str) -> str:
    combined = f"{title} {text[:3500]}"
    # Prefer explicit known venue names; fall back to ID only if recognized.
    found = [v for v in VENUES if v in combined]
    if found: return max(found, key=len)
    return venue_from_id(race_id, kind)


def race_ids_from_list(html: str) -> list[str]:
    soup = soup_of(html); out=[]; seen=set()
    for a in soup.select('a[href*="race_id="]'):
        href = a.get("href", "")
        m = re.search(r"race_id=(\d{10,12})", href)
        if m and m.group(1) not in seen:
            seen.add(m.group(1)); out.append(m.group(1))
    return out[:MAX_RACES_PER_SOURCE]


def race_title(soup: BeautifulSoup, venue: str, race_no: int | None) -> str:
    for sel in [".RaceName", ".race_name", "h1", "h2", "title"]:
        for el in soup.select(sel):
            v = clean(el.get_text(" ", strip=True))
            v = re.sub(r"\s*\|.*$", "", v)
            v = re.sub(r"^\d{4}年\d+月\d+日\s*", "", v)
            if not v or len(v) < 2 or "netkeiba" in v.lower(): continue
            if v in {"出馬表", "レース結果", "競馬データ", venue}: continue
            return v
    return f"{venue}{race_no}R（レース名未取得）" if venue and race_no else "レース名未取得"


def parse_meta(html: str, race_id: str, kind: str) -> tuple[dict, BeautifulSoup]:
    soup=soup_of(html); txt=text_of(soup)
    title=clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    nm=re.search(r"(\d{2})$", race_id); race_no=int(nm.group(1)) if nm else None
    venue=find_venue(txt, title, race_id, kind)
    data_line=" ".join([first_text(soup,[".RaceData01",".race_data",".RaceData","[class*='RaceData']","[class*='race_data']"]),txt[:6000]])
    post=first_group([r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",r"(\d{1,2}:\d{2})\s*発走"],data_line)
    surf=first_group([r"(芝|ダート|ダ)\s*(?:・|[-ー]|\s)*\d{3,4}\s*m?",r"(芝|ダート|ダ)\s*\d{3,4}"],txt[:8000])
    dm=re.search(r"(?:芝|ダート|ダ)\s*(?:・|[-ー]|\s)*(\d{3,4})\s*m?",txt[:8000],re.I)
    weather=first_group([r"天候\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)",r"天気\s*[:：]?\s*(晴|曇|雨|小雨|小雪|雪)"],txt[:9000])
    condition=first_group([r"馬場状態\s*[:：]?\s*(稍重|不良|重|良)",r"馬場\s*[:：]?\s*(稍重|不良|重|良)"],txt[:9000])
    return {"race_name":race_title(soup,venue,race_no),"course":venue,"race_no":race_no,"post_time":post,"surface":surf,"distance_m":int(dm.group(1)) if dm else None,"weather":weather,"track_condition":condition}, soup


def cell(row: Any, selectors: list[str]) -> str: return first_text(row, selectors)


def parse_runners(soup: BeautifulSoup) -> list[dict]:
    rows=[]; seen_rows=set()
    for sel in ["tr.HorseList", "tr[class*='HorseList']", "table.Shutuba_Table tr", "table.RaceTable01 tr", "table.RaceTable tr"]:
        for row in soup.select(sel):
            marker=id(row)
            if marker not in seen_rows: seen_rows.add(marker); rows.append(row)
    runners=[]; seen_ids=set()
    for row in rows:
        a=row.select_one('a[href*="/horse/"]')
        if not a: continue
        name=clean(a.get_text(" ",strip=True)); href=a.get("href","")
        hm=re.search(r"/horse/(\d+)",href); horse_id=hm.group(1) if hm else ""
        identity=horse_id or name
        if not name or identity in seen_ids: continue
        seen_ids.add(identity)
        hno=num(cell(row,[".Umaban",".Horse_Num","td[class*='Umaban']","td[class*='Horse_Num']","td[class*='Waku'] + td"]))
        frame=num(cell(row,[".Waku",".Wakuban","td[class*='Waku']"]))
        odds=num(cell(row,[".Odds",".Popular_Odds","td[class*='Odds']","span[class*='Odds']","[class*='odds']"]))
        pop=num(cell(row,[".Popular","td[class*='Popular']","[class*='popular']"]))
        jockey=cell(row,[".Jockey","td[class*='Jockey']","a[href*='/jockey/']"])
        trainer=cell(row,[".Trainer","td[class*='Trainer']","a[href*='/trainer/']"])
        sex_age=cell(row,[".Barei","td[class*='Barei']"])
        wt=cell(row,["td[class*='Horse_Weight']","td[class*='Weight']"])
        wm=re.search(r"(\d{3})\s*(?:\(([+-]?\d+)\))?",wt)
        runners.append({"horse_no":int(hno) if hno is not None else None,"frame_no":int(frame) if frame is not None else None,"horse":name,"horse_id":horse_id,"jockey":jockey,"trainer":trainer,"sex_age":sex_age,"body_weight":int(wm.group(1)) if wm else None,"body_weight_change":int(wm.group(2)) if wm and wm.group(2) else None,"odds":odds if odds and odds > 0 else None,"popularity":int(pop) if pop and pop > 0 else None,"recent_form":[]})
    # Rank only on evidence actually present. Missing-market races are explicitly unranked.
    valid_odds=[h["odds"] for h in runners if h.get("odds") and h["odds"] > 0]
    for h in runners:
        reasons=[]; score=None; implied=None
        odds=h.get("odds"); pop=h.get("popularity")
        if odds and odds > 0:
            # Lower odds means stronger market support. Log transform avoids huge distortions.
            score=100.0 - min(70.0, 18.0*math.log(max(1.0,odds)))
            reasons.append(f"単勝オッズ {odds:g}倍")
        if pop:
            pop_score=max(0.0, 35.0 - (pop-1)*2.5)
            score=(score*0.7+pop_score*0.3) if score is not None else pop_score
            reasons.append(f"{pop}番人気")
        if odds and len(valid_odds)>0:
            inverse_sum=sum(1/x for x in valid_odds if x>0)
            implied=round((1/odds)/inverse_sum*100,2) if inverse_sum else None
        h["score"]=round(score,2) if score is not None else None
        h["market_implied_pct"]=implied
        h["reasons"]=reasons or ["オッズ・人気未取得。根拠ある順位は算出不可"]
        h["prediction_status"]="RANKED_MARKET_DATA" if score is not None else "INSUFFICIENT_DATA"
    ranked=sorted(runners,key=lambda h:(h["score"] is None, -(h["score"] or 0), h.get("odds") or float("inf"), h.get("horse_no") or 999))
    # Do not pretend unknown horses are genuinely ranked: ranks are display positions only,
    # and prediction_valid=false flags a race with insufficient market evidence.
    any_market=any(h.get("score") is not None for h in runners)
    for idx,h in enumerate(ranked,1):
        h["prediction_rank"]=idx if any_market and h.get("score") is not None else None
        h["number"]=h.get("horse_no"); h["name"]=h.get("horse")
        h["predicted_rank"]=h["prediction_rank"]
        h["weight"]=h.get("body_weight"); h["surface_fit"]="適性データ未取得"
    return ranked


def parse_finish_positions(html: str, race: dict) -> dict[str,int]:
    soup=soup_of(html); positions={}
    for row in soup.select("tr.HorseList, tr[class*='HorseList'], table.RaceTable01 tr, table.Result_Table tr, tr[class*='Result']"):
        a=row.select_one('a[href*="/horse/"]')
        if not a: continue
        rank_text=cell(row,[".Rank","td[class*='Rank']","td[class*='Order']","td[class*='着順']",".着順"])
        m=re.match(r"^\s*(\d{1,2})\s*$",rank_text)
        if not m: continue
        pos=int(m.group(1))
        if not 1 <= pos <= 30: continue
        hm=re.search(r"/horse/(\d+)",a.get("href", "")); hid=hm.group(1) if hm else ""
        name=clean(a.get_text(" ",strip=True))
        for h in race.get("runners",[]):
            if (hid and hid==h.get("horse_id")) or (not hid and name and name==h.get("horse")):
                if h.get("horse_no") is not None: positions[str(h["horse_no"])]=pos
    return positions


def empty_snapshot(race: dict, ranked: list[dict]) -> dict:
    # One virtual win bet is placed only if odds exist at first prediction.
    pick=next((h for h in ranked if h.get("prediction_rank")==1),None)
    can_bet=bool(pick and pick.get("horse_no") is not None and pick.get("odds") is not None and pick.get("prediction_rank") is not None)
    return {"race_id":str(race["id"]),"kind":race["kind"],"category":race["category"],"race_date":race["race_date"],"race_name":race["name"],"course":race["course"],"post_time":race["post_time"],"source_url":race["source_url"],"snapshot_at":NOW.isoformat(),"prediction_method":"市場オッズ・人気の簡易スコア。学習済みAIではありません","prediction_valid":bool(pick and pick.get("score") is not None),"predicted_horse_no":pick.get("horse_no") if pick else None,"predicted_horse":pick.get("horse") if pick else None,"predicted_rankings":[{"horse_no":h.get("horse_no"),"horse":h.get("horse"),"rank":h.get("prediction_rank"),"score":h.get("score"),"odds_at_prediction":h.get("odds"),"popularity_at_prediction":h.get("popularity")} for h in ranked],"result_status":"PENDING","predicted_finish_position":None,"paper_bets":{"win":{"placed":can_bet,"horse_no":pick.get("horse_no") if can_bet else None,"stake_yen":UNIT_YEN if can_bet else 0,"odds_at_prediction":pick.get("odds") if can_bet else None,"hit":None,"return_yen":None},"place":{"placed":False,"horse_no":None,"stake_yen":0,"hit":None,"return_yen":None}},"settlement_note":"単勝は初回予想時オッズで仮想計算。複勝は公式払戻の確認ができるまで購入・集計しません。"}


def ensure_history(history: Any) -> dict:
    if not isinstance(history,dict): history={}
    snaps=history.get("snapshots")
    if not isinstance(snaps,dict): snaps={}
    # Normalize old snapshots without deleting past history.
    history["snapshots"]={str(k):v for k,v in snaps.items() if isinstance(v,dict)}
    history.setdefault("schema_version",3)
    return history


def calculate_stats(snapshots: dict) -> dict:
    stats={"initial_bankroll_yen":INITIAL_BANKROLL_YEN,"races_settled":0,"win_bets":0,"win_hits":0,"win_stake_yen":0,"win_return_yen":0,"place_bets":0,"place_hits":0,"place_stake_yen":0,"place_return_yen":0,"total_stake_yen":0,"total_return_yen":0,"profit_yen":0,"roi_pct":0.0,"virtual_balance_yen":INITIAL_BANKROLL_YEN,"win_hit_rate_pct":0.0,"place_hit_rate_pct":0.0,"payout_data_missing":0}
    for s in snapshots.values():
        if s.get("result_status")!="SETTLED": continue
        stats["races_settled"]+=1
        for typ in ("win","place"):
            b=s.get("paper_bets",{}).get(typ,{})
            if not b.get("placed"): continue
            # Only fully known payouts can be included in ROI. Unknown payout is not a loss.
            if b.get("return_yen") is None:
                stats["payout_data_missing"]+=1
                continue
            stats[typ+"_bets"]+=1
            stats[typ+"_stake_yen"]+=int(b.get("stake_yen") or 0)
            stats[typ+"_return_yen"]+=int(b.get("return_yen") or 0)
            if b.get("hit") is True: stats[typ+"_hits"]+=1
    stats["total_stake_yen"]=stats["win_stake_yen"]+stats["place_stake_yen"]
    stats["total_return_yen"]=stats["win_return_yen"]+stats["place_return_yen"]
    stats["profit_yen"]=stats["total_return_yen"]-stats["total_stake_yen"]
    stats["virtual_balance_yen"]=INITIAL_BANKROLL_YEN+stats["profit_yen"]
    stats["roi_pct"]=round(stats["total_return_yen"]/stats["total_stake_yen"]*100,2) if stats["total_stake_yen"] else 0.0
    for typ in ("win","place"):
        bets=stats[typ+"_bets"]; hits=stats[typ+"_hits"]
        stats[typ+"_hit_rate_pct"]=round(hits/bets*100,2) if bets else 0.0
    return stats


def main() -> None:
    history=ensure_history(load_json(HISTORY,{"schema_version":3,"snapshots":{}}))
    snapshots=history["snapshots"]
    races=[]; errors=[]; attempted=0
    for source in SOURCES:
        try:
            list_html=get(source["list"]+TODAY)
            ids=race_ids_from_list(list_html)
        except Exception as e:
            errors.append(f"{source['kind']}一覧取得失敗: {type(e).__name__}: {str(e)[:180]}")
            continue
        if not ids:
            errors.append(f"{source['kind']}: レースIDを取得できません。非開催日・アクセス制限・ページ変更の可能性")
        for rid in ids:
            attempted+=1
            url=f"{source['base']}/race/shutuba.html?race_id={rid}"
            try:
                html=get(url); meta,soup=parse_meta(html,rid,source["kind"])
                runners=parse_runners(soup)
                if not runners:
                    errors.append(f"{rid}: 出走馬0頭。ページ構造またはアクセス制限を確認")
                    time.sleep(REQUEST_DELAY_SECONDS); continue
                race_name=meta["race_name"]
                race={"id":rid,"kind":source["kind"],"category":source["category"],"date":NOW.strftime("%Y-%m-%d"),"race_date":NOW.strftime("%Y-%m-%d"),"race_no":meta["race_no"],"name":race_name,"race_name":race_name,"course":meta["course"],"post_time":meta["post_time"],"surface":meta["surface"],"distance_m":meta["distance_m"],"weather":meta["weather"],"track_condition":meta["track_condition"],"source_url":url,"source_name":"netkeiba（非公式取得）","runner_count":len(runners),"horses":runners,"runners":runners,"top5":[h for h in runners if h.get("prediction_rank") is not None][:5],"prediction_valid":any(h.get("score") is not None for h in runners),"prediction_note":"オッズ・人気に基づく簡易市場スコア。取得不能時は順位を捏造しません"}
                key=str(rid)
                if key not in snapshots:
                    snapshots[key]=empty_snapshot(race,runners)
                snap=snapshots[key]
                # Store live data separately from frozen first-seen prediction.
                snap["latest_seen_at"]=NOW.isoformat()
                snap["latest_odds"]={str(h.get("horse_no")):h.get("odds") for h in runners if h.get("horse_no") is not None}
                # Attempt result matching; do not settle based on a partial or blank page.
                try:
                    result_html=get(f"{source['base']}/race/result.html?race_id={rid}")
                    positions=parse_finish_positions(result_html,race)
                    picked=snap.get("predicted_horse_no")
                    finish=positions.get(str(picked)) if picked is not None else None
                    # Only settle if result page includes positions for at least one-third of field
                    # and the frozen pick is present; avoids false settlement from partial page text.
                    if finish is not None and len(positions)>=max(1,math.ceil(len(runners)/3)):
                        snap["finish_positions"]=positions
                        snap["predicted_finish_position"]=finish
                        snap["result_status"]="SETTLED"
                        wb=snap.setdefault("paper_bets",{}).setdefault("win",{})
                        if wb.get("placed"):
                            wb["hit"]=(finish==1)
                            odds=wb.get("odds_at_prediction")
                            wb["return_yen"]=int(round(float(odds)*int(wb.get("stake_yen") or UNIT_YEN))) if finish==1 and odds else 0
                        pb=snap.setdefault("paper_bets",{}).setdefault("place",{})
                        # No fictional place payout. Default unplaced and excluded.
                        pb.update({"placed":False,"stake_yen":0,"hit":None,"return_yen":None})
                        snap["settlement_note"]="単勝払戻は初回予想時オッズによる概算。複勝は公式払戻を確認できないため未集計。"
                except Exception as e:
                    errors.append(f"{rid} 結果照合失敗: {type(e).__name__}")
                races.append(race)
            except Exception as e:
                errors.append(f"{rid}: {type(e).__name__}: {str(e)[:180]}")
            time.sleep(REQUEST_DELAY_SECONDS)
    stats=calculate_stats(snapshots)
    history.update({"schema_version":3,"updated_at":NOW.isoformat(),"stats":stats})
    save_json(HISTORY,history)
    settled=[s for s in snapshots.values() if s.get("result_status")=="SETTLED"]
    data={"site":"BAGEN KEIBA","schema_version":3,"generated_at":NOW.isoformat(),"race_date":NOW.strftime("%Y-%m-%d"),"status":"OK" if races else "NO_DATA","source_policy":"Unofficial public-page scraping; free services only; no real-money betting integration.","data_note":"オッズ・人気を使った簡易市場スコアで、学習済みAI勝率ではありません。取得できない情報は推測で補いません。単勝払戻は初回予想時オッズによる概算。複勝公式払戻は未取得のため集計対象外です。","race_count":len(races),"attempted_race_count":attempted,"races":sorted(races,key=lambda r:(0 if r["kind"]=="中央" else 1,r.get("post_time") or "99:99",r.get("race_no") or 99)),"errors":errors[-30:],"history_count":len(snapshots),"paper_betting":{"unit_yen":UNIT_YEN,"initial_bankroll_yen":INITIAL_BANKROLL_YEN,"types":["単勝（概算払戻）"],"real_money":False,"stats":stats,"history":settled[-100:]}}
    save_json(OUT,data)
    print(f"BAGEN update: races={len(races)} attempted={attempted} snapshots={len(snapshots)} errors={len(errors)}")
    print(f"stats: settled={stats['races_settled']} bets={stats['win_bets']} hits={stats['win_hits']} profit={stats['profit_yen']} balance={stats['virtual_balance_yen']}")
    for e in errors[-10:]: print("WARNING:",e)
    if not races: print("WARNING: No races parsed; check source access, date, and page structure.")

if __name__ == "__main__":
    main()
