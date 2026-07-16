# Roadmap — `{{repo_full_name}}`

> 個人プロジェクトです。 「今安定して使えるのか / 何が作りかけか」 を判断するための一覧。
> このファイルは `python personalize.py` で `{{repo_full_name}}` placeholder が置換される。

## いま使えること

- (派生時に列挙)

## 今後やる予定 (= committed)

- (派生時に列挙)

## 検討中 (= まだ着手していない)

- (`planned:` マーカーは実装済みへ移動 — 下記)

## 実装済み (= develop、未 release)

- **baseline 解決型 anchor (v2)**: 「code っぽい token は全部実在すべき」という
  推定を廃止。ack 時に repo へ解決できた token だけが claim として baseline に
  記録され、check は「baseline で実在した claim が解決できなくなった」時だけ
  red を出す (= 証明可能な drift のみ)。解決しない token (prose / flag / 歴史
  / 将来) は unarmed として計数・列挙され、決して red にならず、決して黙って
  covered 扱いにもならない。誤検知クラスを個別に潰すモグラ叩きの構造的終息。
  suffix 解決 (module 相対 path) と basename 解決 (裸 filename) を解決器に追加

- **`planned:` アンカーマーカー**: 未実装 path の引用を `` `planned:<path>` ``
  で「予定」として申告する記法。確定仕様どおり —
  (1) 消音ではなく可視: pending は「planned, not built yet」として毎回
  レポートに出続ける (= red 逃れに使っても全部見える)、
  (2) path が実在に転じたら「remove the planned: marker」を黄で出す
  (= マーカー死骸化の機械検出)、
  (3) check summary に planned 計数 (= マーカー使用中の repo で常時、
  溜まりすぎの可視化)。
  実装 trigger は実測フェーズの field report で成立 (= triage 誘導があっても
  live doc の将来 path 参照が red に混ざり、正確な記述を「修正」しかける実害)

## 採用しない方針 (= 過去に検討、 不採用判断、 再提案 NG)

- (派生時に列挙)

## バグ報告 / 機能要望

- セキュリティ脆弱性: [SECURITY.md](SECURITY.md)
- 機能要望 / 一般バグ: GitHub Issues 経由で報告 (= PR も歓迎)。 ただし**個人プロジェクトなので応答は best effort**、 LTS 約束なし
- 開発の方向性に直結する根本的な機能要望: 検討中 section の review trigger になる
- 「自分で fork して直したい」 場合は LICENSE (Apache-2.0) の許諾範囲で自由

## 過去の release

各 release の note は GitHub Releases tab を参照。
