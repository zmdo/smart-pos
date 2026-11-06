# 单人体测图标准化最佳实践 v4

当前推荐的单图标准化版本。用户批准了 `7cfbb0d23e27a570f52120fe8d0d1d8c148b3a3c` 中经过五组28张验证的非网格几何检查与回退，现整理为可独立部署的完整快照。

**默认入口自动执行：海报背景过滤 → 主体定位 → 网格/相机校正 → 墙面参照及同组尺度修正 → 可疑非网格几何检查 → 最终矩形取景。** 后续同组大小统一仍使用独立的 [body-scan-group-display](../body-scan-group-display/README.md)。

旧 [body-scan-wall v3](../body-scan-wall/README.md) 原样保留，拆分最佳实践锁定的旧依赖不变。新工作流使用拆分的 `--split-only`，再将拆分子图和原有单人图交给本目录；避免使用旧拆分入口隐含的 v3 标准化。拆分算法、同组展示算法没有改变。

## 处理策略

- 复用当前已验证的分类筛选、海报过滤、YOLO/VLM/SAM定位、肩髋关键点、网格及墙面校正。几何检查使用上一轮测试的相同代码与阈值，不按会员名或素材编号设置特例。
- 网格、跳过和待复核项沿用原处理；单独出现相机不确定警告不会回退。
- 横滚 ≥ 3° / 俯仰 ≥ 12°，且该轴估计误差 ≥ 角度绝对值的50%，需要真实墙面证据支持。可信背景线在校正后明显变斜，也会触发回退。
- 回退采用原图方向，重新计算肩髋尺度、锚点、有效区域及最大矩形；不沿用旧坐标，不根据人物体态强制扶正。不重新采样旧成品。
- 未触发回退的标准化图片及遮罩直接复制，保留原有像素。已经做过同组墙面尺度配准的图片如需回退，记录 `retain_for_review`，不能把旧配准套入新坐标；本批没有此情况。
- 输入图片、旧结果以及前置阶段输出保持不变，所有目录必须新建。检查阈值和边界条件详见 [DESIGN.md](DESIGN.md)。

## 入口

远程部署：`/root/apps/case-studio/best-practices/body-scan-wall-v4`。启动器可从任意工作目录调用，清除外部 `PYTHONPATH`，只从本快照加载项目代码；运行前校验文件清单。

### 从已分类 job 运行完整标准化

```bash
bash /root/apps/case-studio/best-practices/body-scan-wall-v4/scripts/run_body_scan_refined.sh \
  --job /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/pairs/dataset/job.json \
  --asset-id a0036__p01 a0036__p02 a0038__p01 a0038__p02 \
  --out /root/autodl-fs/case-studio/experiments/NEW-approved-standardized
```

不指定 `--asset-id` 则处理该job全部资产。`--classification-audit` 可提供原图SHA绑定的历史标签复核；`--settings`、画布参数、姿态/相机模型配置保持开发入口含义。v4总是执行墙面修正和几何检查，仅支持已批准的pinhole模式；`--refine-background` 作为兼容参数保留，不能关闭检查。

最终结果在 `--out`；同时保存 `<out>-pinhole` 基础阶段和 `<out>-wall` 墙面修正阶段。三者必须都不存在。`run_body_scan.sh` 是同一完整流程的别名。

### 升级已有 v3 标准化结果

```bash
bash /root/apps/case-studio/best-practices/body-scan-wall-v4/scripts/run_refinement.sh \
  --input /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/standardized-singles \
          /root/autodl-fs/case-studio/experiments/body-scan-full-model-eval-stores-v1-20261106/standardized-pairs \
  --member 景田店/张小飞 --member 石厦店/黎国萍 \
  --out /root/autodl-fs/case-studio/experiments/NEW-approved-upgrade
```

省略 `--member` 则检查所有输入组；指定时使用完整 `店名/会员名`，可以重复传入。直接复用现有原图绑定证据，不重复做人物检测或相机估计。拒绝已经做过几何检查的输入，避免重复应用。

已有v2 pinhole结果使用 `--baseline PATH --out NEW`：自动执行墙面/同组尺度修正，再做几何检查。只有此模式接受 `--group` 和 `--no-group-scale`，含义与旧版墙面精修入口相同；最终几何检查始终执行。

### 后续一人一画幅

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display/scripts/body_scan_group_display/run.sh \
  --input /root/autodl-fs/case-studio/experiments/NEW-approved-standardized \
  --out /root/autodl-fs/case-studio/experiments/NEW-approved-display
```

可通过多个输入目录汇合同一个人的单人图和拆分图，一起选择共同画幅。需要同时更新的下游结果另存，不覆盖历史结果。本次仅升级最佳实践及部署入口，没有修改网站服务或全量历史成品。

## 输出与兼容性

`aligned.png`、`content_mask.png`、`available_mask.png`、`report.json` 保存每张标准化结果；`index.html` 和 `body-scan-results.zip` 提供预览及下载。

数据格式字段仍为 `version: body-scan-wall-v3`，使既有同组展示读取器保持兼容；算法快照版本另以 `best_practice_version: body-scan-wall-v4` 标明，同时记录 `geometry_guard_version`、来源提交和清单SHA，`experimental: false`。两种版本字段职责不同，不能据格式字段判断是否执行了几何检查。旧几何保存在 `previous_geometry`，不会继续参与采样。

## 来源、环境与验证

处理模块从来源提交逐字节复制；仅完整入口适配默认串接，另增归档启动器及来源标记。逐文件来源、适配说明和SHA见 [manifest.json](manifest.json)。[source-validation.json](source-validation.json) 保留用户批准的五组实验记录；本快照独立验证见 [validation.json](validation.json)。

```bash
bash /root/apps/case-studio/best-practices/body-scan-wall-v4/scripts/run_tests.sh
```

全部推理和测试在远程GPU服务器执行。默认解释器 `/root/apps/non-grid-calibration/.venv/bin/python`，可设置 `CASE_PYTHON`。模型、字体和只读密钥配置复用服务器环境，不进入Git。依赖版本和外部资源清单沿用旧快照，见 [requirements.verified.txt](requirements.verified.txt)、[external-resources.json](external-resources.json)；本次无新增模型或依赖。GeoCalib来源、许可证及作者信息见保留的 [v3环境说明](../body-scan-wall/README.md)。

后续实验继续在开发目录进行；更新最佳实践时必须维护清单与独立验证记录，保留已批准旧版本并提交、推送。
