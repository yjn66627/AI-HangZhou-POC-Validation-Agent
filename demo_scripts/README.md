# demo_scripts｜演示脚本

> 对应冻结版本：`DEMO_FREEZE_v1.0`
> 正式契约：[`../docs/demo/DEMO_FREEZE.md`](../docs/demo/DEMO_FREEZE.md)
> 数据包：[`../demo_cases/README.md`](../demo_cases/README.md)

本目录只写**现场怎么讲、点哪里、失败时说什么**。不实现 UI，不修改 Gateway / Runtime / Prompt。

| 文件 | 用途 |
| --- | --- |
| [`SCRIPT_3MIN.md`](SCRIPT_3MIN.md) | 初赛 / 时间紧：只跑 `DEMO-S` |
| [`SCRIPT_5MIN.md`](SCRIPT_5MIN.md) | 正式路演：`DEMO-S` +（`DEMO-N` 或 `DEMO-U`），`DEMO-F` 一键待命 |
| [`FAILOVER.md`](FAILOVER.md) | LIVE 失败切换口播与操作 |
| [`JUDGE_FAQ.md`](JUDGE_FAQ.md) | 评委可能追问的 10 个问题 |

页面编号（UI 尚未实现时按此预留，不得改顺序）：

1. 首页 / 项目入口
2. 需求与约束
3. 候选方案
4. 实验执行进度
5. 对照结果
6. Evidence
7. Decision
8. 失败 / 证据不足

角标必须始终可见：`真实运行` / `预置回放` / `演示数据`。无角标切换 = 造假。
