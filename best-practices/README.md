# 已确认的权威实现

本目录仅收录用户确认的方案，实验版本继续保留在原目录。新实验不得自动覆盖这里的实现；确认更新后须更新来源和验收记录，并提交、推送。

| 方案 | 权威入口 | 来源 |
|---|---|---|
| 网格体测照：统一人物比例后的最大矩形有效区域 | [grid-portrait/tools/grid_shoulder_frame_max_rectangle.py](grid-portrait/tools/grid_shoulder_frame_max_rectangle.py) | 用户确认的 v5，提交 `06d968a2585cf09e47d092427fb01ac3399f9035` |
| **当前单图标准化 v4**：背景过滤、网格/pinhole、墙面修正、可疑几何检查与回退、最大矩形 | [body-scan-wall-v4/scripts/run_body_scan_refined.sh](body-scan-wall-v4/scripts/run_body_scan_refined.sh) | 用户批准的几何检查方案，来源 `7cfbb0d23e27a570f52120fe8d0d1d8c148b3a3c`；默认自动串接 |
| 历史单图标准化 v3：墙面参照与同组尺度修正，保留用于复现和旧拆分依赖 | [body-scan-wall/scripts/run_body_scan_refined.sh](body-scan-wall/scripts/run_body_scan_refined.sh) | 原样保留 `c3ce38966da8d39cf702778858e8e5881f9744ff` 的快照 |
| 两张体测照片硬拼接：无损拆分、独立分类后交给单图最佳实践 | [body-scan-pairs/scripts/body_scan_pairs/run.sh](body-scan-pairs/scripts/body_scan_pairs/run.sh) | 用户确认的拆分 v1，提交 `5dec62c3b96eedd84c8159d071dbb289957815c4`；渐变淘汰、不确定待复核 |
| 同人图片大小标准化：肩部共同取景、一人一画幅、等比参考与展示版 | [body-scan-group-display/scripts/body_scan_group_display/run.sh](body-scan-group-display/scripts/body_scan_group_display/run.sh) | 用户确认的展示 v2，来源提交 `3aca63e72f65ccd8d63e59a758b9a1f00065297b`；海报过滤后的42张基线 |

当前完整单图流程、已有v2精修和v3升级入口见 [body-scan-wall-v4/README.md](body-scan-wall-v4/README.md)。对比图先使用 [body-scan-pairs/README.md](body-scan-pairs/README.md) 的 `--split-only`，再把派生job交给v4；旧拆分副本的默认自动标准化仍锁定v3，保留用于复现，不能代替新链路。此前仅负责网格最终取景的独立快照继续保留，见 [grid-portrait/README.md](grid-portrait/README.md)。各方案保存来源清单及独立验证记录，不依赖开发目录的后续修改。

标准化后的同人尺寸统一使用 [body-scan-group-display/README.md](body-scan-group-display/README.md)。海报过滤和可疑非网格几何检查都已包含在v4上游标准化入口，不再需要借用开发目录补充这两步。v4沿用兼容的单图结果格式，另外记录最佳实践版本；拆分及同组展示算法保持原样。
