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

## 图片报告与五列表格：原始报告优先（v3）

`tables` 入口输出 `body-report-five-column-v1` 数据包。2026-11-07 用户调整取数规则：**原始体测报告优先；原始报告缺失的指标可由阶段汇总表补充；所有天数和变化量重新计算。** 旧 PDF/DOCX 接口和 `body-report-comparison-v1` 证据包不改，不自动重判照片阶段。

```bash
python -m scripts.body_report_compare tables \
  --input /path/to/私教会员案例项目 --audit /path/to/classification-comparison.json \
  --settings /path/to/private-qwen.json --cache /path/to/table-cache \
  --out /path/to/new-five-column-bundle --workers 3 --as-of 2026-11-07
```

冻结入口为 `best-practices/body-report-compare/run.sh tables`，参数相同。`--as-of` 默认上海时区今天，不能指定未来日期；明确提供它可固定历史重跑的校验上限。

1. 只读取门店目录的报告原图、PDF/DOCX；校验原文件 SHA。识别读取原始图片，复用绑定原图的模型缓存。参考模板和说明目录不处理。
2. 日期必须是有效的 **20xx 年** 日期且不晚于处理日。超长年份（如 20266）、非法日历日期、未来日期一律拦截；原始报告有清晰日期时采用原始日期，不能把异常汇总日期直接绘制出来。没有可靠替代依据时留缺失，不凭空改年/月/日。
3. 优先按原始测试日期配对。原始日期不可读时，只有原表明确前后列和有效日期、至少两项有区分度的指标唯一匹配且无冲突，才用汇总日期补充配对，并保留说明。
4. 生成“时间”行：训练前日期、训练后日期、`后日期 - 前日期` 的实际间隔天数、单位“天”。按日历相减，不把首尾两天同时计入，也不复刻原填天数；支持跨月、跨年和闰日。
5. 按指标逐个取值：原始报告的可靠实测值优先；缺失或无法读取的单元格可由汇总表补充。每格保存来源 ID、SHA、原文、取值方式。原始报告与汇总冲突时使用原始值，`corrections` 保留原汇总值和替换依据。
6. 所有变化量用 Decimal 按后减前重算，单位先归一。体脂率差值为百分点；明确标注的双侧/大腿小腿分别计算，未标左右的双项按原表顺序计算并提示。不识别的单元格留空，不填零，不沿用错误的原填变化量。
7. 目录只负责分组和检索，姓名/门店按报告记录；没有原始报告时可用有效的汇总表数据计算独立表格。有数据疑点或缺失时写入审核清单。

输出 `records.json`（原始转录与日期拒绝记录）、`tables.json`（重算结果、修正记录、来源、缺失）、`index.html`、带 SHA 的 `bundle.json` 及固定 `as_of` 的 `config.json`。原始提取字段保留用于追溯，不直接当作成品表格。原表不再决定成品的变化量和天数。

成品入口见 [report_comparison](../../best-practices/body-scan-delivery/report_comparison/README.md)。修改数据规则后重新生成表格包；仅改版式时复用表格包，不调用模型。

2026-11-07 全量验证：51 份原始资料、18 组、261 行；18 组时间行均通过有效日期和实际日历差校验，329 个原始实测单元格优先级及 242 个数值变化量逐项验证。报告节点 35 项测试通过；复用原图绑定缓存，本次没有新增模型请求。见 `validation-original-first-v3.json`。
