# 单人体测图统一处理

从 `best-practices/grid-portrait` 的权威代码复制、提取的共用实现。基础阶段为 `body-scan-unified-v2-pinhole`；新增 **`body-scan-wall-v3` 墙面参照与同组尺度修正**，推荐通过 `scripts/run_body_scan_refined.sh` 运行。权威副本、独立相机实验和旧成品保留；来源见 `provenance.json`。成品始终由原图生成。

用户已确认的完整v3快照现位于 [best-practices/body-scan-wall](../../best-practices/body-scan-wall/README.md)，来源提交 `c3ce38966da8d39cf702778858e8e5881f9744ff`。复现批准版请使用该归档入口；本目录保留为后续开发工作副本。

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

## 流程

1. 接收上游 `job.json` 的大模型标签，只处理单人、静态站立、主体紧邻墙面的体测图。过滤对比图、训练图、镜面/户外和人数不明确/多人图片。旧标签缺少墙面或体测姿态证据时进入待复核，可通过带原图SHA的 `--classification-audit` 补充分类，不改写历史job；不把 YOLO 框数量当成人数标签。
2. 共用主体定位：YOLO → 尺寸重试/重复框合并 → 大模型粗框 + ROI YOLO → SAM 兜底。大模型粗框提示词已适配不同背景，并升级缓存版本；SAM 与 API 配置读取不再依赖旧实验脚本。
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

`--job` 中每项素材需要 `id/path/store/member/class`，原图路径相对 `job.json` 同级 `input/`。归一化、去重和 VLM 分类仍由现有网站的上游流程负责，本脚本不重新解压或分类。

VLM 兜底按需只读服务器 `settings.json`，也可传 `--settings`；密钥不会写入输出或代码。支持 `CASE_YOLO`、`CASE_SAM`、`CASE_SAM_CONFIG` 覆盖模型，`--pose-weights` 和 `--pose-cache` 覆盖姿态模型及缓存。

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
