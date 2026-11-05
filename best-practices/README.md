# 已确认的权威实现

本目录仅收录用户确认的方案，实验版本继续保留在原目录。新实验不得自动覆盖这里的实现；确认更新后须更新来源和验收记录，并提交、推送。

| 方案 | 权威入口 | 来源 |
|---|---|---|
| 网格体测照：统一人物比例后的最大矩形有效区域 | [grid-portrait/tools/grid_shoulder_frame_max_rectangle.py](grid-portrait/tools/grid_shoulder_frame_max_rectangle.py) | 用户确认的 v5，提交 `06d968a2585cf09e47d092427fb01ac3399f9035` |
| 完整体测图处理：网格/pinhole、可靠墙面参照、同组尺度与最大矩形 | [body-scan-wall/scripts/run_body_scan_refined.sh](body-scan-wall/scripts/run_body_scan_refined.sh) | 用户确认的墙面修正 v3，提交 `c3ce38966da8d39cf702778858e8e5881f9744ff` |

完整流程及已有v2产物的精修入口见 [body-scan-wall/README.md](body-scan-wall/README.md)。此前仅负责网格最终取景的独立快照继续保留，运行与输入要求见 [grid-portrait/README.md](grid-portrait/README.md)。两份快照均冻结必要依赖，并有来源清单及独立验证记录。
