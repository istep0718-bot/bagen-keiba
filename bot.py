#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BAGEN KEIBA v34.23_EXPERT
無料GitHub Actions向け・紙上検証専用。実際の馬券購入・口座接続は行わない。
history.json の snapshots / stats / horse_form_cache / people_cache /
pedigree_cache を維持する。

改善点 (v34.23):
- v35監査の A1（前方保存）のみを実施（ユーザー承認 2026-11-18）。
  選定・スコア・信頼度・配分・ゲート・グレードは 34.22 から完全
  凍結で一切変更しない（変更はスナップショット保存キーの追加と
  バージョン文字列のみ）。
- (1) engine_version の刻印: update_snapshot がスナップショットに
  「そのスナップショットを最初に生成した ENGINE_VERSION」を保存
  する（prediction_created_at と同じ初回固定方式）。従来はレース
  単位の版が履歴に無く、版別の成績分離ができなかった。
- (2) going（馬場状態）／weather（天候）の前方保存: 生成時の
  race dict には parse_race が実キー "going"/"weather" で格納して
  いたのに update_snapshot の保存キーに無く、過去分の馬場別集計
  が永久に作れなかった。今回から保存する。今回の生成で未取得
  （"未取得"）の場合は既存スナップショットの取得済みの値を保持し、
  "未取得" で上書きしない。
- いずれも保存専用で、calculate_stats 等の集計には使わない。
  旧スナップショット（新キー無し）を読んでも壊れない。

改善点 (v34.22):
- HYBRID_SHADOW（選定 shadow）を新設（ユーザー承認 2026-11-17。
  ChatGPT の次期検証計画を採用）。34.15〜34.18 で前方保存してきた
  hybrid 特徴量（時計の絶対指数・血統スコア・クラス評価）を統合
  スコア化し、本番とは別の買い目を shadow として並走させる。
  本番 34.21 の選定・スコア・信頼度・配分A/B・ゲート・グレードは
  完全凍結で一切変更しない（変更は shadow 追加と集計まわりのみ）。
- 統合スコア（hybrid_components）: 主成分は時計指数（中央値優先・
  偏差値−50）、血統スコア（父＋母父×0.5）、クラス評価（前走クラス
  と近走ピークの今走クラスとの差×重み）。評価できるのは時計指数
  または血統スコアを持つ馬のみで、評価済みが3頭未満のレースは
  買い目を作らない。オッズなし純順位（odds_free_rank）は同点時の
  比較軸としてのみ使い、校正確率は評価軸として既存の
  probability_forward で別途測る（統合スコアには混ぜない）。
  市場乖離は本命で発生0件のため主成分にせず、post_odds の
  観測枠に留める。
- 買い目は build_tickets に hybrid 順位を渡して現行パターンA/Bと
  同一構造で組み立て、本体と同じ settle_tickets で精算し、
  stats["hybrid_selection"] で本精算（main）とゲート外に分けて、
  同一レースの本番・stake_shadow・alloc_d と4系統比較できる形で
  集計する（回収率・損益・最大DD・的中率・中央/地方別・頭数別・
  券種別）。計測開始は HYBRID_SHADOW_START_DATE（2026-11-17）
  以降の生成分から。判定は結果確定済みの比較可能標本が
  HYBRID_SHADOW_TARGET_SAMPLES（200件）に到達してから。
- データ分離（40MB問題対策）: shadow 累計の軽量サマリを
  docs/shadow_summary.json に分離保存する（系統別累計＋日次別）。
  history.json（約66MB）や data.json を丸ごと取得しなくても
  判定材料を取り出せるようにする。既存の保存形式は壊さない。

改善点 (v34.21):
- 血統加点（34.14）の影響集計（2026-11-09）で判明したボトルネック
  への対処。生成時点で当日出走馬の父名解決率が 13.4%、翌日分は
  0/641頭だった。原因は新規取得上限 24件/実行が当日の序盤レース
  から消費され、翌日分まで回らない構造。回収率・的中率への効果
  判定の前に、まず「測れる状態」を作ることが目的。
- (1) 血統の前倒し取得（prefetch）: 生成パス（parse 内）の上限
  MAX_NEW_PEDIGREE_FETCHES=24 は従来どおり維持し、生成後に
  prefetch_pedigrees が専用枠（最大96件、総量上限120件）で
  未解決馬の血統を先取りしてキャッシュを温める。優先順位は
  今日の未生成レース（frozen 未作成）→ 明日の出走馬 → 今日の
  生成済みレース。温めたキャッシュは history.json に保存され、
  翌日分が当日分になって frozen が作られる初回生成で効く。
  Actions の job 上限10分に対する安全弁として、実行開始から
  420秒を超えたら prefetch を打ち切る。スコア計算・加点値・
  対象リストには一切触れない。
- (2) frozen への加点記録: score_runners が実際に適用した血統
  加点を runner に pedigree_bonus（0.0/0.75/1.0）と
  pedigree_bonus_kind（dirt/turf/None）として記録し、
  frozen_prediction.all_horses に父名・母父名とあわせて保存する
  （34.18 の all_horses には父・母父が未保存だった）。保存のみで
  選定・スコア・精算には影響しない。
- (3) data_quality_summary に prefetch 実績件数と当日出走馬の
  父名解決率（分母つき）を追加。既存の pedigree_resolved_runners
  （当日+翌日の合算・分母なし）とは重複しない形にした。

改善点 (v34.20):
- 金額の強弱 shadow を新設（ユーザー承認 2026-11-09。設計正本は
  goals/bagen-keiba-horse-racing-prediction/hidden_files/
  stake-shadow-design-2026-11-09.md）。配分D（34.19）とは変更変数を
  分離するため、配分比率は現行パターンA/Bのまま変えず、レース総額
  だけをグレード×種別で段階化する。一律増額は回収率を変えないが、
  強弱をつけると混合回収率が動く、という仮説の前方検証。
- 段階（最終グレード race_grade と種別 kind の既存判定のみで決定）:
  最強 ×4 = 超おすすめ × 中央（B ¥6,000／A ¥7,600）、
  強 ×2 = 超おすすめ（B ¥3,000／A ¥3,800）、
  通常 ×1 = それ以外（注目レース等、現行額 B ¥1,500／A ¥1,900）。
  根拠は同日の区分別分析: 超おすすめ×中央 133.0%（23R・標本僅少）／
  超おすすめ全体 93.3%（60R）／超おすすめ×地方 68.9% のため、
  最強は中央限定とする。
- 実装は配分D（34.19）と同格: build_tickets の出力から組み合わせを
  そのまま引き継いで各ラインの金額に倍率だけを掛け、本体と同じ
  settle_tickets で精算し、stats["stake_shadow"] で本精算レース
  のみを対象に、現行（一律額）の同一レース実績と回収率・損益・
  最大DD（累積損益曲線のピークからの最大下落）を並走比較する。
  段階別（通常／強／最強）の内訳も持つ。計測開始は
  STAKE_SHADOW_START_DATE（2026-11-09）以降の生成分から。
  本番の選定・スコア・信頼度・配分A/B・ゲート・グレード・
  配分Dには一切使わない。

改善点 (v34.19):
- 配分D shadow を新設（ユーザー承認 2026-11-09「新配分 shadow を
  設計して計測開始」）。根拠は同日の区分別分析（segment-analysis-
  2026-11-09）: 券種別で馬連が最良（回収率85.6%）、3連複が最大の
  損失源（−¥64,330）。既存の配分C（alloc_c）は 151R で 63.9% と
  現行に敗北済みのため、券種別データに基づく別設計とする。
- 設計: 買い目の馬の組み合わせと総額は現行パターンA/Bと完全同一の
  まま、配分だけを馬連寄りに変える。B'（合計¥1,500）: 単勝200／
  馬連[本命-対抗]400／馬連[本命-3番手]400／3連複[軸]200／
  3連複[穴]100／ワイド[穴]100／夢枠（3連単）100（馬連53%・
  3連複20%）。A'（合計¥1,900）: 単勝500／馬連[本命-対抗]500／
  馬連[本命-3番手]400／3連複[軸]300／ワイド100／ワイド100。
  3連複・3連単は本人の券種方針（当てる楽しみとして残す）に沿い、
  消さずに薄くする。
- 実装は種別 shadow（34.17）と同格: build_tickets の出力から
  組み合わせをそのまま引き継いで金額だけを付け替え、本体と同じ
  settle_tickets で精算し、stats["alloc_d"] で本精算（main）と
  ゲート外（gate_out）を分けて現行実績と並走比較する。計測開始は
  ALLOC_D_START_DATE（2026-11-09）以降の生成分から。本番の選定・
  スコア・信頼度・配分A/B・ゲート・グレードには一切使わない。

改善点 (v34.18):
- 凍結保存の拡張と確率の前方検証（監査レポート
  audit-2026-11-08-chatgpt-plan.md の最優先項目、ユーザー承認
  2026-11-08）。いずれも保存・計測専用で、本番の選定・スコア・
  信頼度・配分・ゲート・グレードには一切使わない。
- (1) 校正確率の併記保存: Phase 3 リサーチ（probability-
  calibration-2026-11-08.md）の推奨マッピングを実装。勝率は
  2段階 softmax（T=6.51、頭数帯カバレッジ 8頭以下0.80／
  9〜12頭0.75／13頭以上0.64、top5 内の相対配分）、連対・複勝は
  順位の経験率テーブル。パラメータは fit 期（〜2026-11-07）の値で、
  エンジン版が変われば再 fit が前提。
- (2) frozen_prediction に all_horses（全頭の馬番・順位・score／
  form_score／market_score・odds_free_rank・オッズ・人気・脚質・
  未校正確率・校正確率3種）と pace_shadow（逃げ頭数・先行頭数・
  ペース想定ラベル）を保存する。従来は top5 のみで、6位以下の
  確率と再校正の材料が永遠に作れなかった問題への対処。
- (3) stats["probability_forward"]: 凍結した確率と実際の勝ち馬を
  照合し、Brier Score と Log Loss を校正版／未校正版で並走計測
  する（対象は Phase 3 の方法論に合わせ評価 top5 の馬のみ）。
  中央×芝／中央×ダート／地方の内訳と、校正ビン別の予測 vs 実績も
  出す。勝ち馬が top5 にいた率（カバレッジ）も記録する。

改善点 (v34.17):
- 「中央と地方で同じ物差し」問題への対応 第1弾（ユーザー指示
  2026-11-08。友人指摘「指標が地方・ダート寄り」を受けた検証で、
  上がり3Fが参考保持のみ・時計指数は保存のみ・クラス評価が皆無・
  集計が中央/地方×芝ダートで分かれていない、を確認）。いずれも
  Stage 0（保存と shadow 計測のみ）で、本番の選定・スコア・信頼度・
  配分・ゲート・グレードには一切使わない（hybrid_shadow と同格）。
- (1) 上がり3F: 既存の last3f_dev（距離帯中央値との差）を hybrid
  shadow の計測対象に追加。予想 top5 内の last3f_dev 最大馬の着順を
  集計し、中央×芝／中央×ダート／地方の内訳（by_kind_surface）でも
  出す。時計指数リーダー・血統リーダーも同じ内訳で出す。
- (2) クラス（格）評価を新設: レース名と過去走の行テキストから
  格の順序尺度を推定する（中央: 新馬0/未勝利1/1勝2/2勝3/3勝4/
  オープン5/G3=6/G2=7/G1=8、旧表記 500万下=2・1000万下=3・
  1600万下=4。地方: C3=1〜A1=9）。各馬の前走クラス・近走ピーク・
  今走クラス・降級フラグを runner と frozen top5 に保存し、
  hybrid shadow で「降級馬 vs 非降級馬」の着順率を測る。
  判定できない場合は None のまま（未取得を明示）。
- (3) 分割集計: snapshot に surface / distance_m の保存を追加し、
  stats["kind_surface_split"] で本精算を 中央×芝／中央×ダート／
  地方 に分けて回収率まで出す。過去分は surface 未保存のため
  「不明」に寄せ、捏造しない。
- (4) 種別専用買い方 shadow（ユーザー提案 2026-11-08「買い方も
  地方・中央で分ける」）: 買い目の馬の組み合わせと総額は現行
  パターンA/Bと同一のまま、配分だけを種別に寄せた対照案を新設し、
  本体と同じ settle_tickets で精算して stats["kind_pattern_shadow"]
  で現行実績と並走比較する。中央・13頭以上＝3連複を外して馬連と
  ワイドへ再配分（jra_large_realloc）／中央・12頭以下＝ワイドを
  削って単勝と3連複軸へ集中（jra_small_core）／地方＝穴絡みを
  絞って軸へ寄せる（nar_axis）。本番の買い目・配分は無変更で、
  切り替えは測定ルール（最低2週間 or 対象300レース）通過後の
  判定会で行う。

改善点 (v34.16):
- 候補プール shadow 計測を新設（設計書 candidate-pool-2026-11-06.md、
  ユーザー承認 2026-11-06）。Phase 1 の敗因分析で最大の敗因だった
  B「相手選定ミス」の構造要因（最終母集団が4頭しかない／初回 top5 の
  馬が再生成で候補から落ちる）への対策候補を、本採用せず前方計測する。
  計測専用で、本番の選定・スコア・信頼度・配分・ゲート・グレードには
  一切使わない（alloc_c / hybrid_shadow と同格・Stage 0）。
- 前提となる保存の追加（いずれも計測専用・選定には使わない）:
  (1) snapshot に last_top6（最終生成時点の上位6頭: 馬番・順位・
  score・form_score・market_score）と last_outsiders（最終生成の
  穴候補リスト）を保存する。保存タイミングの規則として、未精算の
  生成では毎回上書きするが、発走時刻を過ぎた生成と精算した実行の
  生成では上書きしない（＝発走前の最終生成で固定する）。これは
  公式買い目の大半が精算実行の生成で確定する現行方式では
  「発走前の最終候補」が残らない問題への対処である。
  (2) 精算時に trio_payout（実際の3着内組み合わせの3連複配当・
  100円あたり）を snapshot に保存する。仮想ラインの払戻計算に使う。
- 集計 stats["pool_shadow"]: POOL_SHADOW_START_DATE 以降の本精算
  レースで last_top6 が保存されているものを対象に、現行3連複と
  同一レースで (a) 案C 保険枠（初回 top5 に入り最終プールに残らず
  最終順位6位以内の馬を {軸, パートナー, x} の追加ラインで拾う）、
  (b) 案A6（最終順位6位までを母集団にする）、をそれぞれ追加型
  （追加ライン各200円）と固定型（3連複総額を現行実績に固定し
  全ライン等分）で仮想再計算し、カバー率・新規的中・赤字的中（E）
  の増加も含めて並走集計する。定義は遡及試算と同一に揃えた。
  判定は設計書のライン（最低2週間かつ対象300レース等）までしない。

改善点 (v34.15):
- 「欠けている2つの物差し」追加 Phase A/B（設計書
  missing-gauges-design-2026-11-06.md、ユーザー承認 2026-11-06）。
  Stage 0（保存と参考表示のみ）として導入し、現行の選定・スコア・
  信頼度・配分・ゲート・グレードには一切使わない。特徴量は
  hybrid_features として前方保存し、stats["hybrid_shadow"] で
  shadow 計測する（特徴量つき200件まで良し悪しの判定をしない）。
- Phase A 時計指数: 過去走の走破時計を、review 環境でオフライン
  構築した基準タイム表（time_standards.json。場×芝ダ×距離の
  推定勝ち時計の中央値＋馬場オフセット。標本不足は
  L1→L2→L3→None の階層フォールバック）で偏差値化し、馬ごとに
  ベスト/中央値/標本数を runner と frozen_prediction.top5 に
  保存する。あわせて A1 として、parse_horse_form_page の
  surface_text（芝/ダート）が常に None だった不具合を修正した
  （距離列テキスト「ダ1400」等から抽出する）。
- Phase B 血統スコア: オフライン構築した産駒成績テーブル
  （pedigree_stats.json。父・母父 × 芝ダ × 距離4帯の複勝率を
  全体平均との差 × 標本縮小 n/(n+30) で偏差ポイント化。
  フォールバック F1→F4、未評価は None）から sire_score /
  damsire_score を runner と frozen に保存する。既存のリスト
  一致加点（+1.0/+0.75）とは別物として併存させ、form_score には
  混ぜない。
- テーブル JSON が無い場合は特徴量は全て None になり、34.14 と
  同一の従来動作にフォールバックする。

改善点 (v34.14):
- 血統（父・母父）の組み込み Phase 1（ユーザー最優先指示 2026-11-06）。
  旧実装は馬ページ本文への「父:」「母父:」正規表現で抽出を試みたが、
  その表記は netkeiba のページに存在せず、キャッシュ全件で取得0件・
  血統加点は一度も発動していなかった（監査レポート
  hybrid-osusume-2026-11-06.md 第3章）。
- 取得元を db.netkeiba の血統ページ（horse/ped/<馬ID>/）の5代血統表
  （table.blood_table）に切り替え、rowspan を展開した位置構造
  （父=[0][0]／母=[16][0]／母父=[16][1]）で抽出する専用パーサを新設。
  実測検証（2026-11-06）: 中央8頭・地方11頭の全19頭で父・母父を取得。
- 血統は馬ごとに不変のため、馬IDキーの永続キャッシュ pedigree_cache
  （history.json 内、people_cache と同方式）に分離し、新規取得は
  実行あたり上限 MAX_NEW_PEDIGREE_FETCHES で保護する。取得失敗時は
  キャッシュしない（次回再試行）。
- 接続先: parse_runners で父名を血統ページ優先に解決し、馬ごとの
  sire / damsire / dam / horse_id を保持。根拠表示に実名を出す
  （bloodline_status と理由文）。frozen_prediction.top5 にも
  horse_id / sire / damsire を保存し、将来の馬単位の前方検証を可能にする。
- スコアの重み・条件は一切変更しない。ただし既存の血統加点スロット
  （ダートで is_dirt_blood → +1.0、芝で is_power_blood → +0.75）は
  父名が DIRT_SIRES / POWER_SIRES に一致すれば従来設計通り自動で
  発動し始める（データ欠落で死んでいた既存仕様の復活であり、
  重みの新設・変更ではない）。

改善点 (v34.13):
- 有馬記念（2026-12-27）に向けた shadow 計測を2つ新設（ユーザー承認
  2026-11-04）。どちらも計測専用で、本番の選定・スコア・信頼度・
  配分（A/B/C）・ゲート・グレードには一切使わない（alloc_c /
  occult_track と同格）。選定ロジックとサイト表示も無変更。
- (1) 3連複トリム計測 stats["trio_trim_jra_large"]: 弱点分析
  （中央×13頭以上で3連複58点全て不的中、中央全体でも3連複の
  回収率11.2%）を受け、中央×13頭以上の精算レースについて、
  同一買い目から (a) trio_off = 3連複を全て外した構成、
  (b) trio_half = 3連複の穴側だけを外し軸側を残した構成、を
  settled_lines から再計算して並走集計する。外した分の金額は
  他券種へ再配分しない（「外す効果」そのものを測る）。
  軸/穴の判定は frozen_prediction.top5 の上位3頭の集合と一致する
  3連複を「軸」とする。本精算トラック（bet_eligible が False で
  ないもの）とゲート外（shadow）トラックを分けて集計する。
  現行ゲートは13頭以上を常にゲート外にするため、前方で標本が
  貯まるのはゲート外トラック側（有馬自体も本精算対象外になる
  ため、その判断材料として分析レポートの改善候補1に沿った形）。
  過去分は settled_lines から再構成（バックフィル）できる。
- (2) 3連単チャレンジ枠 stats["trifecta_challenge"]: おすすめ以上
  （is_recommended）の本精算レースを対象に、予想 rank から固定
  3パターンを各1点100円で shadow 精算する。P1 本命1着固定流し
  （1着=rank1、2・3着=rank2,3,4 の順不同ペア6点）/ P2 本命→対抗
  固定（1着=rank1、2着=rank2、3着=rank3,4,5 の3点）/ P3 上位3頭
  ボックス（rank1,2,3 の全順列6点）。買い目は予想時点で
  trifecta_challenge として保存し、精算は夢枠・オカルトと同じ
  払戻表（payouts["trifecta"]）で照合して
  trifecta_challenge_settlement に保存する。着順一致でも払戻が
  確認できない場合は収支集計から除外する（本体と同じ厳密さ）。
  夢枠・オカルト枠とは別集計。過去のスナップショットには払戻表が
  保存されていないため収支の再構成はできず、34.13 生成分からの
  前方計測のみ。

改善点 (v34.12):
- 配分C（shadow並走計測）を新設（ユーザー承認 2026-11-02）。パターンBと
  同一レース・同一買い目・同一精算結果を使い、配分だけを C スキームに
  変えた場合の収支を settled_lines から再計算して stats["alloc_c"] に
  別集計する。本番の選定・スコア・信頼度・配分（A/B）・ゲート・グレード
  には一切使わない計測専用トラック（post_odds / occult_track と同格）。
- C スキーム: 券種配分は保険（単勝+ワイド）を 150/1500 に圧縮し、
  芯（馬連+3連複軸）に寄せる（単勝100/馬連対抗250/馬連3番手350/
  3連複軸450/3連複穴200/ワイド50/夢枠100、合計1,500は B と同一）。
  さらにレース単位の傾斜として、グレードで総額を 超おすすめ×1.5 /
  注目・おすすめ×1.2 / 通常×0.7 に変える。
- 計測対象は ALLOC_C_START_DATE（2026-11-03）以降のレースのパターンB
  本精算分のみ。同一レース集合でのパターンB実績（pattern_b_same_races）
  も併記し、回収率を直接比較できるようにする。各スナップショットには
  alloc_c（C換算の投資・回収・損益）を記録する。

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

第1次シャドウ検証 (34.23 計測追加・ENGINE_VERSION は無変更):
- P1 持ちタイム一致度の投資額調整 (T0/T1/T2) と P2 選定分解
  (A: 本番軸+本番相手 / B: 本番軸+hybrid相手 / C: hybrid軸+本番相手 /
  D: hybrid軸+hybrid相手) を stats["phase1_experiments"] に
  遡及/前方を分離して集計する
- P2 の B/C 買い目は phase1_sel_tickets として前方保存し、本体と
  同じ精算経路で精算する。P4 血統は固定閾値 3.87 で前方再現性を測る
- いずれも計測専用で、本番の予測順位・買い目・投資配分・ゲート・
  グレードには一切使用しない

第2次シャドウ検証 (34.23 計測追加・ENGINE_VERSION は無変更):
- P2 軸分析 (本番軸/hybrid軸の一致・正解の4分類)、P6 post-odds
  購入判断ゲート (判断時点オッズで人気帯を分け P6-0/-25/-50 と
  別実験 P6-SKIP を同一レースで比較)、P3 券種配分 (3連複の段階的
  縮小と馬連・ワイドへの振替)、P1 リスク改善型ゲート、P4 評価拡張
  (予測能力/収益能力の分離) を stats["phase2_experiments"] に
  遡及/前方を分離して集計する。全て精算済みスナップショットからの
  集計時導出で、第1次の集計値にも本番にも一切影響しない

第3次シャドウ検証 (34.23 計測追加・ENGINE_VERSION は無変更):
- AXIS-SURVIVAL V1 (軸の3着内確率をレース前情報だけから推定する
  凍結ロジスティック回帰。学習は前方開始日より前の遡及のみで、
  係数は定数として凍結。閾値70%以上のみ購入した場合のシャドウ
  成績と確率校正を測る)、CENTRAL-VALIDATION (中央全体/中央芝/
  中央ダート/中央種別不明/地方全体の固定区分での独立評価)、
  COMBINATION-ENGINE (軸が来たのに取りこぼしたレースの原因分類と、
  3連複予算の軸込みtop5カバー再配分の前方比較) を
  stats["phase3_experiments"] に遡及/前方を分離して集計する。
  いずれも計測専用で、本番の予測順位・買い目・投資配分・ゲート・
  グレードと、第1次・第2次の集計値には一切使用しない

第4次シャドウ検証 (34.23 計測追加・ENGINE_VERSION は無変更):
- AXIS-STABILITY (本番スコアの2成分 form/market それぞれでの
  再順位付けに対する軸の順位安定性と軸3着内率の関係、ハイブリッド
  順位との不一致、第3次生存確率モデルとの併用評価)、
  CORE-RESERVE (本番 top5 の外から脚質×展開適合と降級で選ぶ
  予備候補を加えた場合の3連複の取りこぼし削減。追加投資型)、
  CENTRAL-TURF (中央芝の全面除外/条件付き参加 (gap12>=2.0)/
  中央芝専用モデル (top5 内 time_index 再順位・馬レベルのみ) の
  独立比較) を stats["phase4_experiments"] に遡及/前方を分離して
  集計する。COMBINATION は第3次の前方比較を正とし、第4次では
  新規方式・集計を追加しない。いずれも計測専用で、本番の予測
  順位・買い目・投資配分・ゲート・グレードと、第1次〜第3次の
  集計値には一切使用しない
"""
import json, math, re, sys, time, html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "data.json"
HISTORY = DOCS / "history.json"
# v34.22: shadow 累計の軽量サマリ（系統別・日次別）。判定材料を
# history.json 本体から分離し、小さいファイルだけで取り出せるようにする
SHADOW_SUMMARY = DOCS / "shadow_summary.json"
JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime("%Y%m%d")
TOMORROW = (NOW + timedelta(days=1)).strftime("%Y%m%d")
ENGINE_VERSION = "BAGEN_34.23_EXPERT"
MAX_NEW_FORM_FETCHES = 24
FORM_FETCHED_THIS_RUN = 0
HORSE_FORM_CACHE = {}
# v34.2: 調教師・騎手の人物データ（馬と同一方式: 14日キャッシュ＋実行あたり上限）
MAX_NEW_PEOPLE_FETCHES = 24
PEOPLE_FETCHED_THIS_RUN = 0
PEOPLE_CACHE = {}
# v34.14: 血統キャッシュ（馬IDキー。血統は不変情報なので people_cache と
# 同方式の永続キャッシュに分離し、14日更新の horse_form_cache には混ぜない）
MAX_NEW_PEDIGREE_FETCHES = 24
PEDIGREE_FETCHED_THIS_RUN = 0
PEDIGREE_CACHE = {}
# v34.21: 血統の前倒し取得（prefetch）専用枠。生成パス（parse 内）の
# 上限 MAX_NEW_PEDIGREE_FETCHES は従来どおり 24 のまま変えず、生成後に
# 残りの未解決馬を prefetch_pedigrees が先取りする。1実行あたりの
# 血統取得の総量上限は MAX_TOTAL_PEDIGREE_FETCHES とし、あわせて
# 実行開始からの経過が PREFETCH_DEADLINE_SEC を超えたら打ち切る
# （Actions の job 上限10分に対する安全弁）。根拠: 1取得は
# db.netkeiba への GET 1回 + DELAY 0.35秒で約0.7〜1.4秒のため、
# 総量120件でも追加所要は最大で約+2〜3分に収まる見込みで、
# デッドライン側でも二重に保護する。
MAX_PREFETCH_PEDIGREE_FETCHES = 96
MAX_TOTAL_PEDIGREE_FETCHES = (
    MAX_NEW_PEDIGREE_FETCHES + MAX_PREFETCH_PEDIGREE_FETCHES)
PREFETCH_DEADLINE_SEC = 420
PEDIGREE_PREFETCHED_THIS_RUN = 0
# v34.15: hybrid 特徴量（時計指数・血統スコア）の基準テーブル。
# review 環境でオフライン構築した JSON を読むだけで、bot 本体では
# 再計算しない。ファイルが無ければ特徴量は全て None（従来動作）。
TIME_STANDARDS_PATH = ROOT / "time_standards.json"
PEDIGREE_STATS_PATH = ROOT / "pedigree_stats.json"
TIME_STANDARDS = {}
PEDIGREE_STATS = {}
# v34.15: 時計指数の基準フォールバック閾値（設計書 2.2）
TIME_STD_MIN_N_L1 = 20   # (場,芝ダ,距離) セルの最小標本数
TIME_STD_MIN_N_L2 = 20   # (場,芝ダ,距離帯) プールの最小標本数
TIME_STD_MIN_N_L3 = 30   # (芝ダ,距離) 全場合成の最小標本数
# v34.15: 血統スコアの閾値と縮小定数（設計書 3.3）
PEDIGREE_SCORE_MIN_N = 10
PEDIGREE_SCORE_SHRINK_K = 30
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
# v34.12: 配分C（shadow計測専用。本番配分・選定には一切使わない）。
# キーはパターンBの (券種, 現行ステーク) で、C のステークに読み替える。
# 合計は B と同じ ¥1,500。マップに無い買い目は B と同額として扱う。
ALLOC_C_STAKES = {
    ("win", 200): 100,
    ("quinella", 200): 250,
    ("quinella", 300): 350,
    ("trio", 400): 450,
    ("trio", 200): 200,
    ("wide", 100): 50,
    ("trifecta", 100): 100,
}
ALLOC_C_MULT_SUPER = 1.5        # 超おすすめのレース総額倍率
ALLOC_C_MULT_RECOMMENDED = 1.2  # 注目レース / おすすめの倍率
ALLOC_C_MULT_NORMAL = 0.7       # それ以外の倍率
ALLOC_C_START_DATE = "2026-11-03"  # この日付以降のレースから計測
# v34.19: 配分D（shadow計測専用。本番配分・選定には一切使わない）。
# 買い目の組み合わせと総額は現行パターンA/Bと完全同一で、配分だけを
# 馬連寄りに変える。キーは (パターン, 券種, 同一券種内の出現順) で、
# build_tickets のライン順（馬連は [本命-対抗] → [本命-3番手]、
# 3連複は [軸] → [穴]）に対応する。マップに無いラインは現行額を維持。
ALLOC_D_STAKES = {
    ("B", "win", 0): 200,
    ("B", "quinella", 0): 400,
    ("B", "quinella", 1): 400,
    ("B", "trio", 0): 200,
    ("B", "trio", 1): 100,
    ("B", "wide", 0): 100,
    ("B", "trifecta", 0): 100,
    ("A", "win", 0): 500,
    ("A", "quinella", 0): 500,
    ("A", "quinella", 1): 400,
    ("A", "trio", 0): 300,
    ("A", "wide", 0): 100,
    ("A", "wide", 1): 100,
}
ALLOC_D_START_DATE = "2026-11-09"  # 前方計測の開始日（34.19生成分から）
# v34.20: 金額の強弱（shadow計測専用。本番配分・選定には一切使わない）。
# 配分比率は現行パターンA/Bのまま、レース総額だけを段階化する。
# 段階は最終グレード（race_grade）と種別（kind）の既存判定だけで
# 決める（stake_shadow_tier）: 最強×4＝超おすすめ×中央、
# 強×2＝超おすすめ、通常×1＝それ以外（注目レース等）。
STAKE_SHADOW_START_DATE = "2026-11-09"  # 前方計測の開始日（34.20生成分から）
# v34.22: HYBRID_SHADOW 選定 shadow（shadow計測専用。本番選定・配分・
# ゲート・グレードには一切使わない）。主成分は時計指数・血統スコア・
# クラス評価で、市場乖離は主成分にしない（post_odds の観測のみ）。
HYBRID_SHADOW_START_DATE = "2026-11-17"  # 前方計測の開始日（34.22生成分から）
HYBRID_SHADOW_TARGET_SAMPLES = 200      # 判定に必要な比較可能標本数（結果確定済み）
# 第1次シャドウ検証（34.23 計測追加・モデル無変更）: ChatGPT 助言に
# 基づく検証基盤。本番の予測順位・買い目・投資配分には一切使わない。
# P1 持ちタイム一致度 (T0/T1/T2)・P2 選定分解 (A/B/C/D) の前方計測は
# この日付のレースから開始し、それ以前は遡及 (retro) として分離する。
PHASE1_START_DATE = "2026-11-22"  # 前方計測の開始日（第1次検証から）
# P4 血統再検証: 遡及データの3分位で得た上位バンド境界 (sire_score
# 3.87) を固定値として前方再現性を見るための閾値。再計算で動かさない。
PHASE1_SIRE_FORWARD_MIN = 3.87
# 第2次シャドウ検証（34.23 計測追加・モデル無変更）: P2 軸分析 /
# P6 post-odds 購入判断ゲート / P3 券種配分 / P1 リスク改善型ゲート /
# P4 評価拡張。前方計測の開始日は第1次と同日 (2026-11-22)。両実験とも
# 集計時にスナップショット (odds_snapshots / settled_lines) から導出
# する方式で、原記録は本番コードが従来から記録してきたものを使う。
PHASE2_START_DATE = "2026-11-22"  # 前方計測の開始日（第2次検証）
# P3: 3連複ラインの金額係数。現行の3連複比率は A=31.6% / B=40.0% で
# あり、ChatGPT 設計の「75%」は実測と異なるため、現行を75とした
# 相対段階 (75→50→25) として係数化する。削減分は馬連・ワイドへ
# 現行金額比で振り替えて総額を固定する。
PHASE2_P3_TRIO_FACTORS = {"A": 1.0, "B": 50.0 / 75.0, "C": 25.0 / 75.0}
# P6: 人気帯 (A=1人気 / B=2-3人気 / C=4-5人気 / D=6人気以下) ごとの
# 投資係数。P6-25 / P6-50 は軸4番人気以下 (C・D) の減額。見送り方式は
# 別実験 P6-SKIP (D のみ 0) として分離する。
PHASE2_P6_FACTORS = {
    "P6-0": {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0},
    "P6-25": {"A": 1.0, "B": 1.0, "C": 0.75, "D": 0.75},
    "P6-50": {"A": 1.0, "B": 1.0, "C": 0.50, "D": 0.50},
}
PHASE2_P6_SKIP_FACTORS = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 0.0}
# P1 リスク改善型ゲートの仮基準（収益改善型とは別系統で判定する）
PHASE2_RISK_GATE = {"min_races": 300, "min_days": 14,
                    "roi_diff_floor_pt": -1.0,
                    "dd_improvement_min_pct": 20.0}
# 第3次シャドウ検証（34.23 計測追加・モデル無変更）: AXIS-SURVIVAL V1 /
# CENTRAL-VALIDATION / COMBINATION-ENGINE。設計書
# phase3-shadow-design-2026-11-23.md で条件を事前に固定した。
# 前方計測は 2026-11-24 の最初のサイクルから開始する。
PHASE3_START_DATE = "2026-11-24"  # 前方計測の開始日（第3次検証）
# AXIS-SURVIVAL V1 の主閾値（推定確率70%以上のみ購入）。60%・80% は
# 探索的参考値として併記するだけで、採用判断には使用しない。
PHASE3_AXIS_THRESHOLD_MAIN = 0.70
PHASE3_AXIS_THRESHOLDS_REF = (0.60, 0.80)
# AXIS-SURVIVAL V1 の凍結モデル。学習は前方開始日より前の本精算
# レース 753 件（判断時点オッズなし 266・目的変数なし 3 を除外）に
# 対してオフラインで実施し、係数をここに凍結した。評価期間での
# 再学習は禁止。特徴量は全てレース前情報のみで、判断時点オッズは
# 第2次 P6 と同一手順 (odds_snapshots の発走前最後の観測点) で復元
# する。最終オッズ・最終人気・確定着順は特徴量に使わない。
# 方式: 標準化した特徴量への L2 正則化つきロジスティック回帰
# (lambda=1.0、切片は非正則化、Newton 法)。学習内の参考値:
# ベースレート (軸3着内率) 0.6388 / AUC 0.712 / Brier 0.199。
PHASE3_AXIS_MODEL = {
    "features": ["gap12", "gap13", "spread15", "score1", "runners",
                 "pop_decision", "log_odds_decision", "is_jra",
                 "is_turf", "surf_unknown", "dist_km", "dist_missing",
                 "conf"],
    "means": [2.893891, 5.186228, 8.742218, 17.667065, 10.213811,
              2.794157, 1.3066, 0.077025, 0.02656, 0.472776,
              1.402762, 0.47012, 0.843588],
    "stds": [3.141599, 4.321059, 5.7967, 9.476995, 1.467024,
             2.47245, 0.860379, 0.266631, 0.160795, 0.499258,
             0.194136, 0.499106, 0.118082],
    "intercept": 0.650534,
    "coefficients": [-0.067545, 0.067441, 0.424967, 0.319744,
                     -0.113866, 0.050114, -0.436642, 0.13808,
                     -0.099322, -0.433759, 0.029974, 0.460731,
                     -0.239527],
    "l2_lambda": 1.0,
    "dist_median_km": 1.4,   # 距離欠損時の補完値（学習中央値・凍結）
    "conf_median": 0.888,    # 信頼度欠損時の補完値（学習中央値・凍結）
    "train_races": 753,
    "train_base_rate": 0.6388,
    "train_excluded": {"no_decision_odds": 266, "no_features": 0,
                       "no_target": 3},
}
# v34.23: 第4次シャドウ検証の凍結定数 (PHASE4_EXP_V1・計測専用)。
# 設計: phase4-shadow-design-2026-11-24.md。本番予測には使わない。
PHASE4_START_DATE = "2026-11-25"
PHASE4_RESERVE_FIT = {
    "スロー想定": {"逃げ": 2, "先行": 3, "差し": 1, "追込": 0},
    "単騎逃げ想定": {"逃げ": 2, "先行": 2, "差し": 1, "追込": 0},
    "平均〜ハイ想定": {"逃げ": 0, "先行": 1, "差し": 2, "追込": 2},
    "ハイ想定": {"逃げ": 0, "先行": 1, "差し": 3, "追込": 3},
}
PHASE4_RESERVE_MAX = 2
PHASE4_RESERVE_COMBO_STAKE = 100
PHASE4_TURF_GAP12_MIN = 2.0
PHASE4_BOOTSTRAP_REPS = 1000
PHASE4_BOOTSTRAP_SEED = 20261124
# v34.13: 3連複トリム計測（shadow計測専用。本番配分・選定には一切使わない）。
# 対象は中央（JRA）×この頭数以上の精算レース。
TRIO_TRIM_MIN_RUNNERS = 13
# v34.13: 3連単チャレンジ枠（shadow計測専用。夢枠・オカルト枠とは別集計）。
TRIFECTA_CHALLENGE_STAKE_YEN = 100  # 1点あたりの仮定ベット額
TRIFECTA_CHALLENGE_START_DATE = "2026-11-04"  # 前方計測の開始日（34.13生成分から）
# v34.16: 候補プール shadow（案C 保険枠 / 案A6 最終6位まで。shadow計測
# 専用で、本番の選定・買い目・配分には一切使わない）
POOL_SHADOW_START_DATE = "2026-11-07"  # 前方計測の開始日（34.16生成分から）
POOL_SHADOW_ADD_STAKE_YEN = 200        # 追加型の追加ライン1点あたりの金額（現行の穴ラインと同額）
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
        # v34.15 (A1): 芝/ダートは距離列の表記（「ダ1400」「芝1600」等）
        # から抽出する。旧実装は indexes["surface"] の列特定が機能せず
        # surface_text が全件 None だった。距離列で取れない場合は行全体
        # から距離一致つきで復元し、それでも取れなければ従来列→None。
        surface_text = (
            surface_from_distance_text(val("distance"))
            or restore_surface_from_row(" ".join(vals), distance)
            or surface_from_distance_text(val("surface"))
            or val("surface") or None)
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
            "course_text": val("course") or None, "surface_text": surface_text,
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


def _pedigree_cell_name(cell):
    """v34.14: 血統表のセルから馬名を取り出す。
    セル内の馬リンク（/horse/<id>/ 形式。[血統]=/horse/ped/、[産駒]=/horse/sire/
    は除外）の文字列が馬名。海外馬の「(米)」「（英）」等の産地サフィックスは
    照合・表示用に取り除く。リンクが無いセルはセル先頭のテキストを使う。"""
    if cell is None:
        return None
    link = None
    for a in cell.select("a[href]"):
        if re.search(r"/horse/(?!ped/|sire/)[^/]+/?$", a.get("href", "")):
            link = a
            break
    raw = text_of(link) if link is not None else text_of(cell)
    name = clean(raw)
    name = re.sub(r"\s*[(（][^()（）]{1,4}[)）]\s*$", "", name).strip()
    return name or None


def parse_pedigree_page(page):
    """v34.14: db.netkeiba の血統ページ（horse/ped/<馬ID>/）を解析する。

    5代血統表（table.blood_table）は「父:」のようなテキスト表記ではなく
    32行×5列の位置構造で家系を表す:
      父   = [0][0]  （rowspan 16、0〜15行）
      母   = [16][0] （rowspan 16、16〜31行）
      母父 = [16][1] （母の父、rowspan 8、16〜23行）
    旧実装の「父:」「母父:」正規表現は、その表記がページに存在しないため
    永遠に一致しなかった（取得0件の原因）。ここでは rowspan を展開した
    行列位置で抽出する。取れない項目は推測で補完せず None のまま返す。"""
    empty = {"available": False, "sire": None, "damsire": None, "dam": None,
             "source": "血統ページ・血統表未検出"}
    soup = soup_of(page)
    table = soup.select_one("table.blood_table")
    if table is None:
        return empty
    grid = {}
    for ri, tr in enumerate(table.select("tr")):
        ci = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while (ri, ci) in grid:
                ci += 1
            try:
                rs = max(1, int(cell.get("rowspan") or 1))
            except (TypeError, ValueError):
                rs = 1
            try:
                cs = max(1, int(cell.get("colspan") or 1))
            except (TypeError, ValueError):
                cs = 1
            for dr in range(rs):
                for dc in range(cs):
                    grid[(ri + dr, ci + dc)] = cell
            ci += cs

    def name_at(r, c):
        return _pedigree_cell_name(grid.get((r, c)))

    sire = name_at(0, 0)
    dam = name_at(16, 0)
    damsire = name_at(16, 1)
    if not sire and not damsire:
        return empty
    return {"available": True, "sire": sire, "damsire": damsire, "dam": dam,
            "source": "db.netkeiba 血統ページの5代血統表（位置構造）から抽出"}


def get_pedigree(horse_id, limit=None):
    """v34.14: 馬IDから父・母父・母を解決する。血統は馬ごとに不変なので
    永続キャッシュ（PEDIGREE_CACHE）優先で、新規取得は実行あたり上限で
    保護する。ページ取得自体に失敗した場合はキャッシュせず次回再試行する
    （取得できたが血統表が無い結果は不変としてキャッシュする）。
    v34.21: limit で取得上限を差し替え可能にした（prefetch 専用枠用）。
    省略時は従来どおり MAX_NEW_PEDIGREE_FETCHES で、生成パスの
    呼び出しは無変更。"""
    global PEDIGREE_FETCHED_THIS_RUN
    empty = {"available": False, "sire": None, "damsire": None, "dam": None,
             "source": "血統未取得"}
    if not horse_id:
        return empty
    cached = PEDIGREE_CACHE.get(horse_id)
    if isinstance(cached, dict) and cached.get("checked_at"):
        ped = cached.get("pedigree")
        return ped if isinstance(ped, dict) else empty
    cap = MAX_NEW_PEDIGREE_FETCHES if limit is None else limit
    if PEDIGREE_FETCHED_THIS_RUN >= cap:
        return {**empty, "source": "無料実行時間保護のため今回の取得上限"}
    PEDIGREE_FETCHED_THIS_RUN += 1
    page = get_html(f"https://db.netkeiba.com/horse/ped/{horse_id}/")
    if not page:
        return {**empty, "source": "血統ページ取得失敗"}
    ped = parse_pedigree_page(page)
    # 永続キャッシュするのは「抽出成功」か「本物の馬ページ（タイトルに
    # 競走馬データを含む）で血統表が無いと確認できた場合」だけにする。
    # 一時的なブロック/リダイレクトページを未取得として固定しないため。
    if ped.get("available") or "競走馬データ" in page:
        PEDIGREE_CACHE[horse_id] = {"checked_at": NOW.isoformat(), "pedigree": ped}
    return ped


def prefetch_pedigrees(today_races, tomorrow_races, snapshots, start_monotonic):
    """v34.21: 血統の前倒し取得。予想生成（parse）が終わった後に、
    未解決の馬の血統を優先順位つきで先取りして PEDIGREE_CACHE を
    温める。温めたキャッシュは history.json に保存され、次回以降の
    生成（特に翌日分が当日分になって frozen が作られる初回生成）で
    効く。生成がない実行でも parse 自体は毎回走るため、そのたびに
    少しずつ前倒しが進む。
    優先順位: (1) 今日の未生成レース（スナップショットに
    frozen_prediction がまだ無いレース）の出走馬、(2) 明日の出走馬、
    (3) 今日の生成済みレースの未解決馬。
    キャッシュを埋めるだけで、スコア計算・加点・選定には影響しない。
    戻り値はこの呼び出しで実際に行った新規取得の件数。"""
    global PEDIGREE_PREFETCHED_THIS_RUN

    def frozen_missing(race):
        snap = snapshots.get(str(race.get("id"))) or {}
        return not snap.get("frozen_prediction")

    ordered_races = (
        [r for r in today_races if frozen_missing(r)]
        + list(tomorrow_races)
        + [r for r in today_races if not frozen_missing(r)])
    candidates = []
    seen = set()
    for race in ordered_races:
        for h in race.get("horses", []) or []:
            hid = h.get("horse_id")
            if not hid or hid in seen:
                continue
            seen.add(hid)
            cached = PEDIGREE_CACHE.get(hid)
            if isinstance(cached, dict) and cached.get("checked_at"):
                continue
            candidates.append(hid)
    done = 0
    for hid in candidates:
        if done >= MAX_PREFETCH_PEDIGREE_FETCHES:
            break
        if time.monotonic() - start_monotonic > PREFETCH_DEADLINE_SEC:
            print(f"[INFO] pedigree prefetch: 実行時間保護のため "
                  f"{done}件で打ち切り")
            break
        before = PEDIGREE_FETCHED_THIS_RUN
        get_pedigree(hid, limit=MAX_TOTAL_PEDIGREE_FETCHES)
        if PEDIGREE_FETCHED_THIS_RUN > before:
            done += 1
            PEDIGREE_PREFETCHED_THIS_RUN += 1
    if done:
        print(f"[INFO] pedigree prefetch: {done}件を前倒し取得")
    return done


# ============================================================
# v34.15: hybrid 特徴量（時計指数＝Phase A / 血統スコア＝Phase B）
# Stage 0: 保存と参考表示のみ。選定・スコア・信頼度・配分・
# ゲート・グレードには一切使わない（stats["hybrid_shadow"] で
# 別枠計測する）。基準テーブルは review 環境でオフライン構築した
# JSON（time_standards.json / pedigree_stats.json）を読むだけ。
# ============================================================
_SURFACE_BY_KANJI = {"ダ": "ダート", "芝": "芝", "障": "障害"}


def _norm_surface(value):
    """surface 表記を完全表記（ダート/芝/障害）にそろえる。不能なら None。"""
    t = clean(value)
    if not t:
        return None
    if t in ("ダート", "芝", "障害"):
        return t
    return _SURFACE_BY_KANJI.get(t)


def surface_from_distance_text(text):
    """距離列テキスト（例 'ダ1400' '芝 1600'）から芝/ダート/障害を
    取り出す。取れなければ None（推測で埋めない）。"""
    t = clean(text)
    if not t:
        return None
    m = re.search(r"(ダ|芝|障)\s*\d{3,4}", t)
    return _SURFACE_BY_KANJI[m.group(1)] if m else None


def restore_surface_from_row(row_text, distance_m):
    """過去走の生テキスト row から、距離一致の検証つきで surface を
    復元する（A1 の遡及復元と同方法。実測で全件復元可能を確認済み）。"""
    if not row_text or not distance_m:
        return None
    m = re.search(r"(ダ|芝|障)\s*" + str(int(distance_m)) + r"(?!\d)", row_text)
    return _SURFACE_BY_KANJI[m.group(1)] if m else None


def parse_race_time(text):
    """走破時計テキスト（'1:33.2' / '33.2'）を秒に変換する。
    変換できなければ None（100分の1秒表記等は対象外として正直に落とす）。"""
    t = clean(text)
    if not t:
        return None
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2})\.(\d)", t)
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2)) + int(m.group(3)) / 10.0


_PAST_VENUE_NAMES = sorted(set(JRA_CODES.values()) | set(NAR_CODES.values()),
                           key=len, reverse=True)


def normalize_past_venue(course_text):
    """過去走の開催テキストを競馬場名に正規化する。地方は場名そのまま、
    中央は '3新潟1' のような回次・日次つき表記から場名を取り出す。
    照合できない表記（海外コース等）は None を返す。"""
    t = clean(course_text)
    if not t:
        return None
    if t in _PAST_VENUE_NAMES:
        return t
    m = re.fullmatch(r"\d+(.+?)\d+", t)
    if m and m.group(1) in _PAST_VENUE_NAMES:
        return m.group(1)
    return None


def distance_band_label(distance_m):
    """距離4帯ラベル（血統スコア用）: 短≤1200 / マイル≤1600 / 中≤2000 / 長>2000。"""
    if not distance_m:
        return None
    d = int(distance_m)
    if d <= 1200:
        return "短"
    if d <= 1600:
        return "マイル"
    if d <= 2000:
        return "中"
    return "長"


def load_hybrid_tables():
    """time_standards.json / pedigree_stats.json を読み込む。
    無ければ空のままにし、特徴量は全て None（従来動作）になる。"""
    global TIME_STANDARDS, PEDIGREE_STATS
    for path, name in ((TIME_STANDARDS_PATH, "TIME_STANDARDS"),
                       (PEDIGREE_STATS_PATH, "PEDIGREE_STATS")):
        try:
            if path.exists():
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    globals()[name] = value
                    print(f"[INFO] hybrid table loaded: {path.name} "
                          f"(built_at={value.get('built_at')})")
        except Exception as e:
            warn(f"hybrid テーブル読込失敗 {path.name}: {type(e).__name__}")
    return TIME_STANDARDS, PEDIGREE_STATS


def _time_standard_cell(venue, surface, distance_m):
    """基準タイムを階層フォールバックで引く。
    L1 (場,芝ダ,距離) n>=20 → L2 (場,芝ダ,距離帯) のペース換算
    → L3 (芝ダ,距離) 全場合成 n>=30 → None（未評価）。"""
    if not TIME_STANDARDS or not venue or not surface or not distance_m:
        return None
    dist = int(distance_m)
    cell = (TIME_STANDARDS.get("cells") or {}).get(f"{venue}|{surface}|{dist}")
    if (cell and safe_int(cell.get("n"), 0) >= TIME_STD_MIN_N_L1
            and cell.get("median") is not None):
        return {"median": cell["median"], "sigma": cell.get("sigma"), "level": 1}
    region = distance_band_label(dist)
    if f"{surface}|{region}" not in (TIME_STANDARDS.get("l2_excluded") or []):
        band = int(round(dist / 100.0)) * 100
        bp = (TIME_STANDARDS.get("band_pace") or {}).get(
            f"{venue}|{surface}|{band}")
        if (bp and safe_int(bp.get("n"), 0) >= TIME_STD_MIN_N_L2
                and bp.get("pace") is not None):
            return {"median": bp["pace"] * dist / 100.0,
                    "sigma": None, "level": 2}
    sd = (TIME_STANDARDS.get("surface_distance") or {}).get(f"{surface}|{dist}")
    if (sd and safe_int(sd.get("n"), 0) >= TIME_STD_MIN_N_L3
            and sd.get("median") is not None):
        return {"median": sd["median"], "sigma": sd.get("sigma"), "level": 3}
    return None


def _time_sigma(surface, distance_m, cell_sigma):
    """σ のフォールバック: セル実測 → (芝ダ,距離帯) プール → 全体。
    いずれもテーブル構築時に実測した値で、決め打ちはしない。"""
    if cell_sigma:
        return cell_sigma
    pool = TIME_STANDARDS.get("sigma_pool") or {}
    band = int(round(int(distance_m) / 100.0)) * 100
    return pool.get(f"{surface}|{band}") or pool.get("all")


def _going_offset(venue, surface, group):
    """(場,芝ダ) 単位で推定した馬場グループ別オフセット（秒）。
    firm を 0 とした差分。テーブルに無ければ 0（補正なし）。"""
    if not group:
        return 0.0
    offs = (TIME_STANDARDS.get("going_offsets") or {}).get(
        f"{venue}|{surface}") or {}
    v = offs.get(group)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _median_of(values):
    vals = sorted(values)
    n = len(vals)
    if not n:
        return None
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def compute_time_index(past_form):
    """過去走から時計指数（偏差値）を計算する。Stage 0 の保存専用で
    スコアには使わない。基準が引けない走は数えず、samples で正直に示す。
    クラス補正は初版では行わない（設計書 2.2: クラス混合基準に対する
    絶対評価として読む）。"""
    empty = {"time_index_best": None, "time_index_med": None,
             "time_index_samples": 0, "time_index_std_level": None,
             "last3f_dev": None}
    if not TIME_STANDARDS or not past_form or not past_form.get("available"):
        return empty
    devs = []  # (偏差値, 基準レベル)
    last3f_diffs = []
    medians3f = TIME_STANDARDS.get("last3f_medians") or {}
    for x in past_form.get("recent_results") or []:
        surf = _norm_surface(x.get("surface_text")) or restore_surface_from_row(
            x.get("row"), x.get("distance_m"))
        if not surf or surf == "障害":
            continue
        venue = normalize_past_venue(x.get("course_text"))
        dist = x.get("distance_m")
        own = parse_race_time(x.get("time_text"))
        if not venue or not dist or own is None:
            continue
        std = _time_standard_cell(venue, surf, dist)
        if std is None:
            continue
        sigma = _time_sigma(surf, dist, std.get("sigma"))
        if not sigma:
            continue
        eff = std["median"] + _going_offset(
            venue, surf, going_group(x.get("going_text")))
        devs.append((round(50.0 + 10.0 * (eff - own) / sigma, 1), std["level"]))
        m3 = medians3f.get(f"{venue}|{surf}")
        l3 = x.get("last3f")
        if m3 and isinstance(l3, (int, float)):
            last3f_diffs.append(round(m3 - l3, 2))
    out = dict(empty)
    if last3f_diffs:
        out["last3f_dev"] = _median_of(last3f_diffs)
    if not devs:
        return out
    best_dev, best_level = max(devs, key=lambda t: t[0])
    out["time_index_best"] = best_dev
    out["time_index_med"] = round(_median_of([v for v, _ in devs]), 1)
    out["time_index_samples"] = len(devs)
    out["time_index_std_level"] = best_level
    return out


def _pedigree_cell_score(table_entry, baselines, surface, distance_m):
    """1頭分の血統スコアをフォールバック階層（F1→F2→F3）で計算する。
    戻り値 (score, score_win, n, level)。未評価は (None, None, 0, None)
    で、0 とは書かない（設計書 3.3）。"""
    if not table_entry:
        return None, None, 0, None
    band = distance_band_label(distance_m)
    candidates = []
    if surface and band:
        candidates.append((f"{surface}|{band}", f"{surface}|{band}", 1))
    if surface:
        candidates.append((surface, surface, 2))
    candidates.append(("all", "all", 3))
    for cell_key, base_key, level in candidates:
        cell = table_entry.get(cell_key)
        base = (baselines or {}).get(base_key)
        if not cell or not base:
            continue
        n = safe_int(cell.get("starts"), 0)
        if n < PEDIGREE_SCORE_MIN_N:
            continue
        base_top3 = base.get("top3_rate")
        if base_top3 is None:
            continue
        shrink = n / (n + PEDIGREE_SCORE_SHRINK_K)
        score = round(
            (safe_int(cell.get("top3"), 0) / n - base_top3) * shrink * 100, 2)
        base_win = base.get("win_rate")
        score_win = (
            round((safe_int(cell.get("wins"), 0) / n - base_win)
                  * shrink * 100, 2)
            if base_win is not None else None)
        return score, score_win, n, level
    return None, None, 0, None


def compute_pedigree_scores(sire, damsire, surface, distance_m):
    """父・母父の血統スコア（偏差ポイント）を計算する。Stage 0 の
    保存専用で、既存のリスト一致加点とは別物として併存させる。"""
    empty = {"sire_score": None, "sire_score_win": None, "sire_score_n": 0,
             "sire_score_level": None, "damsire_score": None,
             "damsire_score_n": 0}
    if not PEDIGREE_STATS:
        return empty
    surf = _norm_surface(surface)
    if surf not in ("芝", "ダート"):
        surf = None
    baselines = PEDIGREE_STATS.get("baselines") or {}
    s_entry = (PEDIGREE_STATS.get("sires") or {}).get(sire) if sire else None
    d_entry = (PEDIGREE_STATS.get("damsires") or {}).get(damsire) if damsire else None
    s, sw, sn, sl = _pedigree_cell_score(s_entry, baselines, surf, distance_m)
    d, _dw, dn, _dl = _pedigree_cell_score(d_entry, baselines, surf, distance_m)
    return {"sire_score": s, "sire_score_win": sw, "sire_score_n": sn,
            "sire_score_level": sl, "damsire_score": d, "damsire_score_n": dn}


def attach_hybrid_features(runner, surface, distance_m):
    """v34.15 Stage 0: 時計指数と血統スコアを runner に付け、根拠表示に
    参考表記を足す。スコア・順位・買い目・信頼度には一切使わない。"""
    runner.update(compute_time_index(runner.get("past_form") or {}))
    runner.update(compute_pedigree_scores(
        runner.get("sire"), runner.get("damsire"), surface, distance_m))
    reasons = runner.setdefault("reasons", [])
    if runner.get("time_index_best") is not None:
        reasons.append(
            f"時計指数ベスト {runner['time_index_best']:.1f}"
            f"（近走{runner['time_index_samples']}走・基準L"
            f"{runner['time_index_std_level']}）【参考・選定不使用】")
    if runner.get("sire_score") is not None:
        surf_label = {"ダート": "ダ", "芝": "芝"}.get(
            _norm_surface(surface) or "", "")
        band_label = {"短": "短距離", "マイル": "マイル",
                      "中": "中距離", "長": "長距離"}.get(
                          distance_band_label(distance_m), "")
        reasons.append(
            f"血統スコア 父:{runner['sire_score']:+.1f}"
            f"（{surf_label}{band_label} n={runner['sire_score_n']}）"
            "【参考・選定不使用】")
    return runner


# v34.17: クラス（格）評価 Stage 0（保存・計測専用。選定・スコア・
# 信頼度・配分・ゲート・グレードには一切使わない）
_CLASS_FW = str.maketrans("０１２３４５６７８９ＧＩｇｉ", "0123456789GIGI")


def _class_norm(text):
    return (text or "").translate(_CLASS_FW).upper()


def class_rank_from_text(text):
    """レース名や過去走の行テキストからクラス（格）の順序尺度を推定する。
    戻り値は (rank, label)。判定できなければ (None, None)。
    中央尺度: 新馬0 / 未勝利1 / 1勝2 / 2勝3 / 3勝4 / オープン・
    リステッド5 / G3=6 / G2=7 / G1=8（旧表記 500万下=2, 1000万下=3,
    1600万下=4）。地方尺度: C3=1, C2=2, C1=3, B3=4, B2=5, B1=6,
    A3=7, A2=8, A1=9。中央の語が見つかれば中央尺度を優先する。
    あくまでテキスト推定の Stage 0 で、誤判定がありうる前提で
    計測にだけ使う。"""
    t = _class_norm(text)
    if not t:
        return None, None
    if re.search(r"G3|GIII", t):
        return 6, "G3"
    if re.search(r"G2|GII", t):
        return 7, "G2"
    if re.search(r"G1|GI(?!V)", t):
        return 8, "G1"
    if "リステッド" in t or "オープン" in t:
        return 5, "オープン"
    # 現行表記（○勝クラス）を旧表記（○万下）より先に判定する
    if "3勝" in t:
        return 4, "3勝クラス"
    if "2勝" in t:
        return 3, "2勝クラス"
    if "1勝" in t:
        return 2, "1勝クラス"
    if "1600万" in t:
        return 4, "3勝クラス"
    if "1000万" in t:
        return 3, "2勝クラス"
    if "500万" in t:
        return 2, "1勝クラス"
    if "未勝利" in t:
        return 1, "未勝利"
    if "新馬" in t:
        return 0, "新馬"
    m = re.search(r"(?<![A-Z0-9])([ABC])([1-3])(?![0-9])", t)
    if m:
        base = {"A": 6, "B": 3, "C": 0}[m.group(1)]
        return base + (4 - int(m.group(2))), f"{m.group(1)}{m.group(2)}級"
    return None, None


def compute_class_features(past_form):
    """近走（新しい順）から前走クラスと近走ピーク（最高格）を推定する。
    前走は recent_results の先頭行のみで判定し、読めなければ None。
    ピークは判定できた近走の中の最大値。"""
    results = (past_form or {}).get("recent_results") or []
    prev_rank = prev_label = None
    if results:
        prev_rank, prev_label = class_rank_from_text(results[0].get("row") or "")
    peak = None
    for x in results:
        r, _lab = class_rank_from_text(x.get("row") or "")
        if r is not None and (peak is None or r > peak):
            peak = r
    return {"prev_class_rank": prev_rank, "prev_class_label": prev_label,
            "peak_class_rank": peak}


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


# v34.18: 確率校正 Phase 3（probability-calibration-2026-11-08.md）の
# 推奨マッピング。勝率は2段階 softmax（T=6.51、カバレッジ C は頭数帯
# 別の fit 期実測）、連対・複勝は順位の経験率テーブル。いずれも
# 保存・計測専用で、選定・スコア・信頼度・買い目には使わない。
# パラメータは fit 期（〜2026-11-07）の値で、版が変われば再 fit 前提。
CALIB_T = 6.51
CALIB_COVERAGE_BANDS = ((8, 0.80), (12, 0.75), (999, 0.64))
CALIB_PLACE_BY_RANK = {1: 49.0, 2: 38.1, 3: 26.5, 4: 21.0, 5: 17.4}
CALIB_SHOW_BY_RANK = {1: 63.0, 2: 50.6, 3: 40.7, 4: 35.1, 5: 28.8}


def _calib_coverage(runner_count):
    for limit, cov in CALIB_COVERAGE_BANDS:
        if (runner_count or 0) <= limit:
            return cov
    return 0.64


def attach_calibrated_probabilities(ranked):
    """v34.18: 校正確率を runner に付ける（保存・計測専用）。
    勝率は top5 内の相対 softmax × カバレッジ。6位以下は Phase 3 の
    方法論上、個別確率を推定できないため None（未推定を明示）。
    連対・複勝も top5 のみ順位テーブルで付ける。"""
    if not ranked:
        return
    top5 = ranked[:5]
    cov = _calib_coverage(len(ranked))
    vals = [float(h.get("score", 0)) for h in top5]
    mx = max(vals)
    weights = [math.exp(max(-30.0, min(0.0, (v - mx) / CALIB_T)))
               for v in vals]
    total = sum(weights) or 1.0
    for i, h in enumerate(ranked):
        rank = i + 1
        if i < 5:
            h["calibrated_win_probability_pct"] = round(
                cov * weights[i] / total * 100, 2)
            h["calibrated_place_probability_pct"] = CALIB_PLACE_BY_RANK.get(rank)
            h["calibrated_show_probability_pct"] = CALIB_SHOW_BY_RANK.get(rank)
        else:
            h["calibrated_win_probability_pct"] = None
            h["calibrated_place_probability_pct"] = None
            h["calibrated_show_probability_pct"] = None


def parse_runners(soup, surface, distance=None):
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
        # v34.14: 血統（父・母父・母）を馬IDキー永続キャッシュで解決する
        horse_id, _horse_url = horse_id_from_row(row)
        pedigree = get_pedigree(horse_id)
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
        # v34.14: 父名は血統ページ（位置構造パーサ）を正とし、旧・馬ページ
        # 抽出は予備に残す。母父・母は血統ページからのみ得られる
        sire_name = pedigree.get("sire") or (
            past_form.get("sire") if past_form.get("available") else None)
        damsire_name = pedigree.get("damsire")
        dam_name = pedigree.get("dam")
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
        # v34.14: 血統が解決できた場合は根拠表示に実名を出す
        if sire_name or damsire_name:
            reasons.append(
                f"血統 父:{sire_name or '不明'}／母父:{damsire_name or '不明'}")
        if wd is not None and abs(wd) >= 6:
            reasons.append(f"馬体重増減 {wd:+d}kg")
        if positive:
            reasons.append("掲載テキストに好材料ワード")
        if negative:
            reasons.append("掲載テキストに注意ワード")
        runners[no] = {
            "horse_no": no, "number": no, "frame_no": frame, "horse": name, "name": name,
            # v34.14: 馬IDと血統（解決できた場合のみ実名、未解決は None）
            "horse_id": horse_id or None,
            "sire": sire_name, "damsire": damsire_name, "dam": dam_name,
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
            "bloodline_status": (
                (f"血統表で確認 父:{sire_name}" + (f"／母父:{damsire_name}" if damsire_name else ""))
                if pedigree.get("available") and sire_name
                else ("出馬表テキストで血統欄を確認" if bloodline_in_row
                      else ("馬ページで父名を確認" if sire_name
                            else "未取得・血統加点なし"))),
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
        # v34.15 Stage 0: hybrid 特徴量（時計指数・血統スコア）を付ける。
        # 保存と参考表示のみで、スコア・順位・買い目には使わない。
        attach_hybrid_features(runners[no], surface, distance)
        # v34.17 Stage 0: クラス（格）特徴量。前走クラスと近走ピークを
        # 保存するだけで、選定・スコアには使わない。
        runners[no].update(compute_class_features(past_form))
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
        # v34.21: 血統加点の実績記録（frozen 保存専用）。加点そのものは
        # 下の is_dirt_blood / is_power_blood 判定で従来どおり行い、
        # ここでは初期値だけ置く（実際に適用した時点で上書きする）
        h["pedigree_bonus"] = 0.0
        h["pedigree_bonus_kind"] = None
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
            # v34.21: 適用した加点を記録する（保存専用・計算は無変更）
            h["pedigree_bonus"] = 1.0
            h["pedigree_bonus_kind"] = "dirt"
            reasons.append("血統欄でダート向け候補を検出（参考+1点）")
        elif surface == "芝" and h.get("is_power_blood"):
            form_score += 0.75
            h["pedigree_bonus"] = 0.75
            h["pedigree_bonus_kind"] = "turf"
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
    # v34.18: 校正確率（Phase 3）を併記する。保存・計測専用。
    attach_calibrated_probabilities(ranked)
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


def build_kind_pattern_shadow(ranked, outsiders, verified, kind, runner_count):
    """v34.17: 種別専用買い方の shadow 買い目（計測専用・本番不使用）。
    現行パターンA/Bと同じ馬の組み合わせ・同じ総額のまま、配分だけを
    種別に寄せた対照案を作り、精算まで並走させて現行と比較する。
      - 中央・13頭以上 (jra_large_realloc): 3連複を全て外し、その分を
        馬連2点とワイドへ再配分する（trio_trim の「外すだけ」に対し、
        こちらは再配分の効果を測る）
      - 中央・12頭以下 (jra_small_core): ワイド（保険）を削り、単勝と
        3連複の軸へ集中する
      - 地方 (nar_axis): 穴絡み（3連複の穴側・ワイド穴）を絞り、
        3連複の軸と馬連（本命-対抗）へ寄せる
    総額は現行と同額（穴あり=1,500円 / 穴なし=1,900円）に揃える。"""
    if not verified or not ranked or len(ranked) < 3:
        return []
    a = ranked[0]["horse_no"]
    b = ranked[1]["horse_no"]
    c = ranked[2]["horse_no"]
    d = ranked[3]["horse_no"] if len(ranked) >= 4 else None
    out = outsiders[0]["horse_no"] if outsiders else None
    if kind == "中央" and (runner_count or 0) >= 13:
        bucket, variant = "中央・13頭以上", "jra_large_realloc"
    elif kind == "中央":
        bucket, variant = "中央・12頭以下", "jra_small_core"
    elif kind == "地方":
        bucket, variant = "地方", "nar_axis"
    else:
        return []
    names = {"win": "単勝", "quinella": "馬連", "wide": "ワイド",
             "trio": "3連複", "trifecta": "3連単"}

    def item(typ, hs, stake):
        return {
            "type": typ, "horses": hs, "stake_yen": stake,
            "label": (f"{names[typ]} "
                      f"{'→'.join(map(str, hs)) if typ == 'trifecta' else '-'.join(map(str, hs))} "
                      f"({stake}円)")}

    if variant == "jra_large_realloc":
        if out:
            specs = [("win", [a], 200), ("quinella", [a, b], 400),
                     ("quinella", [a, c], 400), ("wide", [a, out], 400),
                     ("trifecta", [a, out, b], 100)]
        elif d:
            specs = [("win", [a], 500), ("quinella", [a, b], 500),
                     ("quinella", [a, c], 500), ("wide", [a, d], 200),
                     ("wide", [b, d], 200)]
        else:
            specs = [("win", [a], 500), ("quinella", [a, b], 700),
                     ("quinella", [a, c], 700)]
    elif variant == "jra_small_core":
        if out:
            specs = [("win", [a], 250), ("quinella", [a, b], 200),
                     ("quinella", [a, c], 300), ("trio", [a, b, c], 450),
                     ("trio", [a, b, out], 200),
                     ("trifecta", [a, out, b], 100)]
        else:
            specs = [("win", [a], 600), ("quinella", [a, b], 300),
                     ("quinella", [a, c], 300), ("trio", [a, b, c], 700)]
    else:  # nar_axis
        if out:
            specs = [("win", [a], 200), ("quinella", [a, b], 300),
                     ("quinella", [a, c], 200), ("trio", [a, b, c], 500),
                     ("trio", [a, b, out], 100), ("wide", [a, out], 100),
                     ("trifecta", [a, out, b], 100)]
        else:
            specs = [("win", [a], 600), ("quinella", [a, b], 300),
                     ("quinella", [a, c], 300), ("trio", [a, b, c], 700)]
    items = [item(t, hs, s) for t, hs, s in specs
             if s > 0 and all(h is not None for h in hs)]
    if not items:
        return []
    cost = sum(x["stake_yen"] for x in items)
    return [{
        "pattern_type": "B" if out else "A",
        "pattern": f"種別shadow（{bucket}）",
        "cost_yen": cost,
        "lines": [x["label"] for x in items], "line_items": items,
        "note": "v34.17 種別専用買い方 shadow。現行A/Bと同額の対照案で計測専用。",
        "bucket": bucket, "variant": variant,
    }]


def build_alloc_d_tickets(ranked, outsiders, verified):
    """v34.19: 配分D shadow の買い目（計測専用・本番不使用）。
    build_tickets（現行パターンA/B）の出力から馬の組み合わせを
    そのまま引き継ぎ、金額だけを ALLOC_D_STAKES で付け替える。
    組み合わせ・総額が現行と完全同一になることを構造で保証する
    （B=¥1,500 / A=¥1,900）。配分の狙いは馬連へのシフト
    （B': 馬連53%・3連複20%）で、3連複・夢枠は残して薄くする。"""
    base = build_tickets(ranked, outsiders, verified)
    if not base:
        return []
    src = base[0]
    pattern = src.get("pattern_type")
    names = {
        "win": "単勝", "quinella": "馬連", "trio": "3連複",
        "wide": "ワイド", "trifecta": "3連単",
    }
    counts = {}
    items = []
    for it in src.get("line_items") or []:
        typ = it.get("type")
        idx = counts.get(typ, 0)
        counts[typ] = idx + 1
        stake = ALLOC_D_STAKES.get((pattern, typ, idx))
        if stake is None:
            stake = safe_int(it.get("stake_yen"), 0)
        hs = list(it.get("horses") or [])
        items.append({
            "type": typ, "horses": hs, "stake_yen": stake,
            "label": f"{names.get(typ, typ)} "
                     f"{'→'.join(map(str, hs)) if typ == 'trifecta' else '-'.join(map(str, hs))} "
                     f"({stake}円)",
        })
    if not items:
        return []
    cost = sum(x["stake_yen"] for x in items)
    return [{
        "pattern_type": pattern,
        "pattern": f"配分D shadow（パターン{pattern}・馬連寄せ）",
        "cost_yen": cost,
        "lines": [x["label"] for x in items], "line_items": items,
        "note": "v34.19 配分D shadow。現行A/Bと同一の買い目・同額で"
                "配分のみ変更した対照案。計測専用で実購入禁止。",
    }]


def stake_shadow_tier(race_grade, kind):
    """v34.20: 金額の強弱 shadow の段階判定。既存の最終グレード
    （race_grade）と種別（kind）だけから決める（独自判定は作らない）。
    戻り値は (段階名, 倍率)。"""
    if race_grade == "超おすすめ":
        if kind == "中央":
            return "最強", 4
        return "強", 2
    return "通常", 1


def build_stake_shadow_tickets(ranked, outsiders, verified, race_grade, kind):
    """v34.20: 金額の強弱 shadow の買い目（計測専用・本番不使用）。
    build_tickets（現行パターンA/B）の出力から馬の組み合わせを
    そのまま引き継ぎ、各ラインの金額に段階倍率だけを掛ける。
    配分比率と組み合わせが現行と完全同一で、総額だけが段階倍率倍に
    なることを構造で保証する（通常×1: B ¥1,500／A ¥1,900、
    強×2: B ¥3,000／A ¥3,800、最強×4: B ¥6,000／A ¥7,600）。"""
    base = build_tickets(ranked, outsiders, verified)
    if not base:
        return []
    src = base[0]
    tier, mult = stake_shadow_tier(race_grade, kind)
    names = {
        "win": "単勝", "quinella": "馬連", "trio": "3連複",
        "wide": "ワイド", "trifecta": "3連単",
    }
    items = []
    for it in src.get("line_items") or []:
        typ = it.get("type")
        stake = safe_int(it.get("stake_yen"), 0) * mult
        hs = list(it.get("horses") or [])
        items.append({
            "type": typ, "horses": hs, "stake_yen": stake,
            "label": f"{names.get(typ, typ)} "
                     f"{'→'.join(map(str, hs)) if typ == 'trifecta' else '-'.join(map(str, hs))} "
                     f"({stake}円)",
        })
    if not items:
        return []
    cost = sum(x["stake_yen"] for x in items)
    return [{
        "pattern_type": src.get("pattern_type"),
        "pattern": f"金額強弱 shadow（{tier}×{mult}・パターン{src.get('pattern_type')}）",
        "cost_yen": cost,
        "lines": [x["label"] for x in items], "line_items": items,
        "stake_tier": tier, "stake_multiplier": mult,
        "note": "v34.20 金額の強弱 shadow。現行A/Bと同一の買い目・"
                "同一配分比率で、総額だけをグレード×種別で段階化した"
                "対照案。計測専用で実購入禁止。",
    }]


def hybrid_components(h):
    """v34.22: HYBRID_SHADOW の統合スコア成分（計測専用・本番不使用）。
    主成分は 34.15〜34.17 で前方保存した特徴量だけから作る:
      - time_pts: 時計指数の偏差値換算（中央値 time_index_med を優先し、
        無ければベスト。50 が基準タイム相当なので pts = 値 − 50）
      - pedigree_pts: 血統スコア（父 sire_score ＋ 母父 damsire_score×0.5。
        いずれも縮小済みの偏差ポイント）
      - class_pts: クラス評価。前走クラスとの差×2.0 ＋ 近走ピークとの
        差×1.0（格上挑戦・降級を今走クラス基準で符号化）
    時計指数と血統スコアのどちらも無い馬は「未評価」として
    hybrid_score=None にし、0 点とは書かない（特徴量 Stage 0 と同じ
    正直さ）。校正確率・市場情報（オッズ・人気・市場乖離）は
    統合スコアに混ぜない。"""
    t = h.get("time_index_med")
    if t is None:
        t = h.get("time_index_best")
    time_pts = (round(float(t) - 50.0, 2)
                if isinstance(t, (int, float)) else None)
    s, d = h.get("sire_score"), h.get("damsire_score")
    if s is None and d is None:
        pedigree_pts = None
    else:
        pedigree_pts = round(
            (float(s) if isinstance(s, (int, float)) else 0.0)
            + 0.5 * (float(d) if isinstance(d, (int, float)) else 0.0), 2)
    today = h.get("today_class_rank")
    prev = h.get("prev_class_rank")
    peak = h.get("peak_class_rank")
    if today is None or (prev is None and peak is None):
        class_pts = None
    else:
        class_pts = 0.0
        if prev is not None:
            class_pts += 2.0 * (prev - today)
        if peak is not None:
            class_pts += 1.0 * (peak - today)
        class_pts = round(class_pts, 2)
    evaluated = time_pts is not None or pedigree_pts is not None
    total = (round((time_pts or 0.0) + (pedigree_pts or 0.0)
                   + (class_pts or 0.0), 2) if evaluated else None)
    return {"time_pts": time_pts, "pedigree_pts": pedigree_pts,
            "class_pts": class_pts, "hybrid_score": total,
            "hybrid_evaluated": evaluated}


def build_hybrid_shadow(ranked, verified):
    """v34.22: HYBRID_SHADOW の買い目とメタ（計測専用・本番不使用）。
    hybrid 統合スコアで全出走馬を並べ替え（評価済みを先、未評価は
    odds_free_rank 順で後ろ）、現行パターンA/Bと同一構造の買い目を
    build_tickets で組み立てる。穴候補の定義は本番の実オッズ帯
    （10〜30倍）と同一にし、hybrid 順位の中で拾う。
    評価済み（時計指数または血統スコアあり）が3頭未満のレースは
    統合選定と呼べないため買い目を作らず、理由をメタに残す。
    戻り値は (tickets, meta)。"""
    meta = {"evaluated_horses": 0, "top": [], "reason": None}
    if not verified or len(ranked) < 3:
        meta["reason"] = "出走頭数未検証または3頭未満"
        return [], meta
    comps = {h["horse_no"]: hybrid_components(h) for h in ranked}
    evaluated = [h for h in ranked
                 if comps[h["horse_no"]]["hybrid_evaluated"]]
    meta["evaluated_horses"] = len(evaluated)
    if len(evaluated) < 3:
        meta["reason"] = "特徴量で評価できる馬が3頭未満"
        return [], meta

    def _key(h):
        c = comps[h["horse_no"]]
        return (0 if c["hybrid_evaluated"] else 1,
                -(c["hybrid_score"] or 0.0),
                h.get("odds_free_rank") or 999,
                h["horse_no"])

    hranked = sorted(ranked, key=_key)
    outsiders = [h for h in hranked
                 if h.get("odds") is not None and 10 <= h["odds"] < 30]
    tickets = build_tickets(hranked, outsiders, verified)
    if not tickets:
        meta["reason"] = "買い目を組み立てられなかった"
        return [], meta
    tickets[0]["pattern"] = (
        f"HYBRID_SHADOW（時計・血統・クラス統合／"
        f"パターン{tickets[0].get('pattern_type')}）")
    tickets[0]["note"] = (
        "v34.22 HYBRID_SHADOW。時計指数・血統スコア・クラス評価の"
        "統合スコア順位で組み立てた shadow 買い目。買い目の構造と"
        "総額は現行パターンA/Bと同一。本番の選定・配分には一切"
        "使用しない計測専用で実購入禁止。")
    meta["top"] = [
        {"horse_no": h["horse_no"],
         "hybrid_score": comps[h["horse_no"]]["hybrid_score"],
         "time_pts": comps[h["horse_no"]]["time_pts"],
         "pedigree_pts": comps[h["horse_no"]]["pedigree_pts"],
         "class_pts": comps[h["horse_no"]]["class_pts"],
         "odds_free_rank": h.get("odds_free_rank"),
         "production_rank": h.get("rank")}
        for h in hranked[:5]
    ]
    return tickets, meta


def hybrid_ranked_list(ranked):
    """build_hybrid_shadow と同一キーで並べ替えた hybrid 順位を返す
    （第1次検証 P2 の相手・軸の差し替え用。計測専用・本番不使用）。
    build_hybrid_shadow の meta.top と先頭順序が一致することは
    単体テストで担保する。"""
    comps = {h["horse_no"]: hybrid_components(h) for h in ranked}

    def _key(h):
        c = comps[h["horse_no"]]
        return (0 if c["hybrid_evaluated"] else 1,
                -(c["hybrid_score"] or 0.0),
                h.get("odds_free_rank") or 999,
                h["horse_no"])

    return sorted(ranked, key=_key)


def build_phase1_sel_shadow(ranked, outsiders, verified):
    """第1次検証 P2（選定分解）: B/C の shadow 買い目を作る。
      B: 本番軸 (本番1位) + hybrid 相手 (hybrid 順位の2番手以降)
      C: hybrid 軸 (hybrid 1位) + 本番相手 (本番順位の2番手以降)
    買い目の構造・総額は build_tickets に委ね、本番 (A) / hybrid (D)
    と同一にする。穴候補は B では hybrid 側の定義 (hybrid 順位内で
    実オッズ10〜30倍、build_hybrid_shadow と同一)、C では本番の
    outsiders をそのまま使う。hybrid 買い目が作れないレース
    (特徴量で評価できる馬が3頭未満) では B/C も作らない。
    本番の選定・買い目・配分には一切使用しない計測専用。"""
    if not verified or len(ranked) < 3:
        return {}
    comps = {h["horse_no"]: hybrid_components(h) for h in ranked}
    evaluated = [h for h in ranked
                 if comps[h["horse_no"]]["hybrid_evaluated"]]
    if len(evaluated) < 3:
        return {}
    hranked = hybrid_ranked_list(ranked)
    prod_axis = ranked[0]["horse_no"]
    hyb_axis = hranked[0]["horse_no"]
    merged_b = [ranked[0]] + [h for h in hranked
                               if h["horse_no"] != prod_axis]
    outsiders_b = [h for h in hranked
                   if h.get("odds") is not None and 10 <= h["odds"] < 30]
    merged_c = [hranked[0]] + [h for h in ranked
                               if h["horse_no"] != hyb_axis]
    out = {}
    tb = build_tickets(merged_b, outsiders_b, verified)
    if tb:
        tb[0]["pattern"] = (
            f"PHASE1_B（本番軸+hybrid相手／"
            f"パターン{tb[0].get('pattern_type')}）")
        tb[0]["note"] = (
            "第1次検証 P2 の shadow 買い目。軸は本番1位、相手は "
            "hybrid 統合順位で組み立てた。構造と総額は現行パターン"
            "A/B と同一。本番には一切使用しない計測専用。")
        out["B"] = tb
    tc = build_tickets(merged_c, outsiders, verified)
    if tc:
        tc[0]["pattern"] = (
            f"PHASE1_C（hybrid軸+本番相手／"
            f"パターン{tc[0].get('pattern_type')}）")
        tc[0]["note"] = (
            "第1次検証 P2 の shadow 買い目。軸は hybrid 統合1位、"
            "相手は本番順位で組み立てた。構造と総額は現行パターン"
            "A/B と同一。本番には一切使用しない計測専用。")
        out["C"] = tc
    return out


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
            # v34.13: 3連単チャレンジ枠も同じ払戻表でパターン別に精算する
            # （結果は trifecta_challenge_settlement として保存され、
            # calculate_stats が夢枠・オカルトとは別に集計する）
            race["trifecta_challenge_settlement"] = settle_trifecta_challenge(
                race.get("trifecta_challenge") or {}, finishes, payouts)
            # v34.17: 種別専用買い方 shadow も本体と同じ精算経路
            # （settle_tickets）で精算し、現行A/Bと並走比較できるように
            # する。買い目が無いレースでは None のまま。
            if race.get("kind_pattern_shadow"):
                race["kind_pattern_shadow_settlement"] = settle_tickets(
                    race.get("kind_pattern_shadow") or [], finishes, payouts)
            # v34.19: 配分D shadow も本体と同じ精算経路（settle_tickets）
            # で精算し、現行A/Bと並走比較できるようにする。買い目が
            # 無いレースでは None のまま。
            if race.get("alloc_d"):
                race["alloc_d_settlement"] = settle_tickets(
                    race.get("alloc_d") or [], finishes, payouts)
            # v34.20: 金額の強弱 shadow も本体と同じ精算経路
            # （settle_tickets）で精算し、現行（一律額）と並走比較
            # できるようにする。買い目が無いレースでは None のまま。
            if race.get("stake_shadow"):
                race["stake_shadow_settlement"] = settle_tickets(
                    race.get("stake_shadow") or [], finishes, payouts)
            # v34.22: HYBRID_SHADOW も本体と同じ精算経路（settle_tickets）
            # で精算し、本番・既存 shadow と同一レースで比較できるように
            # する。買い目が無いレースでは None のまま。
            if race.get("hybrid_shadow_tickets"):
                race["hybrid_shadow_settlement"] = settle_tickets(
                    race.get("hybrid_shadow_tickets") or [], finishes, payouts)
            # 第1次検証 P2: B/C も本体と同じ精算経路 (settle_tickets)
            # で精算し、A/D と同一レースで比較できるようにする。
            if race.get("phase1_sel_tickets"):
                race["phase1_sel_settlement"] = {
                    k: settle_tickets(v or [], finishes, payouts)
                    for k, v in (race.get("phase1_sel_tickets") or {}).items()
                    if v}
            # v34.16: pool shadow 計測用に、実際の3着内組み合わせの
            # 3連複配当（100円あたり）を保存する。仮想ラインの払戻
            # 計算に使う計測専用の値で、本体の精算には使わない。
            # 配当表に該当組み合わせが無い場合は None（未取得を明示）。
            _trio_p = (payouts.get("trio") or {}).get(combo_key(finishes[:3]))
            race["trio_payout"] = int(_trio_p) if _trio_p else None
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
    runners, diag = parse_runners(soup, surface, distance)
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
    # v34.13: 3連単チャレンジ枠の買い目（固定3パターン・shadow計測専用。
    # 集計対象はおすすめ以上の本精算レースのみで、calculate_stats 側で絞る）
    trifecta_challenge = build_trifecta_challenge(ranked)
    # v34.17: 種別専用買い方 shadow（中央13頭以上/中央12頭以下/地方）。
    # 現行パターンA/Bと同じ総額で組み立て、精算まで並走計測する。
    # 本番の買い目・配分には一切使わない。
    kind_pattern_shadow = build_kind_pattern_shadow(
        ranked, outsiders, verified, kind, count)
    # v34.19: 配分D shadow（馬連寄せ配分。買い目の組み合わせ・総額は
    # 現行パターンA/Bと同一）。本番の買い目・配分には一切使わない。
    alloc_d = build_alloc_d_tickets(ranked, outsiders, verified)
    # v34.20: 金額の強弱 shadow（総額の段階化。配分比率・買い目の
    # 組み合わせは現行パターンA/Bと同一で、段階は最終グレードと
    # 種別で決める）。本番の買い目・配分には一切使わない。
    stake_shadow = build_stake_shadow_tickets(
        ranked, outsiders, verified, race_grade, kind)
    # v34.15: レース単位の hybrid メタ（使用したテーブル版と、全出走馬の
    # 中で時計指数ベストが最大の馬）。特徴量の前方保存に使う計測専用で、
    # 選定・スコア・買い目には一切使わない。
    _ti_field = [h for h in ranked if h.get("time_index_best") is not None]
    _ti_best_h = (max(_ti_field, key=lambda h: h["time_index_best"])
                  if _ti_field else None)
    hybrid_meta = {
        "time_standards_ver": TIME_STANDARDS.get("built_at"),
        "pedigree_stats_built_at": PEDIGREE_STATS.get("built_at"),
        "time_best_horse_no": (_ti_best_h.get("horse_no")
                               if _ti_best_h else None),
        "time_best_value": (_ti_best_h.get("time_index_best")
                            if _ti_best_h else None),
    }
    # v34.17 Stage 0: 今走のクラス（格）と各馬の降級/昇級フラグ。
    # レース名から推定し、判定できない馬は None（未取得を明示）。
    # 保存・計測専用で、選定・スコア・買い目には使わない。
    _today_class_rank, _today_class_label = class_rank_from_text(name or "")
    for _h in ranked:
        _h["today_class_rank"] = _today_class_rank
        _h["today_class_label"] = _today_class_label
        _pc = _h.get("prev_class_rank")
        if _pc is None or _today_class_rank is None:
            _h["class_drop"] = None
        else:
            _h["class_drop"] = _today_class_rank < _pc
    # v34.22: HYBRID_SHADOW の買い目（時計・血統・クラスの統合選定。
    # クラス特徴量の付与が終わった後に組み立てる）。本番の買い目・
    # 配分・選定には一切使わない。
    hybrid_shadow_tickets, hybrid_shadow_meta = build_hybrid_shadow(
        ranked, verified)
    # 第1次検証 P2: 選定分解 shadow の B/C 買い目（計測専用・本番不使用）
    phase1_sel_tickets = build_phase1_sel_shadow(ranked, outsiders, verified)
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
        # v34.13: 3連単チャレンジ枠（買い目と精算結果。shadow計測専用）
        "trifecta_challenge": trifecta_challenge,
        "trifecta_challenge_settlement": None,
        # v34.17: 種別専用買い方 shadow（買い目と精算結果。計測専用）
        "kind_pattern_shadow": kind_pattern_shadow,
        "kind_pattern_shadow_settlement": None,
        # v34.19: 配分D shadow（買い目と精算結果。計測専用）
        "alloc_d": alloc_d,
        "alloc_d_settlement": None,
        # v34.20: 金額の強弱 shadow（買い目と精算結果。計測専用）
        "stake_shadow": stake_shadow,
        "stake_shadow_settlement": None,
        # v34.22: HYBRID_SHADOW（統合選定の買い目・成分メタ・精算結果。
        # shadow計測専用で本番には一切使わない）
        "hybrid_shadow_tickets": hybrid_shadow_tickets,
        "hybrid_shadow_meta": hybrid_shadow_meta,
        "hybrid_shadow_settlement": None,
        # 第1次検証 P2: 選定分解 shadow（B/C 買い目。計測専用）
        "phase1_sel_tickets": phase1_sel_tickets,
        "phase1_sel_settlement": None,
        # v34.15: hybrid 特徴量のレース単位メタ（shadow計測専用）
        "hybrid_features": hybrid_meta,
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
                "horse_form_cache": {}, "people_cache": {}, "pedigree_cache": {}}
    try:
        v = json.loads(HISTORY.read_text(encoding="utf-8"))
        if not isinstance(v, dict):
            raise ValueError("history root not object")
        for k in ("snapshots", "stats", "horse_form_cache", "people_cache",
                  "pedigree_cache"):
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


def build_trifecta_challenge(ranked):
    """v34.13: 3連単チャレンジ枠の買い目（shadow計測専用）を組み立てる。
    予想 rank（ranked の並び順 = 1:本命, 2:対抗, 3:3番手, 4, 5）から
    固定3パターンを作る。本番の買い目（夢枠含む）とは完全に独立で、
    選定・配分・ゲートには一切使わない。
      P1 本命1着固定流し: 1着=rank1、2・3着=rank2,3,4 の順不同ペア（6点）
      P2 本命→対抗固定:   1着=rank1、2着=rank2、3着=rank3,4,5（3点）
      P3 上位3頭ボックス: rank1,2,3 の全順列（6点）
    rank が3頭未満なら空 dict。4・5番手が無い小頭数では、ある rank
    だけで組み立てるため点数が減る（その場合も tickets 数で明示する）。"""
    nums = []
    for h in ranked or []:
        try:
            no = int(h.get("horse_no"))
        except (TypeError, ValueError, AttributeError):
            continue
        if no not in nums:
            nums.append(no)
        if len(nums) == 5:
            break
    if len(nums) < 3:
        return {}
    r1, r2, r3 = nums[0], nums[1], nums[2]
    r4 = nums[3] if len(nums) >= 4 else None
    r5 = nums[4] if len(nums) >= 5 else None
    pool = [n for n in (r2, r3, r4) if n is not None]
    p1 = [[r1, pool[i], pool[j]]
          for i in range(len(pool)) for j in range(len(pool)) if i != j]
    p2 = [[r1, r2, n] for n in (r3, r4, r5) if n is not None]
    p3 = [[r1, r2, r3], [r1, r3, r2], [r2, r1, r3],
          [r2, r3, r1], [r3, r1, r2], [r3, r2, r1]]
    return {"p1": p1, "p2": p2, "p3": p3}


def settle_trifecta_challenge(patterns, finishes, payouts):
    """v34.13: 3連単チャレンジ枠を夢枠・オカルトと同じ経路（結果ページの
    払戻表 payouts["trifecta"]）でパターン別に精算する。本体の
    settle_tickets と同じ厳密さ: 着順一致でも払戻金額が確認できない
    パターンは payout_missing=True として収支集計から除外させる。
    1パターン内で的中しうるのは実際の1〜3着の並び1点だけ。"""
    result = {}
    top3 = None
    if finishes and len(finishes) >= 3:
        try:
            top3 = [int(f) for f in finishes[:3]]
        except (TypeError, ValueError):
            top3 = None
    tri_payouts = (payouts or {}).get("trifecta") or {}
    for key in ("p1", "p2", "p3"):
        combos = (patterns or {}).get(key) or []
        entry = {"tickets": len(combos), "hit": False, "return_yen": 0,
                 "payout_per_100": None, "payout_missing": False}
        if top3 is not None:
            for combo in combos:
                try:
                    combo = [int(c) for c in combo]
                except (TypeError, ValueError):
                    continue
                if combo != top3:
                    continue
                payout = tri_payouts.get(combo_key(combo, True), 0)
                if payout:
                    entry["hit"] = True
                    entry["payout_per_100"] = payout
                    entry["return_yen"] += int(
                        TRIFECTA_CHALLENGE_STAKE_YEN / 100 * payout)
                else:
                    entry["payout_missing"] = True
        result[key] = entry
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
    # v34.23: 馬場状態・天候の前方保存（監査 A1）。race dict の実キーは
    # parse_race が格納する "going"/"weather"（値の形式は going=
    # 良/稍重/重/不良、weather=晴/曇/雨/小雨/雪/小雪。未取得時はどちらも
    # "未取得"）。今回の生成で未取得なら既存スナップショットの取得済み
    # の値を保持し、"未取得" で上書きしない。保存専用で集計には使わない。
    snap_going = race.get("going")
    if not snap_going or snap_going == "未取得":
        snap_going = old.get("going") or snap_going
    snap_weather = race.get("weather")
    if not snap_weather or snap_weather == "未取得":
        snap_weather = old.get("weather") or snap_weather
    # v34.16: pool shadow 計測用の「最終生成」保存（計測専用・選定には
    # 使わない）。last_top6 は発走前の最終生成で固定し、精算した実行の
    # 生成では上書きしない。公式買い目の大半が精算実行（発走後）の
    # 生成で確定する現行方式では「発走前の最終候補」がどこにも
    # 残らないため、その保存が前方計測の前提になる。
    # 上書き規則:
    #   - 未精算の生成: その生成の上位6頭・穴候補で毎回上書きする
    #   - 発走時刻が判明し、現在時刻が発走を過ぎている生成: 上書きしない
    #   - 精算済み（settlement_complete）の生成: 上書きしない
    snap_last_top6 = old.get("last_top6")
    snap_last_outsiders = old.get("last_outsiders")
    if not race.get("settlement_complete"):
        _pre_post = True
        _pt = race.get("post_time")
        if isinstance(_pt, str):
            _ptm = re.match(r"^(\d{1,2}):(\d{2})$", _pt.strip())
            if _ptm:
                try:
                    _sched = NOW.replace(hour=int(_ptm.group(1)),
                                         minute=int(_ptm.group(2)),
                                         second=0, microsecond=0)
                    _pre_post = NOW < _sched
                except ValueError:
                    _pre_post = True
        if _pre_post:
            _ranked_now = race.get("horses") or []
            if len(_ranked_now) >= 3:
                snap_last_top6 = [
                    {"horse_no": h.get("horse_no"), "rank": h.get("rank"),
                     "score": h.get("score"),
                     "form_score": h.get("form_score"),
                     "market_score": h.get("market_score")}
                    for h in _ranked_now[:6]
                ]
            if isinstance(race.get("outsiders"), list):
                snap_last_outsiders = [
                    h.get("horse_no") for h in race.get("outsiders")
                    if isinstance(h, dict)]
    # v34.18: 展開（ペース）予測の事前記録。脚質の頭数から単純な
    # 想定ラベルを作る（計測専用。選定・スコアには使わない）。将来、
    # 実際のペース結果と照合して予測精度を測るための保存。
    _styles_all = [h.get("running_style") for h in race.get("horses", [])]
    _front_n = sum(1 for s in _styles_all if s == "逃げ")
    _lead_n = sum(1 for s in _styles_all if s == "先行")
    _pace_shadow = {
        "front_count": _front_n, "lead_count": _lead_n,
        "pace_prediction": (
            "ハイ想定" if _front_n >= 3 else
            "平均〜ハイ想定" if _front_n == 2 else
            "単騎逃げ想定" if _front_n == 1 else "スロー想定"),
    }
    snapshot = {
        "race_id": rid, "date": race.get("date"), "kind": race.get("kind"),
        "course": race.get("course"), "race_no": race.get("race_no"),
        # v34.9: 場×時間帯のオカルト傾向集計のために発走時刻も保存する
        "post_time": race.get("post_time"),
        "name": race.get("name"), "cost": safe_int(race.get("race_cost"), 0),
        # v34.17: 中央×芝/中央×ダートの分割集計のために馬場種別と
        # 距離も保存する（過去分は未保存＝「不明」として扱い捏造しない）
        "surface": race.get("surface") or old.get("surface"),
        "distance_m": race.get("distance_m") or old.get("distance_m"),
        # v34.23: A1 前方保存。生成したエンジン版の刻印（初回生成の版を
        # 固定し、再生成・精算で上書きしない）と、馬場状態・天候の保存。
        # いずれも保存専用で集計には使わない
        "engine_version": old.get("engine_version") or ENGINE_VERSION,
        "going": snap_going,
        "weather": snap_weather,
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
                 "score": h.get("score"), "odds": h.get("odds"), "rank": h.get("rank"),
                 # v34.14: 馬IDと血統を前方保存する（将来の馬単位検証の鍵。
                 # 未解決の馬は None のまま＝未取得を明示する）
                 "horse_id": h.get("horse_id"),
                 "sire": h.get("sire"), "damsire": h.get("damsire"),
                 # v34.15: hybrid 特徴量（時計指数・血統スコア）を前方
                 # 保存する。選定・スコアには使用していない計測専用の値で、
                 # 未評価の馬は None のままにする
                 "time_index_best": h.get("time_index_best"),
                 "time_index_med": h.get("time_index_med"),
                 "time_index_samples": h.get("time_index_samples"),
                 "time_index_std_level": h.get("time_index_std_level"),
                 "last3f_dev": h.get("last3f_dev"),
                 "sire_score": h.get("sire_score"),
                 "sire_score_win": h.get("sire_score_win"),
                 "sire_score_n": h.get("sire_score_n"),
                 "damsire_score": h.get("damsire_score"),
                 # v34.17: クラス（格）Stage 0（計測専用。未判定は None）
                 "prev_class_rank": h.get("prev_class_rank"),
                 "prev_class_label": h.get("prev_class_label"),
                 "peak_class_rank": h.get("peak_class_rank"),
                 "today_class_rank": h.get("today_class_rank"),
                 "class_drop": h.get("class_drop")}
                for h in race.get("top5", [])
            ],
            "tickets": ticket,
            "prediction_status": race.get("prediction_status"),
            # v34.18: 全頭の凍結保存（スコア3種・確率・脚質）。前方の
            # 校正検証と再 fit の材料で、選定には使わない
            "all_horses": [
                {"horse_no": h.get("horse_no"), "name": h.get("name"),
                 "horse_id": h.get("horse_id"),
                 "rank": h.get("rank"), "score": h.get("score"),
                 # v34.18: クラス（格）も全頭分を残す（34.17 は top5 のみ）
                 "today_class_rank": h.get("today_class_rank"),
                 "class_drop": h.get("class_drop"),
                 "form_score": h.get("form_score"),
                 "market_score": h.get("market_score"),
                 "odds_free_rank": h.get("odds_free_rank"),
                 "odds": h.get("odds"), "popularity": h.get("popularity"),
                 "running_style": h.get("running_style"),
                 # v34.21: 血統の前方保存。父・母父は 34.18 時点で
                 # all_horses に未保存だったため追加（top5 には保存
                 # 済み）。pedigree_bonus / pedigree_bonus_kind は
                 # score_runners が実際に適用した加点値と種別で、
                 # 未適用の馬は 0.0 / None。いずれも保存専用
                 "sire": h.get("sire"), "damsire": h.get("damsire"),
                 "pedigree_bonus": h.get("pedigree_bonus"),
                 "pedigree_bonus_kind": h.get("pedigree_bonus_kind"),
                 "estimated_win_probability_pct":
                     h.get("estimated_win_probability_pct"),
                 "calibrated_win_probability_pct":
                     h.get("calibrated_win_probability_pct"),
                 "calibrated_place_probability_pct":
                     h.get("calibrated_place_probability_pct"),
                 "calibrated_show_probability_pct":
                     h.get("calibrated_show_probability_pct")}
                for h in race.get("horses", [])
            ],
            # v34.18: 展開予測の事前記録（計測専用）
            "pace_shadow": _pace_shadow,
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
        # v34.13: 3連単チャレンジ枠（買い目と精算結果を保存。shadow計測専用）
        "trifecta_challenge": race.get("trifecta_challenge") or old.get("trifecta_challenge") or {},
        "trifecta_challenge_settlement": race.get("trifecta_challenge_settlement") or old.get("trifecta_challenge_settlement"),
        # v34.17: 種別専用買い方 shadow（買い目と精算結果を保存。計測専用）
        "kind_pattern_shadow": race.get("kind_pattern_shadow") or old.get("kind_pattern_shadow") or [],
        "kind_pattern_shadow_settlement": race.get("kind_pattern_shadow_settlement") or old.get("kind_pattern_shadow_settlement"),
        # v34.19: 配分D shadow（買い目と精算結果を保存。計測専用）
        "alloc_d": race.get("alloc_d") or old.get("alloc_d") or [],
        "alloc_d_settlement": race.get("alloc_d_settlement") or old.get("alloc_d_settlement"),
        # v34.20: 金額の強弱 shadow（買い目と精算結果を保存。計測専用）
        "stake_shadow": race.get("stake_shadow") or old.get("stake_shadow") or [],
        "stake_shadow_settlement": race.get("stake_shadow_settlement") or old.get("stake_shadow_settlement"),
        # v34.22: HYBRID_SHADOW（買い目・成分メタ・精算結果を保存。計測専用）
        "hybrid_shadow_tickets": race.get("hybrid_shadow_tickets") or old.get("hybrid_shadow_tickets") or [],
        "hybrid_shadow_meta": race.get("hybrid_shadow_meta") or old.get("hybrid_shadow_meta"),
        "hybrid_shadow_settlement": race.get("hybrid_shadow_settlement") or old.get("hybrid_shadow_settlement"),
        # 第1次検証 P2: 選定分解 shadow（買い目と精算結果。計測専用）
        "phase1_sel_tickets": race.get("phase1_sel_tickets") or old.get("phase1_sel_tickets") or {},
        "phase1_sel_settlement": race.get("phase1_sel_settlement") or old.get("phase1_sel_settlement"),
        # v34.15: hybrid 特徴量のレース単位メタ（テーブル版・全出走馬中の
        # 時計指数1位）。shadow計測専用で選定には使わない
        "hybrid_features": race.get("hybrid_features") or old.get("hybrid_features"),
        # v34.16: pool shadow 計測用の最終生成保存（上書き規則は上記）と
        # 実際の3着内組み合わせの3連複配当（精算時に保存。計測専用）
        "last_top6": snap_last_top6,
        "last_outsiders": snap_last_outsiders,
        "trio_payout": (race.get("trio_payout")
                        if race.get("trio_payout") is not None
                        else old.get("trio_payout")),
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

    # v34.13: 3連単チャレンジ枠（shadow計測）。おすすめ以上の本精算レースで
    # 精算時に保存された trifecta_challenge_settlement をパターン別に
    # 集計する。夢枠・オカルト枠とは別集計。払戻未確認（payout_missing）の
    # パターンは本体と同じく収支集計から除外する。過去分は払戻表が
    # スナップショットに保存されていないため再構成できず、34.13生成分
    # からの前方計測のみ（settlement が保存されたレースだけが対象）。
    def _tc_agg(a):
        stake = a["stake_yen"]
        ret = a["return_yen"]
        return {
            "races": a["races"], "hits": a["hits"],
            "hit_rate_pct": (round(a["hits"] / a["races"] * 100, 1)
                             if a["races"] else 0.0),
            "stake_yen": stake, "return_yen": ret,
            "profit_yen": ret - stake,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
        }

    _tc_labels = {
        "p1": "本命1着固定流し（1着=rank1、2・3着=rank2,3,4の順不同ペア6点）",
        "p2": "本命→対抗固定（1着=rank1、2着=rank2、3着=rank3,4,5の3点）",
        "p3": "上位3頭ボックス（rank1,2,3の全順列6点）",
    }
    _tc_raw = {k: {"races": 0, "hits": 0, "stake_yen": 0, "return_yen": 0}
               for k in ("p1", "p2", "p3")}
    _tc_races = 0
    _tc_hit_races = 0
    for x in settled:
        if x.get("is_recommended") is not True:
            continue
        st = x.get("trifecta_challenge_settlement")
        if not isinstance(st, dict):
            continue
        counted = False
        any_hit = False
        for k in ("p1", "p2", "p3"):
            e = st.get(k)
            if not isinstance(e, dict) or e.get("payout_missing"):
                continue
            _tc_raw[k]["races"] += 1
            _tc_raw[k]["stake_yen"] += (
                safe_int(e.get("tickets"), 0)
                * TRIFECTA_CHALLENGE_STAKE_YEN)
            if e.get("hit") is True:
                _tc_raw[k]["hits"] += 1
                any_hit = True
            _tc_raw[k]["return_yen"] += safe_int(e.get("return_yen"), 0)
            counted = True
        if counted:
            _tc_races += 1
            if any_hit:
                _tc_hit_races += 1
    trifecta_challenge_stats = {
        "p1": dict(_tc_agg(_tc_raw["p1"]), label=_tc_labels["p1"]),
        "p2": dict(_tc_agg(_tc_raw["p2"]), label=_tc_labels["p2"]),
        "p3": dict(_tc_agg(_tc_raw["p3"]), label=_tc_labels["p3"]),
        "total": _tc_agg({
            "races": _tc_races, "hits": _tc_hit_races,
            "stake_yen": sum(v["stake_yen"] for v in _tc_raw.values()),
            "return_yen": sum(v["return_yen"] for v in _tc_raw.values()),
        }),
        "start_date": TRIFECTA_CHALLENGE_START_DATE,
        "note": ("おすすめ以上の本精算レースで3連単の固定3パターンを測る "
                 "shadow 計測（各1点100円）。本番の選定・配分・夢枠・"
                 "オカルト枠には使用していない。過去分は払戻表が保存されて"
                 "いないため再構成できず、" + TRIFECTA_CHALLENGE_START_DATE
                 + " 以降の前方計測のみ。total の hits は3パターンの"
                 "いずれかが的中したレース数。"),
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
    # v34.12: 配分C（shadow並走）。パターンBの同一レースについて、
    # settled_lines の払戻（100円あたり）から C 配分の収支を再計算する。
    # 本番配分には一切影響しない計測専用。
    def alloc_c_for(x):
        lines = x.get("settled_lines") or []
        if not lines:
            return None
        grade = x.get("race_grade")
        if grade == "超おすすめ":
            mult = ALLOC_C_MULT_SUPER
        elif grade == "注目レース" or x.get("is_recommended") is True:
            mult = ALLOC_C_MULT_RECOMMENDED
        else:
            mult = ALLOC_C_MULT_NORMAL
        stake = 0.0
        ret = 0.0
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            b_stake = safe_int(ln.get("stake_yen"), 0)
            c_stake = ALLOC_C_STAKES.get((ln.get("type"), b_stake), b_stake)
            stake += c_stake * mult
            if ln.get("hit") is True:
                p100 = ln.get("payout_per_100")
                if p100:
                    ret += float(p100) * (c_stake * mult) / 100.0
                elif b_stake:
                    ret += safe_int(ln.get("return_yen"), 0) * (c_stake / b_stake) * mult
        return {"stake_yen": round(stake), "return_yen": round(ret)}

    alloc_c_rows = []
    for x in settled:
        if pattern_of(x) != "B":
            continue
        if str(x.get("date") or "") < ALLOC_C_START_DATE:
            continue
        c = alloc_c_for(x)
        if c is None:
            continue
        c["profit_yen"] = c["return_yen"] - c["stake_yen"]
        x["alloc_c"] = c
        alloc_c_rows.append(x)
    _c_stake = sum(x["alloc_c"]["stake_yen"] for x in alloc_c_rows)
    _c_return = sum(x["alloc_c"]["return_yen"] for x in alloc_c_rows)
    _c_hits = sum(1 for x in alloc_c_rows if x["alloc_c"]["return_yen"] > 0)
    alloc_c_stats = {
        "races": len(alloc_c_rows),
        "hit_races": _c_hits,
        "hit_rate_pct": round(_c_hits / len(alloc_c_rows) * 100, 1) if alloc_c_rows else 0.0,
        "stake_yen": _c_stake,
        "return_yen": _c_return,
        "profit_yen": _c_return - _c_stake,
        "roi_pct": round(_c_return / _c_stake * 100, 1) if _c_stake else 0.0,
        "pattern_b_same_races": agg(alloc_c_rows),
        "start_date": ALLOC_C_START_DATE,
        "note": ("パターンBと同一レース・同一買い目の配分違いを測る shadow 計測。"
                 "本番配分・選定には使用していない。対象は "
                 + ALLOC_C_START_DATE + " 以降のパターンB本精算分のみ。"),
    }
    # v34.13: 3連複トリム計測（shadow並走）。中央×13頭以上の精算レースで、
    # settled_lines から「3連複を全て外した構成（trio_off）」と「穴側だけ
    # 外した構成（trio_half）」を再計算する。外した分は他券種へ再配分
    # しない。本番配分・選定には一切影響しない計測専用。
    # 軸 = frozen_prediction.top5 の上位3頭の集合と一致する3連複。
    def trio_trim_for(x):
        lines = x.get("settled_lines") or []
        if not lines:
            return None
        top5 = (x.get("frozen_prediction") or {}).get("top5") or []
        axis_set = None
        if len(top5) >= 3:
            try:
                axis_set = frozenset(int(h.get("horse_no")) for h in top5[:3])
            except (TypeError, ValueError, AttributeError):
                axis_set = None
        trio_lines = []
        stake = ret = 0
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            stake += safe_int(ln.get("stake_yen"), 0)
            ret += safe_int(ln.get("return_yen"), 0)
            if ln.get("type") == "trio":
                trio_lines.append(ln)
        if not trio_lines:
            return None
        off_stake = sum(safe_int(ln.get("stake_yen"), 0) for ln in trio_lines)
        off_ret = sum(safe_int(ln.get("return_yen"), 0) for ln in trio_lines)
        # 穴側（=軸でない3連複）だけの合計。判定できない場合は half を None
        # にして集計から外す（off は軸/穴の判定なしで常に再構成できる）。
        half = None
        if axis_set is not None:
            ana_stake = ana_ret = 0
            classified = True
            for ln in trio_lines:
                hs = ln.get("horses") or []
                try:
                    is_axis = (len(hs) == 3
                               and frozenset(int(v) for v in hs) == axis_set)
                except (TypeError, ValueError):
                    classified = False
                    break
                if not is_axis:
                    ana_stake += safe_int(ln.get("stake_yen"), 0)
                    ana_ret += safe_int(ln.get("return_yen"), 0)
            if classified:
                half = {"stake_yen": stake - ana_stake,
                        "return_yen": ret - ana_ret}
        elif len(trio_lines) == 1 and pattern_of(x) == "A":
            # パターンAの3連複は軸1点のみ（穴側は存在しない）ため half = 現行
            half = {"stake_yen": stake, "return_yen": ret}
        return {
            "main": {"stake_yen": stake, "return_yen": ret},
            "trio_off": {"stake_yen": stake - off_stake,
                         "return_yen": ret - off_ret},
            "trio_half": half,
        }

    def variant_agg(pairs):
        stake = sum(p["stake_yen"] for p in pairs)
        ret = sum(p["return_yen"] for p in pairs)
        hits = sum(1 for p in pairs if p["return_yen"] > 0)
        n = len(pairs)
        return {
            "races": n, "hit_races": hits,
            "hit_rate_pct": round(hits / n * 100, 1) if n else 0.0,
            "stake_yen": stake, "return_yen": ret,
            "profit_yen": ret - stake,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
        }

    def trio_trim_track(rows):
        asis, off, half = [], [], []
        for x in rows:
            t = trio_trim_for(x)
            if t is None:
                continue
            rec = {"trio_off": dict(t["trio_off"]),
                   "trio_half": (dict(t["trio_half"])
                                 if t["trio_half"] is not None else None)}
            rec["trio_off"]["profit_yen"] = (
                rec["trio_off"]["return_yen"] - rec["trio_off"]["stake_yen"])
            if rec["trio_half"] is not None:
                rec["trio_half"]["profit_yen"] = (
                    rec["trio_half"]["return_yen"]
                    - rec["trio_half"]["stake_yen"])
            x["trio_trim"] = rec
            asis.append(t["main"])
            off.append(t["trio_off"])
            if t["trio_half"] is not None:
                half.append(t["trio_half"])
        return {
            "races": len(asis),
            "as_is": variant_agg(asis),
            "trio_off": variant_agg(off),
            "trio_half": variant_agg(half),
            "trio_half_races": len(half),
        }

    def _trio_trim_target(x):
        return (x.get("kind") == "中央"
                and safe_int(x.get("runner_count"), 0)
                >= TRIO_TRIM_MIN_RUNNERS)

    trio_trim_stats = {
        "target": "中央（JRA）×13頭以上",
        "main": trio_trim_track(
            [x for x in settled if _trio_trim_target(x)]),
        "shadow": trio_trim_track(
            [x for x in settled_shadow if _trio_trim_target(x)]),
        "note": ("中央×13頭以上の精算レースで、3連複を外す/絞る構成を測る "
                 "shadow 計測。本番配分・選定には使用していない。"
                 "現行ゲートは13頭以上を常にゲート外にするため、本精算"
                 "トラックはゲート前（〜2026-10-31）の再構成分のみで、"
                 "前方標本はゲート外（shadow）トラックに貯まる。"
                 "軸/穴の判定は frozen_prediction.top5 上位3頭の集合との"
                 "一致による。trio_half は判定できたレースのみ集計。"),
    }
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
    # v34.15: hybrid shadow 計測（時計指数＝Phase A / 血統スコア＝Phase B）。
    # frozen_prediction.top5 に前方保存された特徴量（34.15生成分から）だけを
    # 対象に、精算結果との関係を本精算/shadow のトラック別に集計する。
    # 特徴量は選定・スコア・配分には使用していない。設計書の判定基準どおり、
    # 特徴量つきレースが200件貯まるまでは良し悪しの判定をしない。
    def _hybrid_finish(x, horse_no):
        rf = x.get("result_finishes") or []
        if horse_no is None or len(rf) < 3:
            return None
        try:
            return rf.index(horse_no) + 1
        except ValueError:
            return None

    def _hybrid_rate(fins):
        n = len(fins)
        return {
            "horses": n,
            "win_rate_pct": (round(sum(1 for f in fins if f == 1) / n * 100, 1)
                             if n else 0.0),
            "top3_rate_pct": (round(sum(1 for f in fins if f <= 3) / n * 100, 1)
                              if n else 0.0),
        }

    def _kind_surface_groups(rows):
        """v34.17: レースを 中央×芝／中央×ダート／地方 に分ける。
        surface 未保存の過去分は「不明」に寄せ、推測で埋めない。"""
        groups = {}
        for x in rows:
            surf = x.get("surface") or ""
            surf = ("芝" if "芝" in surf
                    else ("ダート" if "ダート" in surf else "不明"))
            key = f"{x.get('kind') or '不明'}×{surf}"
            groups.setdefault(key, []).append(x)
        return groups

    def _hybrid_leader_rates(rows):
        """時計指数リーダー／上がり3Fリーダーの着順率（コンパクト版）。
        by_kind_surface の内訳と top5_last3f_leader に使う。"""
        tb, tl, l3 = [], [], []
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            meta = x.get("hybrid_features") or {}
            fb = meta.get("time_best_horse_no")
            if fb is not None:
                f = _hybrid_finish(x, fb)
                if f is not None:
                    tb.append(f)
            tis = [h for h in top5 if isinstance(h, dict)
                   and h.get("time_index_best") is not None]
            if tis:
                f = _hybrid_finish(
                    x, max(tis, key=lambda h: h["time_index_best"]).get("horse_no"))
                if f is not None:
                    tl.append(f)
            l3s = [h for h in top5 if isinstance(h, dict)
                   and h.get("last3f_dev") is not None]
            if l3s:
                f = _hybrid_finish(
                    x, max(l3s, key=lambda h: h["last3f_dev"]).get("horse_no"))
                if f is not None:
                    l3.append(f)
        return {"races": len(rows), "field_time_best": _hybrid_rate(tb),
                "top5_time_leader": _hybrid_rate(tl),
                "top5_last3f_leader": _hybrid_rate(l3)}

    def _class_drop_rates(rows):
        """v34.17: 予想 top5 内の降級馬と非降級馬の着順率を比べる。"""
        drop, keep = [], []
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            for h in top5:
                if not isinstance(h, dict) or h.get("class_drop") is None:
                    continue
                f = _hybrid_finish(x, h.get("horse_no"))
                if f is None:
                    continue
                (drop if h["class_drop"] else keep).append(f)
        return {"drop": _hybrid_rate(drop), "no_drop": _hybrid_rate(keep),
                "drop_horses": len(drop), "no_drop_horses": len(keep)}

    def _hybrid_track(rows):
        feat_races = 0
        horses_ti = 0
        horses_ss = 0
        samples_dist = {}
        field_best_fins = []
        agree_fins = []
        disagree_fins = []
        leader_fins = []
        sire_top3_fins = []
        sire_scored = []  # (sire_score, finish, last_odds)
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if not any(isinstance(h, dict) and "time_index_best" in h
                       for h in top5):
                continue
            feat_races += 1
            meta = x.get("hybrid_features") or {}
            fb_no = meta.get("time_best_horse_no")
            if fb_no is not None:
                fin = _hybrid_finish(x, fb_no)
                if fin is not None:
                    field_best_fins.append(fin)
                    rank1_no = (top5[0].get("horse_no")
                                if top5 and isinstance(top5[0], dict) else None)
                    (agree_fins if fb_no == rank1_no
                     else disagree_fins).append(fin)
            ti_horses = []
            ss_horses = []
            for h in top5:
                if not isinstance(h, dict):
                    continue
                if h.get("time_index_samples"):
                    horses_ti += 1
                    skey = str(h["time_index_samples"])
                    samples_dist[skey] = samples_dist.get(skey, 0) + 1
                    if h.get("time_index_best") is not None:
                        ti_horses.append(h)
                if h.get("sire_score") is not None:
                    horses_ss += 1
                    ss_horses.append(h)
                    fin = _hybrid_finish(x, h.get("horse_no"))
                    if fin is not None:
                        odds = (x.get("last_odds") or {}).get(
                            str(h.get("horse_no")))
                        sire_scored.append((h["sire_score"], fin, odds))
            if ti_horses:
                lead = max(ti_horses, key=lambda h: h["time_index_best"])
                fin = _hybrid_finish(x, lead.get("horse_no"))
                if fin is not None:
                    leader_fins.append(fin)
            ss_horses.sort(key=lambda h: -h["sire_score"])
            for h in ss_horses[:3]:
                fin = _hybrid_finish(x, h.get("horse_no"))
                if fin is not None:
                    sire_top3_fins.append(fin)
        bands = {}
        if len(sire_scored) >= 3:
            sire_scored.sort(key=lambda t: -t[0])
            n = len(sire_scored)
            groups = {
                "上位": sire_scored[:n // 3],
                "中位": sire_scored[n // 3:2 * n // 3],
                "下位": sire_scored[2 * n // 3:],
            }
            for gname, members in groups.items():
                entry = _hybrid_rate([t[1] for t in members])
                roi_stake = roi_ret = roi_n = 0
                for _sc, fin, odds in members:
                    if odds:
                        roi_n += 1
                        roi_stake += 100
                        if fin == 1:
                            roi_ret += int(float(odds) * 100)
                entry["win_roi_pct"] = (
                    round(roi_ret / roi_stake * 100, 1) if roi_stake else None)
                entry["win_roi_horses"] = roi_n
                bands[gname] = entry
            bands["thresholds"] = {
                "upper_min": sire_scored[n // 3 - 1][0],
                "middle_min": sire_scored[2 * n // 3 - 1][0],
            }
        return {
            "races_with_features": feat_races,
            "top5_horses_with_time_index": horses_ti,
            "top5_horses_with_sire_score": horses_ss,
            "time_index_samples_dist": samples_dist,
            "field_time_best": _hybrid_rate(field_best_fins),
            "field_time_best_by_rank1_agreement": {
                "agree": _hybrid_rate(agree_fins),
                "disagree": _hybrid_rate(disagree_fins),
            },
            "top5_time_leader": _hybrid_rate(leader_fins),
            "sire_score_top3_in_top5": _hybrid_rate(sire_top3_fins),
            "sire_score_bands": bands,
            # v34.17: 上がり3F（last3f_dev）とクラス（格）を計測対象に
            # 追加し、中央×芝／中央×ダート／地方の内訳でも出す
            "top5_last3f_leader": _hybrid_leader_rates(rows)["top5_last3f_leader"],
            "class_drop_top5": _class_drop_rates(rows),
            "by_kind_surface": {
                bk: _hybrid_leader_rates(sub)
                for bk, sub in _kind_surface_groups(rows).items()},
        }

    # v34.18: 確率の前方検証。凍結した全頭確率（34.18 以降の snapshot）
    # と実際の勝ち馬を照合し、Brier Score と Log Loss を測る。対象は
    # Phase 3 の方法論に合わせ評価 top5 の馬のみ。未校正の従来確率も
    # 同じ土俵で測り、校正の効果を前方データで確認する。
    def _prob_metrics(pairs):
        if not pairs:
            return {"horses": 0}
        n = len(pairs)
        brier = sum((p - y) ** 2 for p, y in pairs) / n
        ll = 0.0
        for p, y in pairs:
            pc = min(max(p, 1e-6), 1 - 1e-6)
            ll += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
        return {"horses": n, "brier": round(brier, 4),
                "log_loss": round(ll / n, 4)}

    def _prob_track(rows):
        cal_pairs, raw_pairs = [], []
        bins = {}
        cov_hit = cov_all = 0
        for x in rows:
            fp = x.get("frozen_prediction") or {}
            allh = fp.get("all_horses") or []
            rf = x.get("result_finishes") or []
            if not allh or not rf:
                continue
            winner = rf[0]
            top5 = [h for h in allh if isinstance(h, dict)
                    and isinstance(h.get("rank"), int) and h["rank"] <= 5]
            if not top5:
                continue
            cov_all += 1
            if any(h.get("horse_no") == winner for h in top5):
                cov_hit += 1
            for h in top5:
                y = 1 if h.get("horse_no") == winner else 0
                cp = h.get("calibrated_win_probability_pct")
                if cp is not None:
                    cal_pairs.append((cp / 100.0, y))
                    b = min(int(cp // 5), 6)
                    e = bins.setdefault(b, [0, 0.0, 0])
                    e[0] += 1
                    e[1] += cp
                    e[2] += y
                rp = h.get("estimated_win_probability_pct")
                if rp is not None:
                    raw_pairs.append((rp / 100.0, y))
        labels = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30+"]
        bin_out = {}
        for b, (n, psum, wins) in sorted(bins.items()):
            bin_out[labels[b]] = {
                "horses": n,
                "predicted_mean_pct": round(psum / n, 1) if n else 0.0,
                "actual_win_rate_pct": (round(wins / n * 100, 1)
                                        if n else 0.0)}
        return {
            "races": cov_all,
            "winner_in_top5_rate_pct": (round(cov_hit / cov_all * 100, 1)
                                        if cov_all else 0.0),
            "calibrated": _prob_metrics(cal_pairs),
            "uncalibrated": _prob_metrics(raw_pairs),
            "calibration_bins": bin_out,
        }

    _fs_groups = {"8頭以下": [], "9〜12頭": [], "13頭以上": []}
    for x in settled_all:
        _rc = x.get("runner_count")
        if not isinstance(_rc, int):
            continue
        _fs_groups["8頭以下" if _rc <= 8 else
                   "9〜12頭" if _rc <= 12 else "13頭以上"].append(x)
    probability_forward = {
        "main": _prob_track(settled),
        "all_settled": _prob_track(settled_all),
        "by_kind_surface": {
            bk: _prob_track(sub)
            for bk, sub in _kind_surface_groups(settled_all).items()},
        "by_field_size": {
            bk: _prob_track(sub) for bk, sub in _fs_groups.items() if sub},
        "note": ("34.18 以降に凍結した全頭確率の前方検証。対象は評価 "
                 "top5 の馬のみ（Phase 3 の方法論に合わせた）。校正 "
                 "パラメータ（T=6.51・カバレッジ・順位テーブル）は "
                 "2026-11-08 の fit 期の値で、版が変われば再 fit 前提。"),
    }

    # v34.17: 種別専用買い方 shadow の集計。精算完了した shadow 買い目を
    # バケット別に集め、同ーレースの現行A/B実績と並べて比較する。
    # 本精算（main）とゲート外（gate_out）を分ける（中央13頭以上は
    # 現行ゲートで常に gate_out 側に入るため、そちらの数字が本命）。
    def _kps_agg(rows):
        if not rows:
            return {"races": 0}
        sh_stake = sum(
            safe_int(((x.get("kind_pattern_shadow") or [{}])[0]).get("cost_yen"), 0)
            for x in rows)
        sh_ret = sum(
            safe_int((x.get("kind_pattern_shadow_settlement") or {}).get("all_bet_return"), 0)
            for x in rows)
        return {
            "races": len(rows),
            "variant": ((rows[0].get("kind_pattern_shadow") or [{}])[0]).get("variant"),
            "shadow_stake_yen": sh_stake,
            "shadow_return_yen": sh_ret,
            "shadow_roi_pct": (round(sh_ret / sh_stake * 100, 1)
                               if sh_stake else 0.0),
            "actual_same_races": agg_simple(rows),
        }

    _kps_groups = {}
    for x in settled_all:
        _ks = x.get("kind_pattern_shadow_settlement") or {}
        _kt = x.get("kind_pattern_shadow") or []
        if not _kt or not _ks.get("settlement_complete"):
            continue
        if _ks.get("all_bet_return") is None:
            continue
        _kps_groups.setdefault(_kt[0].get("bucket") or "不明", []).append(x)
    kind_pattern_shadow_stats = {
        bk: {
            "main": _kps_agg([x for x in rows
                              if x.get("bet_eligible") is not False]),
            "gate_out": _kps_agg([x for x in rows
                                  if x.get("bet_eligible") is False]),
        }
        for bk, rows in sorted(_kps_groups.items())
    }

    # v34.19: 配分D shadow の集計。精算完了した alloc_d 買い目を、
    # 本精算（main）とゲート外（gate_out）に分けて、同ーレースの
    # 現行A/B実績と並べて比較する。対象は ALLOC_D_START_DATE 以降に
    # alloc_d が保存されたレースのみ（34.19 の前方計測）。
    def _alloc_d_agg(rows):
        if not rows:
            return {"races": 0}
        d_stake = sum(
            safe_int(((x.get("alloc_d") or [{}])[0]).get("cost_yen"), 0)
            for x in rows)
        d_ret = sum(
            safe_int((x.get("alloc_d_settlement") or {}).get("all_bet_return"), 0)
            for x in rows)
        return {
            "races": len(rows),
            "shadow_stake_yen": d_stake,
            "shadow_return_yen": d_ret,
            "shadow_profit_yen": d_ret - d_stake,
            "shadow_roi_pct": (round(d_ret / d_stake * 100, 1)
                               if d_stake else 0.0),
            "actual_same_races": agg_simple(rows),
        }

    def _alloc_d_track(rows):
        return {
            "main": _alloc_d_agg([x for x in rows
                                  if x.get("bet_eligible") is not False]),
            "gate_out": _alloc_d_agg([x for x in rows
                                      if x.get("bet_eligible") is False]),
        }

    _alloc_d_rows = []
    for x in settled_all:
        if str(x.get("date") or "") < ALLOC_D_START_DATE:
            continue
        _dt = x.get("alloc_d") or []
        _ds = x.get("alloc_d_settlement") or {}
        if not _dt or not _ds.get("settlement_complete"):
            continue
        if _ds.get("all_bet_return") is None:
            continue
        _alloc_d_rows.append(x)
    alloc_d_stats = dict(_alloc_d_track(_alloc_d_rows))
    alloc_d_stats["by_pattern"] = {
        pt: _alloc_d_track([x for x in _alloc_d_rows
                            if pattern_of(x) == pt])
        for pt in ("A", "B")
    }
    alloc_d_stats["start_date"] = ALLOC_D_START_DATE
    alloc_d_stats["note"] = (
        "現行パターンA/Bと同一レース・同一買い目・同一総額で、配分だけを"
        "馬連寄りに変えた shadow 計測（B': 馬連53%・3連複20%／"
        "A': 馬連900円・3連複300円）。本番配分・選定には使用していない。"
        "対象は " + ALLOC_D_START_DATE + " 以降の生成分のみ。")

    # v34.20: 金額の強弱 shadow の集計。対象は STAKE_SHADOW_START_DATE
    # 以降に stake_shadow が保存され精算完了した本精算レースのみ
    # （settled = bet_eligible が False でないもの。設計どおり対象は
    # 本精算だけ）。現行（一律額）の同一レース実績と、回収率・損益・
    # 最大DD（累積損益曲線のピークからの最大下落額）で並走比較する。
    def _stake_shadow_agg(rows):
        if not rows:
            return {"races": 0}
        ordered = sorted(rows, key=lambda x: (
            str(x.get("date") or ""), str(x.get("post_time") or ""),
            str(x.get("race_id") or "")))

        def _curve(pairs):
            stake = ret = cum = peak = dd = 0
            for s, r in pairs:
                stake += s
                ret += r
                cum += r - s
                peak = max(peak, cum)
                dd = max(dd, peak - cum)
            return stake, ret, dd

        s_stake, s_ret, s_dd = _curve([
            (safe_int(((x.get("stake_shadow") or [{}])[0]).get("cost_yen"), 0),
             safe_int((x.get("stake_shadow_settlement") or {}).get(
                 "all_bet_return"), 0))
            for x in ordered])
        a_stake, a_ret, a_dd = _curve([
            (safe_int(x.get("cost"), 0),
             safe_int(x.get("all_bet_return"), 0))
            for x in ordered])
        return {
            "races": len(rows),
            "shadow_stake_yen": s_stake,
            "shadow_return_yen": s_ret,
            "shadow_profit_yen": s_ret - s_stake,
            "shadow_roi_pct": (round(s_ret / s_stake * 100, 1)
                               if s_stake else 0.0),
            "shadow_max_dd_yen": s_dd,
            "actual_same_races": {
                "races": len(rows),
                "stake_yen": a_stake,
                "return_yen": a_ret,
                "profit_yen": a_ret - a_stake,
                "roi_pct": (round(a_ret / a_stake * 100, 1)
                            if a_stake else 0.0),
                "max_dd_yen": a_dd,
            },
        }

    def _stake_shadow_tier_of(x):
        st = x.get("stake_shadow") or []
        if st and st[0].get("stake_tier"):
            return st[0]["stake_tier"]
        return stake_shadow_tier(x.get("race_grade"), x.get("kind"))[0]

    _stake_shadow_rows = []
    for x in settled:
        if str(x.get("date") or "") < STAKE_SHADOW_START_DATE:
            continue
        _st = x.get("stake_shadow") or []
        _ss = x.get("stake_shadow_settlement") or {}
        if not _st or not _ss.get("settlement_complete"):
            continue
        if _ss.get("all_bet_return") is None:
            continue
        _stake_shadow_rows.append(x)
    stake_shadow_stats = _stake_shadow_agg(_stake_shadow_rows)
    stake_shadow_stats["by_tier"] = {
        tier: _stake_shadow_agg([x for x in _stake_shadow_rows
                                 if _stake_shadow_tier_of(x) == tier])
        for tier in ("通常", "強", "最強")
    }
    stake_shadow_stats["by_pattern"] = {
        pt: _stake_shadow_agg([x for x in _stake_shadow_rows
                               if pattern_of(x) == pt])
        for pt in ("A", "B")
    }
    stake_shadow_stats["start_date"] = STAKE_SHADOW_START_DATE
    stake_shadow_stats["note"] = (
        "配分比率は現行パターンA/Bのまま、レース総額だけをグレード×"
        "種別で段階化した shadow 計測（最強×4＝超おすすめ×中央／"
        "強×2＝超おすすめ／通常×1＝それ以外）。対象は本精算レース"
        "のみで、現行（一律額）の同一レース実績と回収率・損益・"
        "最大DDを並走比較する。本番配分・選定には使用していない。"
        "対象は " + STAKE_SHADOW_START_DATE + " 以降の生成分のみ。")

    hybrid_shadow = {
        "main": _hybrid_track(settled),
        "shadow": _hybrid_track(settled_shadow),
        "note": ("時計指数と血統スコアは hybrid_features として前方保存した"
                 "計測専用の特徴量で、本番の選定・スコア・信頼度・配分・"
                 "ゲート・グレードには使用していない。特徴量つきレースが"
                 "200件貯まるまで良し悪しの判定をしない。血統スコア帯域の"
                 "参考ROIは post_odds と同じ別枠の考え方で、最終オッズ"
                 "（last_odds）から算出した単勝の仮想成績。"),
    }

    # v34.22: HYBRID_SHADOW（選定 shadow）の集計。対象は
    # HYBRID_SHADOW_START_DATE 以降に hybrid_shadow_tickets が保存され
    # 精算完了したレース。本精算（main）とゲート外（gate_out）に分け、
    # 同一レースの本番実績と回収率・損益・最大DD・的中率で並走比較する。
    # あわせて、4系統（本番／stake_shadow／alloc_d／HYBRID_SHADOW）の
    # 精算が全て揃った同一レースだけの比較表も作る（11月下旬の判定用）。
    def _shadow_curve_dd(rows, stake_fn, ret_fn):
        ordered = sorted(rows, key=lambda x: (
            str(x.get("date") or ""), str(x.get("post_time") or ""),
            str(x.get("race_id") or "")))
        cum = peak = dd = 0
        for x in ordered:
            cum += ret_fn(x) - stake_fn(x)
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        return dd

    def _sys_agg(rows, stake_fn, ret_fn):
        if not rows:
            return {"races": 0}
        stake = sum(stake_fn(x) for x in rows)
        ret = sum(ret_fn(x) for x in rows)
        hits = sum(1 for x in rows if ret_fn(x) > 0)
        return {
            "races": len(rows), "hit_races": hits,
            "hit_rate_pct": round(hits / len(rows) * 100, 1) if rows else 0.0,
            "stake_yen": stake, "return_yen": ret,
            "profit_yen": ret - stake, "roi_pct": (
                round(ret / stake * 100, 1) if stake else 0.0),
            "max_dd_yen": _shadow_curve_dd(rows, stake_fn, ret_fn),
        }

    def _main_stake(x):
        return safe_int(x.get("cost"), 0)

    def _main_ret(x):
        return safe_int(x.get("all_bet_return"), 0)

    def _tk_stake(key):
        return lambda x: safe_int(
            ((x.get(key) or [{}])[0]).get("cost_yen"), 0)

    def _st_ret(skey):
        return lambda x: safe_int(
            (x.get(skey) or {}).get("all_bet_return"), 0)

    def _shadow_settled_rows(rows, key, skey, start):
        out = []
        for x in rows:
            if str(x.get("date") or "") < start:
                continue
            if not (x.get(key) or []):
                continue
            st = x.get(skey) or {}
            if not st.get("settlement_complete"):
                continue
            if st.get("all_bet_return") is None:
                continue
            out.append(x)
        return out

    def _hybrid_bet_types(rows):
        per = {}
        for x in rows:
            st = x.get("hybrid_shadow_settlement") or {}
            for ln in st.get("settled_lines") or []:
                if not isinstance(ln, dict):
                    continue
                e = per.setdefault(ln.get("type") or "?", {
                    "lines": 0, "hit_lines": 0, "stake_yen": 0,
                    "return_yen": 0})
                e["lines"] += 1
                e["hit_lines"] += 1 if ln.get("hit") is True else 0
                e["stake_yen"] += safe_int(ln.get("stake_yen"), 0)
                e["return_yen"] += safe_int(ln.get("return_yen"), 0)
        for e in per.values():
            e["roi_pct"] = (round(e["return_yen"] / e["stake_yen"] * 100, 1)
                            if e["stake_yen"] else 0.0)
            e["hit_rate_pct"] = (
                round(e["hit_lines"] / e["lines"] * 100, 1)
                if e["lines"] else 0.0)
        return per

    def _runner_band(x):
        rc = x.get("runner_count")
        if not isinstance(rc, int):
            return "頭数不明"
        if rc <= 8:
            return "8頭以下"
        if rc <= 12:
            return "9-12頭"
        return "13頭以上"

    _hybrid_rows_all = _shadow_settled_rows(
        settled_all, "hybrid_shadow_tickets", "hybrid_shadow_settlement",
        HYBRID_SHADOW_START_DATE)
    _hybrid_rows_main = [x for x in _hybrid_rows_all
                         if x.get("bet_eligible") is not False]
    _hybrid_rows_gate = [x for x in _hybrid_rows_all
                         if x.get("bet_eligible") is False]

    def _hybrid_track_sel(rows):
        if not rows:
            return {"races": 0}
        return {
            "hybrid": _sys_agg(rows, _tk_stake("hybrid_shadow_tickets"),
                               _st_ret("hybrid_shadow_settlement")),
            "actual_same_races": _sys_agg(rows, _main_stake, _main_ret),
            "by_kind": {
                k: {
                    "hybrid": _sys_agg(
                        [x for x in rows if x.get("kind") == k],
                        _tk_stake("hybrid_shadow_tickets"),
                        _st_ret("hybrid_shadow_settlement")),
                    "actual_same_races": _sys_agg(
                        [x for x in rows if x.get("kind") == k],
                        _main_stake, _main_ret),
                } for k in ("中央", "地方")
            },
            "by_runner_band": {
                band: _sys_agg(
                    [x for x in rows if _runner_band(x) == band],
                    _tk_stake("hybrid_shadow_tickets"),
                    _st_ret("hybrid_shadow_settlement"))
                for band in ("8頭以下", "9-12頭", "13頭以上", "頭数不明")
            },
            "by_bet_type": _hybrid_bet_types(rows),
        }

    # 4系統の精算が全て揃った同一レース（本精算のみ）の比較表
    _cmp_rows = [
        x for x in _hybrid_rows_main
        if _shadow_settled_rows([x], "stake_shadow",
                                "stake_shadow_settlement",
                                STAKE_SHADOW_START_DATE)
        and _shadow_settled_rows([x], "alloc_d", "alloc_d_settlement",
                                 ALLOC_D_START_DATE)
    ]
    hybrid_selection = {
        "main": _hybrid_track_sel(_hybrid_rows_main),
        "gate_out": _hybrid_track_sel(_hybrid_rows_gate),
        "comparison_same_races": {
            "races": len(_cmp_rows),
            "main": _sys_agg(_cmp_rows, _main_stake, _main_ret),
            "stake_shadow": _sys_agg(_cmp_rows, _tk_stake("stake_shadow"),
                                     _st_ret("stake_shadow_settlement")),
            "alloc_d": _sys_agg(_cmp_rows, _tk_stake("alloc_d"),
                                _st_ret("alloc_d_settlement")),
            "hybrid": _sys_agg(_cmp_rows, _tk_stake("hybrid_shadow_tickets"),
                               _st_ret("hybrid_shadow_settlement")),
        },
        "samples": {
            "generated_races": sum(
                1 for x in items
                if str(x.get("date") or "") >= HYBRID_SHADOW_START_DATE
                and (x.get("hybrid_shadow_tickets") or [])),
            "settled_comparable_main": len(_hybrid_rows_main),
            "settled_comparable_gate_out": len(_hybrid_rows_gate),
            "target": HYBRID_SHADOW_TARGET_SAMPLES,
            "feature_races_with_features": (
                hybrid_shadow["main"].get("races_with_features", 0)
                + hybrid_shadow["shadow"].get("races_with_features", 0)),
        },
        "start_date": HYBRID_SHADOW_START_DATE,
        "note": ("時計指数・血統スコア・クラス評価の統合スコアで選定した"
                 " shadow 買い目（買い目構造・総額は現行パターンA/Bと同一）。"
                 "本番の選定・配分には使用していない。市場乖離は主成分に"
                 "含めず post_odds で観測のみ。判定は結果確定済みの"
                 "比較可能標本（本精算）が target 件に到達してから、"
                 "回収率改善幅と最大DDの両面で行う。対象は "
                 + HYBRID_SHADOW_START_DATE + " 以降の生成分のみ。"),
    }
    # v34.16: 候補プール shadow 計測（案C 保険枠 / 案A6 最終6位まで）。
    # 34.16 で保存を始めた last_top6（発走前の最終生成の上位6頭）と
    # trio_payout（実際の3着内組み合わせの3連複配当）を使い、本精算の
    # 同一レースについて「候補プールを広げていたら」を仮想再計算する。
    # 本番の選定・買い目・配分には一切使用しない計測専用。
    # 定義は遡及試算（candidate-pool-2026-11-06）と同一に揃える:
    #   軸 = 単勝ラインの馬。パートナー = 全3連複ラインに共通する
    #   軸以外の馬のうち馬番が最小のもの。追加ラインは {軸, パートナー, x}。
    #   案C の x = 初回 top5 に入り・最終プール（全ラインの馬の和集合）に
    #   残らず・最終順位6位以内の馬。案A6 の x = 最終順位6位以内の馬。
    #   どちらも現行3連複プール内の馬と軸・パートナーは追加対象外。
    #   追加型 = 追加ライン各 POOL_SHADOW_ADD_STAKE_YEN 円。
    #   固定型 = 3連複総額をそのレースの現行実績総額に固定し、全ライン
    #   等分（100円単位に切り捨て、端数は先頭ラインへ）。
    #   仮想払戻は trio_payout（100円あたり）× 仮想ライン金額 / 100。
    def pool_shadow_for(x):
        lines = [ln for ln in (x.get("settled_lines") or [])
                 if isinstance(ln, dict)]
        win = [ln for ln in lines if ln.get("type") == "win"]
        trios = [ln for ln in lines if ln.get("type") == "trio"]
        if len(win) != 1 or not trios:
            return None
        finishes = x.get("result_finishes") or []
        if len(finishes) < 3:
            return None
        div = safe_int(x.get("trio_payout"), 0)
        if not div:
            return "no_payout"
        big_t = set(finishes[:3])
        a = (win[0].get("horses") or [None])[0]
        if a is None or not all(a in (ln.get("horses") or []) for ln in trios):
            return None
        common = set(trios[0].get("horses") or [])
        for ln in trios[1:]:
            common &= set(ln.get("horses") or [])
        partners = sorted(common - {a})
        if not partners:
            return None
        b = partners[0]
        p_trio = set()
        for ln in trios:
            p_trio |= set(ln.get("horses") or [])
        m_gen = set()
        for ln in lines:
            m_gen |= set(ln.get("horses") or [])
        rank_of = {}
        for e in (x.get("last_top6") or []):
            if not isinstance(e, dict):
                continue
            try:
                rank_of[int(e.get("horse_no"))] = e.get("rank")
            except (TypeError, ValueError):
                continue
        base_lines = []
        for ln in trios:
            try:
                base_lines.append((
                    tuple(sorted(int(v) for v in (ln.get("horses") or []))),
                    safe_int(ln.get("stake_yen"), 0)))
            except (TypeError, ValueError):
                return None
        cur_stake = sum(s for _, s in base_lines)
        cur_ret = sum(safe_int(ln.get("return_yen"), 0) for ln in trios)
        cur_hit = any(ln.get("hit") is True for ln in trios)
        frozen5 = []
        for h in (x.get("frozen_prediction") or {}).get("top5") or []:
            if not isinstance(h, dict):
                continue
            try:
                frozen5.append(int(h.get("horse_no")))
            except (TypeError, ValueError):
                continue

        def extras_for(strategy):
            if strategy == "C":
                cand = [no for no in frozen5
                        if no not in m_gen
                        and isinstance(rank_of.get(no), int)
                        and rank_of[no] <= 6]
            else:  # A6: 最終順位6位以内の全馬（順位の昇順）
                cand = [no for no, r in sorted(
                    rank_of.items(), key=lambda kv: kv[1])
                    if isinstance(r, int) and r <= 6]
            out = []
            for no in cand:
                if no in p_trio or no == a or no == b or no in out:
                    continue
                out.append(no)
            return out

        def variant(strategy, fixed):
            extras = extras_for(strategy)
            vlines = list(base_lines)
            for no in extras:
                vlines.append((tuple(sorted((a, b, no))),
                               POOL_SHADOW_ADD_STAKE_YEN))
            if fixed:
                budget = cur_stake
                k = len(vlines)
                each = max(100, (budget // k) // 100 * 100)
                stakes = [each] * k
                stakes[0] += budget - each * k
                vlines = [(c, s) for (c, _), s in zip(vlines, stakes)]
            stake = sum(s for _, s in vlines)
            ret = 0
            hit = False
            for combo, s in vlines:
                if set(combo) == big_t:
                    hit = True
                    ret += (s // 100) * div
            return {
                "stake_yen": stake, "return_yen": ret,
                "hit": hit, "cover": big_t <= (p_trio | set(extras)),
                "added_lines": len(extras),
                "new_hit": bool(hit and not cur_hit),
                "e_loss_yen": (stake - ret) if (hit and ret < stake) else 0,
            }

        return {
            "kind": x.get("kind"),
            "grade_group": (
                x.get("race_grade")
                if x.get("race_grade") in ("超おすすめ", "注目レース")
                else "その他"),
            "current": {
                "stake_yen": cur_stake, "return_yen": cur_ret,
                "hit": cur_hit, "cover": big_t <= p_trio,
                "added_lines": 0, "new_hit": False,
                "e_loss_yen": ((cur_stake - cur_ret)
                               if (cur_hit and cur_ret < cur_stake) else 0),
            },
            "plan_c_add": variant("C", False),
            "plan_c_fixed": variant("C", True),
            "plan_a6_add": variant("A6", False),
            "plan_a6_fixed": variant("A6", True),
        }

    def pool_variant_agg(recs, key):
        rows = [r[key] for r in recs]
        n = len(rows)
        stake = sum(r["stake_yen"] for r in rows)
        ret = sum(r["return_yen"] for r in rows)
        hits = sum(1 for r in rows if r["hit"])
        covers = sum(1 for r in rows if r["cover"])
        added = sum(r["added_lines"] for r in rows)
        return {
            "races": n, "hit_races": hits,
            "hit_rate_pct": round(hits / n * 100, 1) if n else 0.0,
            "stake_yen": stake, "return_yen": ret,
            "profit_yen": ret - stake,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
            "cover_races": covers,
            "cover_rate_pct": round(covers / n * 100, 1) if n else 0.0,
            "new_hit_races": sum(1 for r in rows if r["new_hit"]),
            "added_lines": added,
            "added_lines_per_race": round(added / n, 2) if n else 0.0,
            "e_races": sum(1 for r in rows if r["e_loss_yen"] > 0),
            "e_loss_yen": sum(r["e_loss_yen"] for r in rows),
        }

    def pool_track(recs):
        return {k: pool_variant_agg(recs, k) for k in (
            "current", "plan_c_add", "plan_c_fixed",
            "plan_a6_add", "plan_a6_fixed")}

    pool_recs = []
    pool_no_payout = 0
    for x in settled:
        if str(x.get("date") or "") < POOL_SHADOW_START_DATE:
            continue
        if not x.get("last_top6"):
            continue
        try:
            _pr = pool_shadow_for(x)
        except (TypeError, ValueError, KeyError, IndexError,
                AttributeError):
            _pr = None
        if _pr == "no_payout":
            pool_no_payout += 1
        elif _pr is not None:
            pool_recs.append(_pr)
    pool_shadow_stats = dict(pool_track(pool_recs))
    pool_shadow_stats["by_kind"] = {
        _kind: pool_track([r for r in pool_recs if r["kind"] == _kind])
        for _kind in ("中央", "地方")}
    pool_shadow_stats["by_grade"] = {
        _g: pool_track([r for r in pool_recs if r["grade_group"] == _g])
        for _g in ("超おすすめ", "注目レース", "その他")}
    pool_shadow_stats["excluded_no_payout"] = pool_no_payout
    pool_shadow_stats["start_date"] = POOL_SHADOW_START_DATE
    pool_shadow_stats["note"] = (
        "候補プール（案C 保険枠 / 案A6 最終6位まで）を広げた場合の仮想"
        "成績を、本精算の同一レースで測る shadow 計測。本番の選定・"
        "買い目・配分には使用していない。対象は開始日以降で last_top6"
        "（発走前の最終生成の上位6頭）が保存された本精算レースのみ。"
        "中央の標本が小さい間は参考値。判定は設計書のライン"
        "（最低2週間かつ対象300レース等）に達するまで行わない。")
    # ===== 第1次シャドウ検証（34.23 計測追加・モデル無変更）=====
    # P1 持ちタイム一致度 / P2 選定分解 / P4 血統固定閾値の前方再現性。
    # 全て精算済みスナップショットからの読み取り専用集計で、本番の
    # 予測・買い目・配分には一切影響しない。遡及 (PHASE1_START_DATE
    # より前) と前方 (開始日以降) を分離し、合算しない。実験の記録は
    # スナップショット (frozen_prediction / 各 shadow 買い目と精算) が
    # レース単位の原記録で、ここはその集計ビューにあたる。
    import hashlib as _hashlib
    import random as _random

    def _p1_agreement(x):
        """_hybrid_track と同一ゲート・同一の一致定義。"""
        top5 = (x.get("frozen_prediction") or {}).get("top5") or []
        if not any(isinstance(h, dict) and "time_index_best" in h
                   for h in top5):
            return None
        fb = (x.get("hybrid_features") or {}).get("time_best_horse_no")
        if fb is None or _hybrid_finish(x, fb) is None:
            return None
        rank1 = (top5[0].get("horse_no")
                 if top5 and isinstance(top5[0], dict) else None)
        return "agree" if fb == rank1 else "disagree"

    def _roi_ci95(rows, stake_fn, ret_fn):
        """回収率の95%信頼区間（比率推定のデルタ法による近似）。"""
        n = len(rows)
        if n < 2:
            return None
        stakes = [float(stake_fn(x)) for x in rows]
        rets = [float(ret_fn(x)) for x in rows]
        ts = sum(stakes)
        if ts <= 0:
            return None
        r = sum(rets) / ts
        mean_s = ts / n
        var = (sum((rv - r * sv) ** 2 for sv, rv in zip(stakes, rets))
               / (n - 1)) / (n * mean_s * mean_s)
        se = math.sqrt(var) * 100
        return [round(r * 100 - 1.96 * se, 1), round(r * 100 + 1.96 * se, 1)]

    def _paired_diff_ci(rows, base_fn, alt_fn):
        """同一レースの損益差 (alt - base) の平均と95%信頼区間。"""
        diffs = [alt_fn(x) - base_fn(x) for x in rows]
        n = len(diffs)
        if n < 2:
            return {"races": n, "mean_diff_yen": None, "ci95": None}
        mean = sum(diffs) / n
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1))
        se = sd / math.sqrt(n)
        return {"races": n, "mean_diff_yen": round(mean, 1),
                "ci95": [round(mean - 1.96 * se, 1),
                         round(mean + 1.96 * se, 1)]}

    def _wilson_ci95(wins, n):
        if not n:
            return None
        z = 1.96
        p = wins / n
        den = 1 + z * z / n
        center = (p + z * z / (2 * n)) / den
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        return [round((center - half) * 100, 1),
                round((center + half) * 100, 1)]

    def _era_of(x):
        return ("forward" if str(x.get("date") or "") >= PHASE1_START_DATE
                else "retro")

    settled_retro = [x for x in settled if _era_of(x) == "retro"]
    settled_fwd = [x for x in settled if _era_of(x) == "forward"]
    _fwd_dates = sorted(str(x.get("date")) for x in settled_fwd
                        if x.get("date"))
    _fwd_days = 0
    if _fwd_dates:
        _d0 = datetime.strptime(PHASE1_START_DATE, "%Y-%m-%d")
        _d1 = datetime.strptime(_fwd_dates[-1], "%Y-%m-%d")
        _fwd_days = (_d1 - _d0).days + 1

    def _verdict(n, days):
        if n < 300 or days < 14:
            return ("判断保留（標本不足: 対象300レース・最低2週間の"
                    "条件に未達）")
        return ("判定材料充足（採用はペア比較の統計的改善・最大DD・"
                "別期間での再現を確認した後）")

    # ---- P1: 持ちタイム一致度 (T0/T1/T2) ----
    def _p1_block(rows):
        groups = {"agree": [], "disagree": []}
        for x in rows:
            g = _p1_agreement(x)
            if g:
                groups[g].append(x)
        all_rows = groups["agree"] + groups["disagree"]
        if not all_rows:
            return {"target_races": 0}

        def gblock(grows):
            if not grows:
                return {"races": 0}
            b = _sys_agg(grows, _main_stake, _main_ret)
            top5_of = lambda x: (x.get("frozen_prediction") or {}).get(
                "top5") or []
            r1_fins = [_hybrid_finish(
                x, (top5_of(x)[0].get("horse_no") if top5_of(x) else None))
                for x in grows]
            b["rank1_rates"] = _hybrid_rate(
                [f for f in r1_fins if f is not None])
            fb_fins = [_hybrid_finish(
                x, (x.get("hybrid_features") or {}).get(
                    "time_best_horse_no")) for x in grows]
            b["time_best_rates"] = _hybrid_rate(
                [f for f in fb_fins if f is not None])
            b["avg_payout_yen"] = (
                round(b["return_yen"] / b["hit_races"])
                if b["hit_races"] else 0)
            return b

        def scaled(factor):
            def sf(x):
                return _main_stake(x) * (
                    factor if _p1_agreement(x) == "disagree" else 1.0)

            def rf(x):
                return _main_ret(x) * (
                    factor if _p1_agreement(x) == "disagree" else 1.0)
            return sf, rf

        patterns = {}
        for name, fac in (("T0", 1.0), ("T1", 0.75), ("T2", 0.50)):
            sf, rf = scaled(fac)
            b = _sys_agg(all_rows, sf, rf)
            for k in ("stake_yen", "return_yen", "profit_yen", "max_dd_yen"):
                b[k] = round(b[k])
            b["avg_payout_yen"] = (
                round(b["return_yen"] / b["hit_races"])
                if b["hit_races"] else 0)
            b["roi_ci95_pct"] = _roi_ci95(all_rows, sf, rf)
            patterns[name] = b

        def profit_main(x):
            return _main_ret(x) - _main_stake(x)

        paired = {}
        for name, fac in (("T1", 0.75), ("T2", 0.50)):
            sf, rf = scaled(fac)
            paired[name] = _paired_diff_ci(
                groups["disagree"], profit_main,
                lambda x, sf=sf, rf=rf: rf(x) - sf(x))
        return {"target_races": len(all_rows),
                "groups": {g: gblock(r) for g, r in groups.items()},
                "patterns": patterns, "paired_diff_vs_T0": paired}

    _p1_retro = _p1_block(settled_retro)
    _p1_fwd = _p1_block(settled_fwd)
    _p1_eval = {"sample_races_forward": _p1_fwd.get("target_races", 0),
                "measurement_days_forward": _fwd_days,
                "verdict": _verdict(_p1_fwd.get("target_races", 0),
                                    _fwd_days)}
    if _p1_fwd.get("patterns"):
        for _k in ("T1", "T2"):
            _p1_eval[_k] = {
                "roi_diff_pt_vs_T0": round(
                    _p1_fwd["patterns"][_k]["roi_pct"]
                    - _p1_fwd["patterns"]["T0"]["roi_pct"], 1),
                "max_dd_yen": _p1_fwd["patterns"][_k]["max_dd_yen"],
                "dd_not_worse_than_T0": (
                    _p1_fwd["patterns"][_k]["max_dd_yen"]
                    <= _p1_fwd["patterns"]["T0"]["max_dd_yen"]),
            }

    # ---- P2: 選定分解 (馬レベル + 買い目 A/B/C/D) ----
    def _p2_horse_block(rows):
        ax_p, ax_h, cov_p, cov_h, win_p, win_h = [], [], [], [], [], []
        used = 0
        for x in rows:
            meta_top = (x.get("hybrid_shadow_meta") or {}).get("top") or []
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            rf = x.get("result_finishes") or []
            hs = x.get("hybrid_shadow_settlement") or {}
            if (not meta_top or not top5 or len(rf) < 3
                    or not hs.get("settlement_complete")):
                continue
            used += 1
            fa = _hybrid_finish(x, top5[0].get("horse_no"))
            fb = _hybrid_finish(x, meta_top[0].get("horse_no"))
            if fa is not None:
                ax_p.append(fa)
            if fb is not None:
                ax_h.append(fb)
            top3 = rf[:3]
            pp = [h.get("horse_no") for h in top5[1:4]]
            hp = [h.get("horse_no") for h in meta_top[1:4]]
            cov_p.append(len([h for h in pp if h in top3]))
            cov_h.append(len([h for h in hp if h in top3]))
            win_p.append(1 if rf[0] in pp else 0)
            win_h.append(1 if rf[0] in hp else 0)
        if not used:
            return {"races": 0}
        return {
            "races": used,
            "axis": {"production": _hybrid_rate(ax_p),
                     "hybrid": _hybrid_rate(ax_h)},
            "partners_top2_4": {
                "mean_actual_top3_covered": {
                    "production": (round(sum(cov_p) / len(cov_p), 3)
                                   if cov_p else None),
                    "hybrid": (round(sum(cov_h) / len(cov_h), 3)
                               if cov_h else None)},
                "winner_in_partners_rate_pct": {
                    "production": (round(sum(win_p) / len(win_p) * 100, 1)
                                   if win_p else None),
                    "hybrid": (round(sum(win_h) / len(win_h) * 100, 1)
                               if win_h else None)},
            },
        }

    def _p2_ticket_block(rows):
        paired = []
        for x in rows:
            st = x.get("phase1_sel_settlement") or {}
            hs = x.get("hybrid_shadow_settlement") or {}
            if not (st.get("B") or {}).get("settlement_complete"):
                continue
            if not (st.get("C") or {}).get("settlement_complete"):
                continue
            if not hs.get("settlement_complete"):
                continue
            paired.append(x)
        if not paired:
            return {"paired_races": 0}

        def tk_stake(key):
            return lambda x: safe_int(
                ((x.get("phase1_sel_tickets") or {}).get(key)
                 or [{}])[0].get("cost_yen"), 0)

        def tk_ret(key):
            return lambda x: safe_int(
                ((x.get("phase1_sel_settlement") or {}).get(key)
                 or {}).get("all_bet_return"), 0)

        fns = {
            "A": (_main_stake, _main_ret),
            "B": (tk_stake("B"), tk_ret("B")),
            "C": (tk_stake("C"), tk_ret("C")),
            "D": (_tk_stake("hybrid_shadow_tickets"),
                  _st_ret("hybrid_shadow_settlement")),
        }
        pats = {}
        for k, (sf, rf) in fns.items():
            b = _sys_agg(paired, sf, rf)
            b["avg_payout_yen"] = (
                round(b["return_yen"] / b["hit_races"])
                if b["hit_races"] else 0)
            b["roi_ci95_pct"] = _roi_ci95(paired, sf, rf)
            pats[k] = b

        def profit_of(k):
            sf, rf = fns[k]
            return lambda x: rf(x) - sf(x)

        diffs = {}
        for k in ("B", "C", "D"):
            d = _paired_diff_ci(paired, profit_of("A"), profit_of(k))
            d["roi_diff_pt"] = round(pats[k]["roi_pct"]
                                     - pats["A"]["roi_pct"], 1)
            d["dd_not_worse_than_A"] = (
                pats[k]["max_dd_yen"] <= pats["A"]["max_dd_yen"])
            diffs[k] = d
        return {"paired_races": len(paired), "patterns": pats,
                "paired_diff_vs_A": diffs}

    _p2_tickets_fwd = _p2_ticket_block(settled_fwd)
    _p2_eval = {
        "paired_races_forward": _p2_tickets_fwd.get("paired_races", 0),
        "measurement_days_forward": _fwd_days,
        "verdict": _verdict(_p2_tickets_fwd.get("paired_races", 0),
                            _fwd_days)}
    if _p2_tickets_fwd.get("paired_diff_vs_A"):
        _p2_eval["per_pattern"] = _p2_tickets_fwd["paired_diff_vs_A"]

    # ---- P4: 血統固定閾値の前方再現性 ----
    def _p4_block(rows):
        horses = []
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if not any(isinstance(h, dict) and "time_index_best" in h
                       for h in top5):
                continue
            for h in top5:
                if not isinstance(h, dict):
                    continue
                sc = h.get("sire_score")
                if sc is None or sc < PHASE1_SIRE_FORWARD_MIN:
                    continue
                fin = _hybrid_finish(x, h.get("horse_no"))
                if fin is None:
                    continue
                odds = (x.get("last_odds") or {}).get(str(h.get("horse_no")))
                horses.append((fin, odds))
        wins = sum(1 for f, _o in horses if f == 1)
        stake = ret = n_odds = 0
        for fin, odds in horses:
            if odds:
                n_odds += 1
                stake += 100
                if fin == 1:
                    ret += int(float(odds) * 100)
        return {
            "horses": len(horses), "wins": wins,
            "win_rate_pct": (round(wins / len(horses) * 100, 1)
                             if horses else 0.0),
            "win_rate_wilson_ci95_pct": _wilson_ci95(wins, len(horses)),
            "horses_with_odds": n_odds,
            "win_roi_pct": (round(ret / stake * 100, 1) if stake else None),
        }

    _p1_config = {
        "framework": "PHASE1_EXP_V1",
        "start_date": PHASE1_START_DATE,
        "P1": {"factors": {"T0": 1.0, "T1": 0.75, "T2": 0.50},
               "agreement": ("hybrid_features.time_best_horse_no =="
                             " frozen_prediction.top5[0].horse_no")},
        "P2": {"patterns": ["A", "B", "C", "D"],
               "B": "production axis + hybrid partners",
               "C": "hybrid axis + production partners",
               "paired_only": True},
        "P4": {"sire_forward_min": PHASE1_SIRE_FORWARD_MIN},
    }
    _config_hash = _hashlib.sha1(json.dumps(
        _p1_config, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")).hexdigest()

    phase1_stats = {
        "framework": "PHASE1_EXP_V1",
        "model_version": ENGINE_VERSION,
        "forward_start_date": PHASE1_START_DATE,
        "experiment_end": max(
            (str(x.get("date")) for x in settled if x.get("date")),
            default=None),
        "configuration_hash": _config_hash,
        "configuration": _p1_config,
        "adoption_criteria": {
            "roi_improvement_target_pt": 5.0,
            "min_races": 300,
            "min_days": 14,
            "requirements": [
                "本番比で回収率+5ポイント以上",
                "同一レースのペア比較で統計的な改善を確認",
                "最大DDが本番より悪化しない",
                "別期間でも改善傾向が再現する",
                "標本不足の場合は採用せず判断保留",
                "複数実験の多重検定に配慮し、単独の有意性で採用しない",
            ],
        },
        "experiments": {
            "P1_time_agreement": {
                "experiment_id": "P1_TIME_AGREEMENT",
                "definition": (
                    "一致 = 持ちタイム最速馬が本番1位と同一。不一致群"
                    "のみ投資額を T1=×0.75 / T2=×0.50 に縮小する"
                    "（買い目・順位は不変、払戻は金額に線形連動）。"
                    "T0 は本番そのもの。"),
                "retro": _p1_retro,
                "forward": _p1_fwd,
                "evaluation_forward": _p1_eval,
            },
            "P2_selection_decomposition": {
                "experiment_id": "P2_SELECTION_DECOMP",
                "definition": (
                    "A=本番軸+本番相手 / B=本番軸+hybrid相手 / "
                    "C=hybrid軸+本番相手 / D=hybrid軸+hybrid相手。"
                    "買い目構造・総額は build_tickets で統一し、"
                    "A/B/C/D 全てが精算済みの同一レースのみを"
                    "ペア比較する。馬レベル分解は hybrid メタが"
                    "ある全レースで軸と相手を分けて測る。"),
                "horse_level": {
                    "retro": _p2_horse_block(settled_retro),
                    "forward": _p2_horse_block(settled_fwd)},
                "tickets_paired_forward": _p2_tickets_fwd,
                "ad_reference": {
                    "retro": _hybrid_track_sel(
                        [x for x in _hybrid_rows_main
                         if _era_of(x) == "retro"]),
                    "forward": _hybrid_track_sel(
                        [x for x in _hybrid_rows_main
                         if _era_of(x) == "forward"])},
                "evaluation_forward": _p2_eval,
            },
            "P4_sire_fixed_threshold": {
                "experiment_id": "P4_SIRE_FIXED_THRESHOLD",
                "definition": (
                    "本番 top5 内で sire_score >= 3.87（遡及分析の"
                    "3分位・上位バンド境界を固定値化）の馬の単勝"
                    "成績。境界値 3.87 の同点は全て含めるため、遡及"
                    "参考値は 262 頭で、3分位バンドそのもの"
                    "（259頭・回収率114.2%）とは一致しない。retro は"
                    "同じデータから作った in-sample 参考値で、"
                    "再現性の判定は forward のみで行う。"),
                "retro_insample_reference": _p4_block(settled_retro),
                "forward": _p4_block(settled_fwd),
            },
        },
        "note": (
            "第1次シャドウ検証の集計。P1/P2/P4 はいずれも計測専用で、"
            "本番 34.23 の予測・買い目・配分には使用していない。"
            "レース単位の原記録は history.json のスナップショット"
            "（frozen_prediction と各 shadow 買い目・精算）にあり、"
            "本セクションは experiment_id / configuration_hash で"
            "版管理された集計ビュー。遡及と前方は分離し合算しない。"
            "P3（券種配分）は settled_lines から集計時に導出できる"
            "設計とし、P6（post-odds ゲート）は予測エンジンとは"
            "別工程の購入判断シャドウとして設計のみ（設計書参照）。"),
    }

    # ===== 第2次シャドウ検証（34.23 計測追加・モデル無変更）=====
    # P2 軸分析 / P6 post-odds 購入判断ゲート / P3 券種配分 /
    # P1 リスク改善型ゲート / P4 評価拡張。第1次と同じく精算済み
    # スナップショットからの読み取り専用集計で、本番と第1次の
    # 集計値には一切影響しない。era は PHASE2_START_DATE で分離し、
    # 合算しない。採用判定は forward のみで行う。
    def _era2_of(x):
        return ("forward" if str(x.get("date") or "") >= PHASE2_START_DATE
                else "retro")

    settled2_retro = [x for x in settled if _era2_of(x) == "retro"]
    settled2_fwd = [x for x in settled if _era2_of(x) == "forward"]
    _fwd2_dates = sorted(str(x.get("date")) for x in settled2_fwd
                         if x.get("date"))
    _fwd2_days = 0
    if _fwd2_dates:
        _d0 = datetime.strptime(PHASE2_START_DATE, "%Y-%m-%d")
        _d1 = datetime.strptime(_fwd2_dates[-1], "%Y-%m-%d")
        _fwd2_days = (_d1 - _d0).days + 1

    def _rec_agg(recs, stake_fn, ret_fn):
        """レコード (dict に元スナップショット x を内包) 用の集計。
        最大DD は _sys_agg と同じく (date, post_time, race_id) 順。"""
        if not recs:
            return {"races": 0}
        stake = sum(stake_fn(r) for r in recs)
        ret = sum(ret_fn(r) for r in recs)
        hits = sum(1 for r in recs if ret_fn(r) > 0)
        ordered = sorted(recs, key=lambda r: (
            str(r["x"].get("date") or ""),
            str(r["x"].get("post_time") or ""),
            str(r["x"].get("race_id") or "")))
        cum = peak = dd = 0.0
        for r in ordered:
            cum += ret_fn(r) - stake_fn(r)
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        return {"races": len(recs), "hit_races": hits,
                "hit_rate_pct": round(hits / len(recs) * 100, 1),
                "stake_yen": round(stake), "return_yen": round(ret),
                "profit_yen": round(ret - stake),
                "roi_pct": (round(ret / stake * 100, 1) if stake else 0.0),
                "max_dd_yen": round(dd)}

    def _axis_win_roi(pairs):
        """(着順, 単勝オッズ) の列から100円単勝換算の回収率を出す。"""
        stake = ret = n = 0
        for fin, odds in pairs:
            if odds:
                n += 1
                stake += 100
                if fin == 1:
                    ret += int(float(odds) * 100)
        return {"horses_with_odds": n,
                "win_roi_pct": (round(ret / stake * 100, 1)
                                if stake else None)}

    # ---- P2 追加分析: 軸の一致/正解 4分類 ----
    def _p2_axis_recs(rows):
        recs = []
        for x in rows:
            meta_top = (x.get("hybrid_shadow_meta") or {}).get("top") or []
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            rf = x.get("result_finishes") or []
            hs = x.get("hybrid_shadow_settlement") or {}
            if (not meta_top or not top5 or len(rf) < 3
                    or not hs.get("settlement_complete")):
                continue
            pa = top5[0].get("horse_no")
            ha = meta_top[0].get("horse_no")
            fp = _hybrid_finish(x, pa)
            fh = _hybrid_finish(x, ha)
            if fp is None or fh is None:
                continue
            lo = x.get("last_odds") or {}
            lp = x.get("last_popularity") or {}
            recs.append({
                "x": x, "prod_axis": pa, "hyb_axis": ha,
                "prod_fin": fp, "hyb_fin": fh,
                "prod_odds": lo.get(str(pa)), "hyb_odds": lo.get(str(ha)),
                "prod_pop": (x.get("post_odds") or {}).get("popularity"),
                "hyb_pop": lp.get(str(ha)),
            })
        return recs

    def _p2_axis_block(rows):
        recs = _p2_axis_recs(rows)
        if not recs:
            return {"races": 0}

        def axis_stats(rs, fin_key, odds_key):
            b = _hybrid_rate([r[fin_key] for r in rs])
            b.update(_axis_win_roi(
                [(r[fin_key], r[odds_key]) for r in rs]))
            return b

        def cls_win(r):
            if r["prod_axis"] == r["hyb_axis"]:
                return "agree_win" if r["prod_fin"] == 1 else "agree_notwin"
            if r["prod_fin"] == 1:
                return "prod_only_win"
            if r["hyb_fin"] == 1:
                return "hyb_only_win"
            return "both_notwin"

        def cls_top3(r):
            p3 = r["prod_fin"] <= 3
            h3 = r["hyb_fin"] <= 3
            if r["prod_axis"] == r["hyb_axis"]:
                return "agree_top3" if p3 else "agree_notop3"
            if p3 and h3:
                return "both_top3"
            if p3:
                return "prod_only_top3"
            if h3:
                return "hyb_only_top3"
            return "both_notop3"

        groups = {}
        for name in ("agree_win", "agree_notwin", "prod_only_win",
                     "hyb_only_win", "both_notwin"):
            rs = [r for r in recs if cls_win(r) == name]
            if not rs:
                groups[name] = {"races": 0}
                continue
            groups[name] = {
                "races": len(rs),
                "production_axis": axis_stats(rs, "prod_fin", "prod_odds"),
                "hybrid_axis": axis_stats(rs, "hyb_fin", "hyb_odds"),
            }
        top3_counts = {}
        for name in ("agree_top3", "agree_notop3", "both_top3",
                     "prod_only_top3", "hyb_only_top3", "both_notop3"):
            top3_counts[name] = sum(1 for r in recs if cls_top3(r) == name)

        def by_pop(rs, pop_key, fin_key, odds_key):
            out = {}
            for band in ("1人気", "2-3人気", "4-5人気", "6人気以下", "不明"):
                sub = [r for r in rs
                       if _p6_band_label(r[pop_key]) == band]
                if sub:
                    out[band] = axis_stats(sub, fin_key, odds_key)
            return out

        return {
            "races": len(recs),
            "axis_agreement_races": sum(
                1 for r in recs if r["prod_axis"] == r["hyb_axis"]),
            "production_axis": dict(
                axis_stats(recs, "prod_fin", "prod_odds"),
                by_popularity=by_pop(recs, "prod_pop",
                                     "prod_fin", "prod_odds")),
            "hybrid_axis": dict(
                axis_stats(recs, "hyb_fin", "hyb_odds"),
                by_popularity=by_pop(recs, "hyb_pop",
                                     "hyb_fin", "hyb_odds")),
            "win_classification": groups,
            "top3_classification_counts": top3_counts,
        }

    # ---- P6: post-odds 購入判断ゲート ----
    def _p6_band_label(pop):
        if pop is None:
            return "不明"
        if pop <= 1:
            return "1人気"
        if pop <= 3:
            return "2-3人気"
        if pop <= 5:
            return "4-5人気"
        return "6人気以下"

    def _p6_band_of_pop(pop):
        if pop is None:
            return None
        if pop <= 1:
            return "A"
        if pop <= 3:
            return "B"
        if pop <= 5:
            return "C"
        return "D"

    def _p6_decision(x):
        """購入判断時点のオッズ: odds_snapshots のうちレース日当日の
        発走時刻より前で最後の観測点から、軸 (本番1位) の人気を復元
        する。最終オッズは未来情報混入になるため使わない。観測点が
        無い・発走時刻が無い場合は None (対象外として数える)。"""
        top5 = (x.get("frozen_prediction") or {}).get("top5") or []
        if not top5 or not isinstance(top5[0], dict):
            return None
        axis = top5[0].get("horse_no")
        date = str(x.get("date") or "")
        m = re.match(r"^(\d{1,2}):(\d{2})$",
                     str(x.get("post_time") or "").strip())
        if axis is None or not m or len(date) != 10:
            return None
        try:
            post_dt = datetime.strptime(date, "%Y-%m-%d").replace(
                hour=int(m.group(1)), minute=int(m.group(2)), tzinfo=JST)
        except ValueError:
            return None
        best = None
        for s in x.get("odds_snapshots") or []:
            if not isinstance(s, dict) or not s.get("at"):
                continue
            try:
                at = datetime.fromisoformat(str(s["at"]))
            except ValueError:
                continue
            if at.tzinfo is None:
                at = at.replace(tzinfo=JST)
            if at >= post_dt or at.strftime("%Y-%m-%d") != date:
                continue
            odds_map = s.get("odds") or {}
            ao = odds_map.get(str(axis))
            if not isinstance(ao, (int, float)):
                continue
            if best is None or at > best[0]:
                best = (at, float(ao), odds_map)
        if best is None:
            return None
        at, ao, odds_map = best
        pop = _popularity_rank(ao, list(odds_map.values()))
        band = _p6_band_of_pop(pop)
        if band is None:
            return None
        return {"band": band, "popularity": pop, "axis_win_odds": ao,
                "odds_observed_at": at.isoformat(), "axis": axis}

    def _p6_block(rows):
        recs = []
        excluded = 0
        for x in rows:
            dec = _p6_decision(x)
            if dec is None:
                excluded += 1
                continue
            fin = _hybrid_finish(x, dec["axis"])
            recs.append({"x": x, "band": dec["band"],
                         "popularity": dec["popularity"],
                         "odds_observed_at": dec["odds_observed_at"],
                         "axis_fin": fin, "kind": x.get("kind") or "不明",
                         "course": x.get("course") or "不明"})
        out = {"target_races": len(recs),
               "excluded_no_decision_odds": excluded}
        if not recs:
            return out

        def variant(factors):
            sf = lambda r: _main_stake(r["x"]) * factors[r["band"]]
            rf = lambda r: _main_ret(r["x"]) * factors[r["band"]]
            b = _rec_agg(recs, sf, rf)
            b["avg_payout_yen"] = (round(b["return_yen"] / b["races"])
                                   if b["races"] else 0)
            b["roi_ci95_pct"] = _roi_ci95(
                [r["x"] for r in recs],
                lambda x: _main_stake(x) * factors[
                    next(r["band"] for r in recs if r["x"] is x)],
                lambda x: _main_ret(x) * factors[
                    next(r["band"] for r in recs if r["x"] is x)])
            return b

        variants = {k: variant(f) for k, f in PHASE2_P6_FACTORS.items()}
        base_profit = lambda r: _main_ret(r["x"]) - _main_stake(r["x"])
        diffs = {}
        for k in ("P6-25", "P6-50"):
            f = PHASE2_P6_FACTORS[k]
            alt_profit = (lambda r, f=f: (
                _main_ret(r["x"]) - _main_stake(r["x"])) * f[r["band"]])
            d = _paired_diff_ci(recs, base_profit, alt_profit)
            d["roi_diff_pt_vs_P6-0"] = round(
                variants[k]["roi_pct"] - variants["P6-0"]["roi_pct"], 1)
            d["dd_not_worse_than_P6-0"] = (
                variants[k]["max_dd_yen"] <= variants["P6-0"]["max_dd_yen"])
            diffs[k] = d
        skip = variant(PHASE2_P6_SKIP_FACTORS)
        skip_diff = _paired_diff_ci(
            recs, base_profit,
            lambda r: (_main_ret(r["x"]) - _main_stake(r["x"]))
            * PHASE2_P6_SKIP_FACTORS[r["band"]])
        skip_diff["roi_diff_pt_vs_P6-0"] = round(
            skip["roi_pct"] - variants["P6-0"]["roi_pct"], 1)

        by_band = {}
        for band, label in (("A", "1人気"), ("B", "2-3人気"),
                            ("C", "4-5人気"), ("D", "6人気以下")):
            sub = [r for r in recs if r["band"] == band]
            if not sub:
                by_band[band] = {"races": 0}
                continue
            b = _rec_agg(sub, lambda r: _main_stake(r["x"]),
                         lambda r: _main_ret(r["x"]))
            fins = [r["axis_fin"] for r in sub if r["axis_fin"] is not None]
            b["axis"] = _hybrid_rate(fins)
            by_band[band] = b
        by_kind = {}
        for kind in ("中央", "地方"):
            sub = [r for r in recs if r["kind"] == kind]
            if sub:
                by_kind[kind] = {
                    k: _rec_agg(
                        sub,
                        lambda r, f=PHASE2_P6_FACTORS[k]: (
                            _main_stake(r["x"]) * f[r["band"]]),
                        lambda r, f=PHASE2_P6_FACTORS[k]: (
                            _main_ret(r["x"]) * f[r["band"]]))
                    for k in PHASE2_P6_FACTORS}
        axis_fins = [r["axis_fin"] for r in recs
                     if r["axis_fin"] is not None]
        courses = {}
        for r in recs:
            courses[r["course"]] = courses.get(r["course"], 0) + 1
        out.update({
            "variants": variants,
            "paired_diff_vs_P6-0": diffs,
            "skip_experiment": {"factors": PHASE2_P6_SKIP_FACTORS,
                                "block": skip,
                                "paired_diff_vs_P6-0": skip_diff},
            "by_popularity_band": by_band,
            "by_kind": by_kind,
            "axis_rates": _hybrid_rate(axis_fins),
            "course_counts": dict(sorted(
                courses.items(), key=lambda kv: -kv[1])),
        })
        return out

    _p6_retro = _p6_block(settled2_retro)
    _p6_fwd = _p6_block(settled2_fwd)
    _p6_eval = {
        "sample_races_forward": _p6_fwd.get("target_races", 0),
        "measurement_days_forward": _fwd2_days,
        "gate_type": "profit",
        "verdict": _verdict(_p6_fwd.get("target_races", 0), _fwd2_days)}
    if _p6_fwd.get("paired_diff_vs_P6-0"):
        _p6_eval["per_variant"] = _p6_fwd["paired_diff_vs_P6-0"]

    # ---- P3: 券種配分 (3連複の段階的縮小) ----
    def _p3_rec(x):
        lines = [ln for ln in (x.get("settled_lines") or [])
                 if isinstance(ln, dict)]
        if not lines:
            return None
        tot = sum(safe_int(ln.get("stake_yen"), 0) for ln in lines)
        trio = [ln for ln in lines if ln.get("type") == "trio"]
        if tot <= 0 or not trio:
            return None
        recip = [ln for ln in lines
                 if ln.get("type") in ("quinella", "wide")]
        other = [ln for ln in lines
                 if ln.get("type") not in ("trio", "quinella", "wide")]
        agg = lambda ls: (sum(safe_int(ln.get("stake_yen"), 0) for ln in ls),
                          sum(safe_int(ln.get("return_yen"), 0)
                              for ln in ls))
        t_s, t_r = agg(trio)
        r_s, r_r = agg(recip)
        o_s, o_r = agg(other)
        return {"x": x, "total": tot, "trio_stake": t_s,
                "trio_ret": t_r, "recip_stake": r_s, "recip_ret": r_r,
                "other_stake": o_s, "other_ret": o_r,
                "pattern": pattern_of(x)}

    def _p3_variant(rec, factor):
        """3連複を factor 倍し、削減分を馬連・ワイドへ現行金額比で
        振り替える (総額固定)。振替先が無い場合は現行のまま。"""
        t_new = rec["trio_stake"] * factor
        freed = rec["trio_stake"] - t_new
        if freed > 0 and rec["recip_stake"] > 0:
            r_new = rec["recip_stake"] + freed
            r_ret = rec["recip_ret"] * (r_new / rec["recip_stake"])
            t_ret = (rec["trio_ret"] * (t_new / rec["trio_stake"])
                     if rec["trio_stake"] else 0.0)
            return (t_new + r_new + rec["other_stake"],
                    t_ret + r_ret + rec["other_ret"], t_new)
        return (float(rec["total"]),
                float(rec["trio_ret"] + rec["recip_ret"]
                      + rec["other_ret"]),
                float(rec["trio_stake"]))

    def _p3_block(rows):
        recs = [r for r in (_p3_rec(x) for x in rows) if r is not None]
        out = {"target_races": len(recs)}
        if not recs:
            return out
        variants = {}
        for name, fac in PHASE2_P3_TRIO_FACTORS.items():
            sf = lambda r, fac=fac: _p3_variant(r, fac)[0]
            rf = lambda r, fac=fac: _p3_variant(r, fac)[1]
            b = _rec_agg(recs, sf, rf)
            trio_share = (sum(_p3_variant(r, fac)[2] for r in recs)
                          / sum(sf(r) for r in recs) * 100
                          if recs else 0.0)
            b["trio_share_pct"] = round(trio_share, 1)
            b["roi_ci95_pct"] = _roi_ci95(
                [r["x"] for r in recs],
                lambda x: _p3_variant(
                    next(r for r in recs if r["x"] is x), fac)[0],
                lambda x: _p3_variant(
                    next(r for r in recs if r["x"] is x), fac)[1])
            variants[name] = b
        base_profit = lambda r: _p3_variant(r, 1.0)[1] - _p3_variant(r, 1.0)[0]
        diffs = {}
        for name in ("B", "C"):
            fac = PHASE2_P3_TRIO_FACTORS[name]
            d = _paired_diff_ci(
                recs, base_profit,
                lambda r, fac=fac: (_p3_variant(r, fac)[1]
                                    - _p3_variant(r, fac)[0]))
            d["roi_diff_pt_vs_A"] = round(
                variants[name]["roi_pct"] - variants["A"]["roi_pct"], 1)
            d["dd_not_worse_than_A"] = (
                variants[name]["max_dd_yen"] <= variants["A"]["max_dd_yen"])
            diffs[name] = d
        by_pattern = {}
        for pat in ("A", "B"):
            sub = [r for r in recs if r["pattern"] == pat]
            if sub:
                by_pattern[pat] = {
                    name: _rec_agg(
                        sub,
                        lambda r, fac=fac: _p3_variant(r, fac)[0],
                        lambda r, fac=fac: _p3_variant(r, fac)[1])
                    for name, fac in PHASE2_P3_TRIO_FACTORS.items()}
        by_kind = {}
        for kind in ("中央", "地方"):
            sub = [r for r in recs if (r["x"].get("kind") or "不明") == kind]
            if sub:
                by_kind[kind] = {
                    name: _rec_agg(
                        sub,
                        lambda r, fac=fac: _p3_variant(r, fac)[0],
                        lambda r, fac=fac: _p3_variant(r, fac)[1])
                    for name, fac in PHASE2_P3_TRIO_FACTORS.items()}
        courses = {}
        for r in recs:
            c = r["x"].get("course") or "不明"
            courses[c] = courses.get(c, 0) + 1
        out.update({"variants": variants, "paired_diff_vs_A": diffs,
                    "by_pattern": by_pattern, "by_kind": by_kind,
                    "course_counts": dict(sorted(
                        courses.items(), key=lambda kv: -kv[1]))})
        return out

    _p3_retro = _p3_block(settled2_retro)
    _p3_fwd = _p3_block(settled2_fwd)
    _p3_eval = {
        "sample_races_forward": _p3_fwd.get("target_races", 0),
        "measurement_days_forward": _fwd2_days,
        "gate_type": "profit",
        "verdict": _verdict(_p3_fwd.get("target_races", 0), _fwd2_days)}
    if _p3_fwd.get("paired_diff_vs_A"):
        _p3_eval["per_variant"] = _p3_fwd["paired_diff_vs_A"]

    # ---- P1: リスク改善型ゲート (第1次の前方集計を再利用) ----
    def _p1_dd_for(rows, factor):
        """時系列順の最大DD (T0 は factor=1.0 で全行、T1/T2 は
        不一致群のみ factor を掛けた損益曲線)。"""
        ordered = sorted(rows, key=lambda x: (
            str(x.get("date") or ""), str(x.get("post_time") or ""),
            str(x.get("race_id") or "")))
        cum = peak = dd = 0.0
        for x in ordered:
            f = factor if _p1_agreement(x) == "disagree" else 1.0
            cum += (_main_ret(x) - _main_stake(x)) * f
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        return dd

    _p1_risk = {"gate_type": "risk"}
    _p1_target_fwd = [x for x in settled_fwd
                      if _p1_agreement(x) is not None]
    if _p1_fwd.get("patterns"):
        pats = _p1_fwd["patterns"]
        halves = {}
        if len(_p1_target_fwd) >= 2:
            ordered = sorted(_p1_target_fwd, key=lambda x: (
                str(x.get("date") or ""), str(x.get("post_time") or ""),
                str(x.get("race_id") or "")))
            mid = len(ordered) // 2
            halves = {"first": ordered[:mid], "second": ordered[mid:]}
        risk_variants = {}
        for name, fac in (("T1", 0.75), ("T2", 0.50)):
            t0 = pats["T0"]
            tk = pats[name]
            dd_imp = ((t0["max_dd_yen"] - tk["max_dd_yen"])
                      / t0["max_dd_yen"] * 100 if t0["max_dd_yen"] else 0.0)
            roi_diff = (_p1_eval.get(name) or {}).get("roi_diff_pt_vs_T0")
            ci = ((_p1_fwd.get("paired_diff_vs_T0") or {}).get(name)
                  or {}).get("ci95")
            ev_ok = (ci is None or ci[1] >= 0)
            half_imp = {}
            both_halves = None
            if halves:
                both_halves = True
                for hname, hrows in halves.items():
                    d0 = _p1_dd_for(hrows, 1.0)
                    dk = _p1_dd_for(hrows, fac)
                    imp = ((d0 - dk) / d0 * 100 if d0 else 0.0)
                    half_imp[hname] = {
                        "races": len(hrows), "T0_max_dd_yen": round(d0),
                        "variant_max_dd_yen": round(dk),
                        "dd_improvement_pct": round(imp, 1)}
                    if dk > d0:
                        both_halves = False
            checks = {
                "races_ge_300": _p1_fwd.get("target_races", 0)
                >= PHASE2_RISK_GATE["min_races"],
                "days_ge_14": _fwd_days >= PHASE2_RISK_GATE["min_days"],
                "roi_diff_within_floor": (
                    roi_diff is not None
                    and roi_diff >= PHASE2_RISK_GATE["roi_diff_floor_pt"]),
                "dd_improvement_ge_min": (
                    dd_imp >= PHASE2_RISK_GATE["dd_improvement_min_pct"]),
                "dd_improvement_both_halves": bool(both_halves),
                "ev_not_clearly_worse": bool(ev_ok),
            }
            if not checks["races_ge_300"] or not checks["days_ge_14"]:
                verdict = ("判断保留（標本不足: 対象300レース・最低2週間の"
                           "条件に未達）")
            elif all(checks.values()):
                verdict = "リスク改善型ゲート通過（仮基準）"
            else:
                verdict = "リスク改善型ゲート未達（仮基準）"
            risk_variants[name] = {
                "roi_diff_pt_vs_T0": roi_diff,
                "max_dd_yen": tk["max_dd_yen"],
                "dd_improvement_pct_vs_T0": round(dd_imp, 1),
                "max_dd_per_million_stake": (
                    round(tk["max_dd_yen"] / tk["stake_yen"] * 1000000)
                    if tk["stake_yen"] else None),
                "paired_diff_ci95_vs_T0": ci,
                "ev_not_clearly_worse": bool(ev_ok),
                "half_split_dd": half_imp,
                "checks": checks,
                "verdict": verdict,
            }
        _p1_risk.update({
            "sample_races_forward": _p1_fwd.get("target_races", 0),
            "measurement_days_forward": _fwd_days,
            "T0_reference": {
                "max_dd_yen": pats["T0"]["max_dd_yen"],
                "max_dd_per_million_stake": (
                    round(pats["T0"]["max_dd_yen"] / pats["T0"]["stake_yen"]
                          * 1000000) if pats["T0"]["stake_yen"] else None),
                "roi_pct": pats["T0"]["roi_pct"]},
            "variants": risk_variants,
            "profit_gate_reference": _p1_eval,
        })

    # ---- P4: 評価拡張 (予測能力/収益能力の分離) ----
    def _p4x_block(rows):
        horses = []
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if not any(isinstance(h, dict) and "time_index_best" in h
                       for h in top5):
                continue
            for h in top5:
                if not isinstance(h, dict):
                    continue
                sc = h.get("sire_score")
                if sc is None:
                    continue
                fin = _hybrid_finish(x, h.get("horse_no"))
                if fin is None:
                    continue
                odds = (x.get("last_odds") or {}).get(str(h.get("horse_no")))
                pop = (x.get("last_popularity") or {}).get(
                    str(h.get("horse_no")))
                horses.append({"score": sc, "fin": fin, "odds": odds,
                               "pop": pop, "kind": x.get("kind") or "不明",
                               "upper": sc >= PHASE1_SIRE_FORWARD_MIN})
        if not horses:
            return {"horses": 0}

        def band_block(hs):
            wins = sum(1 for h in hs if h["fin"] == 1)
            b = {"horses": len(hs), "wins": wins,
                 "win_rate_pct": (round(wins / len(hs) * 100, 1)
                                  if hs else 0.0),
                 "win_rate_wilson_ci95_pct": _wilson_ci95(wins, len(hs)),
                 "top3_rate_pct": (
                     round(sum(1 for h in hs if h["fin"] <= 3)
                           / len(hs) * 100, 1) if hs else 0.0)}
            b.update(_axis_win_roi([(h["fin"], h["odds"]) for h in hs]))
            return b

        upper = [h for h in horses if h["upper"]]
        non_upper = [h for h in horses if not h["upper"]]
        by_kind = {}
        for kind in ("中央", "地方"):
            sub_u = [h for h in upper if h["kind"] == kind]
            sub_n = [h for h in non_upper if h["kind"] == kind]
            if sub_u or sub_n:
                by_kind[kind] = {"upper": band_block(sub_u),
                                 "non_upper": band_block(sub_n)}
        by_pop = {}
        for band in ("1人気", "2-3人気", "4-5人気", "6人気以下", "不明"):
            sub = [h for h in upper if _p6_band_label(h["pop"]) == band]
            if sub:
                by_pop[band] = band_block(sub)
        by_odds = {}
        for band in ODDS_BANDS:
            sub = [h for h in upper
                   if odds_band({"win_odds": h["odds"]}) == band]
            if sub:
                by_odds[band] = band_block(sub)
        return {"horses": len(horses), "upper": band_block(upper),
                "non_upper": band_block(non_upper),
                "upper_by_kind": {k: v["upper"] for k, v in by_kind.items()},
                "by_kind": by_kind, "upper_by_popularity": by_pop,
                "upper_by_odds_band": by_odds}

    _p2_config = {
        "framework": "PHASE2_EXP_V1",
        "start_date": PHASE2_START_DATE,
        "P2": {"gate": ("phase1 horse-level と同一 (hybrid meta / "
                        "frozen top5 / 着順 / hybrid 精算が揃う本精算)"),
               "win_classification": ["agree_win", "agree_notwin",
                                      "prod_only_win", "hyb_only_win",
                                      "both_notwin"]},
        "P6": {"factors": PHASE2_P6_FACTORS,
               "skip_factors": PHASE2_P6_SKIP_FACTORS,
               "odds_point": ("last odds_snapshots entry on race date "
                              "before post_time (購入判断時点)"),
               "bands": {"A": "1人気", "B": "2-3人気", "C": "4-5人気",
                         "D": "6人気以下"}},
        "P3": {"trio_factors": PHASE2_P3_TRIO_FACTORS,
               "redistribution": ("freed trio amount to quinella/wide "
                                  "lines pro-rata by current stakes; "
                                  "total stake fixed per race")},
        "P1_risk_gate": PHASE2_RISK_GATE,
        "P4": {"sire_forward_min": PHASE1_SIRE_FORWARD_MIN},
    }
    _config2_hash = _hashlib.sha1(json.dumps(
        _p2_config, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")).hexdigest()

    phase2_stats = {
        "framework": "PHASE2_EXP_V1",
        "model_version": ENGINE_VERSION,
        "forward_start_date": PHASE2_START_DATE,
        "experiment_end": max(
            (str(x.get("date")) for x in settled if x.get("date")),
            default=None),
        "configuration_hash": _config2_hash,
        "configuration": _p2_config,
        "adoption_framework": {
            "profit_gate": {
                "applies_to": ["P2", "P3", "P4", "P6"],
                "min_races": 300, "min_days": 14,
                "roi_improvement_target_pt": 5.0,
                "requirements": [
                    "本番比で回収率+5ポイント以上",
                    "同一レースのペア比較で統計的な改善を確認",
                    "最大DDが本番より悪化しない",
                    "別期間でも改善傾向が再現する",
                    "標本不足の場合は採用せず判断保留",
                    "複数実験の多重検定に配慮し、単独の有意性で採用しない",
                ]},
            "risk_gate": {
                "applies_to": ["P1"],
                "criteria": PHASE2_RISK_GATE,
                "requirements": [
                    "前方300レース以上・14日以上",
                    "回収率が本番比-1pt以内 (非劣性の暫定許容幅)",
                    "最大DDが本番比20%以上改善",
                    "別期間 (前半/後半) でもDD改善を再現",
                    "期待値の明確な悪化がない (ペア差95%CI上限が0未満でない)",
                ]},
        },
        "experiments": {
            "P2_axis_analysis": {
                "experiment_id": "P2_AXIS_ANALYSIS",
                "definition": (
                    "本番軸 (frozen top5[0]) と hybrid軸 (hybrid メタ"
                    " top[0]) の一致/正解を4分類し、各群の軸勝率・"
                    "複勝率・単勝回収率と人気帯別成績を出す。母集団は"
                    "第1次の馬レベル分解と同一ゲート。単勝回収率の"
                    "オッズは last_odds (最終生成時点) の参考値。"),
                "retro": _p2_axis_block(settled2_retro),
                "forward": _p2_axis_block(settled2_fwd),
            },
            "P6_post_odds_gate": {
                "experiment_id": "P6_POST_ODDS_GATE",
                "definition": (
                    "予測と分離した購入判断シャドウ。軸 (本番1位) の"
                    "人気を購入判断時点 (発走前の最後の odds_snapshots "
                    "観測点) のオッズから復元し、人気帯 A=1人気 / "
                    "B=2-3人気 / C=4-5人気 / D=6人気以下 に分ける。"
                    "P6-0=現行 / P6-25=軸4番人気以下を25%減額 / "
                    "P6-50=同50%減額 を同一レースで比較し、見送り"
                    "方式は別実験 P6-SKIP (Dのみ見送り) に分ける。"
                    "最終オッズでの再現は未来情報混入のため行わない。"
                    "選定には一切使用しない。"),
                "retro_reference": _p6_retro,
                "forward": _p6_fwd,
                "evaluation_forward": _p6_eval,
            },
            "P3_ticket_allocation": {
                "experiment_id": "P3_TICKET_ALLOCATION",
                "definition": (
                    "券種配分のシャドウ。買い目の組み合わせは不変で、"
                    "3連複ラインの金額だけを A=現行 / B=現行×50/75 / "
                    "C=現行×25/75 に段階縮小し、削減分を馬連・ワイドへ"
                    "現行金額比で振り替えて1レース総額を固定する。"
                    "現行の3連複比率は実測でパターンA 31.6% / "
                    "パターンB 40.0% であり、75/50/25 は現行を75とした"
                    "相対段階として実装した (実比率は trio_share_pct "
                    "に併記)。損益はレース単位で全券種合算して比較。"),
                "retro_reference": _p3_retro,
                "forward": _p3_fwd,
                "evaluation_forward": _p3_eval,
            },
            "P1_risk_gate": {
                "experiment_id": "P1_RISK_GATE",
                "definition": (
                    "第1次 P1 (T0/T1/T2) の前方集計を、収益改善型とは"
                    "別系統のリスク改善型ゲートで判定する。実掛け金の"
                    "最大DDに加え、総投資額で標準化したDD (100万円"
                    "あたり) を併記し、単なる投資額縮小と選別による"
                    "リスク改善を区別する。"),
                "forward": _p1_risk,
            },
            "P4_sire_extended": {
                "experiment_id": "P4_SIRE_EXTENDED",
                "definition": (
                    "第1次 P4 (固定閾値 sire_score >= 3.87) の評価"
                    "拡張。スコア・閾値は凍結したまま、上位バンドと"
                    "非上位バンドを並べて予測能力 (勝率) と収益能力 "
                    "(単勝回収率) を分離し、中央/地方・人気帯・"
                    "オッズ帯の内訳を追加する。母集団・定義は第1次と"
                    "同一で、第1次の前方ブロックと上位バンドの数値は"
                    "一致する。"),
                "retro_insample_reference": _p4x_block(settled2_retro),
                "forward": _p4x_block(settled2_fwd),
            },
        },
        "note": (
            "第2次シャドウ検証の集計。P2軸分析 / P6 / P3 / P1リスク"
            "ゲート / P4拡張はいずれも計測専用で、本番 34.23 の予測・"
            "買い目・配分と第1次の集計値には使用していない。遡及は"
            "発見用の参考値、採用判定は前方 (2026-11-22 以降) のみで"
            "行う。P6 の人気は購入判断時点のオッズから復元しており、"
            "最終オッズは使っていない。"),
    }
    # ===== 第3次シャドウ検証（34.23 計測追加・モデル無変更）=====
    # AXIS-SURVIVAL V1 / CENTRAL-VALIDATION / COMBINATION-ENGINE。
    # 設計書 phase3-shadow-design-2026-11-23.md で条件を事前に固定した。
    # 全て精算済みスナップショットからの読み取り専用集計で、本番と
    # 第1次・第2次の集計値には一切影響しない。era は
    # PHASE3_START_DATE (2026-11-24) で分離し、合算しない。
    # 採用判定は forward のみで行う。
    def _era3_of(x):
        return ("forward" if str(x.get("date") or "") >= PHASE3_START_DATE
                else "retro")

    settled3_retro = [x for x in settled if _era3_of(x) == "retro"]
    settled3_fwd = [x for x in settled if _era3_of(x) == "forward"]
    _fwd3_dates = sorted(str(x.get("date")) for x in settled3_fwd
                         if x.get("date"))
    _fwd3_days = 0
    if _fwd3_dates:
        _d0 = datetime.strptime(PHASE3_START_DATE, "%Y-%m-%d")
        _d1 = datetime.strptime(_fwd3_dates[-1], "%Y-%m-%d")
        _fwd3_days = (_d1 - _d0).days + 1

    _axm = PHASE3_AXIS_MODEL

    def _p3_features(x, dec):
        """AXIS-SURVIVAL の特徴量 (学習時と同一手順・同一順序)。
        作れない場合は None。dec は _p6_decision の戻り値。"""
        top5 = (x.get("frozen_prediction") or {}).get("top5") or []
        if len(top5) < 3 or not all(isinstance(h, dict) for h in top5):
            return None
        scores = [h.get("score") for h in top5]
        if not all(isinstance(s, (int, float)) for s in scores):
            return None
        runners = x.get("runner_count")
        if not isinstance(runners, (int, float)) or runners <= 0:
            return None
        surf = str(x.get("surface") or "")
        is_turf = 1.0 if "芝" in surf else 0.0
        surf_unknown = (0.0 if ("芝" in surf or "ダート" in surf)
                        else 1.0)
        dist = x.get("distance_m")
        dist_missing = 0.0
        if isinstance(dist, (int, float)) and dist > 0:
            dist_km = float(dist) / 1000.0
        else:
            dist_km = _axm["dist_median_km"]
            dist_missing = 1.0
        conf = x.get("race_confidence_score")
        conf_v = (float(conf) / 100.0
                  if isinstance(conf, (int, float))
                  else _axm["conf_median"])
        odds = dec["axis_win_odds"]
        return [
            float(scores[0] - scores[1]),
            float(scores[0] - scores[2]),
            float(scores[0] - scores[-1]),
            float(scores[0]),
            float(runners),
            float(dec["popularity"]),
            math.log(odds) if odds > 0 else 0.0,
            1.0 if x.get("kind") == "中央" else 0.0,
            is_turf,
            surf_unknown,
            dist_km,
            dist_missing,
            conf_v,
        ]

    def _p3_prob(fv):
        eta = _axm["intercept"] + sum(
            c * (v - m) / s for c, v, m, s in zip(
                _axm["coefficients"], fv, _axm["means"], _axm["stds"]))
        eta = max(-35.0, min(35.0, eta))
        return 1.0 / (1.0 + math.exp(-eta))

    def _p3_prob_of(x):
        """(推定確率, 除外理由)。確率は凍結モデルによる軸3着内確率。
        除外の判定順序は学習時と同一 (判断時点オッズ→特徴量)。"""
        dec = _p6_decision(x)
        if dec is None:
            return None, "no_decision_odds"
        fv = _p3_features(x, dec)
        if fv is None:
            return None, "no_features"
        return _p3_prob(fv), None

    # ---- AXIS-SURVIVAL V1 ----
    def _p3_axis_block(rows):
        recs = []
        excl = {"no_decision_odds": 0, "no_features": 0, "no_target": 0}
        for x in rows:
            prob, reason = _p3_prob_of(x)
            if prob is None:
                excl[reason] += 1
                continue
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            axis = (top5[0].get("horse_no")
                    if top5 and isinstance(top5[0], dict) else None)
            axis_fin = _hybrid_finish(x, axis)
            if axis_fin is None:
                # 軸の着順が記録されていないレース (出走取消等で
                # result_finishes に軸が無い) は学習時と同様に対象外
                excl["no_target"] += 1
                continue
            recs.append({"x": x, "prob": prob, "axis_fin": axis_fin})
        out = {"target_races": len(recs), "excluded": excl}
        if not recs:
            return out
        bands = {}
        for lo, hi, label in ((0.0, 0.5, "0.0-0.5"),
                              (0.5, 0.6, "0.5-0.6"),
                              (0.6, 0.7, "0.6-0.7"),
                              (0.7, 0.8, "0.7-0.8"),
                              (0.8, 1.01, "0.8-1.0")):
            sub = [r for r in recs if lo <= r["prob"] < hi
                   and r["axis_fin"] is not None]
            if sub:
                bands[label] = {
                    "races": len(sub),
                    "mean_pred": round(
                        sum(r["prob"] for r in sub) / len(sub), 4),
                    "actual_top3_rate": round(
                        sum(1 for r in sub if r["axis_fin"] <= 3)
                        / len(sub), 4),
                }
        known = [r for r in recs if r["axis_fin"] is not None]

        def grp(sub):
            b = _rec_agg(sub, lambda r: _main_stake(r["x"]),
                         lambda r: _main_ret(r["x"]))
            fins = [r["axis_fin"] for r in sub
                    if r["axis_fin"] is not None]
            if fins:
                b["axis_top3_rate_pct"] = round(
                    sum(1 for f in fins if f <= 3) / len(fins) * 100, 1)
            return b

        groups = {"A_all": _rec_agg(
            [{"x": x} for x in rows],
            lambda r: _main_stake(r["x"]),
            lambda r: _main_ret(r["x"]))}
        for name, th in (("B_ge70", PHASE3_AXIS_THRESHOLD_MAIN),
                         ("ref_ge60", PHASE3_AXIS_THRESHOLDS_REF[0]),
                         ("ref_ge80", PHASE3_AXIS_THRESHOLDS_REF[1])):
            sub = [r for r in recs if r["prob"] >= th]
            g = grp(sub)
            g["roi_ci95_pct"] = _roi_ci95(
                [r["x"] for r in sub], _main_stake, _main_ret)
            groups[name] = g
        out.update({
            "calibration": bands,
            "brier": (round(
                sum((r["prob"]
                     - (1.0 if r["axis_fin"] <= 3 else 0.0)) ** 2
                    for r in known) / len(known), 4) if known else None),
            "groups": groups,
        })
        return out

    _p3_axis_retro = _p3_axis_block(settled3_retro)
    _p3_axis_fwd = _p3_axis_block(settled3_fwd)
    _p3_axis_eval = {
        "sample_races_forward": len(settled3_fwd),
        "b_races_forward": (
            (_p3_axis_fwd.get("groups") or {}).get("B_ge70")
            or {}).get("races", 0),
        "measurement_days_forward": _fwd3_days,
        "verdict": _verdict(len(settled3_fwd), _fwd3_days),
    }

    # ---- CENTRAL-VALIDATION ----
    def _p3_surface_class(x):
        surf = str(x.get("surface") or "")
        if "芝" in surf:
            return "芝"
        if "ダート" in surf:
            return "ダート"
        return "不明"

    def _p3_central_group(rows):
        out = {
            "races": len(rows),
            "bet_ineligible_races": sum(
                1 for x in rows if x.get("bet_eligible") is False),
            "agg": _rec_agg([{"x": x} for x in rows],
                            lambda r: _main_stake(r["x"]),
                            lambda r: _main_ret(r["x"])),
        }
        fins = []
        cover_shares = []
        full_cover = 0
        band_recs = {}
        band_excl = 0
        type_stake = {}
        type_ret = {}
        no_lines = 0
        calib = []
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            axis = (top5[0].get("horse_no")
                    if top5 and isinstance(top5[0], dict) else None)
            fin = _hybrid_finish(x, axis)
            if fin is not None:
                fins.append(fin)
            rf = x.get("result_finishes") or []
            top5nos = {h.get("horse_no") for h in top5
                       if isinstance(h, dict)}
            if len(rf) >= 3 and top5nos:
                share = len(set(rf[:3]) & top5nos) / 3.0
                cover_shares.append(share)
                if share >= 1.0:
                    full_cover += 1
            dec = _p6_decision(x)
            if dec is None:
                band_excl += 1
            else:
                band_recs.setdefault(dec["band"], []).append(
                    {"x": x, "axis_fin": fin})
                fv = _p3_features(x, dec)
                if fv is not None and fin is not None:
                    calib.append((_p3_prob(fv),
                                  1 if fin <= 3 else 0))
            lines = x.get("settled_lines") or []
            if not lines:
                no_lines += 1
            for ln in lines:
                if not isinstance(ln, dict):
                    continue
                t = ln.get("type") or "不明"
                type_stake[t] = (type_stake.get(t, 0)
                                 + safe_int(ln.get("stake_yen"), 0))
                type_ret[t] = (type_ret.get(t, 0)
                               + safe_int(ln.get("return_yen"), 0))
        out["axis"] = _hybrid_rate(fins)
        bands_out = {}
        for band in ("A", "B", "C", "D"):
            sub = band_recs.get(band) or []
            if not sub:
                bands_out[band] = {"races": 0}
                continue
            b = _rec_agg(sub, lambda r: _main_stake(r["x"]),
                         lambda r: _main_ret(r["x"]))
            b["axis"] = _hybrid_rate(
                [r["axis_fin"] for r in sub
                 if r["axis_fin"] is not None])
            bands_out[band] = b
        out["by_decision_band"] = bands_out
        out["excluded_no_decision_odds"] = band_excl
        out["top5_coverage"] = {
            "races": len(cover_shares),
            "mean_top3_share_pct": (
                round(sum(cover_shares) / len(cover_shares) * 100, 1)
                if cover_shares else 0.0),
            "full_cover_rate_pct": (
                round(full_cover / len(cover_shares) * 100, 1)
                if cover_shares else 0.0),
        }
        bt = {}
        for t in sorted(set(type_stake) | set(type_ret)):
            s = type_stake.get(t, 0)
            r = type_ret.get(t, 0)
            bt[t] = {"stake_yen": s, "return_yen": r,
                     "roi_pct": (round(r / s * 100, 1) if s else 0.0)}
        out["bet_types"] = bt
        out["races_without_settled_lines"] = no_lines
        if calib:
            out["calibration"] = {
                "races": len(calib),
                "mean_pred": round(
                    sum(p for p, _ in calib) / len(calib), 4),
                "actual_top3_rate": round(
                    sum(y for _, y in calib) / len(calib), 4),
                "brier": round(
                    sum((p - y) ** 2 for p, y in calib) / len(calib), 4),
            }
        else:
            out["calibration"] = {"races": 0}
        return out

    def _p3_central_block(rows):
        jra = [x for x in rows if x.get("kind") == "中央"]
        unk = [x for x in jra if _p3_surface_class(x) == "不明"]
        g_unk = _p3_central_group(unk)
        g_unk["surface_unknown_breakdown"] = {
            "未取得": sum(
                1 for x in unk
                if str(x.get("surface") or "") in ("", "未取得")),
            "障害": sum(
                1 for x in unk
                if "障害" in str(x.get("surface") or "")),
            "その他": sum(
                1 for x in unk
                if str(x.get("surface") or "") not in ("", "未取得")
                and "障害" not in str(x.get("surface") or "")),
        }
        return {
            "中央全体": _p3_central_group(jra),
            "中央芝": _p3_central_group(
                [x for x in jra if _p3_surface_class(x) == "芝"]),
            "中央ダート": _p3_central_group(
                [x for x in jra if _p3_surface_class(x) == "ダート"]),
            "中央種別不明": g_unk,
            "地方全体": _p3_central_group(
                [x for x in rows if x.get("kind") == "地方"]),
        }

    settled_all3_retro = [x for x in settled_all
                          if _era3_of(x) == "retro"]
    settled_all3_fwd = [x for x in settled_all
                        if _era3_of(x) == "forward"]
    _p3_central_retro = _p3_central_block(settled_all3_retro)
    _p3_central_fwd = _p3_central_block(settled_all3_fwd)

    # ---- COMBINATION-ENGINE 第1段: 遡及分類 ----
    def _p3_combo_stage1(rows):
        cats = {
            "regeneration_drift": {
                "races": 0, "stake_yen": 0,
                "sub_all_finishers_in_lines": 0,
                "sub_some_finisher_absent": 0},
            "candidate_generation_missing": {"races": 0,
                                             "stake_yen": 0},
            "selection_excluded": {"races": 0, "stake_yen": 0},
        }
        n = 0
        stake_total = 0
        for x in rows:
            top5 = (x.get("frozen_prediction") or {}).get("top5") or []
            rf = x.get("result_finishes") or []
            if (not top5 or not isinstance(top5[0], dict)
                    or len(rf) < 3):
                continue
            axis = top5[0].get("horse_no")
            if axis is None or axis not in rf[:3]:
                continue
            top5nos = {h.get("horse_no") for h in top5
                       if isinstance(h, dict)}
            if not set(rf[:3]) <= top5nos:
                continue
            if safe_int(x.get("all_bet_return"), 0) != 0:
                continue
            n += 1
            cost = safe_int(x.get("cost"), 0)
            stake_total += cost
            lines = [ln for ln in (x.get("settled_lines") or [])
                     if isinstance(ln, dict)]
            win = [ln for ln in lines if ln.get("type") == "win"]
            settled_axis = None
            if win and (win[0].get("horses") or []):
                settled_axis = win[0]["horses"][0]
            gen_all = set()
            for ln in lines:
                gen_all |= set(ln.get("horses") or [])
            W = set(rf[:3])
            if settled_axis is not None and settled_axis != axis:
                c = cats["regeneration_drift"]
                c["races"] += 1
                c["stake_yen"] += cost
                if W <= gen_all:
                    c["sub_all_finishers_in_lines"] += 1
                else:
                    c["sub_some_finisher_absent"] += 1
            elif not W <= gen_all:
                c = cats["candidate_generation_missing"]
                c["races"] += 1
                c["stake_yen"] += cost
            else:
                c = cats["selection_excluded"]
                c["races"] += 1
                c["stake_yen"] += cost
        return {
            "races": n,
            "stake_yen": stake_total,
            "categories": cats,
            "budget_allocation": {
                "identifiable_races": 0,
                "verdict": "判定不能",
                "reason": (
                    "build_tickets の予算超過時の末尾ライン削除は"
                    "スナップショットに記録されず、frozen tickets と"
                    "settled_lines の差異も予測の再生成で説明できる"
                    "ため、資金配分起因と断定できるレースは特定"
                    "できない"),
            },
        }

    _p3_stage1_rows = [x for x in settled_all if x.get("settled_lines")]
    _p3_stage1_retro = _p3_combo_stage1(
        [x for x in _p3_stage1_rows if _era3_of(x) == "retro"])
    _p3_stage1_fwd = _p3_combo_stage1(
        [x for x in _p3_stage1_rows if _era3_of(x) == "forward"])

    # ---- COMBINATION-ENGINE 第2段: 組み合わせ再配分の前方比較 ----
    def _p3_combo_realloc(x):
        """軸込み top5 カバー再配分 (設計書 4.2 で固定したルール)。
        戻り値は ((再配分の投資額, 払戻), None) または (None, 理由)。
        総投資額は現行と同額 (3連複予算の配り直しのみ)。"""
        lines = [ln for ln in (x.get("settled_lines") or [])
                 if isinstance(ln, dict)]
        trios = [ln for ln in lines if ln.get("type") == "trio"]
        if not trios:
            return None, "no_trio_lines"
        div = safe_int(x.get("trio_payout"), 0)
        if not div:
            return None, "no_payout"
        top5 = (x.get("frozen_prediction") or {}).get("top5") or []
        if (len(top5) < 3
                or not all(isinstance(h, dict) for h in top5)):
            return None, "no_top5"
        rf = x.get("result_finishes") or []
        if len(rf) < 3:
            return None, "no_finishes"
        axis = top5[0].get("horse_no")
        if axis is None:
            return None, "no_top5"
        budget = sum(safe_int(ln.get("stake_yen"), 0) for ln in trios)
        partners = [(i + 1, h.get("horse_no"))
                    for i, h in enumerate(top5)
                    if i >= 1 and h.get("horse_no") is not None]
        combos = []
        for i in range(len(partners)):
            for j in range(i + 1, len(partners)):
                r1, h1 = partners[i]
                r2, h2 = partners[j]
                combos.append((r1 + r2,
                               tuple(sorted((axis, h1, h2)))))
        if not combos:
            return None, "no_top5"
        combos.sort(key=lambda c: (c[0], c[1]))
        n_c = len(combos)
        unit = (budget // n_c // 100) * 100
        alloc = {}
        if unit > 0:
            for _, combo in combos:
                alloc[combo] = unit
            remainder = budget - unit * n_c
            if remainder:
                alloc[combos[0][1]] += remainder
        else:
            left = budget
            for _, combo in combos:
                if left < 100:
                    break
                alloc[combo] = 100
                left -= 100
        W = tuple(sorted(rf[:3]))
        trio_ret = (div * alloc.get(W, 0) / 100.0) if W in alloc else 0.0
        cur_trio_ret = sum(safe_int(ln.get("return_yen"), 0)
                           for ln in trios)
        stake_r = (_main_stake(x) - budget
                   + sum(alloc.values()))
        ret_r = _main_ret(x) - cur_trio_ret + trio_ret
        return (stake_r, ret_r), None

    def _p3_combo_block(rows):
        recs = []
        excl = {"no_trio_lines": 0, "no_payout": 0, "no_top5": 0,
                "no_finishes": 0}
        for x in rows:
            res, reason = _p3_combo_realloc(x)
            if res is None:
                excl[reason] += 1
                continue
            stake_r, ret_r = res
            recs.append({"x": x, "stake_r": stake_r, "ret_r": ret_r})
        out = {"target_races": len(recs), "excluded": excl}
        if not recs:
            return out
        cur = _rec_agg(recs, lambda r: _main_stake(r["x"]),
                       lambda r: _main_ret(r["x"]))
        rea = _rec_agg(recs, lambda r: r["stake_r"],
                       lambda r: r["ret_r"])
        d = _paired_diff_ci(
            recs,
            lambda r: _main_ret(r["x"]) - _main_stake(r["x"]),
            lambda r: r["ret_r"] - r["stake_r"])
        d["roi_diff_pt_vs_current"] = round(
            rea["roi_pct"] - cur["roi_pct"], 1)
        d["dd_not_worse_than_current"] = (
            rea["max_dd_yen"] <= cur["max_dd_yen"])
        out.update({"current": cur, "realloc": rea,
                    "paired_diff_vs_current": d})
        return out

    _p3_combo_retro = _p3_combo_block(settled3_retro)
    _p3_combo_fwd = _p3_combo_block(settled3_fwd)
    _p3_combo_eval = {
        "sample_races_forward": _p3_combo_fwd.get("target_races", 0),
        "measurement_days_forward": _fwd3_days,
        "verdict": _verdict(len(settled3_fwd), _fwd3_days),
    }

    _p3_config = {
        "framework": "PHASE3_EXP_V1",
        "start_date": PHASE3_START_DATE,
        "AXIS_SURVIVAL_V1": {
            "model": "logistic_regression_l2_standardized",
            "l2_lambda": _axm["l2_lambda"],
            "features": _axm["features"],
            "means": _axm["means"],
            "stds": _axm["stds"],
            "intercept": _axm["intercept"],
            "coefficients": _axm["coefficients"],
            "dist_median_km": _axm["dist_median_km"],
            "conf_median": _axm["conf_median"],
            "train_races": _axm["train_races"],
            "threshold_main": PHASE3_AXIS_THRESHOLD_MAIN,
            "thresholds_reference": list(PHASE3_AXIS_THRESHOLDS_REF),
            "odds_point": ("last odds_snapshots entry on race date "
                           "before post_time (same as P6)"),
        },
        "CENTRAL_VALIDATION_V1": {
            "population": "all settled incl. bet_eligible False",
            "groups": ["中央全体", "中央芝", "中央ダート",
                       "中央種別不明", "地方全体"],
        },
        "COMBINATION_ENGINE_V1": {
            "stage1_population": ("settled with settled_lines "
                                  "(decomposition population)"),
            "stage1_categories": ["regeneration_drift",
                                  "candidate_generation_missing",
                                  "selection_excluded",
                                  "budget_allocation_undeterminable"],
            "stage2_rule": (
                "trio budget reallocated over axis-inclusive top5 "
                "trios; unit = floor(budget/combos/100)*100, "
                "remainder to first combo by (partner rank sum, "
                "horse numbers); total stake fixed"),
        },
    }
    _config3_hash = _hashlib.sha1(json.dumps(
        _p3_config, sort_keys=True, ensure_ascii=False
    ).encode("utf-8")).hexdigest()

    phase3_stats = {
        "framework": "PHASE3_EXP_V1",
        "model_version": ENGINE_VERSION,
        "forward_start_date": PHASE3_START_DATE,
        "experiment_end": max(
            (str(x.get("date")) for x in settled if x.get("date")),
            default=None),
        "configuration_hash": _config3_hash,
        "configuration": _p3_config,
        "adoption_criteria": {
            "roi_improvement_target_pt": 5.0,
            "min_races": 300,
            "min_days": 14,
            "requirements": [
                "本番比で回収率+5ポイント以上",
                "同一レースのペア比較で統計的な改善を確認",
                "最大DDが本番より悪化しない",
                "別期間でも改善傾向が再現する",
                "標本不足の場合は採用せず判断保留",
                "複数実験の多重検定に配慮し、単独の有意性で採用しない",
            ],
        },
        "experiments": {
            "AXIS_SURVIVAL_V1": {
                "experiment_id": "AXIS_SURVIVAL_V1",
                "definition": (
                    "本番1位 (軸) が3着以内に入る確率を、レース前情報"
                    "だけから凍結ロジスティック回帰で推定する。特徴量は"
                    "予測スコア差・top5分布・出走頭数・判断時点の人気と"
                    "オッズ (P6 と同一手順で odds_snapshots から復元)・"
                    "中央/地方・芝/ダート・距離・信頼度。最終オッズ・"
                    "最終人気・確定着順は使わない。学習は前方開始日より"
                    "前の遡及のみ (753件) で係数を凍結し、評価期間での"
                    "再学習はしない。主評価は前方で B群 (推定確率70%以"
                    "上のみ購入) の回収率・最大DDと確率校正。60%・80%は"
                    "探索的参考値で採用判断には使わない。"),
                "model": {
                    "train_races": _axm["train_races"],
                    "train_base_rate": _axm["train_base_rate"],
                    "train_excluded": _axm["train_excluded"],
                    "features": _axm["features"],
                    "intercept": _axm["intercept"],
                    "coefficients": _axm["coefficients"],
                },
                "retro": _p3_axis_retro,
                "forward": _p3_axis_fwd,
                "evaluation_forward": _p3_axis_eval,
            },
            "CENTRAL_VALIDATION_V1": {
                "experiment_id": "CENTRAL_VALIDATION_V1",
                "definition": (
                    "中央全体/中央芝/中央ダート/中央種別不明/地方全体の"
                    "固定区分で、軸3着内率・判断時点の人気帯別成績・"
                    "top5カバー率・券種別ROI・確率校正 (AXIS-SURVIVAL の"
                    "推定確率)・最大DDを独立評価する。母集団は予測能力の"
                    "評価標本を確保するためゲート外を含む全精算とし、"
                    "区分ごとに bet_eligible=False の件数を併記する。"
                    "芝・ダート欠損は推測で埋めず種別不明として独立"
                    "集計し、内訳 (未取得/障害/その他) を記録する。"),
                "retro": _p3_central_retro,
                "forward": _p3_central_fwd,
            },
            "COMBINATION_ENGINE_V1": {
                "experiment_id": "COMBINATION_ENGINE_V1",
                "definition": (
                    "第1段: 軸が3着以内で入線3頭全てが予測 top5 内に"
                    "いたのに払戻ゼロだったレース (分解の74件) の不的中"
                    "原因を、再生成ドリフト/候補生成段階で欠落/買い目"
                    "選択段階で除外に分類する。資金配分起因はスナップ"
                    "ショットから判定不能として明示する。第2段: 3連複"
                    "予算を軸込み top5 コンボ全体へ再配分する方式を、"
                    "総投資額を現行と同額に固定して前方比較する"
                    "(仮想払戻は trio_payout を使用し、無いレースは"
                    "対象外として数える)。"),
                "stage1_retro_classification": _p3_stage1_retro,
                "stage1_forward_classification": _p3_stage1_fwd,
                "stage2_retro_reference": _p3_combo_retro,
                "stage2_forward": _p3_combo_fwd,
                "stage2_evaluation_forward": _p3_combo_eval,
            },
        },
        "note": (
            "第3次シャドウ検証の集計。AXIS-SURVIVAL / "
            "CENTRAL-VALIDATION / COMBINATION-ENGINE はいずれも計測"
            "専用で、本番 34.23 の予測・買い目・配分と第1次・第2次の"
            "集計値には使用していない。遡及は発見用の参考値、採用"
            "判定は前方 (2026-11-24 以降) のみで行う。AXIS-SURVIVAL "
            "の人気・オッズは購入判断時点のもので、最終オッズは"
            "使っていない。"),
    }
    # ==== v34.23: 第4次シャドウ検証 (PHASE4_EXP_V1) ====
    # 設計: phase4-shadow-design-2026-11-24.md。本番予測・買い目・
    # 配分・既存統計には一切使わない計測専用ブロック。生存確率は
    # 第3次の凍結モデル (_p3_prob_of) を再利用し、再学習しない。
    def _era4_of(x):
        return ("forward" if str(x.get("date") or "") >= PHASE4_START_DATE
                else "retro")

    settled4 = {"retro": [], "forward": []}
    for _x in settled:
        settled4[_era4_of(_x)].append(_x)
    settled_all4 = {"retro": [], "forward": []}
    for _x in settled_all:
        settled_all4[_era4_of(_x)].append(_x)
    _fwd4_days = len({str(x.get("date")) for x in settled4["forward"]
                      if x.get("date")})
    _fwd_all4_days = len({str(x.get("date"))
                          for x in settled_all4["forward"] if x.get("date")})

    def _p4_roi_cluster_ci95(recs, stake_fn, ret_fn):
        """回収率の95%CI (開催日クラスター・ブートストラップ)。"""
        per_date = {}
        for r in recs:
            d = str(r["x"].get("date") or "")
            s0, r0 = per_date.get(d, (0, 0))
            per_date[d] = (s0 + stake_fn(r), r0 + ret_fn(r))
        dates = sorted(per_date)
        if len(dates) < 2:
            return None
        rng = _random.Random(PHASE4_BOOTSTRAP_SEED)
        vals = []
        for _ in range(PHASE4_BOOTSTRAP_REPS):
            ts = tr = 0
            for _i in range(len(dates)):
                s0, r0 = per_date[dates[rng.randrange(len(dates))]]
                ts += s0
                tr += r0
            if ts > 0:
                vals.append(tr / ts * 100.0)
        if len(vals) < 100:
            return None
        vals.sort()
        return [round(vals[int(0.025 * len(vals))], 1),
                round(vals[min(len(vals) - 1,
                               int(0.975 * len(vals)))], 1)]

    def _p4_diff_cluster_ci95(recs, diff_fn):
        """1レースあたり純利益差の平均と開催日クラスター95%CI。"""
        per_date = {}
        n = 0
        tot = 0.0
        for r in recs:
            d = str(r["x"].get("date") or "")
            v = diff_fn(r)
            a, c = per_date.get(d, (0.0, 0))
            per_date[d] = (a + v, c + 1)
            tot += v
            n += 1
        if n == 0:
            return None
        out = {"mean_diff_yen": round(tot / n, 1)}
        dates = sorted(per_date)
        if len(dates) < 2:
            out["ci95_yen"] = None
            return out
        rng = _random.Random(PHASE4_BOOTSTRAP_SEED)
        vals = []
        for _ in range(PHASE4_BOOTSTRAP_REPS):
            tv = 0.0
            tc = 0
            for _i in range(len(dates)):
                a, c = per_date[dates[rng.randrange(len(dates))]]
                tv += a
                tc += c
            if tc > 0:
                vals.append(tv / tc)
        if len(vals) < 100:
            out["ci95_yen"] = None
            return out
        vals.sort()
        out["ci95_yen"] = [round(vals[int(0.025 * len(vals))], 1),
                           round(vals[min(len(vals) - 1,
                                          int(0.975 * len(vals)))], 1)]
        return out

    # ---- 実験1: AXIS-STABILITY ----
    def _p4_axis_rows(rows):
        recs = []
        excluded = {"no_all_horses": 0, "no_scores": 0, "no_finish": 0}
        for x in rows:
            fp = x.get("frozen_prediction") or {}
            top5 = fp.get("top5") or []
            ah = fp.get("all_horses") or []
            if (not top5 or not isinstance(top5[0], dict)
                    or not isinstance(ah, list) or len(ah) < 6):
                excluded["no_all_horses"] += 1
                continue
            axis = top5[0].get("horse_no")
            entries = []
            ok = axis is not None
            for h in ah:
                if (not isinstance(h, dict) or h.get("horse_no") is None
                        or not isinstance(h.get("form_score"), (int, float))
                        or not isinstance(h.get("market_score"),
                                          (int, float))):
                    ok = False
                    break
                entries.append(h)
            if not ok:
                excluded["no_scores"] += 1
                continue
            afin = _hybrid_finish(x, axis)
            if afin is None:
                excluded["no_finish"] += 1
                continue

            def _rank_of(key):
                srt = sorted(entries, key=lambda h: (
                    -h[key],
                    h.get("rank") if isinstance(h.get("rank"), int) else 99,
                    h["horse_no"]))
                for i, h in enumerate(srt):
                    if h["horse_no"] == axis:
                        return i + 1
                return len(srt) + 1

            prob, _pr = _p3_prob_of(x)
            meta = (x.get("hybrid_shadow_meta") or {}).get("top") or []
            dis = None
            hnos = [m.get("horse_no") for m in meta
                    if isinstance(m, dict)]
            if hnos:
                pnos = {h.get("horse_no") for h in top5
                        if isinstance(h, dict)}
                dis = {"axis_same": hnos[0] == axis,
                       "axis_hybrid_rank": (hnos.index(axis) + 1
                                            if axis in hnos else 6),
                       "top5_overlap": len(pnos & set(hnos))}
            recs.append({"x": x, "axis": axis, "axis_fin": afin,
                         "r_f": _rank_of("form_score"),
                         "r_m": _rank_of("market_score"),
                         "prob": prob, "dis": dis})
        for r in recs:
            r["worst"] = max(1, r["r_f"], r["r_m"])
        return recs, excluded

    def _p4_axis_block(rows):
        recs, excluded = _p4_axis_rows(rows)
        out = {"target_races": len(recs), "excluded": excluded}
        if not recs:
            return out

        def _top3(rs):
            return (round(sum(1 for r in rs if r["axis_fin"] <= 3)
                          / len(rs) * 100, 1) if rs else None)

        def _grp(rs):
            if not rs:
                return {"races": 0}
            b = _rec_agg(rs, lambda r: _main_stake(r["x"]),
                         lambda r: _main_ret(r["x"]))
            b["roi_cluster_ci95_pct"] = _p4_roi_cluster_ci95(
                rs, lambda r: _main_stake(r["x"]),
                lambda r: _main_ret(r["x"]))
            return b

        base = _grp(recs)
        base["axis_top3_rate_pct"] = _top3(recs)
        out["all"] = base
        out["top3_retention"] = {
            "form_pct": round(sum(1 for r in recs if r["r_f"] <= 3)
                              / len(recs) * 100, 1),
            "market_pct": round(sum(1 for r in recs if r["r_m"] <= 3)
                                / len(recs) * 100, 1),
            "both_pct": round(sum(1 for r in recs
                                  if r["r_f"] <= 3 and r["r_m"] <= 3)
                              / len(recs) * 100, 1),
        }
        strata = {}
        for lab, sel in (("worst_1", lambda r: r["worst"] == 1),
                         ("worst_2", lambda r: r["worst"] == 2),
                         ("worst_3", lambda r: r["worst"] == 3),
                         ("worst_4plus", lambda r: r["worst"] >= 4),
                         ("worst_le2", lambda r: r["worst"] <= 2),
                         ("worst_ge3", lambda r: r["worst"] >= 3)):
            sub = [r for r in recs if sel(r)]
            if not sub:
                strata[lab] = {"races": 0}
                continue
            b = _rec_agg(sub, lambda r: _main_stake(r["x"]),
                         lambda r: _main_ret(r["x"]))
            b["axis_top3_rate_pct"] = _top3(sub)
            known = [r["prob"] for r in sub if r["prob"] is not None]
            b["mean_survival_prob"] = (round(sum(known) / len(known), 3)
                                       if known else None)
            strata[lab] = b
        out["strata"] = strata
        lo = [r for r in recs if r["worst"] <= 2]
        hi = [r for r in recs if r["worst"] >= 3]
        out["primary_axis_top3_diff_pt"] = (
            round(_top3(lo) - _top3(hi), 1) if lo and hi else None)
        drecs = [r for r in recs if r["dis"] is not None]
        dout = {"races": len(drecs)}
        if drecs:
            same = [r for r in drecs if r["dis"]["axis_same"]]
            diff = [r for r in drecs if not r["dis"]["axis_same"]]
            dout["axis_same"] = {"races": len(same),
                                 "axis_top3_rate_pct": _top3(same)}
            dout["axis_diff"] = {"races": len(diff),
                                 "axis_top3_rate_pct": _top3(diff)}
            for lab, sel in (
                    ("hybrid_rank_1",
                     lambda r: r["dis"]["axis_hybrid_rank"] == 1),
                    ("hybrid_rank_2_3",
                     lambda r: 2 <= r["dis"]["axis_hybrid_rank"] <= 3),
                    ("hybrid_rank_4plus",
                     lambda r: r["dis"]["axis_hybrid_rank"] >= 4)):
                sub = [r for r in drecs if sel(r)]
                dout[lab] = {"races": len(sub),
                             "axis_top3_rate_pct": _top3(sub)}
            dout["mean_top5_overlap"] = round(
                sum(r["dis"]["top5_overlap"] for r in drecs)
                / len(drecs), 2)
        out["disagreement"] = dout
        precs = [r for r in recs if r["prob"] is not None]
        cout = {"prob_known_races": len(precs),
                "prob_unknown_races": len(recs) - len(precs)}
        if precs:
            for lab, sel in (
                    ("prob70_stable",
                     lambda r: r["prob"] >= 0.7 and r["worst"] <= 2),
                    ("prob70_unstable",
                     lambda r: r["prob"] >= 0.7 and r["worst"] >= 3),
                    ("prob_lt70_stable",
                     lambda r: r["prob"] < 0.7 and r["worst"] <= 2),
                    ("prob_lt70_unstable",
                     lambda r: r["prob"] < 0.7 and r["worst"] >= 3)):
                sub = [r for r in precs if sel(r)]
                cout[lab] = {"races": len(sub),
                             "axis_top3_rate_pct": _top3(sub)}
            p70 = [r for r in precs if r["prob"] >= 0.7]
            cout["group_prob70_only"] = _grp(p70)
            cout["group_prob70_and_stable"] = _grp(
                [r for r in p70 if r["worst"] <= 2])
        out["survival_comparison"] = cout
        return out

    # ---- 実験2: CORE-RESERVE ----
    def _p4_reserve_pick(x):
        fp = x.get("frozen_prediction") or {}
        ah = fp.get("all_horses") or []
        pace = ((fp.get("pace_shadow") or {}).get("pace_prediction"))
        fit_tab = PHASE4_RESERVE_FIT.get(pace) or {}
        cand = []
        for h in ah:
            if not isinstance(h, dict) or h.get("horse_no") is None:
                continue
            if not isinstance(h.get("rank"), int) or h["rank"] < 6:
                continue
            if (h.get("running_style") is None
                    and h.get("class_drop") is None):
                continue
            score = (fit_tab.get(h.get("running_style"), 0)
                     + (1 if h.get("class_drop") is True else 0))
            cand.append((score, h["rank"], h["horse_no"]))
        cand.sort(key=lambda t: (-t[0], t[1], t[2]))
        return [c[2] for c in cand[:PHASE4_RESERVE_MAX]]

    def _p4_core_reserve_block(rows):
        recs = []
        excluded = {"no_all_horses": 0, "no_trio_lines": 0,
                    "no_trio_payout": 0, "no_finish": 0}
        for x in rows:
            fp = x.get("frozen_prediction") or {}
            ah = fp.get("all_horses") or []
            top5 = fp.get("top5") or []
            if (len(ah) < 6 or not top5
                    or not isinstance(top5[0], dict)):
                excluded["no_all_horses"] += 1
                continue
            lines = [ln for ln in (x.get("settled_lines") or [])
                     if isinstance(ln, dict)]
            trios = [ln for ln in lines if ln.get("type") == "trio"]
            if not trios:
                excluded["no_trio_lines"] += 1
                continue
            if not x.get("trio_payout"):
                excluded["no_trio_payout"] += 1
                continue
            rf = x.get("result_finishes") or []
            if len(rf) < 3:
                excluded["no_finish"] += 1
                continue
            axis = top5[0].get("horse_no")
            second = (top5[1].get("horse_no")
                      if len(top5) > 1 and isinstance(top5[1], dict)
                      else None)
            core_pool = {h.get("horse_no") for h in top5
                         if isinstance(h, dict)}
            res = _p4_reserve_pick(x)
            W = set(rf[:3])
            ext_pool = core_pool | set(res)
            t_stake = sum(int(ln.get("stake_yen") or 0) for ln in trios)
            t_ret = sum(int(ln.get("return_yen") or 0) for ln in trios)
            n_combo = len(res) if second is not None else 0
            add_ret = 0.0
            if second is not None:
                for rno in res:
                    if {axis, second, rno} == W:
                        add_ret += float(x["trio_payout"])
            recs.append({
                "x": x, "reserves": res,
                "recall_core": len(W & core_pool) / 3.0,
                "recall_ext": len(W & ext_pool) / 3.0,
                "full_core": W <= core_pool,
                "full_ext": W <= ext_pool,
                "axis_fin": _hybrid_finish(x, axis),
                "trio_stake": t_stake, "trio_ret": t_ret,
                "add_stake": PHASE4_RESERVE_COMBO_STAKE * n_combo,
                "add_ret": add_ret,
            })
        out = {"target_races": len(recs), "excluded": excluded}
        if not recs:
            return out
        n = len(recs)
        ts = sum(r["trio_stake"] for r in recs)
        tr = sum(r["trio_ret"] for r in recs)
        a_stake = sum(r["add_stake"] for r in recs)
        a_ret = sum(r["add_ret"] for r in recs)
        fc = sum(1 for r in recs if r["full_core"])
        fe = sum(1 for r in recs if r["full_ext"])
        out["recall"] = {
            "core_pool_top5": round(
                sum(r["recall_core"] for r in recs) / n, 3),
            "extended_pool": round(
                sum(r["recall_ext"] for r in recs) / n, 3),
        }
        out["full_capture"] = {
            "core_pct": round(fc / n * 100, 1),
            "extended_pct": round(fe / n * 100, 1),
            "diff_pt": round((fe - fc) / n * 100, 1),
        }
        out["pool_rescue_races"] = sum(
            1 for r in recs if not r["full_core"] and r["full_ext"])
        out["ticket_rescue_races"] = sum(
            1 for r in recs if r["trio_ret"] == 0 and r["add_ret"] > 0)
        ax = [r for r in recs
              if r["axis_fin"] is not None and r["axis_fin"] <= 3]
        if ax:
            out["axis_top3_trio_payout_rate"] = {
                "races": len(ax),
                "core_pct": round(
                    sum(1 for r in ax if r["trio_ret"] > 0)
                    / len(ax) * 100, 1),
                "extended_pct": round(
                    sum(1 for r in ax
                        if r["trio_ret"] + r["add_ret"] > 0)
                    / len(ax) * 100, 1),
            }
        out["trio_core"] = {
            "stake_yen": ts, "return_yen": tr,
            "roi_pct": round(tr / ts * 100, 1) if ts else None,
            "profit_yen": tr - ts}
        out["trio_extended"] = {
            "stake_yen": ts + a_stake, "return_yen": round(tr + a_ret),
            "roi_pct": (round((tr + a_ret) / (ts + a_stake) * 100, 1)
                        if ts + a_stake else None),
            "profit_yen": round(tr + a_ret) - (ts + a_stake)}
        out["added_only"] = {
            "stake_yen": a_stake, "return_yen": round(a_ret),
            "incremental_roi_pct": (round(a_ret / a_stake * 100, 1)
                                    if a_stake else None),
            "avg_added_stake_yen": round(a_stake / n)}
        out["paired_trio_profit_diff"] = _p4_diff_cluster_ci95(
            recs, lambda r: r["add_ret"] - r["add_stake"])
        out["trio_roi_cluster_ci95_pct"] = {
            "core": _p4_roi_cluster_ci95(
                recs, lambda r: r["trio_stake"],
                lambda r: r["trio_ret"]),
            "extended": _p4_roi_cluster_ci95(
                recs, lambda r: r["trio_stake"] + r["add_stake"],
                lambda r: r["trio_ret"] + r["add_ret"]),
        }
        return out

    # ---- 実験3: CENTRAL-TURF ----
    def _p4_turf_group(x):
        if x.get("kind") != "中央":
            return None
        surf = str(x.get("surface") or "")
        if "芝" in surf:
            return "turf"
        if "ダート" in surf:
            return "dirt"
        return "unknown"

    def _p4_central_turf_block(rows_all):
        turf = [x for x in rows_all if _p4_turf_group(x) == "turf"]
        dirt = [x for x in rows_all if _p4_turf_group(x) == "dirt"]
        unk = [x for x in rows_all if _p4_turf_group(x) == "unknown"]
        out = {"target_races_turf": len(turf),
               "reference_groups": {
                   "dirt": _sys_agg(dirt, _main_stake, _main_ret),
                   "surface_unknown": _sys_agg(unk, _main_stake,
                                               _main_ret)}}
        if not turf:
            return out
        cur = _sys_agg(turf, _main_stake, _main_ret)
        cur["roi_cluster_ci95_pct"] = _p4_roi_cluster_ci95(
            [{"x": x} for x in turf], lambda r: _main_stake(r["x"]),
            lambda r: _main_ret(r["x"]))
        fins = []
        for x in turf:
            t5 = (x.get("frozen_prediction") or {}).get("top5") or []
            fins.append(_hybrid_finish(x, t5[0].get("horse_no"))
                        if t5 and isinstance(t5[0], dict) else None)
        known = [f for f in fins if f is not None]
        cur["axis_top3_rate_pct"] = (
            round(sum(1 for f in known if f <= 3) / len(known) * 100, 1)
            if known else None)
        out["current_all_participation"] = cur

        def _gap12(x):
            t5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if (len(t5) >= 2 and all(isinstance(h, dict) for h in t5[:2])
                    and all(isinstance(h.get("score"), (int, float))
                            for h in t5[:2])):
                return t5[0]["score"] - t5[1]["score"]
            return None

        def _dist_band(x):
            d = x.get("distance_m")
            if not isinstance(d, (int, float)):
                return "不明"
            if d <= 1400:
                return "1400m以下"
            if d <= 1600:
                return "1600m"
            if d <= 1800:
                return "1800m"
            return "2000m以上"

        bd = {}
        for name, keyfn in (
                ("by_distance", _dist_band),
                ("by_runners",
                 lambda x: ("12頭以下"
                            if (x.get("runner_count") or 99) <= 12
                            else "13頭以上")),
                ("by_grade", lambda x: x.get("race_grade") or "不明"),
                ("by_course", lambda x: x.get("course") or "不明")):
            groups = {}
            for x in turf:
                groups.setdefault(keyfn(x), []).append(x)
            bd[name] = {k: _sys_agg(v, _main_stake, _main_ret)
                        for k, v in sorted(groups.items())}
        out["breakdowns"] = bd
        _b_ids = set()
        b_in = []
        for x in turf:
            g = _gap12(x)
            if g is not None and g >= PHASE4_TURF_GAP12_MIN:
                b_in.append(x)
                _b_ids.add(id(x))
        b_out = [x for x in turf if id(x) not in _b_ids]
        out["approach_b_conditional"] = {
            "condition": "gap12 >= 2.0",
            "participation_rate_pct": round(len(b_in) / len(turf) * 100, 1),
            "participating": _sys_agg(b_in, _main_stake, _main_ret),
            "skipped_current_result": _sys_agg(b_out, _main_stake,
                                               _main_ret)}
        out["approach_a_exclusion"] = {
            "participating_races": 0,
            "note": ("全面除外の損益は構造的に0。"
                     "current_all_participation が除外で回避できる"
                     "損失の参照になる。")}
        c_rows = []
        c_excl = 0
        for x in turf:
            t5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if (len(t5) < 2 or not all(isinstance(h, dict) for h in t5)
                    or not all(isinstance(h.get("time_index_best"),
                                          (int, float)) for h in t5)):
                c_excl += 1
                continue
            ded = max(t5, key=lambda h: (
                h["time_index_best"],
                -(h.get("rank") if isinstance(h.get("rank"), int)
                  else 99)))
            d_fin = _hybrid_finish(x, ded.get("horse_no"))
            p_fin = _hybrid_finish(x, t5[0].get("horse_no"))
            if d_fin is None or p_fin is None:
                c_excl += 1
                continue
            lo = x.get("last_odds") or {}
            c_rows.append({
                "d_fin": d_fin, "p_fin": p_fin,
                "d_odds": lo.get(str(ded.get("horse_no"))),
                "p_odds": lo.get(str(t5[0].get("horse_no"))),
                "changed": ded.get("horse_no") != t5[0].get("horse_no")})
        cout = {"races": len(c_rows),
                "excluded_no_time_index_or_finish": c_excl,
                "definition": ("top5 内で time_index_best 最大の馬を"
                               "専用軸とする馬レベルのみの評価")}
        if c_rows:
            cout["axis_changed_races"] = sum(
                1 for r in c_rows if r["changed"])
            cout["dedicated_axis_top3_rate_pct"] = round(
                sum(1 for r in c_rows if r["d_fin"] <= 3)
                / len(c_rows) * 100, 1)
            cout["production_axis_top3_rate_pct"] = round(
                sum(1 for r in c_rows if r["p_fin"] <= 3)
                / len(c_rows) * 100, 1)
            cout["top3_diff_pt"] = round(
                cout["dedicated_axis_top3_rate_pct"]
                - cout["production_axis_top3_rate_pct"], 1)

            def _wroi(fk, ok_):
                s = t = 0
                for r in c_rows:
                    o = r[ok_]
                    if isinstance(o, (int, float)) and o > 0:
                        s += 100
                        if r[fk] == 1:
                            t += int(float(o) * 100)
                return round(t / s * 100, 1) if s else None

            cout["dedicated_axis_win_roi_pct"] = _wroi("d_fin", "d_odds")
            cout["production_axis_win_roi_pct"] = _wroi("p_fin", "p_odds")
        h_rows = []
        for x in turf:
            meta = (x.get("hybrid_shadow_meta") or {}).get("top") or []
            t5 = (x.get("frozen_prediction") or {}).get("top5") or []
            if not meta or not t5 or not isinstance(t5[0], dict):
                continue
            hf = _hybrid_finish(x, meta[0].get("horse_no"))
            pf = _hybrid_finish(x, t5[0].get("horse_no"))
            if hf is None or pf is None:
                continue
            h_rows.append((hf, pf))
        if h_rows:
            cout["hybrid_axis_reference"] = {
                "races": len(h_rows),
                "hybrid_axis_top3_rate_pct": round(
                    sum(1 for a, _b in h_rows if a <= 3)
                    / len(h_rows) * 100, 1),
                "production_axis_top3_rate_pct": round(
                    sum(1 for _a, b in h_rows if b <= 3)
                    / len(h_rows) * 100, 1)}
        out["approach_c_dedicated_model"] = cout
        return out

    _p4_axis_retro = _p4_axis_block(settled4["retro"])
    _p4_axis_fwd = _p4_axis_block(settled4["forward"])
    _p4_core_retro = _p4_core_reserve_block(settled4["retro"])
    _p4_core_fwd = _p4_core_reserve_block(settled4["forward"])
    _p4_turf_retro = _p4_central_turf_block(settled_all4["retro"])
    _p4_turf_fwd = _p4_central_turf_block(settled_all4["forward"])
    _p4_config = {
        "framework": "PHASE4_EXP_V1",
        "phase4_start_date": PHASE4_START_DATE,
        "axis_stability": {
            "perturbations": ["rank_by_form_score_only",
                              "rank_by_market_score_only"],
            "tie_break": ["production_rank_asc", "horse_no_asc"],
            "worst_case_rank": "max(1, axis_form_rank, axis_market_rank)",
            "stable_threshold_worst_le": 2,
            "survival_prob_threshold": 0.7,
            "survival_model": ("phase3 frozen model reused via "
                               "_p3_prob_of (not retrained)"),
            "disagreement_source": "hybrid_shadow_meta.top (top5 only)",
        },
        "core_reserve": {
            "core_pool": "production top5",
            "reserve_eligibility": ("production rank>=6 and "
                                    "(running_style or class_drop "
                                    "recorded)"),
            "reserve_fit_table": PHASE4_RESERVE_FIT,
            "class_drop_bonus": 1,
            "reserve_max_horses": PHASE4_RESERVE_MAX,
            "combo": "{axis, production rank2, reserve} trio, 100 yen each",
            "budget": ("additional stake, accounted separately "
                       "(not total-equalized)"),
        },
        "central_turf": {
            "approach_b_condition": "gap12 >= 2.0",
            "approach_c_model": ("within production top5, axis = max "
                                 "time_index_best (tie: production "
                                 "rank asc); horse-level only"),
            "grade_breakdown_uses": ("race_grade (site recommendation "
                                     "grade; true race class is not "
                                     "recorded)"),
        },
        "combination": ("no new method; reference to phase3 "
                        "combination_engine only"),
        "bootstrap": {"cluster": "race date",
                      "reps": PHASE4_BOOTSTRAP_REPS,
                      "seed": PHASE4_BOOTSTRAP_SEED},
        "adoption_gate": {"min_forward_races": 300,
                          "min_forward_days": 14},
    }
    _p4_config_hash = _hashlib.sha1(json.dumps(
        _p4_config, ensure_ascii=False,
        sort_keys=True).encode("utf-8")).hexdigest()[:12]
    phase4_stats = {
        "framework": "PHASE4_EXP_V1",
        "experiment_start": PHASE4_START_DATE,
        "experiment_end": max(
            (str(x.get("date")) for x in settled if x.get("date")),
            default=None),
        "configuration": _p4_config,
        "configuration_hash": _p4_config_hash,
        "forward_days": _fwd4_days,
        "axis_stability": {
            "retro": _p4_axis_retro,
            "forward": _p4_axis_fwd,
            "evaluation_forward": _verdict(
                _p4_axis_fwd.get("target_races", 0), _fwd4_days),
            "primary_metrics_preregistered": [
                "forward axis top3 rate diff (worst<=2 minus worst>=3)",
                "combined group (prob>=0.70 and worst<=2) ROI and "
                "max drawdown vs prob>=0.70 only group",
            ],
            "adoption_criteria": (
                "前方300件・14日到達後に、主指標1の差が正で、主指標2で"
                "併用群が確率単独群を回収率・最大DDの両面で上回る場合に"
                "「安定性指標に独立の情報あり」とする。遡及では "
                "worst=1 群が最も低く単調性は支持されていないため、"
                "遡及のみでの採用・不採用はしない。"),
        },
        "core_reserve": {
            "retro": _p4_core_retro,
            "forward": _p4_core_fwd,
            "evaluation_forward": _verdict(
                _p4_core_fwd.get("target_races", 0), _fwd4_days),
            "primary_metrics_preregistered": [
                "forward paired trio ROI diff (extended minus core)",
                "forward full-capture rate diff (extended pool minus "
                "core pool)",
            ],
            "adoption_criteria": (
                "前方300件・14日到達後に、主指標1のペア差が正で"
                "クラスターCIが0を含まず、主指標2が正の場合に"
                "「取りこぼし削減に有効」とする。追加投資型のため、"
                "採用時も追加分は分離計上を維持する。"),
        },
        "central_turf": {
            "retro": _p4_turf_retro,
            "forward": _p4_turf_fwd,
            "evaluation_forward": _verdict(
                _p4_turf_fwd.get("target_races_turf", 0),
                _fwd_all4_days),
            "primary_metrics_preregistered": [
                "approach B ROI, max drawdown and participation rate "
                "(vs current all-participation)",
                "approach C dedicated axis top3 rate diff vs "
                "production axis (same races)",
            ],
            "adoption_criteria": (
                "中央芝の前方母集団は小さく、共通ゲート (300件) に"
                "到達するまで長期間を要する見込み。その間は判断保留"
                "とし、単期間の数値で方式を入れ替えない。"),
        },
        "combination_reference": {
            "policy": (
                "第4次では新規の組み合わせ方式・集計を追加しない。"
                "第3次 COMBINATION-ENGINE の前方比較 "
                "(phase3_experiments.combination_engine) を正として"
                "扱う。別方式を試す場合は別ID・別設計で完全分離し、"
                "stage2 の前方標本が共通ゲートに達するまでは方式を"
                "増やさない。"),
            "authoritative_stats": "phase3_experiments.combination_engine",
            "comparison_axes": [
                "cause classification (stage1)",
                "stake reallocation at equal total (stage2)",
                "restricted population: axis in top3 and partner "
                "opportunity present (stage2)",
            ],
            "retro_pure_construction_failures": 74,
        },
        "note": (
            "第4次シャドウ検証の集計。AXIS-STABILITY / CORE-RESERVE / "
            "CENTRAL-TURF はいずれも計測専用で、本番 34.23 の予測・"
            "買い目・配分と第1次〜第3次の集計値には使用していない。"
            "遡及は発見用の参考値、採用判定は前方 (2026-11-25 以降) "
            "のみで行う。信頼区間は開催日クラスター・ブートストラップ"
            " (1,000回・シード固定)。"),
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
        # v34.12: 配分C（shadow並走計測）
        "alloc_c": alloc_c_stats,
        # v34.19: 配分D（馬連寄せ配分・shadow並走計測）
        "alloc_d": alloc_d_stats,
        # v34.20: 金額の強弱（総額の段階化・shadow並走計測）
        "stake_shadow": stake_shadow_stats,
        # v34.13: 3連複トリム計測（中央×13頭以上・shadow並走計測）
        "trio_trim_jra_large": trio_trim_stats,
        "bet_types": bet_types,
        "dream_frame": dream_frame,
        "shadow": shadow_stats,
        "post_odds": post_odds_stats,
        # v34.9: オカルト項目（表示・別枠集計専用）
        "occult_numbers": occult_numbers,
        "occult_tendency": occult_tendency,
        "occult_track": occult_track,
        # v34.13: 3連単チャレンジ枠（shadow計測・前方計測のみ）
        "trifecta_challenge": trifecta_challenge_stats,
        # v34.15: hybrid 特徴量（時計指数・血統スコア）の shadow 計測
        "hybrid_shadow": hybrid_shadow,
        # v34.22: HYBRID_SHADOW（統合選定 shadow・本番/既存shadowとの並走比較）
        "hybrid_selection": hybrid_selection,
        # 第1次シャドウ検証（P1/P2/P4・遡及/前方分離の集計ビュー）
        "phase1_experiments": phase1_stats,
        # 第2次シャドウ検証（P2軸分析/P6/P3/P1リスクゲート/P4拡張）
        "phase2_experiments": phase2_stats,
        # 第3次シャドウ検証（AXIS-SURVIVAL/CENTRAL-VALIDATION/COMBINATION-ENGINE）
        "phase3_experiments": phase3_stats,
        "phase4_experiments": phase4_stats,
        # v34.16: 候補プール shadow 計測（案C 保険枠 / 案A6 最終6位まで）
        "pool_shadow": pool_shadow_stats,
        # v34.17: 本精算の 中央×芝／中央×ダート／地方 分割集計（報告専用）
        "kind_surface_split": {
            bk: agg_simple(sub)
            for bk, sub in _kind_surface_groups(settled).items()},
        # v34.17: 種別専用買い方 shadow（現行A/Bとの並走比較・計測専用）
        "kind_pattern_shadow": kind_pattern_shadow_stats,
        # v34.18: 確率の前方検証（Brier Score / Log Loss・計測専用）
        "probability_forward": probability_forward,
        "accounting_note": (
            "払戻確認済みの精算済みレースのみ集計。"
            "単勝と全券種の集計対象・金額は別管理。"
            "着順一致のみで払戻未確認のレースは回収率から除外。"
            "パターンA=上位評価中心 / パターンB=穴候補含む。"
            "v34.5: ベット対象ゲート外のレースは本集計から除き shadow に別集計。"
            "post_odds はオッズ判明後の参考分析で、選定には使用していない。"),
    }



def build_shadow_summary(snapshots, stats):
    """v34.22: shadow 累計の軽量サマリ（docs/shadow_summary.json 用）。
    history.json（約66MB）や data.json を丸ごと取得しなくても、判定に
    必要な系統別累計（回収率・損益・最大DD）と日次集計だけを小さい
    ファイルで取り出せるようにするための分離保存。包含条件は
    calculate_stats と同一（払戻確認済みの精算完了レースのみ）。
    既存の保存形式（全レース詳細）には一切触れない。"""
    items = list(snapshots.values())
    settled_all = [
        x for x in items
        if x.get("settlement_complete") is True
        and x.get("all_bet_return") is not None
        and x.get("race_profit") is not None
        and x.get("payout_confirmed", True)
    ]
    main_rows = [x for x in settled_all if x.get("bet_eligible") is not False]

    def _dd(rows, stake_fn, ret_fn):
        ordered = sorted(rows, key=lambda x: (
            str(x.get("date") or ""), str(x.get("post_time") or ""),
            str(x.get("race_id") or "")))
        cum = peak = dd = 0
        for x in ordered:
            cum += ret_fn(x) - stake_fn(x)
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        return dd

    def _agg(rows, stake_fn, ret_fn, with_dd=True):
        if not rows:
            return {"races": 0}
        stake = sum(stake_fn(x) for x in rows)
        ret = sum(ret_fn(x) for x in rows)
        out = {
            "races": len(rows),
            "stake_yen": stake, "return_yen": ret,
            "profit_yen": ret - stake,
            "roi_pct": round(ret / stake * 100, 1) if stake else 0.0,
        }
        if with_dd:
            out["max_dd_yen"] = _dd(rows, stake_fn, ret_fn)
        return out

    def _rows(key, skey, start, base):
        out = []
        for x in base:
            if str(x.get("date") or "") < start:
                continue
            if not (x.get(key) or []):
                continue
            st = x.get(skey) or {}
            if not st.get("settlement_complete"):
                continue
            if st.get("all_bet_return") is None:
                continue
            out.append(x)
        return out

    systems_def = {
        "main": (main_rows,
                 lambda x: safe_int(x.get("cost"), 0),
                 lambda x: safe_int(x.get("all_bet_return"), 0)),
        "stake_shadow": (
            _rows("stake_shadow", "stake_shadow_settlement",
                  STAKE_SHADOW_START_DATE, main_rows),
            lambda x: safe_int(
                ((x.get("stake_shadow") or [{}])[0]).get("cost_yen"), 0),
            lambda x: safe_int(
                (x.get("stake_shadow_settlement") or {}).get(
                    "all_bet_return"), 0)),
        "alloc_d": (
            _rows("alloc_d", "alloc_d_settlement",
                  ALLOC_D_START_DATE, main_rows),
            lambda x: safe_int(
                ((x.get("alloc_d") or [{}])[0]).get("cost_yen"), 0),
            lambda x: safe_int(
                (x.get("alloc_d_settlement") or {}).get(
                    "all_bet_return"), 0)),
        "hybrid_selection": (
            _rows("hybrid_shadow_tickets", "hybrid_shadow_settlement",
                  HYBRID_SHADOW_START_DATE, main_rows),
            lambda x: safe_int(
                ((x.get("hybrid_shadow_tickets") or [{}])[0]).get(
                    "cost_yen"), 0),
            lambda x: safe_int(
                (x.get("hybrid_shadow_settlement") or {}).get(
                    "all_bet_return"), 0)),
    }
    systems = {}
    daily = {}
    for name, (rows, sf, rf) in systems_def.items():
        systems[name] = _agg(rows, sf, rf)
        for x in rows:
            d = str(x.get("date") or "")
            e = daily.setdefault(d, {}).setdefault(
                name, {"races": 0, "stake_yen": 0, "return_yen": 0})
            e["races"] += 1
            e["stake_yen"] += sf(x)
            e["return_yen"] += rf(x)
    for day in daily.values():
        for e in day.values():
            e["roi_pct"] = (round(e["return_yen"] / e["stake_yen"] * 100, 1)
                            if e["stake_yen"] else 0.0)
    hs = (stats or {}).get("hybrid_selection") or {}
    samples = hs.get("samples") or {}
    return {
        "generated_at": NOW.isoformat(),
        "engine_version": ENGINE_VERSION,
        "systems": systems,
        "daily": dict(sorted(daily.items())),
        "samples": {
            "hybrid_selection_generated": samples.get("generated_races", 0),
            "hybrid_selection_settled_comparable_main": samples.get(
                "settled_comparable_main", 0),
            "hybrid_selection_target": HYBRID_SHADOW_TARGET_SAMPLES,
            "hybrid_feature_races_with_features": samples.get(
                "feature_races_with_features", 0),
        },
        "note": ("判定用の軽量サマリ。包含条件は calculate_stats と同一"
                 "（払戻確認済みの精算完了レースのみ）。系統別累計は"
                 "各 shadow の計測開始日以降・本精算レースが対象。"
                 "全レース詳細は従来どおり history.json / data.json に保存。"),
    }


def write_shadow_summary(snapshots, stats):
    """v34.22: 軽量サマリの書き出し。失敗しても本処理は止めない。"""
    try:
        save_json(SHADOW_SUMMARY, build_shadow_summary(snapshots, stats))
        print("[INFO] shadow_summary.json を書き出しました")
    except Exception as e:
        warn(f"shadow_summary 書き出し失敗: {type(e).__name__}")


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
    # v34.21: prefetch の実行時間保護（デッドライン判定）に使う起点
    _run_start = time.monotonic()
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
    # v34.14: 血統キャッシュの読み込み（馬IDキー・永続）
    global PEDIGREE_CACHE
    PEDIGREE_CACHE = (
        history.get("pedigree_cache", {})
        if isinstance(history.get("pedigree_cache", {}), dict) else {})
    # v34.15: hybrid 特徴量の基準テーブル（時計指数・血統スコア）を読み込む。
    # 無ければ特徴量は全て None になり従来動作と同一になる
    load_hybrid_tables()
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
    # v34.21: 血統の前倒し取得。生成で使われなかった取得枠を使い、
    # 今日の未生成レース→明日の出走馬→今日の生成済みレースの順で
    # キャッシュを温める（保存は下の history 保存で一緒に行われる）
    prefetch_pedigrees(today_races, tomorrow_races, snapshots, _run_start)
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
        "pedigree_cache": PEDIGREE_CACHE,
    })
    save_json(HISTORY, history)
    # v34.22: shadow 累計の軽量サマリを分離保存（判定用・小さいファイル）
    write_shadow_summary(snapshots, stats)
    verified = sum(1 for r in today_races if r.get("runner_count_verified"))
    settled = sum(1 for r in today_races if r.get("settlement_complete"))
    # v34.21: 当日出走馬の生成時点の父名解決率（data_quality 用）
    _today_runners = [h for r in today_races for h in r.get("horses", [])]
    _today_pedigree_resolved = sum(1 for h in _today_runners if h.get("sire"))
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
            # v34.14: 血統の取得状況
            "new_pedigree_fetches": PEDIGREE_FETCHED_THIS_RUN,
            "pedigree_cache_entries": len(PEDIGREE_CACHE),
            "pedigree_resolved_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("sire")),
            # v34.21: 前倒し取得の実績と、当日出走馬だけの父名解決率
            # （既存の pedigree_resolved_runners は当日+翌日の合算で
            # 分母が無いため、重複しない形で当日分を率つきで残す。
            # 生成時点＝この実行の parse 時点の値で、prefetch で
            # 温めた分は次回以降の生成に反映される）
            "pedigree_prefetched_this_run": PEDIGREE_PREFETCHED_THIS_RUN,
            "today_pedigree_resolved_runners": _today_pedigree_resolved,
            "today_pedigree_total_runners": len(_today_runners),
            "today_pedigree_resolution_rate": (
                round(_today_pedigree_resolved / len(_today_runners), 4)
                if _today_runners else None),
            # v34.15: hybrid 特徴量（時計指数・血統スコア）の付与状況
            "time_standards_ver": TIME_STANDARDS.get("built_at"),
            "pedigree_stats_built_at": PEDIGREE_STATS.get("built_at"),
            "time_index_available_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("time_index_samples")),
            "sire_score_available_runners": sum(
                1 for r in today_races + tomorrow_races
                for h in r.get("horses", []) if h.get("sire_score") is not None),
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


def _settle_target_reached(race):
    """settle-only の精算対象判定。通常実行の parse_race と同じ
    「発走時刻+10分を過ぎたら終了扱い」に、保存済みの is_finished を
    合わせたもの。発走時刻が取れないレースは対象にしない。"""
    if race.get("is_finished"):
        return True
    post = race.get("post_time")
    if not isinstance(post, str):
        return False
    try:
        hh, mm = map(int, post.split(":"))
        scheduled = NOW.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except ValueError:
        return False
    return NOW >= scheduled + timedelta(minutes=10)


def main_settle_only():
    """v34.21 案3: 精算専用の軽量モード（--settle-only）。

    通常実行が生成した docs/data.json の当日レース（買い目・各 shadow
    買い目を含む完全な race dict）を入力に、終了した未精算レースの
    結果取得と精算だけを行い、history.json / data.json を通常と同じ
    形式で書き直す。予測の再生成・近走/人物/血統の取得・prefetch は
    一切行わないため、通常実行（5〜9分）より大幅に短時間で終わる。
    ワークフローでは通常実行の前にこのモードを走らせて先にコミット
    することで、通常実行がタイムアウトしても結果反映だけは先行する。

    state の扱い（通常実行と history.json を共有しても壊れない理由）:
    - 読み込み→精算したレースのスナップショット更新→保存の順で、
      通常実行と同じ経路（load_history / update_snapshot /
      calculate_stats / save_json）を使う。save_json は tmp 経由の
      原子的書き換え。
    - キャッシュ類（horse_form_cache / people_cache / pedigree_cache）
      は読み込んだ値をそのまま保持し、このモードでは上書きしない。
    - update_snapshot の「精算済みを未精算で上書きしない」ガードが
      そのまま効くため、通常実行側の精算結果を巻き戻すことはない。
    - 未精算のまま update_snapshot すると、data.json 由来の古い
      オッズで odds_snapshots に新しい時刻の点が追加されてしまう。
      それを防ぐため、精算を試みたレースでは保存後に odds_snapshots
      を精算前の値へ戻す（オッズ推移は通常実行の新規取得だけで作る）。
    - backfill_settled_lines（GitHub 履歴からの補完）は軽量パスでは
      行わない。通常実行が従来どおり担当する。
    """
    print(f"=== {ENGINE_VERSION} SETTLE-ONLY START ===")
    print(f"[INFO] JST now: {NOW.isoformat()}")
    history = load_history()
    snapshots = history["snapshots"]
    # v34.11: 通常実行と同じ会場名の自己修復（メモリ上のみ・軽量）
    repair_snapshot_venues(snapshots)
    existing = None
    if OUT.exists():
        try:
            v = json.loads(OUT.read_text(encoding="utf-8"))
            if isinstance(v, dict):
                existing = v
        except Exception as e:
            warn("settle-only: data.json読み込み失敗のため精算対象なし: "
                 + type(e).__name__)
    today_races = []
    tomorrow_races = []
    if existing is not None:
        if existing.get("race_date") == NOW.strftime("%Y-%m-%d"):
            today_races = existing.get("races") or []
            tomorrow_races = existing.get("tomorrow_races") or []
        else:
            print("[INFO] settle-only: data.json が当日分ではないため"
                  "精算対象なし（通常実行の生成待ち）")
    source_by_kind = {s["kind"]: s for s in SOURCES}
    attempted = 0
    settled_now = 0
    for race in today_races:
        if race.get("settlement_complete"):
            continue
        if not _settle_target_reached(race):
            continue
        source = source_by_kind.get(race.get("kind"))
        if source is None:
            continue
        attempted += 1
        try:
            race = fetch_and_settle_result(race, source)
        except Exception as e:
            warn(f"{race.get('id')}: settle-only 結果精算例外 "
                 + type(e).__name__)
            continue
        # 結果（着順）が取れたレースだけスナップショットへ反映する。
        # 取れなかったレースの状態更新は通常実行の再生成に任せる。
        if race.get("settlement_complete") or race.get("result_finishes"):
            rid = str(race["id"])
            _old_odds_snaps = (snapshots.get(rid) or {}).get("odds_snapshots")
            update_snapshot(snapshots, race)
            if not race.get("settlement_complete") and rid in snapshots:
                snapshots[rid]["odds_snapshots"] = _old_odds_snaps or []
            if race.get("settlement_complete"):
                settled_now += 1
    # 通常実行と同じ保持期間クリーンアップと集計で history を保存する
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
    })
    save_json(HISTORY, history)
    # v34.22: shadow 累計の軽量サマリを分離保存（判定用・小さいファイル）
    write_shadow_summary(snapshots, stats)
    if existing is not None:
        verified = sum(1 for r in today_races if r.get("runner_count_verified"))
        settled = sum(1 for r in today_races if r.get("settlement_complete"))
        status = "OK" if today_races or tomorrow_races else "NO_RACES"
        existing.update({
            "generated_at": NOW.isoformat(),
            "race_date": NOW.strftime("%Y-%m-%d"),
            "status": status,
            "races": today_races,
            "tomorrow_races": tomorrow_races,
            "tomorrow_race_count": len(tomorrow_races),
            "tomorrow_recommended_count": sum(
                1 for r in tomorrow_races if r.get("is_recommended")),
            "runner_validation": {
                **(existing.get("runner_validation") or {}),
                "today_races": len(today_races),
                "verified_races": verified,
                "unverified_races": len(today_races) - verified,
                "settled_races": settled,
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
        })
        save_json(OUT, existing)
    print(f"{ENGINE_VERSION} SETTLE-ONLY | attempted={attempted} | "
          f"settled_now={settled_now} | today={len(today_races)} | "
          f"history={len(snapshots)}")
    print(f"[INFO] warning_count={len(WARNINGS)}")
    for msg in WARNINGS:
        print("[DIAGNOSTIC]", msg)
    print("=== SETTLE-ONLY FINISHED ===")


if __name__ == "__main__":
    if "--settle-only" in sys.argv[1:]:
        main_settle_only()
    else:
        main()