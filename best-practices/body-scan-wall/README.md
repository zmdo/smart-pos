# 体测图权威快照：墙面参照与同组尺度修正 v3

用户已确认这一版为最佳实践。本目录是来源提交 **`c3ce38966da8d39cf702778858e8e5881f9744ff`** 的独立代码快照，涵盖分类结果筛选、主体定位、网格/pinhole校正、墙面参照修正、同组尺度、最大矩形取景及预览。

所有处理模块、必要的相机模块、40项原测试和原有启动器均按来源提交逐字节复制。新增 `scripts/__init__.py` 将本副本与开发目录的Python命名空间隔离。只调整归档文档链接、增加便利启动器及完整性检查，不修改图像处理算法。逐文件来源和SHA256见 [manifest.json](manifest.json)。

## 已批准的处理策略

1. 只处理单人、靠墙、静态体测图；对比图、训练图跳过，缺少新墙面分类证据的旧标签待复核。
2. 共用YOLO → VLM粗框/ROI YOLO → SAM主体定位。网格沿用批准算法；非网格先执行pinhole侧倾/俯仰校正。
3. VLM判断可靠墙面参照 → 实际线段检测及编号复核 → 几何共识与墙面yaw修正 → 单图视觉复核。证据不足或检查不通过，保留批准的pinhole结果并记录原因。
4. 同组背景SIFT/MAGSAC配准至少得到两张中立姿势参考的一致支持，才修正抬臂图明显偏小的尺度；再做组图复核。不以会员名、组号或素材ID设置特殊规则。
5. 默认画布768×1792，普通图肩髋占27%、肩部锚点在23%。获准尺度修正的抬臂图用髋部及中立躯干参照定位，保留真实肩高差异；所有取景都是整体等比缩放和平移。
6. 新成品从原图采样一次，尽用原图并保留包含肩髋的最大有效矩形。按同店同名分组，前后左右排列。正式成品为 `aligned.png`，诊断候选不代表采用。

完整决策与限制见 [DESIGN.md](DESIGN.md)，批准批次的原验证记录为 [source-validation.json](source-validation.json)。本次归档独立验证记录为 [validation.json](validation.json)。

## 两个入口

部署根目录：`/root/apps/case-studio/best-practices/body-scan-wall`。可从任意工作目录启动。

**从已分类job运行完整流程：**

```bash
bash /root/apps/case-studio/best-practices/body-scan-wall/scripts/run_body_scan_refined.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --classification-audit /root/autodl-fs/case-studio/experiments/body-scan-camera-v2-wall-audit/classification.json \
  --out /root/autodl-fs/case-studio/experiments/approved-wall-new
```

新 `cls-v3-wall` job 已有必要证据时可省略audit。示例audit只覆盖已复核的46张素材；其他历史体测素材需由上游重新分类。`--asset-id`、`--background` 和画布参数保持来源入口语义。输出目录和相邻 `<输出目录>-pinhole` 都必须不存在，后者保存基础阶段。

**已有批准v2结果，只运行墙面和尺度修正：**

```bash
bash /root/apps/case-studio/best-practices/body-scan-wall/scripts/run_refinement.sh \
  --baseline /root/autodl-fs/case-studio/experiments/body-scan-unified-v2-camera-20261105 \
  --out /root/autodl-fs/case-studio/experiments/approved-wall-refinement-new
```

该入口验证原图SHA，拒绝把v3结果再次精修；仍从原图生成结果，不对旧成品二次变形。`--group` 可用于验证子集，默认处理所有组；`--no-group-scale` 可仅观察墙面修正。

完整流程读取**已分类job与原图**，不负责ZIP解包、上游素材分类或网站成品页面。精修入口读取**v2产物与原图**。代码运行只依赖本副本，数据、模型、配置和字体仍复用服务器环境。

## 环境与外部资源

- 默认Python：`/root/apps/non-grid-calibration/.venv/bin/python`，可通过 `CASE_PYTHON` 覆盖；实际版本见 [requirements.verified.txt](requirements.verified.txt)。运行和推理均在远程GPU服务器执行。
- 主体/姿态/SAM模型位于 `/root/autodl-fs/portrait-studio/models`，GeoCalib pinhole权重位于 `/root/autodl-fs/case-studio/models/geocalib`；不启用radial分支。文件指纹见 [external-resources.json](external-resources.json)。
- GeoCalib来自先前记录的官方提交 `1dedb29f94fc11b896c5f572005978aeebccd67f`；当前安装目录不含git元数据，本归档额外记录实际Python源码树指纹。其代码遵循Apache-2.0、模型遵循CC BY 4.0，作者为Alexander Veicht、Paul-Edouard Sarlin和Philipp Lindenberger。上游：[GeoCalib](https://github.com/cvg/GeoCalib)。
- VLM按需读取服务器既有 `settings.json`；缓存继续使用数据盘中的 `cache/wall-reference` 等目录。密钥、模型权重、字体和用户照片不进入Git。
- 新增 `scripts/__init__.py` 后，缺失项目依赖会直接报错，不会从开发版 `scripts` 偷读文件。第三方库仍使用上述环境。

## 独立验证

```bash
PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python \
  /root/apps/case-studio/best-practices/body-scan-wall/verify_snapshot.py

bash /root/apps/case-studio/best-practices/body-scan-wall/scripts/run_tests.sh
```

批准的来源批次为46张：41张成品、3张跳过、2张待复核。4张采用墙面修正，其中g010侧面采用约14.4%的同组尺度修正；其他37张成品和遮罩保持v2原样。

归档从服务器 `/tmp` 启动，移除外部 `PYTHONPATH` 后重跑完整流程。39个清单文件通过SHA检查，28个项目模块均从本目录导入，40项测试通过；41张的原图/成品/两种遮罩共164文件，以及30张分组预览，共 **194文件与批准版逐字节一致**。几何、关键点、取景、分类及分组报告也相同。验证输出位于 `/root/autodl-fs/case-studio/experiments/best-practices-body-scan-wall-v3-verification`，详细记录见 `validation.json`。

## 更新约定

本目录是当前完整体测图处理方案的权威快照，`best-practices/grid-portrait` 继续作为此前网格最终取景基线保留。后续实验在开发目录进行；用户明确批准新版本后，才更新对应权威快照、清单、验证记录及目录索引，然后提交并推送。
