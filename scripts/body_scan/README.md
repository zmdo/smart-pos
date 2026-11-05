# 单人体测图统一处理

从 `best-practices/grid-portrait` 的权威代码复制、提取并整理出的独立实现。权威副本和旧实验入口均保持不变；逐文件来源及哈希见 `provenance.json`。本入口直接读取已分类的原图，不需要依次运行 v1–v5 或准备旧实验的中间产物。

## 流程

1. 接收现有素材识别流程产出的 `job.json`，复用大模型的体测图、人数、对比图、朝向和背景标签。过滤非体测图、对比图和人数不明确/多人图片；不重新调用模型分类，不把 YOLO 检测框数量当成人数标签。
2. 共用主体定位：YOLO → 尺寸重试/重复框合并 → 大模型粗框 + ROI YOLO → SAM 兜底。大模型粗框提示词已适配不同背景，并升级缓存版本；SAM 与 API 配置读取不再依赖旧实验脚本。
3. 按背景选择几何变换：网格沿用批准的双轴网格拟合及质量验收；其他背景调用 `non_grid.normal_transform()`，**默认只返回单位矩阵，不做旋转、透视、镜头畸变修正或中间图重采样**。
4. 共用肩髋定位：原图和局部区域互相验证，正背面使用双侧肩髋，侧面使用可信一侧。不使用头部、发型或肩宽确定比例，不把真实高低肩强制转平。
5. 共用取景：肩髋长度统一为画布高度的 27%，肩部锚点置于高度 23%、水平中心；默认画布 768×1792。将背景变换和取景缩放/平移合并，最终图从原图采样一次。尽量使用整个原图范围，排除明确的原图黑边；在真实有效像素内求包含肩髋的最大矩形，矩形之外保留浅色画布。
6. 按门店和同名会员分组，按前、后、左、右排序，输出原图/结果对照、成品拼图与下载包。失败图片列为待复核，不混进成功结果，也不会生成缺失身体部位。

**“非网格不处理”仅指第 3 步几何校正暂不处理；第 4–6 步共用人物标准化仍执行。** 部分身体原本缺失或被标准画布截去时，不自动放大/缩小去补齐，以免破坏人物比例和肩部位置的一致性。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `pipeline.py` | 过滤、路由、组合、报告及分组 |
| `grid.py` / `non_grid.py` | 返回几何矩阵和诊断；后者是后续非网格校正的扩展点 |
| `localization.py` / `segmentation.py` | 主体定位和 SAM 分割 |
| `landmarks.py` / `pose.py` | 肩髋测量与有模型/输入指纹的缓存 |
| `geometry.py` / `framing.py` | 投影、源像素有效范围、统一缩放和最大矩形 |
| `preview.py` | 同名分组预览、成品拼图和 ZIP |

背景模块的输入为 OpenCV 解码的 BGR 原图与主体定位结果，输出为 `(H_source_to_corrected, metadata)`。原图坐标体系与现有已验证脚本一致。共享取景只接受矩阵，不依赖背景模块保存的中间图片。

## 服务器运行

代码放在 `/root/apps/case-studio/scripts/body_scan`，数据和输出放在 `/root/autodl-fs/case-studio`，模型复用 `/root/autodl-fs/portrait-studio/models`。使用现有 GPU 虚拟环境，无需本地 GPU，也不需要安装新依赖。

从代码根目录运行：

```bash
bash scripts/run_body_scan.sh \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --out /root/autodl-fs/case-studio/experiments/body-scan-new-run \
  --background non-grid
```

默认 `--background all`。可用 `--asset-id a0101 a0103 a0104` 指定样本；`--width`、`--height`、`--torso-fraction`、`--shoulder-y` 调整共用取景参数。输出目录必须不存在，以保护之前的实验。

`--job` 中每项素材需要 `id/path/store/member/class`，原图路径相对 `job.json` 同级 `input/`。归一化、去重和 VLM 分类仍由现有网站的上游流程负责，本脚本不重新解压或分类。

VLM 兜底按需只读服务器 `settings.json`，也可传 `--settings`；密钥不会写入输出或代码。支持 `CASE_YOLO`、`CASE_SAM`、`CASE_SAM_CONFIG` 覆盖模型，`--pose-weights` 和 `--pose-cache` 覆盖姿态模型及缓存。

主要产物：`summary.json`、`groups.json`、`counts.json`，每张成功图片的 `original.png`、`aligned.png`、`available_mask.png`、`content_mask.png`、`report.json`，每组 `gXXX-comparison.jpg` / `gXXX-aligned.jpg`，以及可离线打开的 `index.html`、完整 `body-scan-results.zip`。

## 验证

```bash
/root/apps/portrait-studio/.venv/bin/python -m unittest discover \
  -s scripts/body_scan/tests -t . -v
```

测试覆盖恒等变换、非网格仅等比缩放和平移、网格分支路由、过滤先于推理、黑边处理、分组待复核、旧结果保护，以及沿用的最大矩形穷举验证。真实样本验证结果见 `validation.json`。

这是独立脚本，尚未接入网站的成品渲染入口。
