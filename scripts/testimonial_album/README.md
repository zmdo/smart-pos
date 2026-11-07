# 会员感言相册模板

独立开发与效果验证入口，目前先供用户查看 HTML，尚未归档到正式最佳实践。识别、隐私复核、图像处理与渲染均在远程服务器执行。

## 固定版式与内容约束

- 整批固定 **1080×1440**，红色边框 `#e60012`。仅全局配置可改变尺寸，会员不能单独改尺寸。
- **整个“会员感言”模块固定**：默认截图框 `[15,15,1050,1159]`，底部标题区 `[15,1185,1050,240]`（x、y、宽、高）。图标、文字及周围留白都使用相同位置和大小，不随截图长短变化。
- 延用首版横排规格：标题 97 px、图标宽 193.6 px、品牌文字 29 px。全局画布宽度改变时统一等比调整。
- 每张截图仅用一次，相同 SHA 去重。单张素材只做一页单图；多张按评分排主辅、分页，每页至多两张，不借用其他会员素材。
- AI 标出主要反馈、完整气泡及允许取景范围。程序在原图范围内寻找包含主要内容的矩形，尽量适应固定截图框，等比缩放；不切掉有用反馈，不改写聊天文字。
- 实际截图至少占画布 50%；主要内容包围框至少占裁剪区域 40%，防止靠大量背景凑满。单图与合成页均检查，组合不合格时拆成单图页。仍不合格则跳过，并返回原因。

## 隐私范围

只新增会员头像、聊天内人物照片、背景人物照片的马赛克。会员头像即使是动物或图案也遮盖。**对话中的姓名、昵称和全部文字均保留；右侧教练头像保持原样**，即使头像本身是健身人物照片，也不能当成聊天内照片遮挡。普通表情包、非人物图片保留。原图已有的遮挡不恢复。

模型分别圈出需遮图片、完整文字气泡与右侧教练头像。程序从图片遮罩中扣除文字与教练头像保护区，再对源图副本做马赛克；背景人物照片的遮罩也不得覆盖气泡或教练头像。第二次模型检查原图与遮盖图，发现遗漏可补框重试；误遮、坐标异常、低置信或复核未通过则不导出该截图。

当前 HTML 的原截图入口只提供**已遮盖的预览**，不附未遮盖原图或 OCR 转录。模型原始回答留在服务器证据目录。店名、会员目录名仍保留在内部导航中，供用户查找；这不是整站匿名化。旧实验预览不会被覆盖，应使用最新 v4 预览。

## 三个独立阶段

```bash
# 1. 识别感言、区分会员与教练、评分。已有证据可以直接复用。
python -m scripts.testimonial_album.evidence \
  --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json \
  --settings /path/to/private-qwen-settings.json \
  --cache /path/to/testimonial-cache --workers 3 \
  --out /path/to/testimonial-evidence

# 2. 标注主要内容、文字/教练头像保护区与隐私图片，进行遮盖复核。
python -m scripts.testimonial_album.annotate \
  --input /path/to/私教会员案例项目 \
  --evidence /path/to/testimonial-evidence \
  --settings /path/to/private-qwen-settings.json \
  --cache /path/to/testimonial-layout-cache --workers 3 \
  --out /path/to/testimonial-layout-evidence

# 3. 仅消费证据，生成成品和 HTML，无模型调用。
python -m scripts.testimonial_album \
  --input /path/to/私教会员案例项目 \
  --evidence /path/to/testimonial-layout-evidence \
  --font /path/to/NotoSansSC.ttf \
  --config scripts/testimonial_album/presentation.example.json \
  --out /path/to/new-testimonial-products
```

从项目根目录运行，当前远程解释器为 `/root/apps/non-grid-calibration/.venv/bin/python`。私密模型配置只传路径，不写入代码或公开产物。只处理 `xxx店`，排除参考模板与说明文件。

第一阶段输出 `member-testimonial-evidence-v1`，第二阶段输出带 SHA 绑定的 `member-testimonial-layout-privacy-v1`。渲染要求 `privacy_policy=member_images_keep_coach_and_text`、`status=verified` 和 `privacy_audit_passed=true`，不能误用旧遮盖规则的证据。

第二阶段可加 `--reuse-content /path/to/previous-layout-evidence` 复用同 SHA 源图的主要内容框，只重做隐私标注及复核。缓存按图像、提示词与版本区分。改变排版可直接重跑第三阶段。

## 评分与结果

只给会员回复评分，教练文字不计。总分 100：有效文字长度 30（350 字封顶）、具体经历 35、情感表达 20、清晰度 15。模型后三项各给 0–5 分，程序计算权重；情感衡量表达丰富度，不因负面感言而淘汰。分数只用于选主图，不代表评价真实性或训练效果。

长篇（至少 300 字且 70 分）、重点（至少 120 字）、简短与横屏是 HTML 分类，不改变固定标题区。先单独验证来源，再按评分排版；主辅双图使用 60%/40% 宽度。

配置支持全局 `width`、`height`、`title`、`brand`、`accent`、`layout`；`members` 按 `店/会员目录` 指定 `hero_message_id` 或分类。默认“会员感言”与“UP 健身私教馆”。

输出 `index.html`、`results.json`、`review.json`、来源 SHA 绑定、各组 `page-NN.png/jpg`、已遮盖的原尺寸预览和排版元数据。`layers` 记录来源、裁剪、等比缩放、实际马赛克区域与落位。公共 JSON 只保留数字评分，不导出聊天转录。

无素材使用 `skip_kind=missing_material`；有素材但取景或隐私未通过使用 `unsuitable_screenshot`，具体原因在 `quality_rejections` 中（如 `privacy_or_content_unverified`、`main_content_too_sparse`、`chat_area_too_small`）。跳过的组没有成品图片。输出目录必须全新，旧预览保留。

## 验证与预览

```bash
python -m unittest discover -s scripts/testimonial_album/tests -v
```

23 项测试覆盖一图一次、去重分页、统一画布/标题区、完整内容取景、等比像素保真、文字与右侧教练头像保护、背景照片遮盖、未复核不导出、公共结果不泄露未遮原图或转录。真实数据每个会员只有一张合格感言来源，多图由合成测试验证。

全量结果与逐像素核验见 [validation.json](validation.json)。当前预览位于工作区 `artifacts/testimonial-album-v4/validated/index.html`；远程产物 `/root/autodl-fs/case-studio/experiments/testimonial-album-v4-20261107/delivery`。Git 不存会员图片。
