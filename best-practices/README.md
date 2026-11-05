# 已确认的权威实现

本目录仅收录用户确认的方案，实验版本继续保留在原目录。新实验不得自动覆盖这里的实现；确认更新后须更新来源和验收记录，并提交、推送。

| 方案 | 权威入口 | 来源 |
|---|---|---|
| 网格体测照：统一人物比例后的最大矩形有效区域 | [grid-portrait/tools/grid_shoulder_frame_max_rectangle.py](grid-portrait/tools/grid_shoulder_frame_max_rectangle.py) | 用户确认的 v5，提交 `06d968a2585cf09e47d092427fb01ac3399f9035` |
| 完整体测图处理：网格/pinhole、可靠墙面参照、同组尺度与最大矩形 | [body-scan-wall/scripts/run_body_scan_refined.sh](body-scan-wall/scripts/run_body_scan_refined.sh) | 用户确认的墙面修正 v3，提交 `c3ce38966da8d39cf702778858e8e5881f9744ff` |
| 两张体测照片硬拼接：无损拆分、独立分类后交给单图最佳实践 | [body-scan-pairs/scripts/body_scan_pairs/run.sh](body-scan-pairs/scripts/body_scan_pairs/run.sh) | 用户确认的拆分 v1，提交 `5dec62c3b96eedd84c8159d071dbb289957815c4`；渐变淘汰、不确定待复核 |

完整单图流程及已有v2产物的精修入口见 [body-scan-wall/README.md](body-scan-wall/README.md)。对比图先使用 [body-scan-pairs/README.md](body-scan-pairs/README.md)，该副本锁定并复用相邻的单图快照。此前仅负责网格最终取景的独立快照继续保留，运行与输入要求见 [grid-portrait/README.md](grid-portrait/README.md)。三项均保存来源清单及独立验证记录，不依赖开发目录的后续修改。
