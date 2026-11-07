# 日常训练照片成品最佳实践 v2

2026-11-07 用户确认后归档，视觉方案来源提交 `ba42b69`。复用第一步 `daily_training` 分类，不重跑全量图片分类，不判断训练前后。识别与图像处理在远程服务器执行。部署复制整个 `body-scan-delivery`，不依赖开发目录或其他成品节点。

已确认 v2 的历史验证保留在 [source-validation.json](source-validation.json)，独立归档验证见 [validation.json](validation.json)。归档同时修复了模型失败记录缺少尺寸时中断批次的问题：此类记录返回待审，已通过照片的取景与输出不变。

## 已实现

- 仅门店目录的 Qwen `daily_training` 图片作为候选；没有 Qwen 记录时才回退 DeepSeek / 旧分类。参考模板、生活照、说明文件与视频不进入图片渲染。
- Qwen 在等比例补白图上标注真正照片区域、主要训练人物、完整动作和器械接触范围。区分实际训练与摆拍，明确多人主体；不能确定主体则原文件直接输出，不猜人物身份，也不修改模型证据。
- 原图内矩形取景，去除截图黑边和操作条。保护可见身体、手脚、握持器械、脚部支撑及协助教练。原图已有缺失保留并记录，不能补造。
- 普通训练照使用 1080×1440 无外框画布，默认无大标题或文案。等比缩放、不拉伸、不透视变形。动作放不进竖框时完整等比嵌入，周围用低对比模糊背景填充；普通分支短边至少 380px、放大最多 1.8 倍。旧配置的 `border` 也统一按 0 处理。
- **过窄截图**：在模型实际照片范围附近，用像素核实上下/左右的连续黑色填充带。移除黑边及黑边中的手机操作条，保留整块照片；实际画面若不足标准框面积的 45%，改走 `native_crop`，以原始像素输出 PNG，不再取景、不缩放、不调色、不加 Logo 或补背景。不得直接按模型近似框切掉照片边缘。不能核实黑边时不启用此分支；不将摆拍或模糊照片自动放行。
- **主体不明确**：实际训练照片为 `ambiguous` 且证据状态为 accepted / needs_review 时走 `original_passthrough`，按字节复制原文件，保留格式、EXIF、尺寸和所有内容，不做任何图像处理。原始模型状态仍保留，输出状态记录为已选择；无需强行指定主体。
- 统一轻度纪实调色：按可见光照小幅曝光调整（-0.04 至 +0.20 EV），提亮暗部、压缩高光；仅明显色偏时做最高约 2.5% 的白平衡微调。噪声较高时轻度平滑暗部，轻度锐化；不合成不存在的细节。
- 背景在动作保护矩形以外羽化降饱和、压暗。使用保守的动作区域保护，不是人物精细抠图；区域内的器械和人物保持同一全局色调。默认不旋转，不改变身体或器械几何，不新增人脸遮盖，原图已有贴纸保持。
- 每位会员按画质、动作可见度、曝光分数选最多 3 张，相同 SHA 只使用一次；分数不评价训练成绩或动作标准。
- 可配置普通分支画布、效果强度、选图数、最大放大倍数和 Logo。Logo 可选，从外部路径读取，独占底部小条，不覆盖动作。`enhance=false` 可输出只取景的版本。两种保留原像素的分支始终跳过调色、Logo 和画布处理。

## 两个入口

从成品最佳实践根目录执行；远程解释器为 `/root/apps/non-grid-calibration/.venv/bin/python`。

```bash
./training_daily/evidence.sh \
  --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json \
  --settings /path/to/private-model-settings.json \
  --cache /path/to/training-daily-cache --workers 3 \
  --out /path/to/new-training-evidence

./training_daily/run.sh \
  --input /path/to/私教会员案例项目 \
  --evidence /path/to/new-training-evidence \
  --config training_daily/presentation.example.json \
  --out /path/to/new-training-products
```

第一入口输出 `training-daily-evidence-v1` 包，包含原图 SHA、模型原始回答、归一化后的动作保护范围、评分和需确认原因。第二入口只消费证据，不导入模型客户端。改变版式或效果强度可复用证据，输出目录必须全新。

依赖 Pillow、NumPy；识别额外依赖 OpenCV、httpx。数据契约来自成品包内冻结的 `scripts/body_scan_contracts`，模型客户端在本节点独立冻结；不依赖体测变形、训练阶段分类或其他成品生成器。模型配置与照片均不提交 Git。根 `create` / `restyle` 不自动编排本节点。

## 输出与审核

- `index.html`：按会员展示成品，按各成品实际宽高比显示，不用竖框套住横向照片。普通分支可切换调色前后与原图；去黑边分支只对比完整原图；原图直出不展示虚假的处理前后。下载保留实际格式。
- `results.json`、每组 `result.json`：动作名称、选图分数、来源 SHA、裁剪范围、保护范围、统一缩放系数、照片占框比例、颜色参数和审核提示。
- `review.json`：原图局部缺失、识别错误或没有候选图片等情况。当前返回可查阅清单，尚未接入网页审核回传服务；主体不明确已由原图直出策略处理，不再单独等待指定人物。上游证据的 rejected / needs_review 与渲染后的 output_status 分开存储，不能伪造模型通过状态。
- 普通成品输出 PNG / JPG 及同取景调色前；去黑边成品为原像素 PNG；原图直出保留原文件格式和字节。每张保留完整来源预览，不做增肌、瘦身、补肢体或生成式背景替换。

## 当前验证

18 组、13 张候选，生成 12 张、覆盖 9 组：10 张普通无框成品，吴显昉 `a0097` 仅去黑边（928×524），潘艺文 `a0164` 原图直出（1080×1440，文件 SHA 与原图一致）。仅关文博 `a0013` 肌肉摆拍跳过。9 组没有此分类的图片；视频没有抽帧。

16 项训练照测试覆盖目录范围、坐标映射、动作与器械完整性、横向嵌入、画质门槛、背景保护、原像素等比渲染、去重及限额、输入变更拒绝和渲染不导入模型；包含去黑边像素一致、原图字节与 EXIF 一致、旧配置也无边框、原图直出及模型失败记录全流程验证。另逐张核对归档重绘与批准版是否一致，记录见 [validation.json](validation.json)。

```bash
./run_tests.sh
```

本机预览：工作区 `artifacts/training-daily-v2/validated/index.html`。远程结果：`/root/autodl-fs/case-studio/experiments/training-daily-v2-20261107/validated`。
