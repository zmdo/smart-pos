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

## 图片报告与完整五列表格（2026-11-07 新增）

增加 `tables` 入口，旧入口及 `body-report-comparison-v1` 完全保留。新入口输出独立 `body-report-five-column-v1` 数据包，供报告拼图使用；原训练阶段分类、封面、围度展示继续使用旧接口，不会因新图片提取静默改变已有标签。

```bash
python -m scripts.body_report_compare tables \
  --input /path/to/私教会员案例项目 --audit /path/to/classification-comparison.json \
  --settings /path/to/private-qwen.json --cache /path/to/table-cache \
  --out /path/to/new-five-column-bundle --workers 3
```

冻结入口为 `best-practices/body-report-compare/run.sh tables`，参数相同。

1. 只扫描审计清单中的门店报告图片和门店 PDF/DOCX；图片绑定原图 SHA，识别读取原图，避免取景裁掉部分单元格。参考模板和说明目录不处理。
2. 有明确训练前后列的表格：Qwen 转录所有行、原顺序、原单元格、变化量和单位，包括时间、非预设指标、双侧围度；程序保留原填值，另存可计算的变化量和冲突说明。没有明确前后列头的多阶段手写表不随意映射成前后两列。
3. 没有可用表格：按明确测试日期从早到晚配对两份体测数据；有表格日期则优先匹配对应日期，否则采用最早和最晚并记录周期差异。只匹配同名指标，统一 kg/cm 等单位后用 Decimal 计算后减前；体脂率差值代表百分点。缺失、重复、单位不兼容、读不清的指标不填零、不猜数值。
4. 既无表格又无可靠数据配对：不输出表格，返回原因。禁止根据数值“更好”交换训练前后。
5. 按用户原目录分组；目录可能是教练名。报告印刷姓名与目录名分开保存；展示以选中报告的姓名为准，同时保留差异提醒。用户明确以报告为权威：展示姓名、门店采用选中报告，目录仅作分组检索；差异保留说明。全部原始提取记录均保留，候选表格版本也不丢弃。

输出：`records.json` 保存每份来源与全部转录；`tables.json` 保存逐组五列表格、报告配对、来源、姓名、逐行异常及跳过原因；`index.html` 为纯表格预览；`bundle.json` 绑定这三个文件 SHA。私有 `audit/` 保存答复与请求追踪，不含密钥。新接口的视觉转录 不能当作旧接口的文字单元格核验结果；不自动升级为已核验阶段证据。

成品排版入口见 [report_comparison](../../best-practices/body-scan-delivery/report_comparison/README.md)。仅修改版式时复用此数据包，不再次调用模型。

报告日期不可读时，只有在现成表格有明确前后列及日期、两侧分别至少两项有区分度的实测指标唯一匹配且无冲突时，才补充报告配对；显示日期取自原表并标记待核对。只有一项相同、多个候选或已知日期冲突均不能这样配对。

本轮全量 51 份来源：46 张图片、5 份门店文档；18 组中 16 组复刻原表、2 组按体测数据计算，15 张报告组合成品、3 张独立表格，共 165 行。原报告 JSON、清单与 HTML 与旧版本逐字节一致；报告节点 25 项测试、成品包 60 项测试通过。审核项见输出的 review.json。

## 冻结入口

从任意目录执行本目录 `run.sh`。启动核验代码和文档 SHA，清空 PYTHONPATH；`run_tests.sh` 运行原契约及新增五列表格测试。所有识别和图像处理在远程服务器执行。
