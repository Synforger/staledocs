# {{repo_name}}

> {{repo_description}}

> 派生時のチェックリスト (= 派生後にこの noprefix README を埋め直す):
> - [ ] `task doctor` で toolchain floor を満たすか確認
> - [ ] Taskfile.yml の stack stub (setup / lint / test / build / run) を自分の stack で埋める
> - [ ] `python personalize.py` で placeholder 一括置換 (= repo 名 / GitHub URL / バージョン)
> - [ ] `task init:github` で GitHub settings 1 発復元
> - [ ] `task lint` `task test:unit` で local CI green
> - [ ] このセクションを削除し、 利用者向け本文に書き換え

## What this project does

(= 派生後 1-2 段落で説明)

## Quick start

```bash
# Prerequisites: `task doctor` で diagnose
task setup
task run     # stub を埋めたら有効
```

詳細手順は [`docs/`](docs/) を参照。

## Documentation

- 利用者向け = [`docs/`](docs/) (= setup / troubleshooting / reference)
- contributor 向け = [`docs/internals/`](docs/internals/)

## License

Apache-2.0 (= [`LICENSE`](LICENSE))
詳細は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) で全 OSS 依存を一覧化、 [`SECURITY.md`](SECURITY.md) で vulnerability 報告手順を記載。
