# 已确认的权威实现

本目录只保留当前推荐的五个处理节点。实验仍在 `scripts` 开发；用户批准后更新快照、来源和验收记录，再提交推送。

| 节点 | 当前入口 | 职责 |
| --- | --- | --- |
| 硬拼接拆分 | [body-scan-pairs](body-scan-pairs/README.md) | 仅处理两张照片硬拼接，独立分类子图；工作流使用 `--split-only` |
| 单图标准化 v4 | [body-scan-wall-v4](body-scan-wall-v4/README.md) | 海报过滤、网格/非网格校正、可靠几何检查及回退、最大有效矩形 |
| 同组展示 v3 | [body-scan-group-display-v3](body-scan-group-display-v3/README.md) | 共同人物尺度、完整头脚保护、肩部共同取景、一人一画幅 |
| 体检表单对比 | [body-report-compare](body-report-compare/README.md) | 独立提取门店报告、按明确前后列核验、标准 JSON / HTML |
| 训练阶段自动分类 | [body-scan-phase-classification](body-scan-phase-classification/README.md) | 盲评视觉与可选报告辅助，补齐全部阶段标签及推断/待审标记 |

推荐链路：**拆分 `--split-only` → 单图标准化 v4 → 同组展示 v3**。拆分的默认一键入口也已迁移到 v4；已经默认完成标准化时，不要再接一次标准化节点。

拆分需要与 v4 一起部署：它从 v4 导入已冻结的公共人物定位模块，并锁定 v4 清单指纹。v4及同组v3均不读取已删除的旧目录或开发代码。新增的表单对比和阶段分类均包含独立依赖及完整性检查，互不导入。成品审核节点位于 `scripts/body_scan_delivery`，只消费数据，不调用模型。接口及运行说明见[三节点解耦工作流](../docs/workflows/report-phase-delivery.md)。

2026-11-06按用户要求删除 `grid-portrait`、`body-scan-wall`（旧v3）、`body-scan-group-display`（旧v2）。历史代码和验证仍可从Git恢复，不再复制到当前目录；来源清单中的旧路径是指定提交中的历史来源，不是运行依赖。清理范围、恢复方式及远程验证见[版本清理记录](retired-snapshots.md)。

下游链路：**同组展示 → 阶段分类 → 成品生成**；**体检表单对比**可先独立运行，同时向分类与成品提供数据。已有三个图像处理最佳实践的代码和清单保持不变。
