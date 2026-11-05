# 同组统一取景与独立展示版

独立实验节点 `body-scan-group-display-v2`，接在单图标准化之后。输入是批准的 v3 / v2 单图结果目录，也可同时输入硬拼接拆分后产生的 `aligned/` 结果。

**同一个人只生成一种输出比例和尺寸。** 完整度只用于判断整组的共同可见范围，不再按全身、半身等状态把同一个人拆成多个画幅。等比参考与展示版分别在整组内共用尺寸、取景框、缩放和肩部位置，后续可以直接拼接。

所有推理、处理与测试在远程服务器运行。本目录尚未归档为最佳实践、尚未接入网站或统一工作流调度。

## 处理方法

1. 校验来源 SHA、上游状态、有效矩形和坐标变换。只接收 `rectangular`，上游跳过/待复核保持原状态。
2. 去除画布补边，把真实有效照片交给视觉模型判断当前的头、腿、脚可见范围。贴纸或背面不等于缺头。分类描述**当前成品**，不声称原拍摄缺少这些部位。
3. 对模型认为完整的头/脚做 SAM 边界检查，用已批准的肩髋关键点作为前景提示，按置信度和主体约束选轮廓，避免取最大面积时混入背景海报。相交或分割质量不可靠时，用完整照片、顶部及底部放大图复核。可靠轮廓贴边时另记 `touching_border` / `feet_touching_border`，不声称已确认缺失，也不当作有安全余量的全身照；语义模型不确定则待复核。
4. 只按同店同名分组。沿用上游肩髋尺度和肩部锚点，求整组有效矩形在肩部相对坐标中的交集。抬臂图保留已批准的中立肩部锚点。
5. 整组选择一次首选画幅，所有合格图片共用一个取景框和缩放。全身与半身混合时按共同可见范围取景，完整图可能随组裁去部分身体；逐图原始完整度标签仍保留。始终保护肩髋及共同矩形内可保留的身体上下范围；若整组均确认头或脚完整，则完整保护相应部位。
6. 首选比例无法满足身体保护、面积损失或步数限制时，在这些约束允许的高度区间中选择最接近首选值的**整组高度**。不改变单张比例，不放宽缩放上限；共同矩形本身不成立或无可行整组比例则待复核。
7. 输出等比参考和轻微非等比展示版。将所有矩阵合成后从原始单图采样一次；拼图子图仍只在自己的原图边界内取样。

## 1.1 阈值的含义

`vertical_stretch = scale_y / scale_x`，默认范围 `[1, 1.1]`，即额外纵向调整最多 10%。这是纵横缩放**差异**，不是从低分辨率图到高分辨率画布的绝对放大倍数。

设目标高宽比为 `r`，共同取景框尺寸为 `w×h`：

- `h/w < r/1.1`：共同缩窄取景框，直到 `w = h×1.1/r`。
- `h/w > r`：共同减少取景高度，直到 `h = w×r`；避免横向拉胖。
- 介于两者之间：无需额外裁剪，直接作允许范围内的纵向调整。

数学上一次解出最小额外裁剪，记录每步不超过当前宽/高 2% 的裁剪路径，但只渲染最后结果，避免反复缩放损伤画质。默认最多 80 步、额外裁掉共同矩形面积不超过 25%。首选画幅受这些条件限制时调整整组高度，约束保持不变；可用 `--fixed-group-ratio` 禁止自动调整，此时整组待复核。

**不是直接取 `min_w/min_h` 再任意居中。** 两张图的肩部离边缘距离不同，简单取最小尺寸仍可能越界；需要在肩部相对坐标中求共同上下左右边界。

## 整组首选尺寸

下表是整组选择一次的首选模板，不是逐图输出规格：头部是否完整取整组共同条件，下肢范围取整组最受限状态。默认宽768，可通过 `--width` 调整分辨率。实际统一高度受共同有效区域约束，必要时整组一起调整并记录原因；不同人可以有不同画幅，同一人只有一种。

| profile | 当前可见范围 | 默认尺寸 |
| --- | --- | --- |
| `full_body` | 全身完整 | 768×1920 |
| `feet_cropped` | 头与腿可见，脚部贴边或不完整 | 768×1792 |
| `head_cropped` | 头部贴边或不完整，腿脚完整 | 768×1664 |
| `head_feet_cropped` | 头、脚贴边或不完整，腿部可见 | 768×1536 |
| `legs_cropped` | 头完整，底边在小腿/膝附近 | 768×1408 |
| `head_legs_cropped` | 头贴边或不完整，底边在小腿/膝附近 | 768×1184 |
| `upper_body` | 头完整，底边在大腿/髋附近 | 768×1152 |
| `torso` | 头贴边或不完整，底边在大腿/髋附近 | 768×1024 |

`--profiles profile-overrides.json` 可覆盖各状态的 `height`（以宽768计）、`shoulder_y`、`label`，例如：

```json
{"full_body":{"height":1920,"shoulder_y":0.23}}
```

不会为单个会员、组号或照片写特例。缺失部位不补画；全身与半身属于同一人时，共同取景可能将完整图裁成较短的身体范围。为避免一张贴纸贴边就把整组头部裁掉，额外比例调整会保护共同矩形内原本可保留的身体上下范围。

## 远程运行

```bash
cd /root/apps/case-studio
scripts/body_scan_group_display/run.sh \
  --input /root/autodl-fs/case-studio/experiments/body-scan-wall-v3-20261105 \
          /root/autodl-fs/case-studio/experiments/body-scan-pairs-hard-v1-20261105-final/aligned \
  --out /root/autodl-fs/case-studio/experiments/NEW-group-display \
  --max-stretch 1.1
```

环境默认 `/root/apps/non-grid-calibration/.venv/bin/python`；模型配置只读服务器 `settings.json`，可用 `--settings` 指定。结果目录必须不存在。可先用 `python -m scripts.body_scan_group_display.audit --input ... --out NEW-audit` 单独分类，再用 `--audit NEW-audit` 复用；输入指纹不一致或审查不完整时拒绝复用。视觉证据缓存位于数据盘 `cache/body-scan-group-visibility`。

## 输出和校验

- `images/<asset>/baseline.png`：批准的标准化成品逐字节副本。
- `uniform.png`：同一取景框等比缩放参考，必要时上下留白；不增加体形比例变化。
- `display.png`：独立展示版，矩形填满，同人整组采用同一轻微纵向调整。**不作为真实体形测量图**。
- `summary.json`、`reports/`、`groups.json`：分类证据、主体与肩部坐标、共同矩形、裁剪步骤、尺寸、矩阵、SHA、成功/复核原因。
- `verification.json`：来源不变、矩形完整、同组参数一致、缩放阈值及实际输出检查。
- `previews/`、`index.html`、`body-scan-group-display-results.zip`：原标准化/等比参考/展示版对照与下载。

```bash
PYTHONUTF8=1 OMP_NUM_THREADS=4 /root/apps/non-grid-calibration/.venv/bin/python \
  -m unittest discover -s scripts/body_scan_group_display/tests -v
```

真实样本运行记录见 [validation.json](validation.json)。原图、上游结果及冻结最佳实践均不改写；展示版也不会覆盖网站当前成品。

`groups.json` 为兼容既有预览保留 `cohorts` 字段，但每个人最多一个，标识为 `gNNN__shared`。校验器会拒绝同人多个画幅、同一人被拆到多个组或组内不同取景/缩放参数。逐图 `profile` 只描述输入完整度，`display_profile` 是整组选定的模板；实际拼接尺寸以组级 `output_size` 为准。

v1按完整度拆子组的实现保存在提交 `b1e5fa8` 及旧实验目录中，已由本版“一人一画幅”规则替代。
