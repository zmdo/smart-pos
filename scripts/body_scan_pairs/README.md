# 两张体测照片的硬拼接拆分

独立实验方案 `body-scan-pairs-v1`。先识别两张照片的真实接缝，输出无损单图，再调用已批准的 [body-scan-wall](../../best-practices/body-scan-wall/README.md) 完成独立校正、比例统一和矩形取景。原始素材、单图开发模块和最佳实践均不改动；尚未接入网站。

用户已确认本方案，来源提交 `5dec62c3b96eedd84c8159d071dbb289957815c4` 已冻结到 [best-practices/body-scan-pairs](../../best-practices/body-scan-pairs/README.md)。复现批准版请使用归档入口；本目录继续作为后续开发副本。

## 接受和淘汰规则

用户最新规则：**只处理硬拼接，渐变拼接直接淘汰并说明原因。**

| 情况 | 处理 |
| --- | --- |
| 两张独立照片直接左右或上下硬拼接 | 整图与局部判断一致，并通过像素证据与拆分复核后处理 |
| 任一有效模型审查确认渐变混合 | `skipped / feathered_composite_not_supported`，记录中文原因，不输出子图 |
| 单张照片中有两人 | 不确认为拼图，不按人数强行拆分 |
| 分隔带、斜拼、人物重叠、三张以上 | 本版不支持，不按直接硬拼接处理 |
| 模型判断冲突、类型不确定、无可靠硬接缝 | `needs_review`，不继续投票直到获得放行答案 |
| 拆出后不是单人靠墙体测图 | 该子图待复核，不进入校正 |

整图确认渐变时，在 YOLO/SAM 推理和子图分类前直接结束；局部或最终拆分审查发现渐变也会终止。模型的 `confidence` 是自报置信度，不代表统计准确率。本版不尝试剔除渐变带后保留两侧，也不反混合或生成背景。

## 处理流程

1. **版式判断**：读取原图，大模型识别左右/上下布局、照片外边界、人物粗框与接缝位置。然后检查接缝上中下（或左中右）的原始细节。两次都确认硬拼接才继续。
2. **人物边界保护**：全图 YOLO → 粗框附近 ROI YOLO → 必要时粗框 SAM。拒绝明显只覆盖上半身的框/掩码。SAM 必须产生真实掩码，不能用矩形兜底假装验证成功。
3. **接缝像素定位**：只在语义候选附近搜索。两种窗口尺度的颜色变化、8段空间支持和同一像素列/行上的锐利边缘共同筛选，至少6段支持。网格线局部较强不足以直接成为拼接缝。切线不用图像中点、人物中点或相邻人物框边界代替。
4. **拆分复核**：新切边最多遗漏0.2%的 SAM 主体像素（分割噪声容差）；检查原图、边界图和子图，排除邻图残条、渐变和新增人体裁切。原图已有缺失不补齐。候选不通过时保留诊断，最多检查3条有像素证据的候选线。
5. **无损子图**：仅做整数像素切片并保存 PNG，不缩放、不纠正几何。记录原图 SHA、EXIF 方向归一后的坐标、半开矩形 `[x1,y1,x2,y2)` 和父子双向矩阵。
6. **独立分类**：每张子图重新确认人数、靠墙、体测姿势、朝向和网格类型，不直接继承母图标签。保留门店、会员、母图和面板序号。时间标签只有明确的“训练前/后”等文字才采用；日期和其他文字保留为证据，未确定顺序时为 `unknown`，不按胖瘦或左右位置猜测。
7. **批准的单图流程**：在独立子进程中校验并运行冻结副本。从子图自身采样，复用网格/非网格变换、肩髋定位、比例统一、最大有效矩形。默认输出768×1792。两图各自可以有不同的等比缩放倍数，不强制人物同宽。
8. **坐标验证**：`H_parent_to_aligned = H_child_to_aligned × H_parent_to_child`。矩阵只在对应子图裁切域内有效；禁止直接拿它对整张拼图取样，否则可能重新采到邻图。

## 运行

仅在远程服务器运行。复用 `/root/apps/non-grid-calibration/.venv`、现有 YOLO/SAM 权重、模型服务设置及 GPU，不新增依赖。

```bash
cd /root/apps/case-studio
bash scripts/body_scan_pairs/run.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --asset-id a0018 a0180 \
  --out /root/autodl-fs/case-studio/experiments/body-scan-pairs-new
```

默认包含后续校正。`--split-only` 只验证拆分和生成子图job；省略 `--asset-id` 时选择原job中 `phase=both` 或 `is_comparison=true` 的候选，不以 YOLO 框数量判断拼图。输出目录必须全新。

可传 `--settings /path/to/settings.json`、`--cache /path/to/cache`；启动器支持 `CASE_PYTHON`。设置只读，输出与代码均不包含 API Key。缓存绑定图像、提示词版本、模型服务和模型名称。

## 产物

- `index.html`、`aXXXX-review.jpg`：边界、无损子图、校正成品或明确拦截原因。
- `summary.json`、`splits/<id>/report.json`：类型判断、局部判断、候选证据和逐张状态。
- `dataset/input/*.png`：仅通过拆分审查的原尺寸子图；是否进入下游以job为准。
- `dataset/job.json`：通过独立体测分类的子图，兼容批准的单图入口。
- `aligned/`：批准流程的成品；`aligned-pinhole/` 是它保留的基础阶段。
- `parent-coordinate-mapping.json`、`validation.json`：父图到成品映射及独立验证。
- `body-scan-pairs-results.zip`：预览、子图、正式成品和报告，不包含试验候选、重复基础阶段或日志。

## 验证

```bash
PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/body_scan_pairs/tests -t . -v
PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_pairs.verify \
  --out /root/autodl-fs/case-studio/experiments/body-scan-pairs-hard-v1-20261105-final
```

18项测试覆盖不等宽硬拼接、上下拼接、软过渡拒绝、网格线干扰、模型不一致拦截、渐变提前淘汰、二次发现渐变终止、主体误切、独立分类、像素无损、坐标往返、原图篡改检测与旧目录保护。

真实两张样本的正式记录见 [validation.json](validation.json)：

- `a0018`（董彦琦）：硬拼接确认，定位到x=540，拆出两张540×1350原尺寸PNG，均完成768×1792校正成品；逐像素来源、坐标往返、肩髋比例和有效矩形通过验证。
- `a0180`（任胜男）：整图判断硬拼接，但局部审查无法确认接缝；最终为 `needs_review / seam_detail_uncertain`，未生成子图。**不能把这个结果表述成“大模型已正确识别渐变”**。已验证的是冲突拦截；渐变标签触发立即淘汰的路径另有自动化测试覆盖。

只以 `body-scan-pairs-hard-v1-20261105-final` 为本版验收输出；同名前缀的早期试验目录不是本版结果。样本规模有限，未宣称所有拼图自动判定正确；不可靠的结果会显式拦截。
