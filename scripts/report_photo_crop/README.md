# 报告取景 v3 · 原图内的固定比例矩形

用户在 2026-11-07 明确要求：**在原图上移动、调整固定比例的矩形，直接截取框内全部原始像素；超框时以最主要内容优先。** v1/v2 的纸张多边形蒙版和补白画布均已淘汰，本节点不使用它们，也不消费展平结果。

## 取景规则

1. 复用已有报告定位，或由视觉模型定位电子截图的正文矩形、纸张照片的纸面外接矩形及正文矩形。仅处理门店目录下的报告素材，校验原文件 SHA-256。
2. 默认比例为 **3:4**，像素尺寸随原图变化。优先选择能完整包住有效区域及小量边缘余量的最小原图内矩形；靠近原图边缘时移动矩形，不能超出原图。截图优先从正文顶部向下扩展，减少带入上方软件界面的机会。
3. 原图边界不足时，使用原图内最大的同一比例矩形，并增加核心区域定位：训练报告优先指标名称与训练前后数据，体测报告优先身体成分、体重、肌肉、体脂、BMI 等。标题、介绍、运动处方与版权页脚可以舍弃。
4. 根据核心区域移动矩形，最大化核心定位框的覆盖。截图优先从指标名称列开始，并把下边界靠近数据表底部，减少带入底部工具栏；核心仍无法全部容纳时照常给出受限候选，标记 `needs_review`，不能宣称内容完整。
5. 最终就是 `original.crop(rect)`。矩形内的纸张、手、背景、阴影等原像素全部保留。没有多边形、蒙版、补白、图像变形或重新排版。
6. 默认保存原始裁剪分辨率。可显式使用 `--max-side` 做等比导出缩小，仍然不补白。页面单独等比缩略预览，点击打开高清原图和裁剪图。

原图很宽而取景框为竖向时，即使放到最大也可能无法同时容纳所有表格列；原图很窄时也可能装不下整页高度。缩放整张原图不会改变这种相对比例关系。程序会据实记录核心框覆盖率和被裁去的内容，优先数据，不隐瞒受限项。覆盖率是模型矩形的几何覆盖，不是逐字 OCR 核验。

## 输入输出

- 输入：既有分类审计、原始素材目录、可选的来源绑定定位清单 `--selections`、可选的私有模型设置/缓存。
- 指定 `--selections` 时，逐项核验素材 ID、SHA-256 和 EXIF 方向处理后的尺寸。只继承矩形，丢弃历史 `paper_polygon` 字段。
- 正文放得下时不需要模型；正文放不下时，若已有 `priority` 就复用，否则使用提供的 Qwen 接口定位核心区域。未提供模型配置且无核心定位时，返回受限候选与说明。
- 输出：新的 `index.html`、`manifest.json` 和各素材 ID 下的 `original.png`、`framing-preview.jpg`、`crop.png`、`frame.png`、预览图及 `result.json`。绝不覆盖历史结果。
- 左侧原图上绘制实际取景框，右侧是直接裁剪结果：绿框为完整正文，蓝框为核心内容优先，橙框为核心仍超框。标记只画在预览图上，不写进原图或成品。
- JSON 保存原图裁剪坐标、比例、实际像素、原始正文与核心框覆盖率、允许舍弃部分、模型请求数、来源摘要及状态。失败素材仍在清单中。阶段判断不属于此节点。

## 服务器运行

全部图像处理和模型调用在服务器执行：

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.report_photo_crop \
  --audit /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/classification-comparison.json \
  --input-root /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目 \
  --selections /root/autodl-fs/case-studio/experiments/report-photo-crop-v2-20261107/validated/manifest.json \
  --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json \
  --cache /root/autodl-fs/case-studio/cache/report-photo-crop-priority-v1 \
  --out /path/to/NEW-output --ratio 3:4
# 可选 --ids a0039 a0106；--max-side 1600 仅限制导出像素。
# 对 v3 清单再次运行可复用已有 priority，省略 settings/cache 即不调用模型。
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/report_photo_crop/tests -v
```

10 项测试包含直接裁剪的逐像素验证、忽略多边形、原图边界、截图避开上下软件界面、核心区优先、超宽核心受限、来源绑定、等比导出，以及 500 组随机矩形约束检查。

全量 46 张均已输出：35 张正文定位框完整保留，11 张采用核心内容优先，其中 10 张核心定位框完整保留。a0011 横表仍存在核心区域超框，保留候选并标记待审。最终输出全部逐像素等于原图内对应的 3:4 矩形，新增正文定位请求为 0、核心定位请求为 11；35 张不需要核心取景的结果在本轮调整中保持不变。

本轮记录见 [validation.json](validation.json)。远程结果：`/root/autodl-fs/case-studio/experiments/report-photo-crop-v3-20261107/validated-v2`；本机预览：`/Users/zhangming/Projects/FP16-Speed/artifacts/report-photo-crop-v3/validated-v2/index.html`。
