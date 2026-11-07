# 报告取景 · 保持原有纸张形状 v2

用户在 2026-11-07 明确弃用展平。本独立方案直接读取原始素材，不消费展平候选，不依赖 UVDoc，不改变既有报告提取、阶段分类或成品最佳实践。

## 取景规则

- **电子截图/电子表格**：模型定位完整报告正文，包括标题、会员/日期、数据表、报告结论、教练备注；裁去系统状态栏、软件工具栏、推荐按钮和大块无意义空白。
- **纸张照片**：定位主纸张，矩形外接框包含斜纸张各角；外接框中的纸张外背景留白。保留纸张原本的倾斜、卷曲、折痕与阴影。纸张边界使用保守凸包并向外扩两倍余量；如果覆盖模型正文框不足 88%，则停用背景蒙版、保留原像素并标记待检查。这个几何检查不是文字完整性的证明，定位仍需目视确认。
- **不明确/非报告**：返回 `needs_review` 和原因，不生成猜测取景。
- 纸张定位框增加短边 0.6%（至少 4px）的边缘余量。截图增加 3%，防止模型近似框切掉细表格边线。
- **固定的是画框比例，默认 3:4，不固定输出像素。** 以裁剪后的原始像素为基准，构建能够完整容纳它的最小 3:4 整数画布，居中留白，不缩小也不放大原图。
- 例如 2000×1600 的有效内容得到 2001×2668 的 3:4 画框，文字仍保留原始像素。HTML 使用独立缩略图等比展示，点击查看高清 PNG。仅明确提供 `--max-side` 时才限制导出像素，并使用单一缩放系数。
- 没有透视变换、展平、旋转、非等比拉伸，也不会为了铺满画框硬裁正文。初稿固定 540×720 已按用户纠正淘汰。

模型只做区域定位，不重绘、抄写或修改报告上的字与数字，不重新判断训练前后，也不以目录名确认报告正文身份。报告缺失、纸张重叠遮挡、反光等原始问题按模型观察保留在 `review_reasons`；定位仍需目视确认。

## 数据合同

输入：既有全量分类审计、原始项目目录、私有 Qwen 配置、模型调用缓存。仅处理 `xxx店` 下被已有分类标为 `body_report/training_report` 的图片，校验原文件 SHA-256。参考模板、说明文件不进入处理。

输出：新目录中的 `index.html`、`manifest.json`，以及各素材 ID 下的原图 PNG、未缩放裁剪图 `crop.png`、固定比例高清图 `frame.png`、预览 `frame-preview.jpg`、`result.json`。输出不覆盖历史结果，页面可按纸张/截图筛选。JSON 保存模型区域、调用记录引用、取景矩形、输出比例和实际像素、严格相同的 x/y 缩放系数、白边位置、源图与成品摘要以及待关注原因。

模型参数与输入图像参与缓存键，调画框大小可复用定位结果而无需再次付费调用。模型设置及 API Key 不写入报告、代码或预览。失败素材不从清单中消失，保留在 HTML 和 JSON。

## 服务器运行

全部模型调用、图像处理和输出在远程服务器进行：

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.report_photo_crop \
  --audit /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/classification-comparison.json \
  --input-root /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目 \
  --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json \
  --cache /root/autodl-fs/case-studio/cache/report-photo-crop-v1 \
  --out /path/to/NEW-output --ratio 3:4
# 可选 --max-side 1600，仅在确实要限制导出像素时使用；默认不缩小。
# 可用 --ids a0039 a0099 仅测试指定素材；默认并发 3。
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/report_photo_crop/tests -v
```

复用现有 `MeasuredClient`，预览发送给用户提供的 Qwen 视觉接口，按同一项目此前授权的路径缓存；原图本身不写入 git。

## 本次验证

全量 46 张均生成：37 张纸张照片、9 张电子截图。v2 沿用 v1 已定位的原始裁剪区域，新增模型请求为 0；逐张检查输出比例精确为 3:4，放入画框的所有裁剪像素逐像素一致，未缩小原图。a0039 输出 1014×1352，其他素材按自己的有效分辨率输出。

5 项测试通过，276 个 HTML 图片/下载链接有效，记录见 [validation.json](validation.json)。模型区域仍需目视审核，边界遮挡或原素材缺失不会被补画。

远程预览：`/root/autodl-fs/case-studio/experiments/report-photo-crop-v2-20261107/validated`。
本机预览：`/Users/zhangming/Projects/FP16-Speed/artifacts/report-photo-crop-v2/validated/index.html`。
