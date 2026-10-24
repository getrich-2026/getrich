# 本次米筐回补执行器

读者：维护本轮回补的操作人员。状态：2026-10-24 已验收的专用执行脚本，
不是通用 CLI；固定区间 2024-01-30～2026-10-21、三个模型和原 production variant。

代码在此留存审查版本，实际运行在仓库外现有执行目录，保持该目录的模板、
日历、账本、原失败证据和并发锁。不要在本目录建立新账本或启动另一份任务。
代码不包含凭据或配置文件；账号来自 `RICEQUANT_API_KEY`。

`version-policy.json` 必须经人工批准并提供以下字段；不得根据当前 Git 自动生成新版本：

- `schema_version=1`、`legacy_importer_version`、`current_importer_version`。
- `legacy_jobs`：每个已通过 job 的完整 canonical JSON SHA256。
- `legacy_attempt_count`、`legacy_attempts_sha256`：冻结旧尝试前缀，保留失败证据。
- `baseline_sha256`：冻结首 20 日验收证据。
- `repair`：精确指定问题 job、旧 observation/run、新 observation。

首次执行把 policy 哈希钉在账本中；后续变更被拒绝。旧成功批次保留旧版本，
新任务每批记录新 importer。修复批次的 ingest 与审计都显式选择 observation，
无选择且有多个观察时拒绝。只有新批次独立审计全部通过才记录 supersession。
数据库不可变绑定仍由正常 writer 检查，执行器没有重新绑定能力。

恢复前须核对数据库 `ops.data_quality_check` 中旧 run 的
`rule='risk_bundle_publishable'`、`detail.publishable=false`；该审核记录是未来发布的否决证据，
D-022 发布程序必须消费该证据，正式读取当前保持关闭。

已批准恢复后在原工作目录运行本脚本，按月份限定范围。遇到新质量问题暂停；
额度接近预留边界／耗尽时暂停，等待用户明确恢复，不因次日重置自动续跑。
`--resume-after-review` 只允许有明确人工授权及核查记录的恢复，自动跟进不得自行使用。

离线回归（不调用真实 SDK／工作库）：

```bash
uv run --frozen pytest packages/gr-data/ops/ricequant_backfill -q --override-ini addopts=''
```

数值审计保留全行、全元素的 float32 严格相等；协方差为 float64 严格相等。
历史数据等价证明及旧批次处理结果见
[验收记录](../../../../docs/history/2026-10-24-rq-real-recovery.md)。
