# Troubleshooting

利用者向けのトラブルシュート / 運用 / 常駐 service 管理を書く section。 派生プロジェクトで具体内容を埋める。

## 推奨構成

- **troubleshoot.md** — よくある不具合 + 対処 (= 1 問題 1 section、 「症状」 → 「原因」 → 「対処」 の三段)
- **runbook.md** — 日常運用 (= 起動 / 停止 / バックアップ / ログ確認 / アップデート)
- **launchd-systemd.md** — 常駐 service として動かす場合の設定 (= launchd plist / systemd unit / pm2 ecosystem 等)
- **backup.md** — 物理 backup の対象 file / 頻度 / 復元手順

`task install-service` / `task restart` / `task logs` 等の運用 task を `Taskfile.local.yml` に定義した場合、 ここから link する。
