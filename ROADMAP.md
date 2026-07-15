# Roadmap — `{{repo_full_name}}`

> 個人プロジェクトです。 「今安定して使えるのか / 何が作りかけか」 を判断するための一覧。
> このファイルは `python personalize.py` で `{{repo_full_name}}` placeholder が置換される。

## いま使えること

- (派生時に列挙)

## 今後やる予定 (= committed)

- (派生時に列挙)

## 検討中 (= まだ着手していない)

- **`planned:` アンカーマーカー (= 仕様確定済み・実測待ち)**: 未実装 path の
  引用を「予定」として申告する記法。設計は確定している —
  (1) 消音ではなく **amber**: 「planned, not built」として毎回レポートに出続ける
  (= config baseline の管轄外に消音手段を作らない、red 逃れに使っても全部見える)、
  (2) path が実在に転じたら「resolved planned reference — remove the marker」を
  黄で出す (= マーカー死骸化の機械検出)、
  (3) check summary に planned 計数を常時表示 (= 溜まりすぎの可視化)。
  **実装 trigger**: 実測フェーズで「finding 内の誘導 + setup の triage 表が
  あっても planned 参照で実害が出た」実例 1 件。観測ゼロでの記法追加は
  やらない (= 記法は最も取り消しにくい API、 案 B 棄却と同じ判断軸)

## 採用しない方針 (= 過去に検討、 不採用判断、 再提案 NG)

- (派生時に列挙)

## バグ報告 / 機能要望

- セキュリティ脆弱性: [SECURITY.md](SECURITY.md)
- 機能要望 / 一般バグ: GitHub Issues 経由で報告 (= PR も歓迎)。 ただし**個人プロジェクトなので応答は best effort**、 LTS 約束なし
- 開発の方向性に直結する根本的な機能要望: 検討中 section の review trigger になる
- 「自分で fork して直したい」 場合は LICENSE (Apache-2.0) の許諾範囲で自由

## 過去の release

各 release の note は GitHub Releases tab を参照。
