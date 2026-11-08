# 训练前／训练后的朝向单图

绘图代码：[render.py](render.py)，当前为 `body-single-photo-v2`，2026-11-08 按用户要求去除所有画面文字。

每张已批准照片各输出一张，不因同槽位有多张而丢弃。正面、侧面、背面及训练前／训练后标签保留在文件名和审核元数据中。画布为 1080×1440；照片等比完整居中放入整个画布，不再次裁切或拉伸。画面仅有照片和补齐比例的留白，不绘制标题、训练阶段、审核小字，也不保留独立的底部标题条。留白使用 `context.background`，默认 `#F3F0EA`。

沿用输入照片已有遮罩；本节点不检测或重新贴脸部遮罩，不修改人物比例。与 VS 去掉审核小字、三视图不加文字的规则分别维护。

```bash
./run.sh --delivery /path/to/existing-delivery --out /path/to/singles-new
```

输入输出见[总说明](../README.md)。`draw_single(rows, photos, font)` 返回 PIL 图像，`rows` 含一张已完成标签的素材，公共渲染器负责保存 JPEG 及审核来源。
