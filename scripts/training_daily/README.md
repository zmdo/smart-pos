# 日常训练照片成品 v1

独立开发验证节点。复用第一步 `daily_training` 分类，不重跑全量图片分类，不判断训练前后。识别与图像处理在远程服务器执行；当前先用 HTML 确认效果，尚未归档最佳实践。

## 已实现

- 仅门店目录的 Qwen `daily_training` 图片作为候选；没有 Qwen 记录时才回退 DeepSeek / 旧分类。参考模板、生活照、说明文件与视频不进入图片渲染。
- Qwen 在等比例补白图上标注真正照片区域、主要训练人物、完整动作和器械接触范围。区分实际训练与摆拍，明确多人主体；不能确定主体则返回待确认，不猜人物身份。
- 原图内矩形取景，去除截图黑边和操作条。保护可见身体、手脚、握持器械、脚部支撑及协助教练。原图已有缺失保留并记录，不能补造。
- 固定 1080×1440、6px 红边，默认无大标题或文案。等比缩放、不拉伸、不透视变形。动作放不进竖框时完整等比嵌入，周围用低对比模糊背景填充；有效画面占框不足 45%、短边不足 380px 或需要放大超过 1.8 倍则跳过。
- 统一轻度纪实调色：按可见光照小幅曝光调整（-0.04 至 +0.20 EV），提亮暗部、压缩高光；仅明显色偏时做最高约 2.5% 的白平衡微调。噪声较高时轻度平滑暗部，轻度锐化；不合成不存在的细节。
- 背景在动作保护矩形以外羽化降饱和、压暗。使用保守的动作区域保护，不是人物精细抠图；区域内的器械和人物保持同一全局色调。默认不旋转，不改变身体或器械几何，不新增人脸遮盖，原图已有贴纸保持。
- 每位会员按画质、动作可见度、曝光分数选最多 3 张，相同 SHA 只使用一次；分数不评价训练成绩或动作标准。
- 可配置画布、红边、效果强度、选图数、最大放大倍数和 Logo。Logo 可选，从外部路径读取，独占底部小条，不覆盖动作。`enhance=false` 可输出只取景的版本。

## 两个入口

从项目根目录执行；远程解释器为 `/root/apps/non-grid-calibration/.venv/bin/python`。

```bash
python -m scripts.training_daily.analysis \
  --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json \
  --settings /path/to/private-model-settings.json \
  --cache /path/to/training-daily-cache --workers 3 \
  --out /path/to/new-training-evidence

python -m scripts.training_daily \
  --input /path/to/私教会员案例项目 \
  --evidence /path/to/new-training-evidence \
  --config scripts/training_daily/presentation.example.json \
  --out /path/to/new-training-products
```

第一入口输出 `training-daily-evidence-v1` 包，包含原图 SHA、模型原始回答、归一化后的动作保护范围、评分和需确认原因。第二入口只消费证据，不导入模型客户端。改变版式或效果强度可复用证据，输出目录必须全新。

依赖 Pillow、NumPy；识别额外依赖 OpenCV、httpx。使用既有 `body_scan_contracts` 的来源绑定、模型缓存及数据包校验，不依赖体测变形、训练阶段分类或其他成品生成器。模型配置与照片均不提交 Git。

## 输出与审核

- `index.html`：按会员展示成品；按钮切换“处理后”“同取景·调色前”“原始照片”；按已生成、待确认、未生成筛选。
- `results.json`、每组 `result.json`：动作名称、选图分数、来源 SHA、裁剪范围、保护范围、统一缩放系数、照片占框比例、颜色参数和审核提示。
- `review.json`：主体不明确、原图局部缺失、识别错误或没有候选图片等情况。当前返回可查阅清单，尚未接入网页审核回传服务；人工指定主体后需更新对应证据重新运行，不能修改源图或伪造通过状态。
- 每张成品输出 PNG / JPG，同时提供同取景调色前和完整原图的缩略预览。人物照片仍使用原像素，不做增肌、瘦身、补肢体或生成式背景替换。

## 当前验证

18 组、13 张候选，10 张通过并生成，覆盖 8 组；关文博 `a0013` 为肌肉摆拍，吴显昉 `a0097` 有效动作画面过窄，均跳过；潘艺文 `a0164` 是双人跑步机图，待指定主体。9 组没有此分类的图片；视频没有抽帧。

11 项测试覆盖目录范围、坐标映射、动作与器械完整性、横向嵌入、画质门槛、背景保护、原像素等比渲染、拒绝素材不落成品、去重及限额、输入变更拒绝和渲染不导入模型。另逐张核对真实产物的尺寸、保护范围、来源哈希和 HTML 交互，记录见 [validation.json](validation.json)。

```bash
python -m unittest discover -s scripts/training_daily/tests -v
```

本机预览：工作区 `artifacts/training-daily-v1/validated/index.html`。远程结果：`/root/autodl-fs/case-studio/experiments/training-daily-v1-20261107/validated`。
