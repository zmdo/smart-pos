# 体测对比图拆分最佳实践：仅处理硬拼接

用户确认的 `body-scan-pairs-v1`，来源提交 **`5dec62c3b96eedd84c8159d071dbb289957815c4`**。本目录冻结两张体测照片的拆分流程，后续单图校正使用相邻的 [body-scan-wall](../body-scan-wall/README.md) 权威快照。

## 规则

- 仅处理两张独立照片直接左右或上下硬拼接。
- 整图与局部模型审查确认硬拼接，再由多段像素证据定位切线，SAM保护主体并进行拆分复核。
- 模型确认渐变混合时，直接淘汰并给出原因，不尝试去除渐变带后继续处理。
- 类型不确定、模型判断冲突、接缝或人物证据不足，进入待复核，不强行放行。
- 拆分只做原尺寸像素裁切；每张子图独立确认单人、墙面和体测姿势，再进入校正、肩髋比例统一及最大矩形取景。
- 保留原图与父子坐标，不按左右位置或胖瘦推测训练前后，不生成缺失身体或背景。

原设计与边界条件见 [DESIGN.md](DESIGN.md)，批准版的实际验证记录见 [source-validation.json](source-validation.json)。当前仅为独立脚本，尚未接入网站。

## 运行

已部署到 `/root/apps/case-studio/best-practices/body-scan-pairs`，可从任意目录启动：

```bash
bash /root/apps/case-studio/best-practices/body-scan-pairs/scripts/body_scan_pairs/run.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --asset-id a0018 a0180 \
  --out /root/autodl-fs/case-studio/experiments/approved-pairs-new
```

默认包含后续单图校正；`--split-only` 只拆分和独立分类。输出目录必须全新。省略 `--asset-id` 时按原job中的对比标签选取候选。`--settings`、`--cache`、`CASE_PYTHON` 等参数保留来源语义。

运行环境、模型、字体和密钥配置复用服务器；依赖版本和外部资源指纹见相邻单图快照的 [环境记录](../body-scan-wall/requirements.verified.txt) 和 [模型清单](../body-scan-wall/external-resources.json)。用户照片、权重和密钥均不进入Git。

## 来源与依赖隔离

拆分算法、提示词、18项测试和原启动器从来源提交复制。`pipeline.py` 只调整单图最佳实践的位置：由仓库根路径改为相邻的 `body-scan-wall`，算法不变；设计文档只调整链接。逐文件原始SHA、归档SHA及改动说明见 [manifest.json](manifest.json)。

本副本明确依赖同级 `body-scan-wall` 的来源提交 `c3ce38966da8d39cf702778858e8e5881f9744ff`，锁定其manifest SHA。启动时检查本目录文件和该依赖的完整性，然后只从这两份最佳实践导入项目模块；不读取开发目录 `scripts/body_scan`。后续校正仍在单独子进程中运行，保持批准版入口及导入隔离。

这两份目录须一起部署。任一冻结文件或依赖清单变化都会报错，不能静默切换到开发版或其他版本。开发版入口继续保留；后续实验先在开发目录进行，用户明确确认后才更新对应最佳实践和清单。

## 验证与输出

```bash
PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python \
  /root/apps/case-studio/best-practices/body-scan-pairs/verify_snapshot.py
bash /root/apps/case-studio/best-practices/body-scan-pairs/run_tests.sh
```

来源样本中，董彦琦硬拼接图拆为两张540×1350的无损子图，均完成768×1792成品；任胜男样本因整图与局部判断冲突而拦截，未生成子图。不能将其描述为模型已正确识别渐变。渐变标签的立即淘汰路径另有测试覆盖。

每次运行保存边界预览、子图job、原图和子图SHA、坐标映射、逐张原因、成品和下载包；`validation.json` 验证子图像素、映射往返和矩形约束。本次归档独立重跑与来源结果的对照记录见 [validation.json](validation.json)。

归档验证从服务器 `/tmp` 启动，移除 `PYTHONPATH`：17个归档文件及39个单图依赖文件通过SHA检查，21个项目模块均来自两份最佳实践，18项原测试通过。完整重跑生成的 **27个PNG/JPG文件与批准版逐字节一致**，拆分坐标、分类、几何、姿态、取景及父图到成品映射也一致；新增VLM请求为0。仍为1张拼图拆出2张成品、1张拼图待复核。输出位于 `/root/autodl-fs/case-studio/experiments/best-practices-body-scan-pairs-v1-verification`。
