# 已确认的权威实现

本目录只保留当前推荐的六个处理节点。实验仍在 `scripts` 开发；用户批准后更新快照、来源和验收记录，再提交推送。

| 节点 | 当前入口 | 职责 |
| --- | --- | --- |
| 硬拼接拆分 | [body-scan-pairs](body-scan-pairs/README.md) | 仅处理两张照片硬拼接，独立分类子图；工作流使用 `--split-only` |
| 单图标准化 v4 | [body-scan-wall-v4](body-scan-wall-v4/README.md) | 海报过滤、网格/非网格校正、可靠几何检查及回退、最大有效矩形 |
| 同组展示 v3 | [body-scan-group-display-v3](body-scan-group-display-v3/README.md) | 共同人物尺度、完整头脚保护、肩部共同取景、一人一画幅；附封面正面双图独立取景入口 |
| 体检表单对比 | [body-report-compare](body-report-compare/README.md) | 独立提取门店报告；原始报告优先、汇总补缺、有效日期校验及天数/变化量重算 |
| 训练阶段自动分类 | [body-scan-phase-classification](body-scan-phase-classification/README.md) | 盲评视觉与可选报告辅助，补齐全部阶段标签及推断/待审标记 |
| 体测成品生成 | [body-scan-delivery](body-scan-delivery/README.md) | 同目录下八类成品：完整三视图、各朝向 VS、阶段单图、会员案例封面、体测报告对比、会员感言、训练日常、生活照原图 |

推荐链路：**拆分 `--split-only` → 单图标准化 v4 → 同组展示 v3**。拆分的默认一键入口也已迁移到 v4；已经默认完成标准化时，不要再接一次标准化节点。

拆分需要与 v4 一起部署：它从 v4 导入已冻结的公共人物定位模块，并锁定 v4 清单指纹。v4及同组v3均不读取已删除的旧目录或开发代码。表单对比、阶段分类和成品生成均包含独立依赖及完整性检查，互不导入。成品生成开发入口仍在 `scripts/body_scan_delivery`，权威快照位于 `body-scan-delivery`，渲染只消费数据，不调用模型。感言另附显式运行的识别评分及内容/隐私复核准备入口，渲染不会调用它们。接口及运行说明见[三节点解耦工作流](../docs/workflows/report-phase-delivery.md)。

2026-11-06按用户要求删除 `grid-portrait`、`body-scan-wall`（旧v3）、`body-scan-group-display`（旧v2）。历史代码和验证仍可从Git恢复，不再复制到当前目录；来源清单中的旧路径是指定提交中的历史来源，不是运行依赖。清理范围、恢复方式及远程验证见[版本清理记录](retired-snapshots.md)。

下游链路：**同组展示 → 阶段分类 → 成品生成**；**体检表单对比**可先独立运行，同时向分类与成品提供数据。

封面分支：既有阶段结果选定正面前后素材 → 同组展示 v3 的 `run_cover.sh` 复用已确认几何及尺度，从原图生成封面双图 → 成品最佳实践 `member_cover/run.sh`。封面排版已归档为第四类成品，标准组六图及原三类成品算法不变，详见[封面工作流](../docs/workflows/member-cover.md)。

报告成品分支：`body-report-compare/run.sh tables` 生成五列表格数据 → [report_comparison/run.sh](body-scan-delivery/report_comparison/README.md) 消费数据与已裁剪的报告图。当前权威版本为用户于 2026-11-07 确认的 v5：九项指标按有值展示、表格等高，有报告图则上下拼版，无报告图则仅输出去留白的紧凑表格。来源代码为 `f1320dd32b3a2d3bec451ab9e2520058b15b3506`，详见[报告成品工作流](../docs/workflows/report-table-product.md)。

会员感言分支：门店感言候选 → `testimonial_album/evidence.sh` 识别评分 → `annotate.sh` 主要内容及图片隐私复核 → `run.sh` 固定红框成品。第六类已归档用户确认的 v5（来源 `4ae1d98aef16ca6a2ccf65b6927c23522d90a152`），保留对话名字与右侧教练头像，一图一次、统一标题模块及对称信封心形。详见[会员感言最佳实践](body-scan-delivery/testimonial_album/README.md)。

训练日常分支：门店 `daily_training` 分类 → `training_daily/evidence.sh` 动作取景证据 → `training_daily/run.sh`。第七类归档用户确认的无框 v2（来源 `ba42b69`）：普通照片轻度美化，过窄截图只去黑边保留原像素，主体不明确原文件直出。详见[训练日常最佳实践](body-scan-delivery/training_daily/README.md)。

生活照分支：门店 `life_photo` 分类 → `life_photos/run.sh`，第八类按原文件直接输出，不做对比、阶段判断或任何图像处理。全部筛选素材均保留，输出 SHA 与原图一致，详见[生活照最佳实践](body-scan-delivery/life_photos/README.md)。八类成品各自可独立运行，根成品 `create` / `restyle` 尚未自动串联所有分支。
