# 局部可比性与训练报告辅助判断

当前作为训练阶段分类节点的分析内核。报告提取已移至 `body_report_compare`，完整阶段标签补齐在 `body_scan_phase_classification`；推荐调用两个独立最佳实践入口。下述分析入口仍保留供诊断使用。

独立实验节点，保留已有图片和前后判断脚本。先盲评照片上的局部差异，再把报告的明确前后列作为辅助线索；无法确认的照片保留待复核。训练报告的时间顺序不等于照片已经绑定到这些日期。

流程和限制见 [工作流](../../docs/workflows/training-phase-regions.md)。

## 运行

在远程服务器运行，复用现有 Python 环境中的 OpenCV、NumPy、Pillow、httpx、pypdf、python-docx。PDF 页面渲染另用 `pypdfium2==5.14.0`，安装到独立的 `/root/apps/phase-evidence-deps`，不改网站环境。配置文件只从服务器私有路径读取，密钥不进入输出。

```bash
cd /root/apps/case-studio
PYTHONPATH=/root/apps/phase-evidence-deps:/root/apps/case-studio \
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase_regions \
  --input /path/to/full-display \
  --override /path/to/latest-approved-display \
  --baseline /path/to/previous-phase-qwen \
  --reports /path/to/report-bundle \
  --settings /path/to/private-provider.json \
  --provider qwen \
  --cache /path/to/model-cache \
  --out /path/to/new-experiment \
  --workers 3 --controls
```

`--override` 可重复，用于覆盖指定图片的等比参考。必须来自原输入中同一店、同一会员、同一原图哈希、同一朝向；原图和已验证左右阶段规则不变。仅替换参考图，不重新进行标准化。原输入必须是已批准同组展示节点的输出。

不传 `--member` 时覆盖所有已成功展示的店铺图片。可重复传 `--member 姓名` 做指定子集；输出会明确标记子集。上游排除项单独保留，不能把“所有合格图”说成“所有上传图”。

输出目录必须不存在。调用按模型、提示词和图片像素缓存，失败后可以换一个新输出目录重跑，复用已完成请求。不通过反复问同一语义问题投票选择想要的答案。

## 输出

- `index.html`：可离线查看的会员卡、原图、区域框、局部对照、逐项依据、报告数据与异常。
- `baseline-summary.json`、`regional-summary.json`、`summary.json`：相同输入的原整体观察、局部观察、报告辅助三种结果。报告辅助版为本实验最终结果，尚非生产权威。
- `groups.json`：候选拍摄批次、批次可靠性、跨朝向关系和冲突。
- `pairs/*/evidence.json`：正序/换序原始答复、可用性、稳定观察项、报告辅助理由。
- `reports`：报告覆盖清单、原始段落/表格、PDF页面、转录、数值与日期校验。无唯一对应合格照片组的报告只登记，不用于其他会员。
- `controls.json`：正/背/侧同图负对照及模型原始误报记录。生产身份哈希保护始终阻止同图排序。
- `sources.json`、`verification.json`：输入绑定和完整性检查。

## 导出报告标准表（HTML）

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase_regions.report_table \
  --reports /path/to/final-reviewed/reports \
  --out /path/to/new-report-table/index.html
```

输出为独立HTML，可离线按会员筛选、查看标准化数值及原文、打印。变化量统一后减前，体脂变化使用百分点；双项臂围按原顺序保留，不猜左右。未记录指标显示缺失，BMI/变化量/天数异常保留原值并标明；未匹配或未通过核验的门店报告另列。导出只消费既有结果，不调用模型、不修改报告或照片阶段，输出文件必须不存在。

本轮HTML包含4份报告、32项已提取指标、4项骨骼肌量缺失占位，以及1份尚未匹配的门店报告。逐项数值、差值、原填值和筛选/原文展开检查通过；桌面及移动端展示已核对。记录见[validation-report-table.json](validation-report-table.json)。

## 验证

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/body_scan_phase_regions/tests -v

/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase_regions.verify \
  --out /path/to/new-experiment
```

测试检查局部姿势干扰隔离、换序一致性、相同照片、报告字段原文绑定、BMI异常、前后列顺序、体重增加并减脂、冲突和可靠批次传播。采纳数与自动化率不能当作语义准确率。

本轮记录见 [validation.json](validation.json)：82张/16组，29张源规则、19张视觉推断、34张待复核。4份报告通过原文校验，独立报告辅助没有额外增加标签；93项测试通过。背面同图仍有模型原始误报，已被换序/来源保护拦截。预览同时展示成功与复核，旧结果不覆盖。
