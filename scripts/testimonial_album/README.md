# 会员感言相册模板 v1

开发与效果验证入口；当前先供用户在 HTML 中查看，尚未升级为正式最佳实践。所有识别、图像裁剪与渲染在远程服务器执行。

## 确认约束

- 每批统一画布，默认 **1080×1440**。可在全局配置调整宽高，会员配置不能改变尺寸。
- 外边框和卡片分隔使用品牌红色（默认 `#e60012`），与“会员感言”标题保持一致。
- 图标和文字采用首版红框的固定尺寸档，不再随着剩余标题区域变大：1080 宽画布中，横排标题 97 px、图标宽 193.6 px；竖排标题 69 px、图标宽 145.6 px。只有批次全局画布宽度变化时才同比缩放。
- 聊天截图必须成为成品主体：实际截图像素占成品面积至少 50%，标题区域不超过成品面积 40%。不合格截图跳过生成，并在 HTML、结果 JSON 与审核清单返回原因和实际占比。
- 每张原始截图在同一会员的全部成品页中只出现一次。不将同一截图同时做气泡放大图与上下文图；相同 SHA 的重复文件也只使用一次。
- 只有一张有效截图就生成单图版。两张时主辅排版，多于两张分页，每页至多两张，不混用其他会员的素材。
- 仅裁掉聊天 UI 和无关边缘，保留完整相关会员反馈与教练回复，所有可读会员气泡都位于上下文框内。等比缩放，不拉伸、不重写聊天文字、不生成虚构评价。
- 只处理 `xxx店` 目录，排除参考模板与说明文件。训练计划、约课和教练自述不是会员感言；没有素材保留缺失原因。

## 两个独立阶段

```bash
python -m scripts.testimonial_album.evidence \
  --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json \
  --settings /path/to/private-qwen-settings.json \
  --cache /path/to/testimonial-cache --workers 3 \
  --out /path/to/new-testimonial-evidence

python -m scripts.testimonial_album \
  --input /path/to/私教会员案例项目 \
  --evidence /path/to/new-testimonial-evidence \
  --font /path/to/NotoSansSC.ttf \
  --config scripts/testimonial_album/presentation.example.json \
  --out /path/to/new-testimonial-products
```

从项目根目录运行，使用远程 `/root/apps/non-grid-calibration/.venv/bin/python`。第一阶段复用已授权 Qwen 配置，不在代码或产物中写密钥；模型只分析原截图。第二阶段不导入模型客户端，只消费带 SHA 的 `member-testimonial-evidence-v1` 数据包。修改版式无须再次识别。

## 评分与布局

只给会员回复计分，教练文字不计。总分 100：有效文字长度 30 分（350 字封顶）、具体经历与细节 35 分、明确情感表达 20 分、清晰度 15 分。模型对后三项给 0–5 分，程序按权重计算；分项、原文、语气和原因全部可查。情感表达衡量丰富程度，不把负面情感自动算低分，不按情绪正负淘汰素材；分数不代表评价真实性或训练效果。

先选角色和边界明确的完整回复，再按分数排序。长篇、重点、简短和横屏仅是排版分组：长篇至少 300 字且 70 分，重点至少 120 字，其余为简短。单图比较底部标题板与右侧标题板两种构图，在同一固定画布中优先保证文字可读；标题和图标使用固定规格。双图按分差分配主辅面积，并保留各自完整上下文，不复制素材。

保留较小的外边距和截图内边距，让截图等比放大。底部标题布局按截图实际高度收紧主图框；右侧标题布局按截图实际宽度收紧主图框。先按单图版式检查每张截图，防止差的素材借另一张大图通过；再检查最终合成版式。若两张合格截图拼在一页后占比不合格，就拆为两张单图成品，每张来源仍只用一次。标题与信封图案分别布局，不能通过放大标题、裁字或拉伸截图凑满画布。

内容识别结果 `status=accepted` 与版式适用性分别保存。`presentation` 记录每张截图是否适合成品、聊天面积占比、标题区占比与拒绝原因；`quality_rejections` 汇总不合格素材。无合格截图的组返回 `status=skipped` 和 `skip_kind=unsuitable_screenshot`，不写成品 PNG/JPG，保留原图供核查。同组其余合格截图继续生成。没有素材则返回 `skip_kind=missing_material`，不与版式不合格混淆。

图上仅出现截图与标题装饰，评分和技术信息放在 HTML 详情及 JSON。不确定的角色、裁剪边界、原图截断或模型识别疑点写入 `review.json`，不凭空补全。

## 配置与输出

参考 `presentation.example.json`。支持全局 `width`、`height`、`title`、`brand`、`accent`、`layout`；`members` 按 `店/原始会员目录` 覆盖 `hero_message_id` 或布局。默认标题为“会员感言”、品牌文字为“UP 健身私教馆”。

输出 `index.html`、`results.json`、`review.json`、来源绑定及各组 `page-NN.png/jpg`、原截图和排版元数据。`layers` 逐项记录来源 ID、原始尺寸、裁剪矩形、等比缩放系数及落位，可核验一图一次与完整像素。输出目录必须全新，不覆盖旧预览。

```bash
python -m unittest discover -s scripts/testimonial_album/tests -v
```

目前核查 18 个会员组、17 张候选，16 张内容属于感言；何彦霖的 `a0128` 为训练计划，剔除并保留原因。新版中 14 张通过版式检查，生成 14 张成品。李禹衡的 `a0152` 聊天面积仅 12.5%、标题区 81.4%；蒲小东的 `a0030` 聊天面积 40.1%、标题区 53.7%，均不生成。易丽云、黎国萍缺少感言截图。

验证结果见 [validation.json](validation.json)：17 项测试通过。14 张 PNG/JPG 均为 1080×1440，逐一核对原图 SHA、会员气泡范围、截图唯一性、等比缩放像素、固定字号和图标尺寸、标题不重叠。源图裁剪范围不变。另验证不合格截图无成品文件、同组保留合格素材、双图不合格时分开输出。HTML 六个筛选项和下载链接已核验。真实数据每组只有一张内容合格素材，多图行为由合成样例回归测试覆盖。

当前预览：`artifacts/testimonial-album-v3/validated/index.html`（工作区根目录，Git 不存会员图片）。远程产物位于 `/root/autodl-fs/case-studio/experiments/testimonial-album-v1-20261107/validated-chat-first`。旧版预览保留供比较。
