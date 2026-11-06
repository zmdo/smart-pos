# 单人体测图统一处理

从 `best-practices/grid-portrait` 的权威代码复制、提取的共用实现。基础阶段为 `body-scan-unified-v2-pinhole`；新增 **`body-scan-wall-v3` 墙面参照与同组尺度修正**，推荐通过 `scripts/run_body_scan_refined.sh` 运行。原网格快照已退役至Git历史，独立相机实验和旧成品保留；来源见 `provenance.json`。成品始终由原图生成。

当前推荐的完整标准化最佳实践为 [best-practices/body-scan-wall-v4](../../best-practices/body-scan-wall-v4/README.md)，默认包含海报过滤和非网格几何检查/回退，来源提交 `7cfbb0d`。此前 [v3快照](https://github.com/zmdo/smart-pos/blob/ec5dcb4cda00534b7547dbaaa54177b4d5cfe503/best-practices/body-scan-wall/README.md) 已移除，仅在Git历史保留，来源 `c3ce38966da8d39cf702778858e8e5881f9744ff`。本目录继续保留为开发工作副本，默认入口没有自动追加新检查；使用完整批准链路请调用v4归档入口。

## 墙面参照修正 v3

v3 在批准的 pinhole 基础上按证据增加修正，不按会员名、组号或素材ID设置特殊参数：

1. 大模型审查主体是否靠近同一平面墙、哪些结构可以作为参照；印刷木纹、器械、海报纸张边缘不能直接作墙线。
2. SAM 排除人物；LSD/Hough 检测真实线段并编号，大模型再选择属于墙面的横竖线。模型粗坐标仅用来划定搜索区域。
3. 按校准重力方向和真实水平线估计墙面 yaw。长度加权的几何共识剔除模型误选；检查横线残差、竖线退步、画布增长和人物局部变形，再做原成品/候选视觉复核。没有可靠证据时保留 pinhole 成品并记录原因。
4. 对同店同名照片，在墙面区域提取 SIFT，排除人物，以双向匹配和 MAGSAC 估计相对尺度。至少两张中立肩部姿势的正/背面参考给出一致估计，才调整抬臂图中明显偏小的取景；不以人体宽度或头部决定尺度。
5. 抬臂图采用同组背景确定的等比缩放，并以髋部及中立躯干参照定位；实际肩点和真实姿势不改动，因此不再强制抬起的肩点也位于23%高度。其余图片继续原有肩髋27%、肩部23%的规则。组图复核可否决尺度候选。

参考不足、无明显改善、几何/视觉检查未通过时，该张沿用批准的成品。网格不执行上述新分支。所有候选保存在诊断文件中，**`aligned.png` 才是采用的成品**；候选不等于通过验收。

从原job一次运行完整流程：

```bash
bash scripts/run_body_scan_refined.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --classification-audit /root/autodl-fs/case-studio/experiments/body-scan-camera-v2-wall-audit/classification.json \
  --out /root/autodl-fs/case-studio/experiments/body-scan-refined-new
```

该命令相当于基础入口加 `--refine-background`，自动保留相邻 `<输出目录>-pinhole` 基线。两个目录都必须不存在；历史job中未被上述audit覆盖的旧体测标签仍须复核。

已有批准的v2成品可直接运行新阶段，无须重做人物检测：

```bash
PYTHONUTF8=1 OMP_NUM_THREADS=4 /root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan.refinement \
  --baseline /root/autodl-fs/case-studio/experiments/body-scan-unified-v2-camera-20261105 \
  --out /root/autodl-fs/case-studio/experiments/body-scan-refined-new
```

只有通过原图SHA检查的v2 pinhole基线可以输入，避免叠加校正；新成品重用原图关键点并从原图采样，绝不对旧成品再次变形。`--group g010` 只用于指定验证子集；不传则遍历所有组。`--no-group-scale` 可单独观察墙面修正。

模型审查使用已有服务配置和独立 `cache/wall-reference`，缓存绑定模型服务、提示词版本和图片。新增依赖为现有OpenCV的SIFT/MAGSAC功能，无需额外安装模型。

全流程46张验证结果见 `validation-wall-v3.json`：41张成品中4张采用墙面修正，含1张同组尺度修正；另外37张成品及其遮罩与v2逐字节相同。40项单测通过。细节见 [方案23](../../docs/solutions/会员案例素材生产方案/23-墙面参照与同组尺度修正.md)。

## 标准化入口：海报背景排除

标准化开始时，对原图单独进行 `standardization-background-v1` 背景审查，在主体定位、相机/网格校正和肩髋检测之前执行。该规则不改变上游 `body_scan` 分类，也不放在 `body_scan_group_display` 展示节点中。

- 主体紧邻的主要背景为海报、大幅广告、人物照片墙或印刷拼贴：`skipped`，原因码 `poster_background_excluded`。中文原因：主体以海报或广告印刷画面为主要背景，背景人物及复杂图案易干扰人物定位与几何校正，按规则跳过标准化。
- 普通网格、身高刻度、白墙、木纹墙继续原有流程；网格上的数字、少量说明文字，以及画面边缘的小海报不因此淘汰。
- 模型结论不确定、置信度低于0.8、响应不合规或请求失败：`needs_review`，不会静默放行或假装已确认海报。
- 结果保存到 `background_screening`，包含原图SHA、模型依据、版本及缓存轨迹；跳过原因写入 `summary.json`、单图 `report.json` 和预览的“已跳过”清单。被排除的图片不生成新的 `aligned.png`。
- 审查缓存位于 `cache/standardization-background`，绑定图片像素、提示词、版本和模型服务；旧的 `cls-v3-wall` 标签不能代替这项检查。独立 `refinement` 入口处理历史基线时也会审查原图，防止旧成品绕过规则。

当前规则位于可迭代的 `scripts/body_scan`，冻结的 `best-practices` 副本保留历史版本及其哈希。调用当前标准化节点请使用 `scripts/run_body_scan_refined.sh`。既有展示页是历史产物，需接收新的标准化结果后再生成，不会原地删除图片。

2026-11-05远程验证：沿用历史46张输入及2张拆分子图，45张通过基础体测条件的候选接受背景审查；仅蒲小东的 `a0034` 被确认为海报并排除。其余44张通过背景审查，其中原有2张继续因相机/肩髋问题待复核。单图结果40张成功、4张跳过、2张待复核；拆分子图2张成功。42张标准化成品及两种遮罩共126个文件与旧结果逐字节一致，47项单测通过。按原展示算法重建后为42张/11组；只有 `a0025` 的派生取景随同组海报移除而变化，顶部不再额外裁切。详见 [validation-background-v1.json](validation-background-v1.json)。这是验证子集，仍非整个上传包的全量结果。

## 流程

1. 接收上游 `job.json` 的大模型标签，只处理单人、静态站立、主体紧邻墙面的体测图。过滤对比图、训练图、镜面/户外和人数不明确/多人图片。旧标签缺少墙面或体测姿态证据时进入待复核，可通过带原图SHA的 `--classification-audit` 补充分类，不改写历史job；不把 YOLO 框数量当成人数标签。
2. 标准化入口先执行上述海报背景审查；放行后共用主体定位：YOLO → 尺寸重试/重复框合并 → 大模型粗框 + ROI YOLO → SAM 兜底。大模型粗框提示词已适配不同背景，并升级缓存版本；SAM 与 API 配置读取不再依赖旧实验脚本。
3. 按背景选择几何变换：网格沿用批准的双轴拟合及质量验收；非网格使用 `non_grid.NonGridTransform`，复用独立实验的 GeoCalib **pinhole** 相机侧倾/俯仰估计和画布约束。只返回校正矩阵和诊断，不渲染中间图片；不启用 radial。
4. 共用肩髋定位：在原图检测关键点，映射至校正坐标后进行全图/局部一致性核验，并重新计算取景比例。正背面使用双侧肩髋，侧面使用可信一侧。不使用头部、发型或肩宽确定比例，不把真实高低肩强制转平。
5. 共用取景：肩髋长度统一为画布高度的 27%，肩部锚点置于高度 23%、水平中心；默认画布 768×1792。将背景变换和取景缩放/平移合并，最终图从原图采样一次。尽量使用整个原图范围，排除明确的原图黑边；在真实有效像素内求包含肩髋的最大矩形，矩形之外保留浅色画布。
6. 按门店和同名会员分组，按前、后、左、右排序，输出原图/结果对照、成品拼图与下载包。失败图片列为待复核，不混进成功结果，也不会生成缺失身体部位。

相机矩阵为 `H = M · K · Rᵀ · K⁻¹`，最终取景为 `A · H`。不确定性提示留在报告中；用户批准后不因提示本身拦截，但保留实验的角度、视场角、画布增长和局部变形限制。超限或模型失败进入待复核，**不会自动退回未校正图片**。

本版校正侧倾和俯仰，没有径向去畸变，也没有估计墙面绕竖直轴的方向。统一肩髋比例不等于全身高度绝对相等。身体原本缺失或被画框截去时，沿用已批准的局部裁切规则，不通过自动放大/缩小补齐。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `pipeline.py` / `classification.py` | 过滤、旧job复核合并、路由、报告及分组 |
| `background_screening.py` | 标准化前审查原图背景，排除海报并记录原因 |
| `grid.py` / `non_grid.py` | 返回背景几何矩阵和诊断 |
| `../non_grid_camera/calibration.py` / `geometry.py` | 复用批准的相机估计、缓存和画布约束 |
| `localization.py` / `segmentation.py` | 主体定位和 SAM 分割 |
| `landmarks.py` / `pose.py` | 肩髋测量与有模型/输入指纹的缓存 |
| `geometry.py` / `framing.py` | 投影、源像素有效范围、统一缩放和最大矩形 |
| `preview.py` | 同名分组预览、成品拼图和 ZIP |

背景模块的输入为 OpenCV 解码的 BGR 原图与主体定位结果，输出为 `(H_source_to_corrected, metadata)`。原图坐标体系与现有已验证脚本一致。共享取景只接受矩阵，不依赖背景模块保存的中间图片。

## 服务器运行

代码放在 `/root/apps/case-studio/scripts/body_scan`，需同时部署 `scripts/non_grid_camera` 作为校准和几何库；不运行独立实验流程。数据和输出放在 `/root/autodl-fs/case-studio`，主体模型复用 `/root/autodl-fs/portrait-studio/models`。

启动器默认使用 `/root/apps/non-grid-calibration/.venv/bin/python`，通过 `--system-site-packages` 复用原 torch/CUDA，新增 GeoCalib/kornia 与网站环境分开。固定 GeoCalib 提交 `1dedb29f94fc11b896c5f572005978aeebccd67f`；只用 `geocalib-pinhole.tar`。依赖版本及模型归属见 [独立相机实验说明](../non_grid_camera/README.md)。模型推理仍在远程GPU执行。

从代码根目录运行：

```bash
bash scripts/run_body_scan.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --classification-audit /root/autodl-fs/case-studio/experiments/body-scan-camera-v2-wall-audit/classification.json \
  --out /root/autodl-fs/case-studio/experiments/body-scan-new-run \
  --background non-grid
```

默认 `--background all`。可用 `--asset-id a0101 a0103 a0104` 指定样本；`--width`、`--height`、`--torso-fraction`、`--shoulder-y` 调整共用取景参数。输出目录必须不存在，以保护之前的实验。

默认 `--non-grid-mode pinhole`；显式 `--non-grid-mode identity` 重现旧版几何基线，仍执行新墙面筛选。`--previous <旧输出目录>` 额外生成接入前后成品对照，按原图SHA匹配。`--camera-weights` / `--camera-cache` 可覆盖相机权重和缓存；`CASE_PYTHON` 可覆盖环境。

上述audit覆盖本批46张；其他历史素材先用 `scripts.non_grid_camera.audit` 复核并传入新audit。新 `cls-v3-wall` job 已有必要证据时可省略此参数。审计版本不符、重复ID或原图SHA不匹配会在创建输出目录前报错；未覆盖且证据不足的历史标签进入待复核。

`--job` 中每项素材需要 `id/path/store/member/class`，原图路径相对 `job.json` 同级 `input/`。归一化、去重和七类素材分类仍由上游流程负责，本脚本不重新解压或重判素材类别；新增背景审查仅决定是否进入标准化。

标准化背景审查及VLM定位兜底只读服务器 `settings.json`，也可传 `--settings`；密钥不会写入输出或代码。支持 `CASE_YOLO`、`CASE_SAM`、`CASE_SAM_CONFIG` 覆盖模型，`--pose-weights` 和 `--pose-cache` 覆盖姿态模型及缓存。

主要产物：`summary.json`、`groups.json`、`counts.json`、`config.json`，每张成功图片的 `original.png`、`aligned.png`、`available_mask.png`、`content_mask.png`、`report.json`，每组 `gXXX-comparison.jpg` / `gXXX-aligned.jpg` 和可选 `gXXX-upgrade.jpg`，以及可离线打开的 `index.html`、完整 `body-scan-results.zip`。

## 验证

```bash
PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python -m unittest discover \
  -s scripts/body_scan/tests -t . -v

PYTHONUTF8=1 /root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan.verify_run \
  --out /root/autodl-fs/case-studio/experiments/body-scan-unified-v2-camera-20261105 \
  --grid-baseline /root/autodl-fs/case-studio/experiments/grid-single-v2-20261105/grid-shoulder-max-rectangle-v5-verified \
  --camera-baseline /root/autodl-fs/case-studio/experiments/non-grid-camera-v1-20261105
```

27项测试通过，覆盖批准矩阵一致性、单次原图采样、相机失败和异常参数、墙面筛选、审计SHA绑定、诊断留存，以及恒等基线/网格路由/矩形穷举等原有检查。46张回归：41张成品（12网格、29非网格），3张跳过，2张待复核。网格24文件与权威版字节相同；29张非网格矩阵与独立实验一致。最新验证见 `validation.json`，历史基线保留为 `validation-v1.json`。

这是独立脚本，尚未接入网站的成品渲染入口。
