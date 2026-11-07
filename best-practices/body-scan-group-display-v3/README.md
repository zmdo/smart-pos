# 同组展示 v3：共同人物尺度与一人一画幅

用户批准的同人尺度校准方案，初始来源提交 **137054176720ab1b0348364961548a304b4ed754**。初始归档包含尺度算法19项测试与同组展示32项测试；后续边界复核、尺度提案保护及验证见下文。

当前推荐链路：**硬拼接拆分 → 单图标准化v4 → 本节点v3**。本节点包含尺度校准与最终共同取景；旧`body-scan-group-display` v2已删除，所需取景代码完整包含在本目录中。单图v4和拆分最佳实践继续保留，不修改已生成的图片；历史恢复见[清理记录](../retired-snapshots.md)。

## 规则与边界

1. 同人至少两张可靠中立正/背照建立尺度参考；头发、贴纸、腰宽和衣服轮廓不作尺子。
2. 同一背景用实测网格格距或墙面配准，跨背景用可靠身体分段衔接。裤装遮住腿部不自动否定可靠肩髋参考。
3. 每张只采用一个等比倍率，定标和肩部定位分开；抬臂图用髋部与中立躯干参考取景。镜头几何和真实身体倾斜保持不变。
4. 2%内保留；证据不足、冲突、变化过大或头脚余量不足时保留原尺度并待复核。头脚保护结合旧完整度证据和SAM实测轮廓，不拿大模型粗框当精确裁切边界。
5. 最终仍一人一画幅、一个共同取景框。等比参考和展示版分开保存；可选的轻微纵向调整整组共享，默认上限1.1。

2026-11-08 增加了下述微小边界冲突复核和独立尺度提案保护；共同网格尺度回退已撤销。没有增加镜头径向畸变校正，也没有把人强制拉直。网格线弯曲的检查属于后续独立工作。

尺度待复核与最终取景待复核分开记录；“有成品”不等于尺度已校准。缺少可靠基线完整度/成品时停止并保留记录，不跳过这些素材后声称整组完成。

## 远程入口

服务器目录：`/root/apps/case-studio/best-practices/body-scan-group-display-v3`。数据、模型和私有设置继续使用服务器现有资源，仓库不含照片、权重或凭据。

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display-v3/run.sh \
  --input /path/to/approved-v4-standardized \
  --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json \
  --out /path/to/NEW-group-display-v3
```

默认自动生成基线展示与完整度证据，然后运行尺度校准和最终取景。已有匹配基线时增加`--baseline-display /path/to/previous-display`；会检查原图、标准化像素和取景参数是否一致，不能借用另一批图片的基线。

输入是一个v4结果目录及其原图；旧v2/v3兼容格式也能读取，但不会自动补做海报过滤或几何检查。多个来源应先由v4汇总为同一批标准化结果，不重复素材ID。`--out`必须是输入之外的新目录，不覆盖旧产物。

`--settings`用于Qwen尺度证据；完整度节点仍读取服务器原有设置，可用`--visibility-settings`另行指定。`--width`默认768，`--max-stretch`默认1.1；`--focus`只指定报告重点图，不影响算法。`CASE_PYTHON`可覆盖默认远程Python，`CASE_SAM`/`CASE_SAM_CONFIG`指定已有模型。

## 输出

- `baseline-display/`：未提供旧基线时自动生成；若提供则只读复用。
- `standardized/`：尺度校准后的兼容标准化结果、保留原因及验证；记录`best_practice_version=body-scan-group-display-v3`，原上游版本另存。
- `display/`：一人一画幅成品、等比参考、HTML和下载包。
- `comparison/`：新旧对照；沿用实验报告展示格式，其中“新实验”指本次采用的新方案。
- `workflow.json`：阶段、采用数、尺度待复核、取景待复核；`completed_with_review`明确表示仍有保留项。
- `verification.json`：输入/几何/关键点未改、矩形来源、一人一画幅等检查。
- `index.html`：结果和下载入口。

## 归档验证

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display-v3/run_tests.sh
```

启动时验证[manifest.json](manifest.json)中的文件指纹；`verify_snapshot.py`验证所有项目导入都来自本目录，不依赖开发目录或相邻快照。SAM、运行库和缓存等外部依赖见[external-resources.json](external-resources.json)、[requirements.verified.txt](requirements.verified.txt)。

获准实验的5组28张记录保存在[source-validation.json](source-validation.json)。本次归档的独立重跑、两种基线入口和像素一致性结果见[validation.json](validation.json)。覆盖范围为这5组，不代表全量数据均已通过尺度校准。

后续改进在开发目录测试，获用户确认后再更新权威版本及指纹。维护流程见[工作流说明](../../docs/workflows/person-scale-calibration.md)。

## 微小共同取景边界复核（2026-11-08）

原规划通过时完全沿用原结果，不调用额外模型。仅当共同矩形与完整头/脚的 VLM 粗框存在微小纵向冲突时，对冲突图片调用已有 SAM 2 复测实际轮廓。冲突上限为归一化坐标中的 `min(4px, 共同高度×0.003)`；横向、肩髋核心、较大冲突不适用。

轮廓须通过原主体约束、关键点覆盖至少 0.99、置信度至少 0.90。所有前景像素均计入边界（不忽略零散发丝），再保留 2 个输入栅格像素余量。与视觉粗框的差异不得超过 `min(12px, 输入高度×0.01)`。不修改完整度标签、不更改尺度/肩部/有效矩形、不把边界硬夹到取景框；整组必须再次通过原规划器，才能原子性采用新边界，否则继续待审核。

`display/boundary-rechecks/` 保存轮廓掩码，摘要保存输入 SHA、测量坐标、原诊断与采用原因，验证器检查掩码指纹和头脚保护。唐怡婷六张恢复输出，另八组 36 张的显示图、等比参考与取景计划逐项一致；完整验证见 [boundary-recheck-validation.json](boundary-recheck-validation.json)。

## 独立尺度提案保护（2026-11-08，当前规则）

此前 `common-grid-scale-recovery-v1` 强制整组格距一致，造成唐怡婷白衣侧面/背面放大、下肢继续被裁，并连带改变整组展示比例。该算法及整组倍率搜索已移除，历史结果和 [grid-scale-recovery-validation.json](grid-scale-recovery-validation.json) 仅供追溯，不能作为当前视觉验收依据。

当前 `independent-scale-proposal-guard-v1` **只否决有独立证据证明会加重偏差的缩放提案，不由网格产生新倍率**：保留原参考求解器；当可靠中立图的肩髋参考原偏差不超过3%，候选使该偏差增加超过5个百分点，同时让其网格尺度进一步偏离稳定同背景参照超过2个百分点、总偏离超过8%，则取消该图的额外缩放，保留输入像素并待审核。背景参照至少两张未采用缩放的照片，必须同一可靠贴墙网格、语义置信度至少0.90、横纵测量误差不超过7%、参照格距区间跨度不超过20%。使用区间表达不确定性，不把网格中位数当人体真值，也没有人物/图片ID特例。

缺少任一证据不据此指定新尺度。人体/背景独立差异仍记录，超过5%提示复核。原有尺度、姿势、倍率范围和补边保护继续有效。新保护不宣称解决所有跨视角人体比例误差。

尺度候选必须保住旧成品已经可见的身体纵向范围，包括原本缺脚、贴边、缺小腿或缺头的照片。先用SAM测量，再截取旧成品实际保留部分并映射到候选框；仅容许2像素栅格误差。完整头脚余量保护仍更严格；已有缺失不再等于可以继续裁短。

出现提案否决的组，最终展示从指纹绑定的基线中保留共同画幅、取景框、肩位及展示比例；逐图检查原图/几何/关键点匹配、有效矩形和可见身体范围。若旧框不再安全则整组待复核，不能偷偷重选比例。开发CLI需传 `--reference-display`，冻结工作流自动传入基线展示。

唐怡婷六张恢复768×1792及原共同肩位、纵向展示系数1.07241173；相对劣化前版本，仅a0078撤销额外放大（等比倍率下降约6.46%），其余五张标准化/显示/等比图像字节一致。另八组36张同样一致。92项测试通过；指标、限制和发布记录见 [proposal-guard-validation.json](proposal-guard-validation.json) 与 [实施记录](../../docs/design/independent-scale-guard/IMPLEMENTATION.md)。

## 封面专用正面双图分支（2026-11-07）

新增独立 `run_cover.sh`，原 `run.sh` 及既有尺度、取景算法保持不变。该分支消费已选定的正面训练前后素材和原阶段行，复用尺度校准后的肩部坐标及原图校正矩阵，仅两张图参与共同取景，不使用六图成品或展示版非等比拉伸。

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display-v3/run_cover.sh \
  --request /path/to/cover-frame-request.json \
  --out /path/to/NEW-cover-frames
```

请求协议 `cover-frame-request-v1` 由开发目录的封面适配器 `python -m scripts.body_scan_cover.prepare --delivery ... --out ...` 生成，也可由服务按同一协议提交。输入含阶段结果路径/SHA、两张正面素材完整阶段行、各自展示摘要路径/SHA；本节点不导入该适配器、分类节点或成品生成器。冻结代码位于本目录 `scripts/body_scan_cover_frames`，无开发目录回退依赖。原图和几何来自已绑定摘要，原始单图来源的有效边界完整保留。

封面分支 v2（2026-11-07 构图修订）：全身/头胯可用照片优先展示头部到胯部；缺头配对统一肩颈到胯部，相同肩部框为硬约束，不再允许独立垂直偏移。固定窗口容纳不了头胯的窄图标记范围受限。

输出 `frames.json`、每组 `before.png` / `after.png` / `pair.png`、全有效像素掩码和私有输入指纹。阶段与审核标记按素材 ID 原样继承，新增模型调用为 0。`--width` / `--height` 默认 500×478，`--max-torso-heights` 默认 2.8，仅作为安全上限，正常下沿由髋点及 0.25 个肩髋距离余量决定；当前封面模板只接收 500×478，修改该尺寸需同步调整模板。

双图矩形遵守原图有效区域，保留既有几何及人物尺度，只等比缩放。共同肩线必须满足；原图缺头时两侧统一裁成局部对比，新增头部裁切有单独记录。该分支允许扩展至六图裁剪前的有效原像素，不受旧单图 768 宽取景窗口限制。具体规则和数据流见[封面工作流](../../docs/workflows/member-cover.md)，本轮验收见[cover-validation.json](cover-validation.json)。
