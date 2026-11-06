# 体检表单对比生成

独立节点：扫描原始素材根目录中的 `xxx店/会员/...` PDF/DOCX，转录并核验明确的训练前后列，输出标准 JSON 与可直接展示的 HTML。无须照片、照片分组或训练阶段分类结果。参考模版和说明目录记录为排除。

```bash
PYTHONPATH=/root/apps/phase-evidence-deps:/root/apps/case-studio \
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_report_compare \
  --input /path/to/私教会员案例项目 --out /path/to/new-report-bundle \
  --settings /path/to/private-provider.json --cache /path/to/model-cache --provider qwen
```

输出目录必须不存在。可选 `--reuse /path/to/legacy/reports` 按原文件 SHA 复用既有转录答复；仍从原文件重新检查单元格、列顺序、日期和身份，不能直接信任旧模型答案。其他报告继续提取；没有配置模型时保留明确失败原因。

- `reports.json`：每份门店报告一条，包括来源相对路径/SHA、门店/姓名、明确前后列、日期、标准值、原始单元格、后减前变化、单位、缺失、异常及可用性。不含照片阶段推断。
- `inventory.json`：全部候选文档及排除、待审原因。未通过核验的文档不丢弃、不填造数据。
- `index.html`：标准对比表、日期/原填天数、异常提示和原始行，可独立打开、筛选、打印。
- `bundle.json`：`body-report-comparison-v1` 契约，绑定以上三个文件 SHA。消费者不需要原始文档、模型 Key 或提取代码。
- `rNNN/`：私有转录审计、原文、PDF 页面；`sources.json` 绑定原始输入。成品只附带前三个公开数据文件，不包含这些审计文件。

按明确列头确定前后；不因参数更好而交换列。BMI/变化量异常保留原值，标注原因，不静默覆盖。报告日期不自动代表照片拍摄日期。如何将报告变化用于照片阶段判断，由训练阶段分类节点决定。

接口、冻结入口和验证见[三节点工作流](../../docs/workflows/report-phase-delivery.md)。
