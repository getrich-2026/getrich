# 米筐 REAL 修复与旧批次处理验收

读者：数据维护者及 D-022 发布程序实现者。状态：2026-10-24 的历史验收记录；
回补仍在进行，正式风险读取关闭。范围：三模型 production，既有 682 个已通过批次及
2024-12-11 v2 问题批次。

## 历史批次等价依据

原审计在 REPEATABLE READ READ ONLY 事务内读取每个 run 的全部数据行，
核对覆盖完整交集、证券键、因子顺序和矩阵形状，再对全部元素执行
`np.array_equal(actual.astype(np.float32), expected.astype(np.float32))`。
没有抽样、没有相对误差容忍。expected 由原 raw 和显式单位独立计算。

逐一核对 682 份 passed 报告、收据版本和元素计数；全部符合：

| REAL 字段 | 全量比较元素数 |
|---|---:|
| exposure | 164,854,032 |
| factor_return | 32,276 |
| specific_risk | 3,483,408 |
| specific_return | 3,483,408 |

旧 importer 为 `aa54d8063b2d933b35742339a2e8ed408a0b5745`。
REAL 修复 `0111b4c7b901d74a04ace79d784c627056e75a50` 仅在写库边界先量化 binary32，
与上述 expected 完全相同。因此同一 raw、同一单位下，这 682 批全部四类 REAL 存储值
与新 writer 相同，不重导。此结论不宣称供应商未来重新抓取的数据永远不修订。
逐批报告、SHA256、计数保存在本机原执行目录的
`acceptance/real-equivalence-20261024/equivalence.json` 及相邻审计副本。

## 问题批次与替代结果

旧 run `4cc48d3d-663a-5fc9-be51-17548ec23966`、旧 observation
`608016044ef54173a077abe5445c03b5`、原收据与 raw 全部保留。
数据库 `ops.data_quality_check.check_id=37` 追加 `risk_bundle_publishable` 审核，
detail 明确 `publishable=false`，关联旧 run、原 receipt 和 ETL run 2934。
不修改原收据的 quality，不改变用途，不删除失败证据。

```sql
SELECT check_id, detail
FROM ops.data_quality_check
WHERE rule = 'risk_bundle_publishable'
  AND detail->>'factor_model_run_id' = '4cc48d3d-663a-5fc9-be51-17548ec23966';
```

新 importer 为 `6320f70a7dc4a5e4a4d7ae51cbfbf00bb8c1eab3`，新增显式选择 observation；
同 observation 跨 importer 仍禁止重新绑定。
仅重采 2024-12-11 v2 的五件套，新 observation
`dd575eefbfb44f2386be86cb50776d23`，新 run
`206dc517-ad18-55ba-a7cd-6e2d56e36f36`。新旧 raw 五件套全元素、索引、因子顺序和覆盖
记录完全一致。新 available_at 为实际采集时间 2026-10-24 09:46:17.697310+08:00。
候选 5,116，完整 5,115；唯一缺口为已知 IPO 首日缺特异收益。
新批次严格数值、单位、正定/条件数、载荷、日期/顺序、calibrated=false、
收据/绑定/双水位及 available_at 全部审计通过后，执行器才追加 supersession 并继续。
旧 run 的禁用记录永久保留，不因新 run 通过而翻为 true。

## 版本与验证

执行器冻结历史 622 个成功 job、首 20 日的 60 个基线 job 和旧 attempts；
新 job 显式保存新 SHA，policy 首次使用后哈希锁定，不回写历史 importer。
失败新审计不写 supersession。新旧观察都保留，只按明确 ID 选择，不回退最新。

- 米筐测试 478 passed，含一次性 PG 真实 COPY 及不可变绑定反例。
- 全 gr-data：997 passed、21 skipped、8 xfailed；采用 `--import-mode=importlib`
  解决既有同名测试模块收集冲突，没有放宽断言。
- 执行器／审计／版本策略 49 passed；独立代码审查通过。
- Ruff、格式及差异检查通过；测试容器清理。未推送；用户 gr-tools/config.py 改动未提交。

D-022 尚未开放，未来发布必须拒绝命中 `publishable=false` 的旧 run，
仅逐项钉住已验收的替代 run；不能按最新记录推断替代关系。
