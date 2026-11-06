# 完整三视图

绘图代码：[render.py](render.py)，版本 `body-three-views-seamless-v2`。

输入为同一会员六张已批准、同规格的体测展示图。上排训练前，下排训练后；每排依次为正面、侧面、背面。六张图按原尺寸无缝拼接，不加红条、文字、间隔，不重新裁切或缩放。单图为 W×H 时，结果为 3W×2H 的无损 PNG。

缺槽位不出图并记录原因；绘图函数会拒绝非六张或尺寸不同的输入。阶段不确定信息保留在返回数据和审核清单中。

```bash
./run.sh --delivery /path/to/existing-delivery --out /path/to/three-views-new
```

仅重绘完整三视图，输入和输出契约见[总说明](../README.md)。函数 `seamless_grid(rows, photos)` 返回 PIL 图像，`rows` 顺序须为 `[前正, 前侧, 前背, 后正, 后侧, 后背]`；`photos` 为素材 ID 到已批准图片路径的映射，公共规划器负责槽位及不同原图校验。
