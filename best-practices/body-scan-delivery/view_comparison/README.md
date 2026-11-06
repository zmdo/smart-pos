# 各朝向训练前后对比图

绘图代码：[render.py](render.py)，版本 `body-same-view-reference-v5`。

支持正面、侧面、背面。左侧训练前，右侧训练后；必须为不同原图。默认宽 1080，高度随两图宽高比变化，两图等比缩放到共同显示高度后无缝并排，不重新裁切或拉伸人物。

保留用户确认的红白参考版式：顶部 Logo、悬浮朝向标题、中央 VS、英文 Before／After、箭头、姓氏称谓和地址、体检单指标胶囊。Before／After 下不画“推断／待审”；页脚不画“围度变化……”来源说明；顶部红色区域右下角绘制配置中的 `*案例真实有效，经会员本人同意使用`。

Logo 来自用户图片根目录的 `logo/`；SVG 支持透明边界取景。宽度、Logo、地址、称谓和指标通过 [presentation.example.json](presentation.example.json) 配置；新建完整成品时使用 `--presentation`，修改既有配置则通过根入口 `restyle --presentation` 产生新版本。类别入口沿用来源版本配置。

页脚只使用同店同名、通过核验的已绑定报告数据，变化按训练后减训练前重算。缺失项显示“未提供”，不造数。`stage_annotations: false` 仅表示图片不画审核小字，结果中的 `labels`、`requires_review`、`review_asset_ids` 均保留。

```bash
./run.sh --delivery /path/to/existing-delivery --out /path/to/vs-new
```

输入输出见[总说明](../README.md)。`draw_vs(rows, photos, font, context, view)` 返回 PIL 图像；`rows` 为 `[训练前, 训练后]`，`view` 为 `front/side/back`，`context` 由公共 `presentation.resolve` 生成。
