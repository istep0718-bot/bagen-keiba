#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v34.11_EXPERT
無料GitHub Actions向け・紙上検証専用。実際の馬券購入・口座接続は行わない。
history.json の snapshots / stats / horse_form_cache / people_cache を維持する。

改善点 (v34.11):
- 会場名マッピング NAR_CODES の誤りを修正（ユーザー友人の指摘で発覚、
  2026-11-02 に nar.netkeiba 公式の競馬場ページ jyo_cd で全場を実地照合）。
  旧表は南関東が1つずつずれる等、体系的に誤っていた:
  30=帯広→門別（帯広ばんえいは 65）、42=大井→浦和、43=川崎→船橋、
  54=姫路→高知、55=高知→佐賀。未確認コード（37-41,49,52,53,56）は
  誤表示を避けるため削除し、未知コードは「競馬場未取得」に倒す。
  会場名は表示だけでなく、騎手の場別成績（course_splits は開催名テキスト
  由来で正しい名前）との突合や場×時間帯オカルト傾向・枠順バイアスの
  集計キーにも使われるため、選定の精度にも関わる修正。
- 履歴スナップショットに焼き付いた旧会場名を、起動時に race_id から
  再計算して自己修復する（repair_snapshot_venues）。精算金額・着順・
  買い目には一切触れない。選定ロジック・スコア・信頼度・配分・
  ゲート・グレード条件は 34.10 から無変更。

改善点 (v34.10):
- オカルト枠を「3連単狙いのみ」に仕様変更（ユーザー指示）。34.9 の
  単勝100円仮定の別枠計測は計測実績ゼロの段階で置き換える。
  オカルトは引き続き選定・スコア・信頼度・配分（夢枠含む）・ゲート・
  グレードには一切混ぜない別枠計測のまま。
- オカルト買い目（3連単のみ・2点）: occult_pick があるレースだけを
  対象に [注目馬→本命→対抗] と [注目馬→対抗→本命] の2点（各100円、
  合計200円/レース）。注目馬が本命/対抗と重なる場合は、注目馬を除いた
  予想上位2頭を相手にする（3頭は全て異なる組み合わせ）。
  レース dict とスナップショットに occult_trifecta として保存する。
- 精算は夢枠と同じ経路: 結果ページの払戻表から得た payouts["trifecta"]
  を精算時点（fetch_and_settle_result）で照合し、結果を
  occult_settlement としてスナップショットに保存する。
  着順一致でも払戻が確認できない場合は収支集計から除外する
  （本体の精算と同じ厳密さ）。
- 集計の作り替え: stats["occult_track"] を3連単仕様にする
  {races, hits, hit_rate_pct, cost=200×races, return, roi_pct}。
  34.9 の単勝版フィールド（win_hits/place_hits 等）は削除した。
  精算は 34.10 生成分から開始し、遡及再構成はしない。
- occult_pick・occult_numbers・occult_tendency の算出は 34.9 から不変更。

改善点 (v34.9):
- オカルト項目を追加（ユーザー希望）。ただし二本立て方針どおり、選定・
  スコア・信頼度・配分（夢枠含む）・bet_eligible ゲート・グレードには
  一切混ぜず、表示と別枠集計だけに使う。
- 馬番オカルト指数: 精算済み全履歴（paper_betting history と同じ対象）から
  馬番1〜18ごとに実勝ち数とランダム期待値（各レースで 1/出走頭数 の合計）を
  集計し、σ=(実勝ち-期待値)/sqrt(期待値) を stats["occult_numbers"] に保存する。
  発端は 2026-11-01 時点（326レース）で 12番が 24勝/期待11.6 の +3.6σ と
  突出していたこと（1番は 21勝/期待30.8 の -1.8σ）。
- 場×時間帯のオカルト傾向: 競馬場×時間帯（発走時刻で 午前 〜11:59 /
  午後 12:00〜16:59 / ナイター 17:00〜）ごとに同じ集計をし、区分ごとの
  代表（最大σの馬番）を stats["occult_tendency"] に保存する。
  発走時刻が履歴に無いレースはこの集計から除外する。スナップショットに
  post_time を保存するよう追加したため、傾向の集計は 34.9 以降に
  スナップショットが更新されたレースから効き始める。
- オカルト注目馬（occult_pick）: 2サイン制で決める表示専用の注目馬。
  (a) 馬番指数サイン: 出走馬のうち期待値>=5 の馬番の中で最大σの馬
      （最大σ >= +1.0 のときだけ成立）
  (b) 場×時間帯サイン: そのレースの場・時間帯の区分で精算レース数>=15
      かつ代表馬番の σ >= +1.0 のとき、その馬番の馬が成立
  両方ある場合は σ の大きい方を採用し、occult_pick に source
  （"number" / "course_time"）を持たせる。レース dict と
  スナップショットに保存し、サイトで根拠つきバッジ表示する。
- オカルト枠（別枠成績）: 精算時に occult_pick があったレースを
  stats["occult_track"] に夢枠（dream_frame）とは完全に独立に集計する。
  単勝100円の仮定で 1着数・3着以内数を数え、回収は単勝の最終オッズ
  （スナップショットの last_odds）から算出する。オッズ不明のレースは
  cost/return に含めず races/win/place のみ数える。34.9生成分から
  計測開始とし、過去分の遡及再構成はしない。

改善点 (v34.8):
- 「注目レース」にも bet_eligible（ゲート通過＝本精算対象）を必須にした
  （ユーザー決定）。34.7 で超おすすめは厳格化できたが、注目レースは
  実質「データ不足でないレース全部」のままで、2026-11-01 のデータでは
  当日72レース全部が注目以上になり、3段階の看板に意味がなかった。
  そこでグレード最終化を拡張し、bet_eligible が False のレースは
  「注目レース」から最下位グレードへ降格する。最終化の結果、
  「超おすすめ」「注目レース」の両方が bet_eligible=True を必須とする。
- 降格先のラベルは既存の最下位ラベル「データ不足・様子見」に統一する。
  サイト（index.html）はグレードを完全一致文字列で扱う
  （'超おすすめ' / '注目レース' のみバッジ・フィルタ対象で、それ以外は
  無印）ため、新しいラベルを作ると表示・絞り込みから漏れる。
  注意: この統一により、データ不足以外の理由（13頭以上・信頼度100以上・
  オッズ取得率50%未満）でゲート外になったレースも最下位ラベルになる。
  実際のゲート理由は gate_reasons に従来どおり残る。
- 変更はグレード最終化での注目レース降格だけ。選定ロジック、スコア/
  信頼度の計算式、配分、bet_eligible ゲート条件そのもの、34.7 の
  超おすすめ厳格化ルールは変更しない。ゲートは最終化前のグレードで
  判定するため、降格によって bet_eligible / gate_reasons は変わらない。

改善点 (v34.7):
- 「超おすすめ」の付与条件を厳格化（中央・地方共通、種別キャップはしない）:
  34.6 で JRA公式オッズが入った結果、信頼度の「オッズ取得率×15点」
  ボーナスが中央にも効くようになり、2026-11-01 13:39 生成では
  超おすすめが当日28件（うち中央20件）・翌日分と合わせて34件表示に
  膨れた。この状態は「厳選」とは言えないため、従来条件に加えて次の
  全てを満たす場合のみ「超おすすめ」とし、満たさない場合は従来なら
  超おすすめだったレースを「注目レース」に落とす:
  (a) bet_eligible が True（ゲート通過＝本精算対象であること）
  (b) 90 <= race_confidence_score < 100
  (c) 9 <= 出走頭数 <= 12
  根拠は 2026-11-01 の精算データ分析: conf90台は ROI 90.5% で最良の
  バンド、conf90-99＆9-12頭に限ると ROI 101.9%。逆にゲート外
  （データ不足・13頭以上・conf100台）は構造的に悪く、特に conf100台は
  従来ゲートでも除外されるのに表示は超おすすめになり得る不整合が
  あった。閾値は定数 SUPER_RECOMMENDED_* で明示する。
- 変更はグレード最終決定箇所での超おすすめ条件の厳格化のみ。
  選定ロジック、スコア/信頼度の計算式、配分、bet_eligible ゲート条件
  そのものは変更しない（ゲートは「データ不足・様子見」判定で動くため、
  超おすすめ→注目レースの降格ではゲート結果は変わらない）。

改善点 (v34.6):
- 中央（JRA）レースの単勝オッズを JRA公式サイト（www.jra.go.jp、無料）の
  オッズページから取得するようにした。従来は netkeiba のオッズ専用ページが
  JavaScript描画で値を取得できず、中央は全レース odds 未取得（odds_coverage=0）
  のまま「データ不足・様子見」になっていた構造的欠陥への対処。
  取得経路: JRADB accessO.html に固定入口 CNAME（pw15oli00/6D）を POST →
  開催選択ページから対象日の開催 CNAME を辿り → レース選択ページから
  単勝・複勝（馬番順）CNAME を辿り → オッズ表をパースする。
  CNAME 末尾のチェックサムは推測で生成せず、必ず公式ページのリンクから辿る。
- ユーザーの二本立て方針を厳守: オッズは選定に混ぜない。JRAオッズの格納は
  スコア計算・穴選定・買い目生成が全て終わった後に行い、選定結果
  （top5・穴・買い目）は取得前と完全一致させる。格納したオッズは
  odds_coverage / レース信頼度・グレード / bet_eligible ゲート /
  トラック2 post_odds 集計でのみ使う。人気は単勝オッズ順から復元する。
- 取得失敗時は例外で生成全体を落とさず、オッズなし（null）として
  従来動作にフォールバックする（ゲートにより shadow 行きになる）。
- 地方のオッズ取得・配分（パターンA/B）・ゲート条件・集計ロジックは無変更。

改善点 (v34.5):
- 馬の選定ロジック（スコア・本命/対抗/3番手/穴の決定）は無変更。
  オッズを選定に混ぜない（ユーザー方針: オッズなし分析とオッズ判明後の
  分析は別々に集計して比べる二本立て）
- パターンBの配分を S3a（実績ROIシフト）に変更: 単勝200/馬連[本命-対抗]200/
  馬連[本命-3番手]300/3連複[本命軸]400/3連複[穴絡み]200/ワイド[本命-穴]100/
  3連単[夢枠]100 の7点・合計1,500円（夢枠は完全維持、パターンAは無変更）。
  穴絡み額は定数 PATTERN_B_TRIO_OUTSIDER_YEN で保守版（100、その分を
  馬連[本命-3番手] PATTERN_B_QUINELLA_3RD_YEN=400）に切替可能
- bet_eligible ゲート新設（CORE-A相当）: 最終生成時点で
  (a) グレードが「データ不足・様子見」 (b) odds_coverage < 0.5
  (c) 出走頭数 >= 13 (d) race_confidence_score >= 100 のいずれかに該当する
  レースは本精算の対象外とし、shadow（仮想）として精算・別集計する。
  予想・買い目の表示は全レース従来どおり
- 精算レコード（スナップショット）に最終生成時点の race_grade /
  race_confidence_score / odds_coverage / runner_count / kind と
  bet_eligible / gate_reasons を保存（frozen の値で上書きしない）
- トラック2「オッズ判明後の分析」の別集計（選定には使わない）:
  各精算レコードに post_odds（本命の最終単勝オッズと人気順位）を記録し、
  stats["post_odds"] に人気帯別・オッズ帯別・市場乖離の集計
  （本精算/shadow の区分つき）を追加。stats["shadow"] にゲート外の
  件数・投資・回収・ROI・ゲート理由別内訳を追加

改善点 (v34.4):
- 券種別成績の集計を追加: calculate_stats が精算済みレースの買い目明細
  （settled_lines）を券種別（単勝/馬連/3連複/ワイド/3連単）に集計し、
  stats["bet_types"] として出力する（買い目数・的中数・的中率・投資・回収・
  回収率・的中時平均配当）。サイトのトップに「券種別成績」として表示する
- settled_lines を history.json のスナップショットに永続化:
  従来はその日の data.json の races にしか残らず、翌日以降は券種別集計が
  できなかった。スナップショット構築時に新しい精算明細があればそれを、
  なければ旧スナップショットのものを引き継ぐよう変更
- パターンBに「夢枠」として 3連単 [本命→穴→対抗] ¥100 を復活（34.2以前と
  同じ並び）。これにより v34.3 の「6点・合計1,400円」は v34.4 で
  「7点・合計1,500円」に上書きされる。他の6点の配分とパターンAは無変更で、
  精算ロジックにも変更なし
- 夢枠の「見える化」: calculate_stats に stats["dream_frame"]（挑戦回数・
  的中数・的中率・投資/回収/回収率・最大配当・的中レース一覧）を追加し、
  サイトのトップに夢枠専用カードを表示する

改善点 (v34.3):
- パターンBの買い目配分を V2（コア集中）に見直し: 精算明細の券種別集計で
  最悪だった馬連[本命-穴]（回収率34.1%）・3連単（43.7%）・ワイド[対抗-穴] を廃止し、
  単勝400/馬連[本命-対抗]300/馬連[本命-3番手]200/3連複[本命軸]300/
  3連複[穴絡み]100/ワイド[本命-穴]100 の6点・合計1,400円に再配分。
  同一90レースのバックテストで回収率 74.7%→83.8%（黒字化ではなく負け幅の圧縮。
  効果の判定は今後の紙上実績で継続する）

改善点 (v34.2):
- 調教師（厩舎）: 出馬表の調教師名・IDを取得し、db.netkeiba の近走一覧（最大30走）から
  厩舎の直近3着内率を集計。好調な厩舎のみ加点・不振は減点（実績が取れた場合のみ）
- 枠順: 自身の精算済みスナップショットから競馬場別の内枠/外枠 3着内率を算出
  （枠番は頭数と馬番から標準枠組表で復元）。サンプル25レース以上かつ内/外の差が
  8ポイント以上の場だけ ±0.5点 を適用する
- 騎手適性: 騎手の近走一覧から直近3着内率と当該コース別成績を集計し、
  合計最大+0.75点まで加点・不振は減点。従来の is_top_jockey（常に False の死にフラグ）は
  取得した実績から算出するよう置換
- 調教師・騎手の取得は馬ページと同じ 14日キャッシュ＋実行あたり上限
  (MAX_NEW_PEOPLE_FETCHES) で保護する

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
ENGINE_VERSION = "BAGEN_34.11_EXPERT"
MAX_NEW_FORM_FETCHES = 24
FORM_FETCHED_THIS_RUN = 0
HORSE_FORM_CACHE = {}
# v34.2: 調教師・騎手の人物データ（馬と同一方式: 14日キャッシュ＋実行あたり上限）
MAX_NEW_PEOPLE_FETCHES = 24
PEOPLE_FETCHED_THIS_RUN = 0
PEOPLE_CACHE = {}
# v34.2: 競馬場別 枠順バイアス（main でスナップショットから算出して保持）
VENUE_FRAME_BIAS = {}
# v34.9: 馬番オカルト指数 {馬番: {num, wins, expected, sigma}} と
# 場×時間帯傾向 {"場名|時間帯": {races, best}}（main でスナップショットから
# 算出して保持。表示・別枠集計専用で、選定には使わない）
OCCULT_NUMBER_INDEX = {}
OCCULT_TENDENCY = {}
TIMEOUT = (10, 25)
DELAY = 0.35
MAX_WARNINGS = 150
MAX_RACES_PER_SOURCE = 100
RETENTION_DAYS = 180
PAPER_BUDGET_YEN = 2000
# v34.5: パターンB配分（S3a）の切替可能定数。合計は常に ¥1,500 になる組で使うこと。
#   標準版: 穴絡み200 / 馬連[本命-3番手]300
#   保守版: 穴絡み100 / 馬連[本命-3番手]400（3連複[穴絡み]の増額寄与が不確実なため）
PATTERN_B_TRIO_OUTSIDER_YEN = 200
PATTERN_B_QUINELLA_3RD_YEN = 300
# v34.5: bet_eligible ゲート（CORE-A相当）の閾値
BET_GATE_MIN_ODDS_COVERAGE = 0.5
BET_GATE_MAX_RUNNERS = 13          # 出走頭数がこれ以上は対象外
BET_GATE_MAX_CONFIDENCE = 100      # race_confidence_score がこれ以上は対象外
# v34.7: 「超おすすめ」の追加厳格条件（従来条件に加えて全て満たすこと。
# 根拠は 2026-11-01 分析: conf90台 ROI 90.5%、conf90-99＆9-12頭で 101.9%、
# ゲート外・conf100台・13頭以上は構造的に悪い。詳細は冒頭ドキュメント参照）
SUPER_RECOMMENDED_MIN_CONFIDENCE = 90     # 信頼度の下限（含む）
SUPER_RECOMMENDED_MAX_CONFIDENCE = 100    # 信頼度の上限（含まない）
SUPER_RECOMMENDED_MIN_RUNNERS = 9         # 出走頭数の下限（含む）
SUPER_RECOMMENDED_MAX_RUNNERS = 12        # 出走頭数の上限（含む）
# v34.9: オカルト項目の閾値（表示・別枠集計専用。選定・スコア・信頼度・
# 配分・ゲート・グレードには一切使わない）
OCCULT_MIN_EXPECTED = 5.0        # 馬番指数サイン: 期待値がこれ未満の馬番はサンプル不足として扱わない
OCCULT_MIN_SIGMA = 2.0           # サイン（馬番指数・場×時間帯 共通）を立てるσの下限（+1.0では9番等でほぼ全レースに付着し看板が薄まるため、親レビューで+2.0に厳格化）
OCCULT_TENDENCY_MIN_RACES = 15   # 場×時間帯サイン: 区分の精算レース数がこれ以上で有効
OCCULT_TENDENCY_MIN_EXPECTED = 1.0  # 場×時間帯の代表馬番は期待値がこれ以上の馬番から選ぶ（高馬番の低期待値ノイズ除け）
OCCULT_STAKE_YEN = 100           # v34.10: オカルト枠3連単の1点あたりの仮定ベット額（2点で200円/レース）

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
# v34.11: nar.netkeiba 公式の競馬場ページ（jyo_cd）で全場を実地照合した表。
# 旧表は 30=帯広（実際は門別、帯広ばんえいは65）・42=大井（実際は浦和）・
# 43=川崎（実際は船橋）・54=姫路（実際は高知）・55=高知（実際は佐賀）と
# 体系的に誤っていた。未確認のコードは誤表示を避けるため入れない。
NAR_CODES = {
    "30": "門別", "35": "盛岡", "36": "水沢",
    "42": "浦和", "43": "船橋", "44": "大井", "45": "川崎",
    "46": "金沢", "47": "笠松", "48": "名古屋",
    "50": "園田", "51": "姫路", "54": "高知", "55": "佐賀",
    "65": "帯広",
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


def repair_snapshot_venues(snapshots):
    """v34.11: 旧 NAR_CODES の誤りで履歴スナップショットに焼き付いた
    会場名を race_id から再計算して直す。表示と場別集計（枠順バイアス・
    場×時間帯オカルト傾向）の是正のみで、精算金額・着順・買い目には
    一切触れない。"""
    fixed = 0
    for snap in (snapshots or {}).values():
        if not isinstance(snap, dict):
            continue
        rid = snap.get("race_id")
        kind = snap.get("kind")
        if not rid or kind not in ("中央", "地方"):
            continue
        venue = venue_from_id(rid, kind)
        if not venue:
            continue
        old = snap.get("course") or ""
        if old == venue:
            continue
        snap["course"] = venue
        name = snap.get("name") or ""
        if old and old != "競馬場未取得" and name.startswith(old):
            snap["name"] = venue + name[len(old):]
        elif old == "競馬場未取得" and snap.get("race_no"):
            snap["name"] = f"{venue}{snap['race_no']}R"
        fixed += 1
    if fixed:
        print(f"[INFO] venue repair: {fixed} snapshots fixed")
    return fixed


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


def normalize_going(text):
    """v34.1: 馬場表記を完全表記に正規化する。
    netkeiba（特に地方 nar）は馬場を1文字に略記する（稍→稍重、不→不良）。
    テキスト中に馬場表記が見つからなければ空文字を返す。"""
    t = clean(text)
    if not t:
        return ""
    m = re.search(r"(稍重|不良|稍|不|良|重)", t)
    if not m:
        return ""
    return {"稍": "稍重", "不": "不良"}.get(m.group(1), m.group(1))


def going_group(going):
    """v34.1: 馬場状態をグループ分類する。良=firm、稍重=yielding、重・不良=soft。
    略記・完全表記のどちらでも分類できる。判定不能なら None。"""
    g = normalize_going(going)
    if g == "良":
        return "firm"
    if g == "稍重":
        return "yielding"
    if g in ("重", "不良"):
        return "soft"
    return None


def parse_weather_going(meta):
    m = re.search(r"天候\s*[:：]?\s*(小雨|小雪|晴|曇|雨|雪)", meta)
    weather = m.group(1) if m else ""
    # v34.1: 略記（稍/不）も受け付けて完全表記へ正規化する。
    # alternation は完全表記（稍重・不良）を略記より先に置くこと
    m = re.search(r"馬場\s*[:：]?\s*(稍重|不良|稍|不|良|重)", meta)
    going = m.group(1) if m else ""
    going = {"稍": "稍重", "不": "不良"}.get(going, going)
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


# ---------------------------------------------------------------------------
# v34.6: JRA公式サイト（www.jra.go.jp）からの中央単勝オッズ取得
# JRADB の CNAME 末尾にはチェックサムがあり推測生成できないため、固定入口
# （オッズ開催選択 pw15oli00/6D）から公式ページの doAction リンクを辿る。
# 選定には一切使わない: 格納は parse_race の選定完了後に行う（後述）。
# ---------------------------------------------------------------------------
JRA_ODDS_URL = "https://www.jra.go.jp/JRADB/accessO.html"
JRA_ODDS_TOP_CNAME = "pw15oli00/6D"
_JRA_ODDS_CACHE = {}


def _post_jra_odds(cname):
    """JRADB accessO.html へ CNAME を POST し、cp932 デコード済み HTML を返す。
    接続系の失敗のみ最大2回まで再試行し、最終失敗時は例外を出さず "" を返す
    （get_html と同じフォールバック方針）。"""
    last_error = None
    for attempt in range(3):
        try:
            r = SESSION.post(JRA_ODDS_URL, data={"cname": cname}, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "cp932"
            body = r.text
            if len(body) < 100:
                warn(f"JRAオッズ: HTMLが空または短すぎます: {cname}")
                return ""
            low = body.lower()
            if any(x in low for x in ["アクセス制限", "アクセスが集中",
                                       "too many requests", "captcha",
                                       "パラメータエラー"]):
                warn(f"JRAオッズ: 取得不可の応答: {cname}")
                return ""
            time.sleep(DELAY)
            return body
        except requests.RequestException as e:
            last_error = e
            if attempt < 2:
                time.sleep(2.0)
    warn(f"JRAオッズ: HTTP取得失敗: {cname} ({type(last_error).__name__})")
    return ""


def _jra_doaction_cnames(page):
    """JRADB ページ内の doAction('/JRADB/accessO.html', 'CNAME') を出現順に返す。"""
    found = []
    for m in re.finditer(
            r"doAction\('/JRADB/accessO\.html',\s*'([^']+)'\)", page or ""):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def _jra_holding_date(cname):
    """開催 CNAME から日付（YYYYMMDD）を返す。
    形式: pw15orl + 区分2 + 場2 + 年4 + 回2 + 日2 + 日付8 + /チェックサム"""
    m = re.fullmatch(r"pw15orl.{2}\d{2}\d{4}\d{2}\d{2}(\d{8})(?:/\w+)?", cname or "")
    return m.group(1) if m else None


def _jra_race_id_from_odds_cname(cname):
    """単勝・複勝（馬番順）CNAME から netkeiba 形式レースID（12桁）を復元する。
    形式: pw151ou + 区分2 + 場2 + 年4 + 回2 + 日2 + レース2 + 日付8 + 'Z' + /チェックサム"""
    m = re.fullmatch(
        r"pw151ou.{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})\d{8}Z(?:/\w+)?",
        cname or "")
    if not m:
        return None
    venue, year, rnd, day, race = m.groups()
    return f"{year}{venue}{rnd}{day}{race}"


def parse_jra_win_odds_page(page):
    """JRA公式 単勝・複勝オッズ（馬番順）ページから 馬番→単勝オッズ を抽出。
    未発売・取消等で数値でないセルは未取得のままにする。"""
    soup = soup_of(page)
    found = {}
    for row in soup.select("tr"):
        num_node = row.select_one("td.num")
        tan_node = row.select_one("td.odds_tan")
        if num_node is None or tan_node is None:
            continue
        no = safe_int(text_of(num_node), 0)
        if not no:
            continue
        val = numeric(text_of(tan_node))
        if val is not None and 0 < val <= 9999:
            found[no] = float(val)
    return found


def fetch_jra_win_odds(date_str):
    """指定日（YYYYMMDD）の中央全レースの単勝オッズ {race_id: {馬番: odds}}。
    実行内キャッシュし、入口→開催→レースの順に公式リンクだけを辿る。
    どの段階で失敗しても例外は出さず、取れた分だけ返す。"""
    if date_str in _JRA_ODDS_CACHE:
        return _JRA_ODDS_CACHE[date_str]
    result = {}
    try:
        top = _post_jra_odds(JRA_ODDS_TOP_CNAME)
        holdings = []
        if top:
            for cname in _jra_doaction_cnames(top):
                if _jra_holding_date(cname) == date_str:
                    holdings.append(cname)
        race_cnames = {}
        for holding in holdings:
            page = _post_jra_odds(holding)
            if not page:
                continue
            for cname in _jra_doaction_cnames(page):
                rid = _jra_race_id_from_odds_cname(cname)
                if rid and rid not in race_cnames:
                    race_cnames[rid] = cname
        for rid, cname in race_cnames.items():
            page = _post_jra_odds(cname)
            if not page:
                continue
            odds_map = parse_jra_win_odds_page(page)
            if odds_map:
                result[rid] = odds_map
    except Exception as e:  # 取得経路の失敗で生成全体を落とさない
        warn(f"JRAオッズ取得で例外: {type(e).__name__}")
    _JRA_ODDS_CACHE[date_str] = result
    return result


def enrich_odds_from_jra_official(runners, rid, date_str):
    """v34.6: 中央レースの単勝オッズ・人気を JRA公式サイトから補完する。
    必ず選定（スコア・穴・買い目）完了後に呼ぶこと。選定には使わない。
    人気は単勝オッズ順（同値は同順位）から復元する。"""
    missing = [h for h in runners if h.get("odds") is None]
    if not missing:
        return {"attempted": False, "status": "出馬表から取得済み", "fetched": 0}
    odds_map = fetch_jra_win_odds(date_str).get(str(rid), {})
    if not odds_map:
        return {"attempted": True, "status": "JRA公式オッズ未取得", "fetched": 0}
    values = list(odds_map.values())
    updated = 0
    for h in missing:
        val = odds_map.get(int(h["horse_no"]))
        if val is None or val <= 0:
            continue
        h["odds"] = float(val)
        if h.get("popularity") is None:
            h["popularity"] = _popularity_rank(float(val), values)
        h.setdefault("data_quality", {})["odds"] = True
        if h.get("popularity") is not None:
            h["data_quality"]["popularity"] = True
        h["odds_source"] = "JRA公式"
        updated += 1
    status = "JRA公式から一部/全部取得" if updated else "JRA公式オッズ未取得"
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
             # v34.1: 馬場グループ別集計の未取得デフォルト
             "going_group_splits": {
                 g: {"starts": 0, "top3": 0, "top3_rate": None, "avg_finish": None}
                 for g in ("firm", "yielding", "soft")},
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
    # v34.1: 馬場グループ別（良=firm/稍重=yielding/重・不良=soft）の集計。
    # 過去走の going_text は完全表記想定だが、略記が来ても going_group が分類する
    _group_rows = {"firm": [], "yielding": [], "soft": []}
    for x in results:
        _grp = going_group(x.get("going_text"))
        if _grp:
            _group_rows[_grp].append(x)

    def _going_split(rows_):
        n = len(rows_)
        t3 = sum(1 for x in rows_ if x["finish"] <= 3)
        return {
            "starts": n, "top3": t3,
            "top3_rate": round(t3 / n, 4) if n else None,
            "avg_finish": (round(sum(x["finish"] for x in rows_) / n, 2)
                           if n else None),
        }

    going_group_splits = {k: _going_split(v) for k, v in _group_rows.items()}
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
        "going_splits": going_splits, "going_group_splits": going_group_splits,
        "course_splits": course_splits,
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


def frame_no_from_field(field_size, horse_no):
    """v34.2: 頭数と馬番から枠番を復元する（標準の枠組表）。
    8頭以下は馬番=枠番。9頭以上は外枠から順に複数頭を割り当てる。"""
    if not field_size or not horse_no:
        return None
    try:
        field_size = int(field_size)
        horse_no = int(horse_no)
    except (ValueError, TypeError):
        return None
    if field_size < 1 or horse_no < 1 or horse_no > field_size:
        return None
    if field_size <= 8:
        return horse_no
    counts = [1] * 8
    remaining = field_size - 8
    idx = 7
    while remaining > 0:
        counts[idx] += 1
        remaining -= 1
        idx = idx - 1 if idx > 0 else 7
    no = 1
    for frame, cnt in enumerate(counts, 1):
        for _ in range(cnt):
            if no == horse_no:
                return frame
            no += 1
    return None


def compute_frame_bias(snapshots):
    """v34.2: 精算済みスナップショットから競馬場別の枠順バイアスを算出する。
    内枠（1・2枠）と外枠（7・8枠）の 3着内率（着内数/出走数）を比較し、
    サンプル25レース以上かつ差が8ポイント以上の場にだけ direction を立てる。"""
    venues = {}
    for snap in (snapshots or {}).values():
        if not isinstance(snap, dict) or snap.get("settlement_complete") is not True:
            continue
        venue = snap.get("course")
        field = snap.get("runner_count")
        finishes = snap.get("result_finishes") or []
        if not venue or not field or len(finishes) < 3:
            continue
        try:
            field = int(field)
        except (ValueError, TypeError):
            continue
        if field < 5:
            continue
        entry = venues.setdefault(venue, {
            "races": 0, "inner_starters": 0, "inner_top3": 0,
            "outer_starters": 0, "outer_top3": 0})
        entry["races"] += 1
        # 出走頭数は枠組表から内/外の定員を数える
        for no in range(1, field + 1):
            fr = frame_no_from_field(field, no)
            if fr in (1, 2):
                entry["inner_starters"] += 1
            elif fr in (7, 8):
                entry["outer_starters"] += 1
        for no in finishes[:3]:
            fr = frame_no_from_field(field, no)
            if fr in (1, 2):
                entry["inner_top3"] += 1
            elif fr in (7, 8):
                entry["outer_top3"] += 1
    result = {}
    for venue, e in venues.items():
        inner_rate = (e["inner_top3"] / e["inner_starters"]
                      if e["inner_starters"] else None)
        outer_rate = (e["outer_top3"] / e["outer_starters"]
                      if e["outer_starters"] else None)
        direction = None
        if (e["races"] >= 25 and inner_rate is not None and outer_rate is not None):
            diff = inner_rate - outer_rate
            if diff >= 0.08:
                direction = "inner"
            elif diff <= -0.08:
                direction = "outer"
        result[venue] = {
            "races": e["races"],
            "inner_starters": e["inner_starters"], "inner_top3": e["inner_top3"],
            "outer_starters": e["outer_starters"], "outer_top3": e["outer_top3"],
            "inner_top3_rate": round(inner_rate, 4) if inner_rate is not None else None,
            "outer_top3_rate": round(outer_rate, 4) if outer_rate is not None else None,
            "direction": direction,
        }
    return result


def person_id_from_link(row, kind):
    """出馬表行の人物リンクから netkeiba 人物IDを抽出する。取れなければ ''。"""
    a = row.select_one(f"a[href*='/{kind}/']")
    if not a:
        return ""
    href = a.get("href", "")
    m = re.search(rf"/{kind}/(?:result/recent/)?([0-9A-Za-z]+)", href)
    return m.group(1) if m else ""


def parse_trainer(row):
    """v34.2: 出馬表行から調教師名とIDを抽出する。
    JRA・地方とも td.Trainer に「所属 名前」形式で入り、リンク文が名前そのもの。
    取れない場合は ('', '') を返し、推測で埋めない。"""
    pid = person_id_from_link(row, "trainer")
    link = row.select_one("td.Trainer a") or row.select_one("a[href*='/trainer/']")
    if link is not None:
        name = text_of(link)
        if name:
            return clean(name)[:30], pid
    node = get_cell(row, ["td.Trainer", "td[class*='Trainer']", ".Trainer"])
    name = text_of(node)
    if not name:
        return "", pid
    # セル全文が「愛知 服部功」のように所属+名前の場合は名前側（末尾）を残す
    parts = name.split()
    if len(parts) >= 2:
        name = parts[-1]
    return clean(name)[:30], pid


_VENUE_NAMES = sorted(set(JRA_CODES.values()) | set(NAR_CODES.values()),
                      key=len, reverse=True)


def venue_from_holding_text(text):
    """人物近走ページの開催表記（例 '4東京9' / '名古屋'）から競馬場名を取り出す。"""
    t = clean(text)
    for name in _VENUE_NAMES:
        if name in t:
            return name
    return None


def parse_person_recent_page(page):
    """v34.2: db.netkeiba の人物・近走一覧ページ（/trainer|jockey/result/recent/）を解析。
    着順と開催だけをヘッダー名で拾い、最大で表の全行を返す。"""
    soup = soup_of(page)
    for t in soup.select("table"):
        hr = t.select_one("thead tr") or t.select_one("tr")
        if not hr:
            continue
        hs = [re.sub(r"\s+", "", text_of(x))
              for x in hr.find_all(["th", "td"], recursive=False)]
        if not any(re.search(r"着順", h) for h in hs):
            continue
        fi = next((i for i, h in enumerate(hs) if re.search(r"着順", h)), None)
        ki = next((i for i, h in enumerate(hs) if re.search(r"開催", h)), None)
        if fi is None:
            continue
        rows = []
        for tr in t.select("tr"):
            cells = tr.find_all("td", recursive=False)
            if not cells or fi >= len(cells):
                continue
            rank_text = text_of(cells[fi])
            if re.search(r"中止|除外|失格|取消|取止|未出走|競走除外", rank_text):
                continue
            m = re.fullmatch(r"\s*(\d{1,2})\s*", rank_text)
            if not m:
                continue
            finish = int(m.group(1))
            if not 1 <= finish <= 18:
                continue
            venue = venue_from_holding_text(text_of(cells[ki])) if ki is not None and ki < len(cells) else None
            rows.append({"finish": finish, "venue": venue})
        return rows
    return []


def get_person_data(kind, pid):
    """v34.2: 調教師/騎手の近走データを取得する（14日キャッシュ＋実行あたり上限）。
    kind は 'trainer' または 'jockey'。直近最大30走の 3着内率とコース別成績を集計。
    取れない場合は available=False で正直に返す。"""
    global PEOPLE_FETCHED_THIS_RUN
    empty = {"available": False, "starts": 0, "wins": 0, "top3": 0,
             "top3_rate": None, "course_splits": {},
             "source": "人物ID未取得"}
    if not pid:
        return empty
    key = f"{kind}:{pid}"
    cached = PEOPLE_CACHE.get(key)
    if isinstance(cached, dict) and cached.get("checked_at"):
        try:
            checked = datetime.fromisoformat(cached["checked_at"])
            if NOW - checked < timedelta(days=14):
                return cached.get("data", empty)
        except Exception:
            pass
    if PEOPLE_FETCHED_THIS_RUN >= MAX_NEW_PEOPLE_FETCHES:
        return {"available": False, "starts": 0, "wins": 0, "top3": 0,
                "top3_rate": None, "course_splits": {},
                "source": "無料実行時間保護のため今回の取得上限"}
    PEOPLE_FETCHED_THIS_RUN += 1
    base = f"https://db.netkeiba.com/{kind}/result/recent/{pid}"
    rows = parse_person_recent_page(get_html(base))
    if len(rows) >= 20:
        # 1ページ20行のため、30走サンプルに届くよう2ページ目も取る
        rows += parse_person_recent_page(get_html(base + "?page=2"))
    rows = rows[:30]
    if not rows:
        data = {"available": False, "starts": 0, "wins": 0, "top3": 0,
                "top3_rate": None, "course_splits": {},
                "source": "人物近走ページを解析できず"}
    else:
        course_map = {}
        for x in rows:
            if not x.get("venue"):
                continue
            e = course_map.setdefault(x["venue"], {"starts": 0, "top3": 0})
            e["starts"] += 1
            if x["finish"] <= 3:
                e["top3"] += 1
        course_splits = {
            k: {"starts": v["starts"], "top3": v["top3"],
                "top3_rate": round(v["top3"] / v["starts"], 4) if v["starts"] else None}
            for k, v in course_map.items()
        }
        data = {
            "available": True,
            "starts": len(rows),
            "wins": sum(1 for x in rows if x["finish"] == 1),
            "top3": sum(1 for x in rows if x["finish"] <= 3),
            "top3_rate": round(sum(1 for x in rows if x["finish"] <= 3) / len(rows), 4),
            "course_splits": course_splits,
            "source": "db.netkeiba 人物・近走一覧（最大30走）",
        }
    PEOPLE_CACHE[key] = {"checked_at": NOW.isoformat(), "data": data}
    return data


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
        # v34.2: 調教師・騎手の人物データ（IDが取れた場合のみ取得を試みる）
        trainer_name, trainer_id = parse_trainer(row)
        jockey_id = person_id_from_link(row, "jockey")
        trainer_form = get_person_data("trainer", trainer_id)
        jockey_form = get_person_data("jockey", jockey_id)
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
        # v34.2: is_top_jockey は固定リストではなく取得した騎手近走実績から判定する
        topj = bool(jockey_form.get("available")
                    and jockey_form.get("starts", 0) >= 10
                    and (jockey_form.get("top3_rate") or 0) >= 0.40)
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
            # v34.2: 調教師と人物データ
            "trainer": trainer_name or "未取得", "trainer_id": trainer_id or None,
            "jockey_id": jockey_id or None,
            "trainer_form": trainer_form, "jockey_form": jockey_form,
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
                # v34.2: 調教師・人物データの取得状況
                "trainer": bool(trainer_name),
                "trainer_form": bool(trainer_form.get("available")),
                "jockey_form": bool(jockey_form.get("available")),
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
    # v34.2: 調教師・人物データの取得状況
    diagnostic["trainer_count"] = sum(
        1 for x in result if x.get("trainer") and x.get("trainer") != "未取得")
    diagnostic["trainer_form_count"] = sum(
        1 for x in result if x.get("trainer_form", {}).get("available"))
    diagnostic["jockey_form_count"] = sum(
        1 for x in result if x.get("jockey_form", {}).get("available"))
    diagnostic["past_form_count"] = sum(
        1 for x in result if x.get("past_form", {}).get("available"))
    diagnostic["past_form_missing_count"] = len(result) - diagnostic["past_form_count"]
    diagnostic["past_form_status"] = (
        "OK" if result and diagnostic["past_form_missing_count"] == 0
        else ("一部取得" if diagnostic["past_form_count"] else "未取得"))
    return result, diagnostic


def score_runners(runners, surface, venue, going=None, weather=None):
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
            # v34.1: 馬場適性（馬場グループ別: 良=firm/稍重=yielding/重・不良=soft）
            # 得意な馬場は加点、不得意な馬場は減点する。データ不足時は加減点しない
            grp = going_group(going)
            assumed_soft = False
            if grp is None and weather in ("雨", "小雨", "雪"):
                # going未取得でも悪天候なら道悪（soft）想定で抑制評価する。
                # 晴/曇で未取得なら推測で埋めず評価しない
                grp = "soft"
                assumed_soft = True
            if grp:
                ggs = (form.get("going_group_splits") or {}).get(grp) or {}
                g_starts = ggs.get("starts", 0)
                g_top3 = ggs.get("top3", 0)
                g_rate = ggs.get("top3_rate")
                g_label = normalize_going(going) or {
                    "firm": "良", "yielding": "稍重", "soft": "重・不良"}[grp]
                cap = 0.5 if assumed_soft else 0.75
                assumed_note = "（雨天のため道悪想定で評価）" if assumed_soft else ""
                if g_starts >= 2 and g_rate is not None and g_rate >= 0.5:
                    form_score += cap
                    reasons.append(
                        f"{g_label}馬場で{g_starts}走・3着内率"
                        f"{g_rate * 100:.0f}%（+{cap}点）{assumed_note}")
                elif g_starts >= 3 and (g_rate is None or g_rate <= 0.15):
                    form_score -= cap
                    if g_top3 == 0:
                        reasons.append(
                            f"{g_label}馬場で{g_starts}走・3着内なし"
                            f"（-{cap}点）{assumed_note}")
                    else:
                        reasons.append(
                            f"{g_label}馬場で{g_starts}走・3着内率"
                            f"{g_rate * 100:.0f}%と低く不得意"
                            f"（-{cap}点）{assumed_note}")
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
        # v34.2: 調教師（厩舎）の近況。実績が取れた場合のみ加減点する
        tf = h.get("trainer_form") or {}
        if tf.get("available"):
            t_starts = tf.get("starts", 0)
            t_rate = tf.get("top3_rate")
            if t_rate is not None and t_starts >= 10:
                if t_rate >= 0.45:
                    form_score += 0.75
                    reasons.append(
                        f"厩舎（{h.get('trainer', '')}）の直近{t_starts}走で3着内率"
                        f"{t_rate * 100:.0f}%と好調（+0.75点）")
                elif t_rate >= 0.35:
                    form_score += 0.5
                    reasons.append(
                        f"厩舎（{h.get('trainer', '')}）の直近{t_starts}走で3着内率"
                        f"{t_rate * 100:.0f}%（+0.5点）")
                elif t_starts >= 15 and t_rate <= 0.10:
                    form_score -= 0.5
                    reasons.append(
                        f"厩舎（{h.get('trainer', '')}）の直近{t_starts}走で3着内率"
                        f"{t_rate * 100:.0f}%と不振（-0.5点）")
        # v34.2: 騎手適性（近況＋当該コース実績）。加点は合計+0.75点まで
        jf = h.get("jockey_form") or {}
        if jf.get("available"):
            j_points = 0.0
            j_starts = jf.get("starts", 0)
            j_rate = jf.get("top3_rate")
            if j_rate is not None and j_starts >= 10 and j_rate >= 0.40:
                j_points += 0.5
                reasons.append(
                    f"騎手の直近{j_starts}走で3着内率{j_rate * 100:.0f}%と好調（+0.5点）")
            if venue:
                js = (jf.get("course_splits") or {}).get(venue) or {}
                if js.get("starts", 0) >= 5 and (js.get("top3_rate") or 0) >= 0.50:
                    j_points += 0.5
                    reasons.append(
                        f"騎手の{venue}コース実績{js['starts']}走で3着内率"
                        f"{js['top3_rate'] * 100:.0f}%（+0.5点）")
            if j_points > 0.75:
                j_points = 0.75
                reasons.append("騎手適性の加点は上限+0.75点に制限")
            form_score += j_points
            if (j_points == 0 and j_rate is not None
                    and j_starts >= 15 and j_rate <= 0.10):
                form_score -= 0.5
                reasons.append(
                    f"騎手の直近{j_starts}走で3着内率{j_rate * 100:.0f}%と不振（-0.5点）")
        # v34.2: 枠順バイアス（競馬場別の履歴集計で有意な差がある場のみ）
        fb = VENUE_FRAME_BIAS.get(venue) if venue else None
        if fb and fb.get("direction"):
            inner_rate = fb.get("inner_top3_rate") or 0
            outer_rate = fb.get("outer_top3_rate") or 0
            if fb["direction"] == "inner":
                if h.get("is_inner"):
                    form_score += 0.5
                    reasons.append(
                        f"{venue}は内枠有利（内枠3着内率{inner_rate * 100:.0f}% vs "
                        f"外枠{outer_rate * 100:.0f}%・{fb['races']}レース集計）で内枠（+0.5点）")
                elif h.get("is_outer"):
                    form_score -= 0.5
                    reasons.append(
                        f"{venue}は内枠有利（内枠3着内率{inner_rate * 100:.0f}% vs "
                        f"外枠{outer_rate * 100:.0f}%・{fb['races']}レース集計）だが外枠（-0.5点）")
            else:
                if h.get("is_outer"):
                    form_score += 0.5
                    reasons.append(
                        f"{venue}は外枠有利（外枠3着内率{outer_rate * 100:.0f}% vs "
                        f"内枠{inner_rate * 100:.0f}%・{fb['races']}レース集計）で外枠（+0.5点）")
                elif h.get("is_inner"):
                    form_score -= 0.5
                    reasons.append(
                        f"{venue}は外枠有利（外枠3着内率{outer_rate * 100:.0f}% vs "
                        f"内枠{inner_rate * 100:.0f}%・{fb['races']}レース集計）だが内枠（-0.5点）")
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


def evaluate_bet_gate(race_grade, odds_coverage, runner_count, confidence_score):
    """v34.5: 紙上ベット対象ゲート（CORE-A相当）。最終生成時点の値で判定する。
    戻り値は (bet_eligible, gate_reasons)。選定・表示には一切影響しない。"""
    reasons = []
    if race_grade == "データ不足・様子見":
        reasons.append("データ不足・様子見")
    if odds_coverage is not None and odds_coverage < BET_GATE_MIN_ODDS_COVERAGE:
        reasons.append("オッズ取得率50%未満")
    if runner_count is not None and runner_count >= BET_GATE_MAX_RUNNERS:
        reasons.append("13頭以上")
    if confidence_score is not None and confidence_score >= BET_GATE_MAX_CONFIDENCE:
        reasons.append("信頼度100以上")
    return (not reasons), reasons


def finalize_super_recommendation(race_grade, bet_eligible, confidence_score,
                                  runner_count):
    """v34.7: 「超おすすめ」の厳格化。従来条件で超おすすめになったレースでも、
    追加条件（ゲート通過・信頼度90台・9〜12頭）を全て満たさなければ
    「注目レース」に落とす。それ以外のグレードはそのまま返す。
    根拠: 2026-11-01 分析で conf90台 ROI 90.5%（最良バンド）、
    conf90-99＆9-12頭で 101.9%。ゲート外・conf100台・13頭以上は構造的に
    悪く、conf100台はゲートで除外されるのに超おすすめ表示になり得る
    不整合もあった。ゲート条件そのものは evaluate_bet_gate 側で不変。"""
    if race_grade != "超おすすめ":
        return race_grade
    if (bet_eligible
            and confidence_score is not None
            and SUPER_RECOMMENDED_MIN_CONFIDENCE <= confidence_score < SUPER_RECOMMENDED_MAX_CONFIDENCE
            and runner_count is not None
            and SUPER_RECOMMENDED_MIN_RUNNERS <= runner_count <= SUPER_RECOMMENDED_MAX_RUNNERS):
        return "超おすすめ"
    return "注目レース"


def finalize_recommended_grade(race_grade, bet_eligible):
    """v34.8: 「注目レース」にもゲート通過を必須にする。bet_eligible が
    False のレースは「注目レース」から最下位グレードへ降格する。
    finalize_super_recommendation の後に適用し、最終的に「超おすすめ」
    「注目レース」の両方が bet_eligible=True を必須とする形にする。
    降格先は既存の最下位ラベル「データ不足・様子見」に統一する
    （サイトはグレードを完全一致文字列で扱い、新ラベルは表示・絞り込み
    から漏れるため）。データ不足以外のゲート理由（13頭以上・信頼度
    100以上・オッズ取得率50%未満）でも同じラベルになるが、実際の理由は
    gate_reasons に残る。ゲート判定は最終化前のグレードで行うため、
    この降格で bet_eligible / gate_reasons は変わらない。"""
    if race_grade == "注目レース" and not bet_eligible:
        return "データ不足・様子見"
    return race_grade


def build_tickets(ranked, outsiders, verified):
    if not verified or len(ranked) < 3:
        return []
    top = ranked[:5]
    a, b, c = [h["horse_no"] for h in top[:3]]
    d = top[3]["horse_no"] if len(top) >= 4 else c
    outsider = next((h["horse_no"] for h in outsiders if h["horse_no"] not in (a, b, c)), None)
    if outsider is not None:
        # v34.5: 配分を S3a（実績ROIシフト）へ。単勝400→200、馬連[本命-対抗]300→200、
        # 馬連[本命-3番手]200→300、3連複[本命軸]300→400、3連複[穴絡み]100→200。
        # ワイド・夢枠（3連単）は据え置き。合計 ¥1,500 は不変。
        lines = [
            ("win", [a], 200),
            ("quinella", sorted([a, b]), 200),
            ("quinella", sorted([a, c]), PATTERN_B_QUINELLA_3RD_YEN),
            ("trio", sorted([a, b, c]), 400),
            ("trio", sorted([a, b, outsider]), PATTERN_B_TRIO_OUTSIDER_YEN),
            ("wide", sorted([a, outsider]), 100),
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
            "label": f"{names[typ]} {'→'.join(map(str, hs)) if typ == 'trifecta' else '-'.join(map(str, hs))} ({stake}円)",
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
            # v34.10: オカルト3連単も夢枠と同じ払戻表で精算する
            # （結果は occult_settlement としてスナップショットに保存され、
            # calculate_stats が別枠集計する）
            race["occult_settlement"] = settle_occult_trifecta(
                race.get("occult_trifecta") or [], finishes, payouts)
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
    ranked = score_runners(runners, surface, venue, going or None, weather or None)
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
    # v34.6: 中央は選定（スコア・穴・買い目）が全て完了した後に JRA公式
    # オッズを格納する。選定ロジックへは一切渡らない（ユーザーの二本立て
    # 方針）。格納後に odds_count 等を再計算し、odds_coverage / 信頼度 /
    # グレード / bet_eligible ゲート / post_odds 集計が公式オッズで
    # 機能するようにする。
    if kind == "中央":
        jra_odds_diag = enrich_odds_from_jra_official(
            runners, rid, date_iso.replace("-", ""))
        diag["jra_odds_attempted"] = jra_odds_diag["attempted"]
        diag["jra_odds_status"] = jra_odds_diag["status"]
        diag["jra_odds_fetched_count"] = jra_odds_diag["fetched"]
        odds_count = sum(1 for h in runners if h.get("odds") is not None)
        diag["odds_count"] = odds_count
        diag["odds_missing_count"] = len(runners) - odds_count
        diag["odds_status"] = (
            "OK" if runners and odds_count == len(runners)
            else ("一部取得" if odds_count else "未取得"))
        diag["popularity_count"] = sum(
            1 for h in runners if h.get("popularity") is not None)
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
    # v34.5: ベット対象ゲートは最終生成時点の値（この生成の grade/coverage/
    # 頭数/confidence）で判定する。表示・買い目生成には影響しない。
    bet_eligible, gate_reasons = evaluate_bet_gate(
        race_grade, odds_coverage, count, race_confidence)
    # v34.7: 「超おすすめ」は追加条件（ゲート通過・信頼度90台・9〜12頭）を
    # 全て満たす場合に限る。満たさなければ「注目レース」に落とす。
    # ゲートは「データ不足・様子見」判定でのみ grade を見るため、この降格で
    # bet_eligible / gate_reasons は変わらない。信頼度スコア自体も変更しない。
    race_grade = finalize_super_recommendation(
        race_grade, bet_eligible, race_confidence, count)
    # v34.8: 「注目レース」もゲート通過（本精算対象）を必須とする。
    # ゲート外のレースは最下位グレードへ落とし、看板の3段階
    # （超おすすめ/注目レース/データ不足・様子見）に意味を持たせる。
    race_grade = finalize_recommended_grade(race_grade, bet_eligible)
    # v34.9: オカルト注目馬（表示専用）。履歴から算出済みの馬番オカルト指数と
    # 場×時間帯傾向（いずれも main でグローバルに保持）だけから決める。
    # 選定・スコア・買い目・ゲート・グレードには一切影響しない。
    occult_pick = pick_occult_horse(ranked, venue or "競馬場未取得", post)
    # v34.10: オカルト買い目（3連単2点）。注目馬がいるレースだけ生成する。
    occult_trifecta = build_occult_trifecta(ranked, occult_pick)
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
        "odds_coverage": round(odds_coverage, 4),
        "bet_eligible": bet_eligible, "gate_reasons": gate_reasons,
        # v34.9: オカルト注目馬（表示・別枠集計専用。選定には無関係）
        "occult_pick": occult_pick,
        # v34.10: オカルト買い目（3連単2点・各100円の仮定。別枠集計専用）
        "occult_trifecta": occult_trifecta,
        "occult_settlement": None,
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
        return {"schema_version": 29, "snapshots": {}, "stats": {},
                "horse_form_cache": {}, "people_cache": {}}
    try:
        v = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(v, dict):
            raise ValueError("history root not object")
        for k in ("snapshots", "stats", "horse_form_cache", "people_cache"):
            if not isinstance(v.get(k), dict):
                v[k] = {}
        v["schema_version"] = 29
        return v
    except Exception as e:
        warn("history.json読み込み失敗。既存履歴保護のため処理中止: " + type(e).__name__)
        raise


def _popularity_rank(odds, odds_values):
    """単勝オッズの順位（小さい順、同値は同順位）。人気は単勝オッズ順で決まるため、
    人気が未取得の場合の復元に使う。"""
    if odds is None:
        return None
    vals = [v for v in odds_values if isinstance(v, (int, float))]
    if not vals:
        return None
    return 1 + sum(1 for v in vals if v < odds)


def post_odds_from_race(race):
    """v34.5 トラック2: 最終生成のレース dict から本命の単勝オッズと人気順位を取る。
    選定には使わず、集計専用。"""
    horses = race.get("horses", []) or []
    top5 = race.get("top5") or []
    top = top5[0] if top5 else (horses[0] if horses else {})
    honmei_no = top.get("horse_no")
    target = next((h for h in horses if h.get("horse_no") == honmei_no), None)
    if target is None:
        return {"horse_no": honmei_no, "win_odds": None, "popularity": None}
    odds = target.get("odds")
    odds = float(odds) if isinstance(odds, (int, float)) else None
    pop = target.get("popularity")
    if not isinstance(pop, int):
        pop = _popularity_rank(odds, [h.get("odds") for h in horses])
    return {"horse_no": honmei_no, "win_odds": odds, "popularity": pop}


def derive_post_odds(snap):
    """v34.5 トラック2: スナップショットから post_odds を復元する。
    保存済みがあればそれを使い、なければ単勝の買い目（本命）と
    last_odds / last_popularity から組み立てる（34.4以前の履歴用）。"""
    stored = snap.get("post_odds")
    if isinstance(stored, dict) and stored.get("horse_no") is not None:
        return stored
    honmei_no = None
    for ln in snap.get("settled_lines") or []:
        if isinstance(ln, dict) and ln.get("type") == "win" and ln.get("horses"):
            honmei_no = ln["horses"][0]
            break
    if honmei_no is None:
        top5 = (snap.get("frozen_prediction") or {}).get("top5") or []
        if top5 and isinstance(top5[0], dict):
            honmei_no = top5[0].get("horse_no")
    if honmei_no is None:
        return {"horse_no": None, "win_odds": None, "popularity": None}
    last_odds = snap.get("last_odds") or {}
    raw = last_odds.get(str(honmei_no))
    odds = float(raw) if isinstance(raw, (int, float)) else None
    pop = None
    pv = (snap.get("last_popularity") or {}).get(str(honmei_no))
    if isinstance(pv, int):
        pop = pv
    elif odds is not None:
        pop = _popularity_rank(odds, list(last_odds.values()))
    return {"horse_no": honmei_no, "win_odds": odds, "popularity": pop}


# ===== v34.9: オカルト項目（表示・別枠集計専用。選定には使わない） =====

def _occult_settled_rows(snapshots):
    """オカルト集計の対象行: paper_betting history と同じフィルタ
    （精算完了・収支確定・払戻確認済み）のスナップショットだけを返す。"""
    rows = snapshots.values() if isinstance(snapshots, dict) else (snapshots or [])
    out = []
    for snap in rows:
        if not isinstance(snap, dict):
            continue
        if snap.get("settlement_complete") is not True:
            continue
        if snap.get("all_bet_return") is None or snap.get("race_profit") is None:
            continue
        if not snap.get("payout_confirmed", True):
            continue
        out.append(snap)
    return out


def occult_time_band(post_time):
    """発走時刻 "HH:MM" を時間帯に変換する: 午前（〜11:59）/
    午後（12:00〜16:59）/ ナイター（17:00〜）。
    時刻が取得できない場合は None を返し、そのレースは場×時間帯の
    集計・判定の材料にしない。"""
    try:
        hh, mm = map(int, str(post_time).split(":")[:2])
    except (ValueError, AttributeError):
        return None
    t = hh * 60 + mm
    if t < 12 * 60:
        return "午前"
    if t < 17 * 60:
        return "午後"
    return "ナイター"


def compute_occult_numbers(snapshots):
    """v34.9: 馬番オカルト指数。精算済み全履歴から馬番1〜18ごとに
    実勝ち数・ランダム期待値・σ を算出する。期待値は「その馬番が存在する
    レースごとに 1/出走頭数」を合計したもの（全馬が等しく勝つと仮定した
    場合の勝ち数）で、σ = (実勝ち - 期待値) / sqrt(期待値)。
    あくまでオカルト（表示・別枠集計専用）で、選定・スコアには使わない。"""
    wins = {n: 0 for n in range(1, 19)}
    expected = {n: 0.0 for n in range(1, 19)}
    for snap in _occult_settled_rows(snapshots):
        finishes = snap.get("result_finishes") or []
        field = snap.get("runner_count")
        if not finishes or not field:
            continue
        try:
            field = int(field)
            winner = int(finishes[0])
        except (ValueError, TypeError):
            continue
        if field < 1:
            continue
        if winner in wins:
            wins[winner] += 1
        for n in range(1, min(field, 18) + 1):
            expected[n] += 1.0 / field
    out = []
    for n in range(1, 19):
        e = expected[n]
        sigma = (wins[n] - e) / math.sqrt(e) if e > 0 else 0.0
        out.append({
            "num": n,
            "wins": wins[n],
            "expected": round(e, 2),
            "sigma": round(sigma, 2),
        })
    return out


def compute_occult_tendency(snapshots):
    """v34.9: 場×時間帯のオカルト傾向。精算済み履歴を
    「競馬場|時間帯」区分に分け、区分ごとに馬番別の実勝ち vs 期待値（σ）を
    集計し、最もσが高い馬番を代表（best）として返す。
    発走時刻（post_time）が履歴に無いレースはこの集計から除外する
    （34.8以前のスナップショットには post_time が無いため、傾向は
    34.9 以降に更新されたスナップショットから効き始める）。"""
    divisions = {}
    for snap in _occult_settled_rows(snapshots):
        course = snap.get("course")
        band = occult_time_band(snap.get("post_time"))
        finishes = snap.get("result_finishes") or []
        field = snap.get("runner_count")
        if not course or band is None or not finishes or not field:
            continue
        try:
            field = int(field)
            winner = int(finishes[0])
        except (ValueError, TypeError):
            continue
        if field < 1:
            continue
        div = divisions.setdefault(
            f"{course}|{band}", {"races": 0, "wins": {}, "expected": {}})
        div["races"] += 1
        if 1 <= winner <= 18:
            div["wins"][winner] = div["wins"].get(winner, 0) + 1
        for n in range(1, min(field, 18) + 1):
            div["expected"][n] = div["expected"].get(n, 0.0) + 1.0 / field
    out = {}
    for key, div in divisions.items():
        # 代表（best）は期待値が OCCULT_TENDENCY_MIN_EXPECTED 以上の馬番から
        # 選ぶ。頭数の多いレースでしか存在しない高馬番は期待値が極小になり、
        # 1勝だけで σ が跳ね上がるノイズ（例: 期待0.06で1勝 = +3.9σ）を
        # 「熱い馬番」と誤認しないため。該当が無ければ best は None。
        best = None
        for n, e in div["expected"].items():
            if e < OCCULT_TENDENCY_MIN_EXPECTED:
                continue
            w = div["wins"].get(n, 0)
            sigma = (w - e) / math.sqrt(e)
            if best is None or sigma > best["sigma"]:
                best = {"num": n, "wins": w,
                        "expected": round(e, 2), "sigma": round(sigma, 2)}
        out[key] = {"races": div["races"], "best": best}
    return out


def pick_occult_horse(runners, course, post_time):
    """v34.9: レースのオカルト注目馬を2サイン制で決める（表示専用）。
    (a) 馬番指数サイン: 出走馬のうち、馬番指数の期待値が
        OCCULT_MIN_EXPECTED 以上ある馬番の中で σ が最大の馬。
        最大σ が OCCULT_MIN_SIGMA 未満なら不成立。
    (b) 場×時間帯サイン: そのレースの場・時間帯の区分で精算レース数が
        OCCULT_TENDENCY_MIN_RACES 以上かつ代表馬番の σ が
        OCCULT_MIN_SIGMA 以上のとき、その馬番の馬。
    両方ある場合は σ の大きい方を採用する（同点なら (a) を優先）。
    選定・スコア・買い目・ゲート・グレードには一切影響しない。"""
    candidates = []
    # (a) 馬番指数サイン
    best_a = None
    for h in runners or []:
        try:
            no = int(h.get("horse_no"))
        except (TypeError, ValueError):
            continue
        entry = OCCULT_NUMBER_INDEX.get(no)
        if not entry or entry.get("expected", 0.0) < OCCULT_MIN_EXPECTED:
            continue
        if best_a is None or entry["sigma"] > best_a["sigma"]:
            best_a = {"number": no, "name": h.get("name"),
                      "sigma": entry["sigma"], "source": "number"}
    if best_a is not None and best_a["sigma"] >= OCCULT_MIN_SIGMA:
        candidates.append(best_a)
    # (b) 場×時間帯サイン
    band = occult_time_band(post_time)
    if course and band is not None:
        div = OCCULT_TENDENCY.get(f"{course}|{band}")
        best = (div or {}).get("best")
        if (div and div.get("races", 0) >= OCCULT_TENDENCY_MIN_RACES
                and best and best.get("sigma", 0.0) >= OCCULT_MIN_SIGMA):
            for h in runners or []:
                try:
                    no = int(h.get("horse_no"))
                except (TypeError, ValueError):
                    continue
                if no == best["num"]:
                    candidates.append({
                        "number": no, "name": h.get("name"),
                        "sigma": best["sigma"], "source": "course_time"})
                    break
    if not candidates:
        return None
    # σ の大きい方（同点なら先に入れた (a) 馬番指数サインを優先）
    pick = candidates[0]
    for c in candidates[1:]:
        if c["sigma"] > pick["sigma"]:
            pick = c
    return pick


def build_occult_trifecta(ranked, occult_pick):
    """v34.10: オカルト買い目（3連単のみ・2点）を組み立てる。
    注目馬を1着に固定し、相手は予想上位2頭（本命・対抗）。
    注目馬が本命/対抗と重なる場合は、注目馬を除いた予想上位2頭を
    相手に使う（3頭が全て異なる組み合わせにする）。
    注目馬が無い、または相手が2頭揃わない場合は空リスト。"""
    if not isinstance(occult_pick, dict) or occult_pick.get("number") is None:
        return []
    try:
        pno = int(occult_pick["number"])
    except (TypeError, ValueError):
        return []
    partners = []
    for h in ranked or []:
        try:
            no = int(h.get("horse_no"))
        except (TypeError, ValueError, AttributeError):
            continue
        if no == pno:
            continue
        partners.append(no)
        if len(partners) == 2:
            break
    if len(partners) < 2:
        return []
    a, b = partners
    return [[pno, a, b], [pno, b, a]]


def settle_occult_trifecta(combos, finishes, payouts):
    """v34.10: オカルト3連単を夢枠と同じ経路（結果ページの払戻表
    payouts["trifecta"]）で精算する。本体の settle_tickets と同じ厳密さ:
    着順一致でも払戻金額が確認できない場合は的中扱いにせず、
    payout_missing=True として収支集計から除外させる。"""
    result = {"hit": False, "return_yen": 0,
              "payout_per_100": None, "payout_missing": False}
    if not combos or not finishes or len(finishes) < 3:
        return result
    top3 = [int(f) for f in finishes[:3]]
    tri_payouts = (payouts or {}).get("trifecta") or {}
    for combo in combos:
        combo = [int(c) for c in combo]
        if combo != top3:
            continue
        payout = tri_payouts.get(combo_key(combo, True), 0)
        if payout:
            result["hit"] = True
            result["payout_per_100"] = payout
            result["return_yen"] += int(OCCULT_STAKE_YEN / 100 * payout)
        else:
            result["payout_missing"] = True
    return result


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
    # v34.5: 最終生成時点の値を保存する（frozen の値で上書きしない）。
    # odds_coverage はレース側に無い場合のみ last odds 相当から復元する。
    snap_odds_coverage = race.get("odds_coverage")
    if snap_odds_coverage is None:
        _lo = [h.get("odds") for h in race.get("horses", [])]
        _rc = race.get("runner_count") or len(_lo)
        snap_odds_coverage = (
            round(sum(1 for v in _lo if v is not None) / _rc, 4) if _rc else 0.0)
    snap_bet_eligible = race.get("bet_eligible")
    if snap_bet_eligible is None:
        snap_bet_eligible = old.get("bet_eligible")
    snap_gate_reasons = race.get("gate_reasons")
    if snap_gate_reasons is None:
        snap_gate_reasons = old.get("gate_reasons") or []
    snapshot = {
        "race_id": rid, "date": race.get("date"), "kind": race.get("kind"),
        "course": race.get("course"), "race_no": race.get("race_no"),
        # v34.9: 場×時間帯のオカルト傾向集計のために発走時刻も保存する
        "post_time": race.get("post_time"),
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
        "settled_lines": race.get("settled_lines") or old.get("settled_lines") or [],
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
        # v34.5: 最終生成スナップショット（grade/confidence は上の既存キーで
        # 最終値が入る。ここでは coverage・頭数・ゲート・post_odds を追加保存）
        "last_popularity": {str(h.get("horse_no")): h.get("popularity")
                            for h in race.get("horses", [])},
        "post_odds": post_odds_from_race(race),
        # v34.9: オカルト注目馬を保存し、精算後に occult_track へ別集計する
        "occult_pick": race.get("occult_pick"),
        # v34.10: オカルト買い目（3連単2点）とその精算結果を保存する
        "occult_trifecta": race.get("occult_trifecta") or old.get("occult_trifecta") or [],
        "occult_settlement": race.get("occult_settlement") or old.get("occult_settlement"),
        "odds_coverage": snap_odds_coverage,
        "bet_eligible": snap_bet_eligible,
        "gate_reasons": snap_gate_reasons,
        "runner_count": race.get("runner_count"),
        "runner_count_verified": race.get("runner_count_verified"),
        "odds_snapshots": odds_snaps,
        "prediction_created_at": old.get("prediction_created_at") or NOW.isoformat(),
    }
    snapshots[rid] = snapshot


def calculate_stats(snapshots):
    """払戻確認済みの精算完了レースのみ集計。パターンA/B別も算出。
    v34.5: 本精算（bet_eligible が False でないもの）と shadow（ゲート外）を分け、
    shadow は stats["shadow"]、オッズ判明後の分析は stats["post_odds"] に別集計する。
    34.4以前の履歴には bet_eligible が無いため本精算扱いになる
    （ゲートは 34.5 で生成されたレースから効く）。"""
    items = list(snapshots.values())
    settled_all = [
        x for x in items
        if x.get("settlement_complete") is True
        and x.get("all_bet_return") is not None
        and x.get("race_profit") is not None
        and x.get("payout_confirmed", True)
    ]
    # v34.5 トラック2: 各精算レコードに post_odds を記録する（保存済みが
    # なければ last_odds 等から復元。snapshots はそのまま history に保存される）
    for x in settled_all:
        x["post_odds"] = derive_post_odds(x)
    settled = [x for x in settled_all if x.get("bet_eligible") is not False]
    settled_shadow = [x for x in settled_all if x.get("bet_eligible") is False]

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

    def agg_simple(rows):
        stake = sum(safe_int(x.get("cost"), 0) for x in rows)
        ret = sum(safe_int(x.get("all_bet_return"), 0) for x in rows)
        return {
            "races": len(rows),
            "stake_yen": stake,
            "return_yen": ret,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
        }

    # v34.5: shadow（ゲート外）集計。理由別内訳は複数理由の重複カウントあり。
    shadow_by_reason = {}
    for x in settled_shadow:
        for reason in (x.get("gate_reasons") or ["不明"]):
            shadow_by_reason.setdefault(reason, []).append(x)
    shadow_stats = dict(agg(settled_shadow))
    shadow_stats["by_reason"] = {
        reason: agg(rows) for reason, rows in sorted(shadow_by_reason.items())
    }

    # v34.5 トラック2: オッズ判明後の分析（選定には使わない集計専用）
    POP_BANDS = ("1人気", "2-3人気", "4-5人気", "6人気以下", "オッズなし")
    ODDS_BANDS = ("1.0-1.9", "2.0-2.9", "3.0-4.9", "5.0-9.9", "10.0以上", "なし")

    def pop_band(po):
        if not po or po.get("win_odds") is None or po.get("popularity") is None:
            return "オッズなし"
        p = po["popularity"]
        if p <= 1:
            return "1人気"
        if p <= 3:
            return "2-3人気"
        if p <= 5:
            return "4-5人気"
        return "6人気以下"

    def odds_band(po):
        if not po or po.get("win_odds") is None:
            return "なし"
        o = po["win_odds"]
        if o < 2.0:
            return "1.0-1.9"
        if o < 3.0:
            return "2.0-2.9"
        if o < 5.0:
            return "3.0-4.9"
        if o < 10.0:
            return "5.0-9.9"
        return "10.0以上"

    def band_split(rows_all, band_fn, bands):
        out = {}
        for band in bands:
            rows = [x for x in rows_all if band_fn(x.get("post_odds")) == band]
            out[band] = {
                "main": agg_simple(
                    [x for x in rows if x.get("bet_eligible") is not False]),
                "shadow": agg_simple(
                    [x for x in rows if x.get("bet_eligible") is False]),
                "all": agg_simple(rows),
            }
        return out

    def is_divergent(po):
        if not po:
            return False
        return ((po.get("popularity") is not None and po["popularity"] >= 6)
                or (po.get("win_odds") is not None and po["win_odds"] >= 20.0))

    div_rows = [x for x in settled_all if is_divergent(x.get("post_odds"))]
    post_odds_stats = {
        "note": ("精算時点の最終オッズで集計した参考分析。馬の選定には使用していない。"
                 "人気は保存値、無ければ最終オッズ順から復元。"),
        "by_popularity": band_split(settled_all, pop_band, POP_BANDS),
        "by_win_odds": band_split(settled_all, odds_band, ODDS_BANDS),
        "market_divergence": {
            "definition": "本命が6人気以下 または 本命の単勝オッズ20倍以上",
            "main": agg_simple(
                [x for x in div_rows if x.get("bet_eligible") is not False]),
            "shadow": agg_simple(
                [x for x in div_rows if x.get("bet_eligible") is False]),
            "all": agg_simple(div_rows),
        },
    }

    # v34.9: オカルト項目（表示・別枠集計専用。選定には使わない）。
    # 馬番オカルト指数と場×時間帯傾向は精算済み全履歴（shadow 含む）から算出。
    occult_numbers = compute_occult_numbers(settled_all)
    occult_tendency = compute_occult_tendency(settled_all)
    # オカルト枠（v34.10で3連単仕様に作り替え）: occult_trifecta と
    # occult_settlement が保存されている精算レース（34.10生成分から）を
    # 夢枠とは完全に独立に集計する。買い目は注目馬1着固定の3連単2点
    # （各100円＝200円/レース）。払戻は精算時に夢枠と同じ払戻表から
    # 照合済みの occult_settlement を使う。着順一致でも払戻未確認
    # （payout_missing）のレースは、本体の精算と同じく収支集計から
    # 除外する（races にも数えない）。
    occult_track = {
        "races": 0, "hits": 0, "hit_rate_pct": 0.0,
        "cost": 0, "return": 0, "roi_pct": 0.0,
        "note": ("オカルト注目馬を1着固定にした3連単2点（各100円）だけを追う"
                 "別枠計測（夢枠とは独立）。払戻未確認のレースは収支集計から除外。"
                 "34.10生成分から計測開始。"),
    }
    for x in settled_all:
        combos = x.get("occult_trifecta")
        st = x.get("occult_settlement")
        if not combos or not isinstance(st, dict):
            continue
        if st.get("payout_missing"):
            continue
        occult_track["races"] += 1
        occult_track["cost"] += OCCULT_STAKE_YEN * len(combos)
        if st.get("hit") is True:
            occult_track["hits"] += 1
            occult_track["return"] += safe_int(st.get("return_yen"), 0)
    if occult_track["races"]:
        occult_track["hit_rate_pct"] = round(
            occult_track["hits"] / occult_track["races"] * 100, 1)
    if occult_track["cost"]:
        occult_track["roi_pct"] = round(
            occult_track["return"] / occult_track["cost"] * 100, 1)

    win_items = [x for x in settled if x.get("win_hit") is not None]
    win_stake = sum(safe_int(x.get("cost"), 0) for x in win_items)
    win_return = sum(safe_int(x.get("win_return"), 0) for x in win_items)
    all_stake = sum(safe_int(x.get("cost"), 0) for x in settled)
    all_return = sum(safe_int(x.get("all_bet_return"), 0) for x in settled)
    hits = sum(1 for x in settled if safe_int(x.get("all_bet_return"), 0) > 0)
    by_a = [x for x in settled if pattern_of(x) == "A"]
    by_b = [x for x in settled if pattern_of(x) == "B"]
    by_u = [x for x in settled if pattern_of(x) not in ("A", "B")]
    # v34.4: 券種別成績。買い目1点単位で集計し、的中率は hits/lines で算出する
    # （サイト側のランダム目安ベンチマークと比較できるよう買い目ベースに統一）。
    bet_types = {}
    for typ in ("win", "quinella", "trio", "wide", "trifecta"):
        bt_lines = bt_hits = bt_stake = bt_return = 0
        for x in settled:
            for ln in x.get("settled_lines") or []:
                if not isinstance(ln, dict) or ln.get("type") != typ:
                    continue
                bt_lines += 1
                bt_stake += safe_int(ln.get("stake_yen"), 0)
                bt_return += safe_int(ln.get("return_yen"), 0)
                if ln.get("hit") is True:
                    bt_hits += 1
        bet_types[typ] = {
            "lines": bt_lines,
            "hits": bt_hits,
            "hit_rate_pct": round(bt_hits / bt_lines * 100, 2) if bt_lines else 0.0,
            "stake_yen": bt_stake,
            "return_yen": bt_return,
            "roi_pct": round(bt_return / bt_stake * 100, 1) if bt_stake else 0.0,
            "avg_payout_per_hit_yen": round(bt_return / bt_hits) if bt_hits else 0,
        }
    # v34.4: 夢枠（パターンBの3連単¥100）専用集計。3連単は夢枠でのみ買うため、
    # trifecta の買い目がそのまま夢枠の全記録になる。基本数値は bet_types と共通。
    df_base = bet_types["trifecta"]
    df_best = 0
    df_hit_races = []
    for x in settled:
        for ln in x.get("settled_lines") or []:
            if not isinstance(ln, dict) or ln.get("type") != "trifecta":
                continue
            ln_ret = safe_int(ln.get("return_yen"), 0)
            if ln_ret > df_best:
                df_best = ln_ret
            if ln.get("hit") is True:
                df_hit_races.append({
                    "date": x.get("date"),
                    "course": x.get("course"),
                    "race_no": x.get("race_no"),
                    "horses": ln.get("horses") or [],
                    "return_yen": ln_ret,
                })
    df_hit_races.sort(key=lambda r: -safe_int(r.get("return_yen"), 0))
    dream_frame = {
        "lines": df_base["lines"],
        "hits": df_base["hits"],
        "hit_rate_pct": df_base["hit_rate_pct"],
        "stake_yen": df_base["stake_yen"],
        "return_yen": df_base["return_yen"],
        "roi_pct": df_base["roi_pct"],
        "best_payout_yen": df_best,
        "hit_races": df_hit_races[:20],
    }
    return {
        "races_seen": len(items),
        "races_settled": len(settled),
        "races_settled_including_shadow": len(settled_all),
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
        "bet_types": bet_types,
        "dream_frame": dream_frame,
        "shadow": shadow_stats,
        "post_odds": post_odds_stats,
        # v34.9: オカルト項目（表示・別枠集計専用）
        "occult_numbers": occult_numbers,
        "occult_tendency": occult_tendency,
        "occult_track": occult_track,
        "accounting_note": (
            "払戻確認済みの精算済みレースのみ集計。"
            "単勝と全券種の集計対象・金額は別管理。"
            "着順一致のみで払戻未確認のレースは回収率から除外。"
            "パターンA=上位評価中心 / パターンB=穴候補含む。"
            "v34.5: ベット対象ゲート外のレースは本集計から除き shadow に別集計。"
            "post_odds はオッズ判明後の参考分析で、選定には使用していない。"),
    }



# v34.4: settled_lines が保存されていなかった期間（2026-10-28〜31）の埋め戻し。
# 各日の最終版 docs/data.json（GitHub のコミット履歴）から一度だけ補完する。
# 補完済みの日は取得しない。失敗しても警告のみで処理は継続する。
BACKFILL_DATES = ("2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31")


def backfill_settled_lines(snapshots):
    missing = sorted({
        str(x.get("date")) for x in snapshots.values()
        if isinstance(x, dict) and not x.get("settled_lines")
        and str(x.get("date")) in BACKFILL_DATES
    })
    for date in missing:
        try:
            api = ("https://api.github.com/repos/istep0718-bot/bagen-keiba/commits"
                   f"?path=docs/data.json&since={date}T00:00:00%2B09:00"
                   f"&until={date}T23:59:59%2B09:00&per_page=1")
            r = SESSION.get(api, timeout=TIMEOUT)
            r.raise_for_status()
            commits = r.json()
            if not commits:
                continue
            sha = commits[0]["sha"]
            raw = ("https://raw.githubusercontent.com/istep0718-bot/"
                   f"bagen-keiba/{sha}/docs/data.json")
            r2 = SESSION.get(raw, timeout=(10, 60))
            r2.raise_for_status()
            day = r2.json()
        except Exception as e:
            warn(f"settled_lines backfill failed ({date}): {e}")
            continue
        by_id = {
            str(race.get("id")): race.get("settled_lines")
            for race in day.get("races", [])
            if race.get("settled_lines")
        }
        filled = 0
        for rid, snap in snapshots.items():
            if (isinstance(snap, dict) and str(snap.get("date")) == date
                    and not snap.get("settled_lines")
                    and str(rid) in by_id):
                snap["settled_lines"] = by_id[str(rid)]
                filled += 1
        print(f"[BACKFILL] {date}: settled_lines filled for {filled} snapshots")


def main():
    print(f"=== {ENGINE_VERSION} START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")
    history = load_history()
    snapshots = history["snapshots"]
    backfill_settled_lines(snapshots)
    # v34.11: 旧会場マッピングで焼き付いた履歴の会場名を自己修復する
    repair_snapshot_venues(snapshots)
    global HORSE_FORM_CACHE
    HORSE_FORM_CACHE = (
        history.get("horse_form_cache", {})
        if isinstance(history.get("horse_form_cache", {}), dict) else {})
    # v34.2: 人物キャッシュの読み込みと、履歴からの枠順バイアス算出
    global PEOPLE_CACHE, VENUE_FRAME_BIAS
    PEOPLE_CACHE = (
        history.get("people_cache", {})
        if isinstance(history.get("people_cache", {}), dict) else {})
    VENUE_FRAME_BIAS = compute_frame_bias(snapshots)
    # v34.9: 馬番オカルト指数と場×時間帯傾向を履歴から算出する
    # （表示・別枠集計専用。parse_race が occult_pick の判定にだけ使う）
    global OCCULT_NUMBER_INDEX, OCCULT_TENDENCY
    OCCULT_NUMBER_INDEX = {
        e["num"]: e for e in compute_occult_numbers(snapshots)}
    OCCULT_TENDENCY = compute_occult_tendency(snapshots)
    _occult_top = sorted(
        OCCULT_NUMBER_INDEX.values(), key=lambda e: -e["sigma"])[:3]
    print("[INFO] occult_numbers top: " + ", ".join(
        f"{e['num']}番({e['sigma']:+.1f}σ)" for e in _occult_top))
    _hot_divs = [
        k for k, v in OCCULT_TENDENCY.items()
        if v.get("races", 0) >= OCCULT_TENDENCY_MIN_RACES
        and v.get("best") and v["best"]["sigma"] >= OCCULT_MIN_SIGMA]
    print(f"[INFO] occult_tendency divisions={len(OCCULT_TENDENCY)} "
          f"hot={len(_hot_divs)}")
    biased = [f"{v}({'内' if b['direction'] == 'inner' else '外'}有利)"
              for v, b in VENUE_FRAME_BIAS.items() if b.get("direction")]
    print(f"[INFO] frame_bias venues={len(VENUE_FRAME_BIAS)} biased={biased}")
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
        "people_cache": PEOPLE_CACHE,
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
            # v34.2: 人物データと枠順バイアスの取得状況
            "new_people_fetches": PEOPLE_FETCHED_THIS_RUN,
            "people_cache_entries": len(PEOPLE_CACHE),
            "frame_bias": VENUE_FRAME_BIAS,
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
                "穴候補は実オッズ帯と近走成績ベースを分離表示。"
                "v34.2: 調教師・騎手は近走実績が取得できた場合のみ加減点。"
                "枠順は履歴集計で有意な内/外バイアスがある競馬場のみ加減点。"),
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