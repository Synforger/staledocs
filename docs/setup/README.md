# Setup

利用者向けのインストール / 初期設定 / 前提環境を書く section。 派生プロジェクトで具体内容を埋める。

## 推奨構成

- **prerequisites.md** — 前提環境 (= OS / 言語 floor / 必須 binary)
- **install.md** — 手元での install 手順 (= clone → `task doctor` → `task setup` → 実行確認)
- **first-run.md** — 初回起動時の挙動 / 想定される警告 / 1 回だけ走らせる migration 等
- **uninstall.md** — クリーンアップ手順 (= deps / build artefacts / config / data 全部の所在)

新規派生時はこの placeholder を派生 repo 固有の手順で上書きする。 `_core/docs/README.md` に追記される top index は手書きで更新する。
