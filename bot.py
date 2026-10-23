#!/usr/bin/env python3
"""BAGEN KEIBA: free race-card collector and paper-prediction ledger."""
import json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
DOCS=ROOT/"docs"; OUT=DOCS/"data.json"; HISTORY=DOCS/"history.json"
JST=timezone(timedelta(hours=9)); NOW=datetime.now(JST); TODAY=NOW.strftime("%Y%m%d")
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; BAGEN-Keiba/2.0)"}
SOURCES=[
 {"kind":"中央","base":"https://race.netkeiba.com","list":"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date="},
 {"kind":"地方","base":"https://nar.netkeiba.com","list":"https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date="}]
UNIT=100

def clean(x): return re.sub(r"\s+"," ",x or "").strip()
def number(x):
 m=re.search(r"\d+(?:\.\d+)?",clean(x).replace(",",""))
 try: return float(m.group()) if m else None
 except ValueError: return None
def get(url):
 r=requests.get(url,headers=HEADERS,timeout=20); r.raise_for_status()
 r.encoding=r.apparent_encoding or "utf-8"; return r.text
def load(path,default):
 try: return json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError): return default
def save(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp")
 tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); tmp.replace(path)
def ids(html):
 soup=BeautifulSoup(html,"html.parser"); out=[]
 for a in soup.select('a[href*="race_id="]'):
  m=re.search(r"race_id=(\d{10,12})",a.get("href",""))
  if m and m.group(1) not in out: out.append(m.group(1))
 return out[:60]
def cell(row,selectors):
 for s in selectors:
  e=row.select_one(s)
  if e and clean(e.get_text(" ",strip=True)): return clean(e.get_text(" ",strip=True))
 return ""
def parse_card(html):
 soup=BeautifulSoup(html,"html.parser"); title=clean(soup.title.get_text(" ",strip=True)) if soup.title else "レース名未取得"
 text=clean(soup.get_text(" ",strip=True)); surface=""; distance=None; weather=""; condition=""; post=""
 m=re.search(r"(芝|ダート|ダ)\s*(\d{3,4})\s*m",text,re.I)
 if m: surface=m.group(1); distance=int(m.group(2))
 m=re.search(r"天候\s*[:：]?\s*(晴|曇|雨|小雨|雪|小雪)",text)
 if m: weather=m.group(1)
 m=re.search(r"馬場状態\s*[:：]?\s*(良|稍重|重|不良)",text)
 if m: condition=m.group(1)
 m=re.search(r"発走\s*[:：]?\s*(\d{1,2}:\d{2})",text)
 if m: post=m.group(1)
 course=next((n for n in ["札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉","門別","盛岡","水沢","浦和","船橋","大井","川崎","金沢","笠松","名古屋","園田","姫路","高知","佐賀","帯広"] if n in text[:700] or n in title),"")
 runners=[]; seen=set()
 for row in soup.select("tr.HorseList,tr[class*='HorseList'],table.Shutuba_Table tr,table.RaceTable01 tr"):
  a=row.select_one('a[href*="/horse/"]')
  if not a: continue
  horse=clean(a.get_text(" ",strip=True))
  if not horse or horse in seen: continue
  seen.add(horse); hm=re.search(r"/horse/(\d+)",a.get("href",""))
  hn=number(cell(row,[".Umaban",".Horse_Num","td[class*='Umaban']","td[class*='Horse_Num']"]))
  fn=number(cell(row,[".Waku",".Wakuban","td[class*='Waku']"]))
  odds=number(cell(row,[".Odds",".Popular_Odds","td[class*='Odds']"]))
  pop=number(cell(row,[".Popular","td[class*='Popular']"]))
  bwtext=cell(row,["td[class*='Horse_Weight']"])
  bwm=re.search(r"(\d{3,})\s*(?:\(([+-]?\d+)\))?",bwtext)
  recent=[]
  for td in row.select("td"):
   cls=" ".join(td.get("class",[])).lower()
   if any(k in cls for k in ("past","result","race_history","horse_past")):
    v=clean(td.get_text(" ",strip=True))
    if v: recent.append(v[:80])
  runners.append({"horse_no":int(hn) if hn else None,"frame_no":int(fn) if fn else None,
   "horse":horse,"horse_id":hm.group(1) if hm else "",
   "jockey":cell(row,[".Jockey","td[class*='Jockey']"]),
   "trainer":cell(row,[".Trainer","td[class*='Trainer']"]),
   "sex_age":cell(row,[".Barei","td[class*='Barei']"]),
   "body_weight":int(bwm.group(1)) if bwm else None,
   "body_weight_change":int(bwm.group(2)) if bwm and bwm.group(2) else None,
   "odds":odds,"popularity":int(pop) if pop else None,"recent_form":recent})
 inv=sum(1/r["odds"] for r in runners if r.get("odds") and r["odds"]>1)
 for r in runners:
  score=50.; reasons=[]; implied=None
  if r.get("odds") and r["odds"]>1 and inv:
   implied=(1/r["odds"])/inv*100; score+=min(35,implied*1.8); reasons.append(f"市場評価 {implied:.1f}%相当")
  if r.get("popularity"): score+=max(0,12-(r["popularity"]-1)*1.4); reasons.append(f'{r["popularity"]}番人気')
  if not r.get("odds") and not r.get("popularity"): reasons.append("オッズ・人気未取得")
  r["score"]=round(score,2); r["market_implied_pct"]=round(implied,2) if implied is not None else None; r["reasons"]=reasons
 runners.sort(key=lambda r:(-r["score"],r.get("odds") or 999999,r.get("horse_no") or 999))
 for i,r in enumerate(runners,1): r["prediction_rank"]=i
 return {"title":re.sub(r"\s*\|.*$","",title).strip(),"course":course,"post_time":post,"surface":surface,"distance_m":distance,"weather":weather,"track_condition":condition},runners

def parse_positions(html,race):
 soup=BeautifulSoup(html,"html.parser"); by_id={}; by_name={}
 for row in soup.select("tr.HorseList,tr[class*='HorseList'],table.RaceTable01 tr,table.Result_Table tr"):
  a=row.select_one('a[href*="/horse/"]')
  if not a: continue
  txt=clean(row.get_text(" ",strip=True)); pos=cell(row,[".Rank","td[class*='Rank']","td[class*='Order']","td.num","td[class*='着順']"])
  m=re.match(r"^(\d{1,2})$",pos) or re.search(r"(?:^|\s)(\d{1,2})\s+(?:[牡牝セ]\d|[牡牝セ])",txt)
  if not m: continue
  n=int(m.group(1))
  if not 1<=n<=30: continue
  hm=re.search(r"/horse/(\d+)",a.get("href","")); name=clean(a.get_text(" ",strip=True))
  if hm: by_id[hm.group(1)]=n
  by_name[name]=n
 mapped={}
 for h in race.get("runners",[]):
  v=by_id.get(h.get("horse_id")) if h.get("horse_id") else None
  if v is None: v=by_name.get(h.get("horse"))
  if v is not None and h.get("horse_no") is not None: mapped[str(h["horse_no"])]=v
 return mapped

def stats(snaps):
 s={"settled_races":0,"win_bets":0,"win_hits":0,"win_stake_yen":0,"win_return_yen":0,
    "place_bets":0,"place_hits":0,"place_stake_yen":0,"place_return_yen":0}
 for x in snaps.values():
  if x.get("result_status")!="SETTLED": continue
  s["settled_races"]+=1
  for t in ("win","place"):
   b=x.get("paper_bets",{}).get(t,{})
   if not b.get("placed"): continue
   s[t+"_bets"]+=1; s[t+"_stake_yen"]+=int(b.get("stake_yen") or 0)
   if b.get("hit"): s[t+"_hits"]+=1
   if b.get("return_yen") is not None: s[t+"_return_yen"]+=int(b["return_yen"])
 for t in ("win","place"):
  s[t+"_profit_yen"]=s[t+"_return_yen"]-s[t+"_stake_yen"]
  s[t+"_hit_rate_pct"]=round(s[t+"_hits"]/s[t+"_bets"]*100,2) if s[t+"_bets"] else None
  s[t+"_roi_pct"]=round(s[t+"_return_yen"]/s[t+"_stake_yen"]*100,2) if s[t+"_stake_yen"] else None
 s["total_stake_yen"]=s["win_stake_yen"]+s["place_stake_yen"]
 s["total_return_yen"]=s["win_return_yen"]+s["place_return_yen"]
 s["total_profit_yen"]=s["total_return_yen"]-s["total_stake_yen"]
 s["total_roi_pct"]=round(s["total_return_yen"]/s["total_stake_yen"]*100,2) if s["total_stake_yen"] else None
 return s

def main():
 hist=load(HISTORY,{"schema_version":1,"snapshots":{}})
 if not isinstance(hist,dict): hist={"schema_version":1,"snapshots":{}}
 snaps=hist.setdefault("snapshots",{}); races=[]; errors=[]
 for source in SOURCES:
  try: raceids=ids(get(source["list"]+TODAY))
  except Exception as e: errors.append(f'{source["kind"]}一覧: {type(e).__name__}: {e}'); continue
  if not raceids: errors.append(f'{source["kind"]}: レースIDなし（非開催日・アクセス制限・ページ変更の可能性）')
  for rid in raceids:
   url=f'{source["base"]}/race/shutuba.html?race_id={rid}'
   try:
    meta, runners=parse_card(get(url))
    if not runners: errors.append(f"{rid}: 出走馬なし"); continue
    m=re.search(r"(\d{2})$",rid); rn=int(m.group(1)) if m else None
    race={"id":rid,"kind":source["kind"],"race_date":NOW.strftime("%Y-%m-%d"),"race_no":rn,"race_name":meta["title"],
      "course":meta["course"],"post_time":meta["post_time"],"surface":meta["surface"],"distance_m":meta["distance_m"],
      "weather":meta["weather"],"track_condition":meta["track_condition"],"source_url":url,"source_name":"netkeiba・非公式取得",
      "runner_count":len(runners),"top5":runners[:5],"runners":runners}
    key=str(rid)
    if key not in snaps:
     pick=next((h for h in runners if h["prediction_rank"]==1),None)
     snaps[key]={"race_id":key,"kind":race["kind"],"race_date":race["race_date"],"race_name":race["race_name"],
      "course":race["course"],"post_time":race["post_time"],"source_url":url,"snapshot_at":NOW.isoformat(),
      "predicted_horse_no":pick.get("horse_no") if pick else None,"predicted_horse":pick.get("horse") if pick else None,
      "predicted_rankings":[{"horse_no":h.get("horse_no"),"horse":h.get("horse"),"rank":h.get("prediction_rank"),"odds_at_prediction":h.get("odds")} for h in runners],
      "predicted_odds":pick.get("odds") if pick else None,"result_status":"PENDING","predicted_finish_position":None,
      "paper_bets":{"win":{"placed":bool(pick and pick.get("horse_no") is not None and pick.get("odds") and pick["odds"]>=1),"horse_no":pick.get("horse_no") if pick else None,"stake_yen":UNIT,"odds_at_prediction":pick.get("odds") if pick else None,"hit":None,"return_yen":None},
                    "place":{"placed":bool(pick and pick.get("horse_no") is not None),"horse_no":pick.get("horse_no") if pick else None,"stake_yen":UNIT,"hit":None,"return_yen":None}}}
    # Result parser is conservative. Only settle when the predicted horse is explicitly matched.
    try:
     result_html=get(f'{source["base"]}/race/result.html?race_id={rid}')
     positions=parse_positions(result_html,race); snap=snaps[key]
     pick_no=snap.get("predicted_horse_no"); finish=positions.get(str(pick_no)) if pick_no is not None else None
     if finish is not None:
      snap["finish_positions"]=positions; snap["predicted_finish_position"]=finish; snap["result_status"]="SETTLED"
      win=snap["paper_bets"]["win"]; place=snap["paper_bets"]["place"]
      win["hit"]=finish==1
      # This is an estimate from the frozen prediction-time win odds, not official payout.
      win["return_yen"]=int(round((win.get("odds_at_prediction") or 0)*UNIT)) if win["hit"] else 0
      place["hit"]=finish<=3
      # Place payout is not inferred from win odds; official place payout parser is not implemented.
      place["return_yen"]=None
      snap["settlement_note"]="単勝払戻は予想時オッズによる概算。複勝は公式払戻未取得のため収支未確定。"
    except Exception: pass
    races.append(race)
   except Exception as e: errors.append(f"{rid}: {type(e).__name__}: {e}")
   time.sleep(1.3)
 hist["updated_at"]=NOW.isoformat(); st=stats(snaps); hist["stats"]=st; save(HISTORY,hist)
 settled=[x for x in snaps.values() if x.get("result_status")=="SETTLED"][-100:]
 data={"site":"BAGEN KEIBA","schema_version":2,"generated_at":NOW.isoformat(),"race_date":NOW.strftime("%Y-%m-%d"),
  "status":"OK" if races else "NO_DATA","source_policy":"Unofficial public-page scraping. No paid API or live betting integration.",
  "data_note":"オッズ・人気による簡易予想で、実証済みAI勝率ではありません。予想時点の順位は初回取得時に固定します。複勝の公式払戻金は未取得のため収支に推測値を使いません。",
  "race_count":len(races),"races":sorted(races,key=lambda r:(0 if r["kind"]=="中央" else 1,r.get("post_time") or "99:99",r.get("race_no") or 99)),
  "errors":errors[-30:],"history_count":len(snaps),"paper_betting":{"unit_yen":UNIT,"types":["単勝","複勝"],"real_money":False,"stats":st,"history":settled}}
 save(OUT,data); print(f"BAGEN: {len(races)} races; {len(snaps)} snapshots; {len(errors)} warnings")
 for e in errors[-10:]: print("WARNING:",e)
if __name__=="__main__": main()
