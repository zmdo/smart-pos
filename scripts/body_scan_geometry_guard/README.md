# 可疑非网格相机校正检查（独立实验）

`body-scan-geometry-guard-v1` 接在已完成墙面修正的单图标准化之后、同组展示之前。五组实验获准后，已经归档到 [单图标准化最佳实践 v4](../../best-practices/body-scan-wall-v4/README.md)，其入口自动串接本检查。本目录继续作为独立开发/实验入口；原v3快照、网站及旧结果保持不变。

## 判断规则

- 网格图、跳过和待复核项不改变。
- 大角度且不确定：横滚绝对值 ≥ 3° 或俯仰绝对值 ≥ 12°，同时该轴估计误差 ≥ 角度绝对值的 50%。此比值是筛查规则，不是统计置信区间。单独出现旧版不确定警告不会回退。
- 背景明确退步：复用绑定原图的既有墙面语义审查、实测线段与模型编号选择。仅认可高置信、同一平面墙的物理线段；编号、方向、边界独立核验。一个方向出现错误编号不会抹掉另一个方向的合法证据。
- 按线段投影区间的并集计算覆盖，避免重复边缘虚增覆盖。覆盖 ≥ 25%，且 ≥ 75% 的线段长度支持“原角度误差 ≤ 1°、新误差 ≥ 3°、退步 ≥ 2°”，才判定明确退步。原本透视倾斜的单根线不能仅因不水平就触发回退。
- 大角度不确定但无明确退步时，需横竖两族都有足够覆盖、空间分布和实测改善，才认可候选；否则保留原图方向。
- 人物肩膀、躯干倾斜不参与以上判断，避免消除真实体态差异。

本节点复用已有大模型墙面证据，不新增模型请求。缺乏证据不会凭空补造参照。已经执行了同组背景尺度配准的图片如需回退，记录 `retain_for_review / group_registration_requires_recompute`，保留旧成品等待重算配准，不将旧尺度套入新坐标。本次没有命中该分支。

## 取景与保护

通过检查的图片直接复制成品和遮罩，不重新编码。回退图片采用单位几何矩阵，由原图关键点重新计算肩髋锚点、尺度、有效区域及最大矩形，从原图重新采样一次。原来的几何与审查保留为历史记录，不能误认为仍然应用。相同店名和会员名整组交给既有展示节点，依然一人一画幅。

输出沿用单图结果格式 `body-scan-wall-v3`，另用 `geometry_guard_version` 标明实验阶段；绝不声称属于冻结版。拒绝重复检查、覆盖结果、来源 SHA 变化、重复资产 ID、未知组名和不同取景配置。没有任何会员名、资产编号特例。

## 远程复现

工作目录 `/root/apps/case-studio`，所有图像处理、测试在服务器运行：

```bash
PY=/root/apps/non-grid-calibration/.venv/bin/python
OLD=/root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106
OUT=/root/autodl-fs/case-studio/experiments/NEW-geometry-guard

$PY -m scripts.body_scan_geometry_guard \
  --input "$OLD/standardized-singles" "$OLD/standardized-pairs" \
  --out "$OUT/standardized" \
  --member 景田店/张小飞 --member 石厦店/黎国萍 \
  --member 石厦店/郑远晨 --member 石厦店/冯雪奕 --member 石厦店/潘艺文
$PY -m scripts.body_scan_group_display \
  --input "$OUT/standardized" --out "$OUT/display"
$PY -m scripts.body_scan_geometry_guard.report \
  --root "$OUT" --previous-display "$OLD/display"

$PY -m unittest discover -s scripts/body_scan_geometry_guard/tests -v
$PY -m unittest discover -s scripts/body_scan/tests -t . -q
$PY -m unittest discover -s scripts/body_scan_group_display/tests -q
```

省略 `--member` 会检查输入中的全部组；本轮只运行上述五组。`report` 验证所有未改变几何的组最终成品字节不变，否则直接报错，不能只以肉眼判断通过。

2026-11-06：5 组 28 张全部输出；仅张小飞白墙正面 `a0036__p01` 回退。其余 27 张标准化 PNG、有效/可用遮罩、等比参考和最终展示 PNG 均逐字节一致，包含 8 张网格图及已成功墙面修正的图片。13 项新测试、47 项单图测试、32 项同组测试通过。详见 [工作流与验证记录](../../docs/workflows/non-grid-geometry-guard.md) 和 [validation.json](validation.json)。
