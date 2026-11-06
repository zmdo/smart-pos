# 训练阶段自动分类

独立节点消费批准的同组展示输出和可选体检表对比 bundle。视觉判断使用原图及等比参考，保持当前局部观察、换序复核、可靠拍摄批次和多朝向规则；不读取原始 PDF/DOCX，不生成成品。

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase_classification run \
  --input /path/to/approved-display --override /path/to/newer-approved-display \
  --reports /path/to/report-bundle --out /path/to/new-phase-run \
  --settings /path/to/private-provider.json --cache /path/to/model-cache --provider qwen
```

`--override`、`--reports`、`--baseline` 均可省略。`--baseline` 仅用于重用同源同参考的既有整体观察及历史对照，不是运行必需条件。缺少报告时使用视觉证据。多个报告无法与照片批次绑定时不任意选择一份。视觉提示词不含报告目标，报告变化的解释和融合在视觉盲评后进行。

完整运行输出 `analysis/`（原分析与审计）和 `classification/`（可交给成品节点的完整标签包）：

- `labels.json`：每张图必有 before/after；规则、推断、待审、人工确认分别记录。推断和待审含中文后缀及 `requires_review=true`。
- `inputs.json`：照片和输入文件 SHA，保留身份与覆盖校验。
- `report-link.json`：所消费报告 bundle 的路径与 SHA；未使用报告则为空。
- `bundle.json`：`body-scan-phase-labels-v1` 契约，成品节点通过该契约读数据。
- `audits/`：补齐标签时的模型排序、配对/批次约束选择依据。

规则/推断保留；无推断的图采用同朝向候选支持分，并保留可靠批次一致性与不同原图配对约束。分数不是校准概率。无法获得有效评分时输出明确的待审占位，confidence=null，不编造模型置信度。

可以直接为已经完成的视觉分析补齐标签：

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase_classification finalize \
  --analysis /path/to/analysis --reports /path/to/report-bundle --out /path/to/new-labels \
  --settings /path/to/private-provider.json --cache /path/to/model-cache
```

该入口核对分析时使用的报告内容；报告内容或覆盖变化须重新执行 `run`。省略模型配置时，无法从现有证据推断的项目保留无评分待审标记。

`--corrections` 可接 JSON 列表，每项包括 `asset_id`、`source_sha256`、`phase`、`confirm:true`。人工确认在最终标签中优先。成品页面的既有审核回传接口仍可直接重生成，不需要重新运行本节点或调用模型。

接口、冻结入口和验证见[三节点工作流](../../docs/workflows/report-phase-delivery.md)。
