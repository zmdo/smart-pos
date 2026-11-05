# 同人图片大小标准化最佳实践

用户确认的 **`body-scan-group-display-v2`**：同店同名只使用一种尺寸、比例、取景框和缩放。来源提交 **`3aca63e72f65ccd8d63e59a758b9a1f00065297b`**，沿用 `da3fd40` 的“一人一画幅”算法。本次只冻结代码及运行依赖，不改变处理效果。

这是单图标准化之后的尺寸统一节点。上游负责分类、硬拼接拆分、海报背景排除、网格/非网格校正和人物定位；本节点复用上游坐标和尺度，完成同人共同取景与输出。海报过滤仍在上游，不在这里重复判断。

## 处理规则

1. 接收一个或多个已批准的单图结果目录，检查原图SHA、成品SHA、有效矩形及变换，只处理 `rectangular`。其他状态和原因保存为 `upstream_excluded`。
2. 视觉模型判断有效照片当前的头、腿、脚可见范围；SAM使用已批准的肩髋点检查轮廓，必要时放大顶部和底部复核。贴边与确认缺失分别留档，不推断原始拍摄是否缺失身体。
3. 按门店和会员姓名分组，在肩部相对坐标中求整组有效矩形的交集。同一个人的全身/半身照片不拆成不同画幅，不能只取最小宽高后任意居中。
4. 整组选择一次首选比例，共用取景框、缩放和肩部位置；保护肩髋和共同矩形内可保留的身体上下范围。首选比例不可行时，整组调整高度，仍不满足约束则待复核。
5. 合成上游变换和本次取景矩阵，从原始单图采样一次。原标准化图保留，另存等比参考 `uniform.png` 和展示版 `display.png`。

展示版允许轻微非等比调整，默认 `scale_y / scale_x` 为 **1～1.1**，不是限制绝对像素放大倍数。每步裁剪不超过当前宽/高的2%，最多80步；额外裁剪最多损失共同矩形面积的25%。共同交集之前失去的面积单独记录，不能把这个25%理解为相对原图的总裁剪上限。

默认宽768。整组首选高度为：全身1920、脚部贴边/缺失1792、头部贴边/缺失1664、头脚均贴边/缺失1536、小腿/膝附近截断1408（头也不完整时1184）、上半身1152、躯干1024。实际高度由共同可用范围确定；同一人始终只输出一种尺寸，不同人可以不同。

保持真实高低肩、体态差异和正侧面宽度差异；不补画缺失身体。展示版用于排版展示，不作为真实体形测量结果。

## 输入与阶段边界

输入目录须包含 `config.json`、`summary.json`、每张合格照片的 `aligned.png` / `content_mask.png`，以及报告指向的原始单图。支持 `body-scan-wall-v3`、`body-scan-unified-v2-pinhole` 结果和拆分子图经标准化后的结果。`store/member` 必须明确；相同素材ID不能重复输入。

当前应使用已经过海报过滤的上游结果，例如：

- `/root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/standardized`
- `/root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/pairs-standardized`

上游海报规则由 `scripts/run_body_scan_refined.sh` 执行。旧的 `best-practices/body-scan-wall` 是历史快照，尚不含海报过滤；本节点不会把旧输入自动升级或纠正错误肩髋点。硬拼接节点接工作流时使用 `--split-only`，把子图交给当前标准化入口后再传入本节点。

## 远程运行

部署目录：`/root/apps/case-studio/best-practices/body-scan-group-display`。从任意工作目录启动：

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display/scripts/body_scan_group_display/run.sh \
  --input /root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/standardized \
          /root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/pairs-standardized \
  --out /root/autodl-fs/case-studio/experiments/NEW-approved-group-display \
  --max-stretch 1.1
```

输出目录必须全新。`--width`、`--profiles` 可配置整组模板，`--fixed-group-ratio` 禁止自动调整整组高度。`--max-crop-loss`、`--crop-step`、`--max-steps` 保留原脚本语义。

默认使用服务器 `/root/apps/non-grid-calibration/.venv/bin/python`，可通过 `CASE_PYTHON` 覆盖。模型设置只读服务器配置，可用 `--settings` 指定；密钥、照片、权重不进入Git。视觉缓存为 `cache/body-scan-group-visibility`，`CASE_SAM` / `CASE_SAM_CONFIG` 可指定SAM权重及配置。依赖版本见 [requirements.verified.txt](requirements.verified.txt)，外部资源指纹见 [external-resources.json](external-resources.json)。

如已有同一批输入的完整可见性审查，可追加：

```bash
--audit /root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/display/visibility
```

`--audit` 会校验输入目录、配置/汇总SHA、原图/成品/遮罩SHA、变换和边界审查完整性，不能用于另一批输入。省略时由副本独立执行审查，按图像和提示词复用证据缓存。

## 输出与验证

- `images/<id>/baseline.png`：批准标准化成品的原样副本。
- `uniform.png` / `display.png`：共同取景后的等比参考与独立展示版。
- `summary.json`、`groups.json`、`reports/`、`upstream-excluded.json`：逐图证据、排除原因、组内统一尺寸、坐标与取景参数。
- `verification.json`：原图/上游成品未变、一人一画幅、矩形有效、缩放和裁剪阈值、输出尺寸及SHA检查。
- `index.html`、`previews/`、`body-scan-group-display-results.zip`：效果对照和完整下载包。

```bash
/root/apps/non-grid-calibration/.venv/bin/python \
  /root/apps/case-studio/best-practices/body-scan-group-display/verify_snapshot.py
bash /root/apps/case-studio/best-practices/body-scan-group-display/run_tests.sh
```

批准前的43张验证记录保存在 [source-validation.json](source-validation.json)，海报过滤后的42张记录在 [source-background-validation.json](source-background-validation.json)。本次独立副本的重跑、原32项测试和像素比对记录在 [validation.json](validation.json)。这些均为历史验证子集，不代表整个上传包已全量处理。

## 冻结与维护

算法、提示词、测试和原启动器从来源提交逐字节复制，所需共享模块也一并冻结；不会从开发目录或相邻最佳实践读取项目代码。共享的 `body_scan` / `non_grid_camera` 模块用于满足原模块导入依赖，本归档入口不重新运行YOLO人物定位或GeoCalib校正。

[manifest.json](manifest.json) 记录逐文件来源与SHA；启动时自动校验文件完整性，`verify_snapshot.py` 额外验证项目导入均位于本副本内。归档辅助代码只处理完整性、依赖隔离和测试启动，不修改图像算法。后续改进先在开发目录进行，用户确认后再更新本副本及清单；既有原图、成品和其他最佳实践保持各自版本。
