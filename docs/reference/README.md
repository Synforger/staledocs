# Reference

利用者向けの設定 / データスキーマ / API リファレンスを書く section。 派生プロジェクトで具体内容を埋める。

## 推奨構成

- **config.md** — 設定 file (= `config.json` / `.env` 等) の全項目仕様、 default 値 + 許容範囲 + 例
- **data-schema.md** — persist data の構造 (= sqlite / jsonl / dump 形式)、 例 + マイグレーション履歴
- **api.md** — 公開 API がある場合の reference (= endpoint / params / response / status code)
- **cli.md** — CLI 提供時の全 sub-command + flag

実装に変更が入ったら必ずここを更新する (= `task docs:check` が path 参照を機械検証してる)。
