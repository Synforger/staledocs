# Internals (= contributor 向け)

派生プロジェクトの内部設計・開発フロー資料。 利用者向けではない情報はここに集約する。

## ここに置く資料の例

- アーキテクチャ図 / コンポーネント分割
- データフロー / 状態管理
- protocol / wire format
- contributor 向け開発フロー (= branch / PR / release)
- 設計判断のログ (= ADR 等)

## 既存資料

- [branch-protection.md](branch-protection.md) — GitHub branch protection の設定方針

## 開発フロー (= 派生プロジェクト共通)

1. `feature/<scope>` branch を切る
2. 実装 + `task lint` + `task test:unit` を緑にする
3. PR を出す (= squash merge + delete-branch)
4. main 保護で直接 push は不可、 `task setup:branch-protection` で gh CLI 経由設定

## ローカル CI ガード

`task` で動くガード一覧:

- `task lint` — stack の linter (= stub、 派生 repo が Taskfile.local.yml 等で埋める)
- `task test:unit` — pytest unit
- `task docs:check` — md 内 path 参照 / `task` 名 / tree 図 / git conflict marker (4 軸) が実態と一致するか機械検証
- `task doctor` — `.tooling/versions.yaml` を元に MISSING / TOO OLD / OK を診断
- `task lint:versions` — 下流 config (= `pyproject.toml` `requires-python` 等) が真値と乖離してないか機械検証
- `task audit` — anon-scan + gitleaks full history + pip-audit + npm audit + cargo audit を集約 (= 各 tool は不在なら skip)
- `task clean LAYER=<layer>` — layer 別 build artefact / cache 削除 (= python/node/rust/swift/kotlin/cs/docs/all)
- `task version:bump LEVEL=<level>` — `.tooling/bump-targets.yaml` の `current_version` を bump + 列挙 file を rewrite (LEVEL=patch|minor|major、 DRY_RUN=1 で plan 確認)
- `task release:cut LEVEL=<level>` — version:bump + git commit + tag + push 1 発 (= SKIP_PUSH=1 で local 留め、 DRY_RUN=1 で plan 確認)
- `task gen-notices` — THIRD_PARTY_NOTICES.md を installed dep tree から再生成
- `task setup:branch-protection` — main 保護を gh CLI で設定

詳細は `_core/.tooling/local-ci/` 内のスクリプトを参照。

## toolchain 真値

`_core/.tooling/versions.yaml` が**host が満たすべき toolchain version の floor 真値**。 派生 repo は新 PC で `task doctor` を叩けば「何 install すべきか」 が出るし、 `versions.yaml` を bump した時は `task lint:versions` で下流 config (= pyproject.toml / package.json) が同期してるか確認できる。 新 stack 追加時は本 file に 1 行追加 + 下流 config を該当 file に書く形 = 真値分散ゼロ。
