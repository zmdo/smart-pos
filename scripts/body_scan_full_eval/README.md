# 全量门店素材与双视觉模型评测

独立实验工具。只处理原始包的 `xxx店` 目录；`参考模板`（包括原始素材）、`参考模版`、`会员案例素材生产标准（说明文件）` 整目录排除。所有图像解码、推理、测试、成品渲染都在远程服务器运行。本机只编辑代码、盘点文件与查看结果。

本轮不更改已冻结的 `best-practices`、生产模型设置或现有几何/标签决策策略。模型不是通过各自产生不同裁剪结果来比较，而是使用同一份已验证的原图和等比参考。

## 评测方法

1. `inventory` 对本机/服务器全文件做 SHA256 多重集核对，视频、文档、PSD 与目录排除均有记录。
2. `sweep --mode classification` 扫描所有门店静态图片，两模型使用相同墙面分类提示词、1280 最长边 / JPEG 92、temperature=0 和 JSON 输出；不按旧 `body_scan` 子集筛选。
3. `review` 合并新旧分类候选，输出原图索引；`prepare` 要求候选均有来源 SHA 绑定的复核结论，生成独立派生 job。任何门店图片无分类、候选无复核、来源发生变化都会报错。
4. 调用现有硬拼接、标准化、同组展示节点处理所有候选。海报在标准化节点排除；对比图先拆后逐子图审查，渐变直接淘汰，不确定待复核。单人和拆分子图合并后按同店同名统一画幅。
5. `sweep --mode background` 独立比较单图/拆分子图背景审查。整张混合背景对比图的探测仅为诊断，不用于代替子图过滤。
6. `observations` 对全部同人同朝向候选固定成对输入，两种顺序都检查，不受各模型拍摄批次分组不同影响；另加入 6 对相同照片的负对照。规则可比较性、换序方向与具体观察项均保留。
7. `phase` 注入计量客户端，运行不变的拍摄批次 v2 决策。模型单独复核批次，使用已缓存的对应外观比较答复。左右拆分的固定规则不会被 AI 覆盖。
8. `report` 生成逐文件去向、同人组旧/新效果、两模型标签、请求/错误/耗时/token/费用指标。每一张门店图片必须有明确去向，失败项不能从分母中消失。

## 模型和缓存

- DeepSeek 配置只读 `/root/autodl-fs/case-studio/settings.json`，`thinking: {type: disabled}`。
- Qwen 独立私有配置只读 `/root/autodl-fs/case-studio/private/qwen3.8-max-eval.json`，`enable_thinking: false`。
- 配置至少包含 `base_url/model/api_key`，不得把真实 key 写入 Git、日志或报告。
- 缓存绑定模型端点、模型名、请求选项、提示词、版本和全部输入像素。两模型隔离。相同调用成功后不重复付费；不同顺序是不同输入。
- 网络/可恢复 HTTP/格式错误最多重试一次；有效语义答复不反复投票。`calls/history` 保留失败后再恢复的原始尝试，统计不只看最后一次成功。
- `scope` 是本轮用户收窄目录范围后的迁移工具：只复用已测量的门店调用，排除参考目录的记录/费用/耗时。新数据直接运行 `sweep` 就只扫描门店，不需要先扩大再收窄。
- 耗时是接口墙钟时间，包含传输；冷调用指标来自 history，不把缓存重放当成模型速度。费用来自 usage 与公开价估算，不是账单。

## 远程复现

工作目录 `/root/apps/case-studio`，解释器 `/root/apps/non-grid-calibration/.venv/bin/python`。所有输出指定新目录，几何与展示节点拒绝覆盖已有结果。示意变量 `EVAL_ROOT` 使用新的实验目录，`JOB` 为已上传的完整 job。

```bash
PY=/root/apps/non-grid-calibration/.venv/bin/python
JOB=/root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json
EVAL_ROOT=/root/autodl-fs/case-studio/experiments/NEW-store-evaluation

# 分别对 deepseek/qwen 执行；使用各自 settings 和目录。
$PY -m scripts.body_scan_full_eval.sweep --job "$JOB" \
  --out "$EVAL_ROOT/classification-deepseek" --provider deepseek \
  --settings /root/autodl-fs/case-studio/settings.json
$PY -m scripts.body_scan_full_eval.sweep --job "$JOB" \
  --out "$EVAL_ROOT/classification-qwen" --provider qwen \
  --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json
$PY -m scripts.body_scan_full_eval.review --root "$EVAL_ROOT"
# 查看原图后生成 intake-audit.json，再创建不可变派生 job。
$PY -m scripts.body_scan_full_eval.prepare --root "$EVAL_ROOT" --audit "$EVAL_ROOT/intake-audit.json"
```

标准化分别传入 `single-ids.json` 中的全部 ID，以及拆分生成的 `pairs/dataset/job.json`；不要只选历史验证 ID。

```bash
$PY -m scripts.body_scan --job "$EVAL_ROOT/dataset/job.json" \
  --asset-id ALL_SINGLE_IDS --out "$EVAL_ROOT/standardized-singles" --refine-background
$PY -m scripts.body_scan_pairs --job "$EVAL_ROOT/dataset/job.json" \
  --asset-id ALL_PAIR_IDS --out "$EVAL_ROOT/pairs" --split-only
$PY -m scripts.body_scan --job "$EVAL_ROOT/pairs/dataset/job.json" \
  --out "$EVAL_ROOT/standardized-pairs" --refine-background
$PY -m scripts.body_scan_group_display \
  --input "$EVAL_ROOT/standardized-singles" "$EVAL_ROOT/standardized-pairs" --out "$EVAL_ROOT/display"

# 以 Qwen 为例，DeepSeek 同样执行，cache 由 provider 隔离。
$PY -m scripts.body_scan_full_eval.observations --input "$EVAL_ROOT/display" \
  --out "$EVAL_ROOT/observations-qwen" --cache "$EVAL_ROOT/phase-calls-qwen" \
  --provider qwen --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json
$PY -m scripts.body_scan_full_eval.phase --input "$EVAL_ROOT/display" \
  --out "$EVAL_ROOT/phase-qwen" --cache "$EVAL_ROOT/phase-calls-qwen" \
  --provider qwen --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json
```

`--help` 查看各入口的参数。测试：

```bash
$PY -m unittest discover -s scripts/body_scan_full_eval/tests -v
```

没有独立的真实拍摄时间标注，因此“已采用标签数量”“模型置信度”“交换顺序仍一致”都不能命名为准确率。规则标签、文字标签和 AI 推断必须分别统计。完整实验结果、限制与建议见 [全量评测工作流](../../docs/workflows/full-dataset-model-evaluation.md)。
