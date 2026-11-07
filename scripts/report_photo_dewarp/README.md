# 报告照片曲面展平 · 独立试验 v1

**已弃用**：用户审阅后否决展平效果，现使用 [report_photo_crop](../report_photo_crop/README.md) 保持纸张形状并等比取景。本目录仅留作历史实验，不再推荐接入成品。

本目录验证体测报告纸张能否展平，尚未接入成品最佳实践、表单数字提取或训练阶段判断。

使用作者发布的 [UVDoc](https://github.com/tanguymagne/UVDoc)（MIT，固定提交 `4c9b82b537057aff2526e6dd118a847cdd072e82`）。模型预测二维反向网格，再对原图做双线性采样；没有生成文字、数字、补画遮挡区域，也没有重新排版 OCR 文本。第三方代码和权重放在远程独立目录，未复制进本仓库。

## 输入和输出

- 只选择现有全量分类结果中 `qwen.kind=body_report/training_report` 的门店素材；这只是选样依据，不代表报告身份、日期已核实。
- 校验原文件 SHA-256、门店范围、模型固定版本和干净工作区；参考模板、说明目录不能进入本试验。
- 输出必须是新目录。保存经过 EXIF 方向处理的原图、展平候选 PNG、预览 JPEG、反向网格 NPY、`manifest.json` 和左右对比 HTML。
- 输出像素尺寸沿用原图，不强制 A4 比例。这只是首轮模型基线，不能认为真实纸张纵横比已恢复。
- 检查网格有限值、局部翻折和采样越界；越界处白底且明确记录。这些检查不能证明没漏字或没裁边。
- 所有结果均是 `candidate_requires_review`，自动采纳数为 0。截图也输入模型作为负对照，用来验证为什么需要前置分流；并非推荐处理截图。

## 远程运行

仅在服务器执行模型与图像处理，复用已有 Torch/CUDA 环境，不安装或变更线上服务依赖：

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.report_photo_dewarp \
  --audit /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/classification-comparison.json \
  --input-root /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/input/私教会员案例项目 \
  --uvdoc /root/apps/report-dewarp/uvdoc-4c9b82b \
  --out /path/to/NEW-experiment
# --ids a0006 a0099 可仅跑指定报告。
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/report_photo_dewarp/tests -v
```

环境依赖：Torch、NumPy、OpenCV、Pillow；作者模型权重 `model/best_model.pkl` 随官方仓库提供。加载使用 `weights_only=True`。模型版本、权重摘要、输入摘要、输出摘要、实际峰值分配显存随实验记录。

## 首轮观察与下一步

已目视检查六张典型样本：

| 样本 | 观察 |
| --- | --- |
| a0006 关文博 | 中部表格线弯曲有所改善；左侧仍有卷曲残留，且边缘文字损失风险明显 |
| a0099 黎国萍 | 表格整体更平；顶部遮挡本来就无法恢复，候选又多裁去了顶部标题，不能直接采纳 |
| a0037 张小飞 | 中部折痕、阴影仍在，部分线条还斜；没有达到扫描稿效果 |
| a0138 何彦霖 | 原图已经较平，模型收益有限且额外裁边；应更保守 |
| a0114 郑远晨 | 几何有调整，但局部弯曲、折痕和阴影仍在 |
| a0039 张小飞目录的训练报告截图 | 原本平直表格被拉弯，明确负对照；目录归属不等于报告正文身份已核验 |

建议后续分流：电子截图/平整扫描件保留原状，平面透视照片先四边校正，确有弯曲的纸张照片才尝试曲面展平。采用前必须检查表格横纵线、正文边界及关键字段完整性；不通过时保留原图并返回原因。OCR 只用于辅助核对，不用识别文字重绘“原报告”。原图拍漏、重叠遮挡、反光抹去的内容无法从单张照片可靠还原。

本试验没有实现上述自动分流和内容质量门控，不应把实验入口当作生产标准化节点。详细运行记录见 `validation.json`，工作流说明见 [报告照片展平](../../docs/workflows/report-photo-dewarp.md)。
