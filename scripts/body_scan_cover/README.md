# 会员案例封面 · 独立样式实验 v2

按用户参考图制作 1080×1440 封面，先生成图片与离线 HTML 供微调，不修改已归档的三类体测成品最佳实践，不重新跑标准化或训练阶段判断。

## 当前版式

- 米白底、红色大标题及下划线；右上固定“会员案例”，不开放替换该标签。
- 棕色副标题、深色成果标题。减重由已核验 kg 差值换算为斤；体脂变化明确使用百分点，不以体重增长推断增肌。
- 对比图片固定为左右各 500×478，左训练前、右训练后，红色外框下是 Logo 与地址栏。
- 下方为报告数据支持的故事文案，教练与指标可以红色强调。原始数字、单位、数据来源和用户覆盖字段保存在 JSON 中。

## 取景

使用既有训练前后标签，优先选择正面全身照，其次头部完整的正面照，再按原有配对与标签优先级选择。要求两张不同原图；不以侧面、同图复制来填补缺失正面配对。

封面专用双图由同组展示最佳实践的 `run_cover.sh` 输出：从原图复用已确认几何、共同人物尺度和肩部坐标，仅正面前后两张图求共同取景框。跳过旧同组六图裁剪及纵向展示拉伸，允许恢复旧取景窗口之外的有效原像素。新取景只等比缩放；保留头部区域、尽量展示腹部及大腿，不以人体宽度决定放大倍数。

原图可用区域和头部保护冲突时，允许两图取景框纵向偏移，仍共用宽高和缩放，并独立标记取景待审。阶段标签、置信度、推断/待审与人审信息从既有结果整行继承，新增模型调用为 0。数据合同及全部边界规则见[封面工作流](../../docs/workflows/member-cover.md)。

`--cover-frames` 是默认必需输入，生成器只校验并排版现成双图，不再自行取景。`--legacy-display-crop` 仅用于旧版回归对照；旧取景函数保留但不作为默认路径。

## 数据与文案

报告取自成品任务已绑定的独立报告包，按同店同名和选定报告 ID 解析。只消费 `usable` 的单值指标并核对前后差值；缺少已核验报告的会员生成无数字封面，HTML 中提示补充资料。

教练优先由用户配置提供，否则从该报告已有的文本提取结果读取明确“教练：”一行；转录记录的源 SHA、门店及会员必须与报告一致。不从文件夹前缀猜教练。这里读取已有 JSON/文本，不重新解析原始 PDF/DOCX，不调用 OCR。

只有报告填写天数与日期差一致时才展示具体天数；不一致则使用通用副标题，原警告保留在封面说明中。照片的实际拍摄日期仍未据此确认。

自动文案采用数据驱动的叙述模板，而不是大模型临场补事实。没有教练时用记录与阶段变化组织故事；不补造年龄、病史、训练频率、情绪或生活经历。有教练时引用报告教练姓名。用户可直接提供更符合品牌语气的完整文字。

## 运行与用户文字入口

所有渲染在远程服务器执行：

```bash
cd /root/apps/case-studio
# 1. 只选择素材并引用现有阶段结果，不做图像处理。
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_cover.prepare \
  --delivery /path/to/approved-delivery --out /path/to/NEW-request.json
# 2. 独立最佳实践节点：输出封面专用前、后图和无标注拼接图。
bash best-practices/body-scan-group-display-v3/run_cover.sh \
  --request /path/to/NEW-request.json --out /path/to/NEW-cover-frames
# 3. 只排版。可增加 --config /path/to/cover-overrides.json。
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_cover \
  --delivery /path/to/approved-delivery --cover-frames /path/to/NEW-cover-frames \
  --out /path/to/NEW-cover-preview
# 可选：为同一配对生成旧/新 HTML 对照页。
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_cover.compare \
  --previous /path/to/old-cover-preview --current /path/to/NEW-cover-preview \
  --frames /path/to/NEW-cover-frames
```

`--config` 可省略。输入为包含 `current.json`、`private-inputs.json` 的完整成品根目录；输出必须为新目录，已有图片不覆盖。

配置参考 [cover.example.json](cover.example.json)。`defaults` 提供全局值，`members[店名/会员名]` 覆盖单人值，支持：

| 字段 | 用途 |
| --- | --- |
| `title` | 红色下划线主标题，最多 12 字符，过长无法适配时明确报错 |
| `subtitle` | 棕色副标题 |
| `headline` | 深色成果标题 |
| `story` | 完整替换底部正文，最多 280 字符 |
| `highlights` | 要标红的正文片段列表，按原文字面匹配 |
| `coach` | 教练姓名；空字符串表示不提教练 |
| `address` | 地址栏文字 |
| `brand_name` | 没有 Logo 时使用的品牌文字 |

页面右侧可以编辑这些常用文字，导出该会员的 JSON 配置后，用 `--config` 重新生成；页面明确提示当前预览不会因导出而自动改变。用户自定义的内容记录为 `user_override`，不会修改报告或阶段标签。

## 输出与审核

`index.html`、`gallery.css/js`、`media/*.jpg`、`cases.json` 提供离线预览、筛选、放大和单图下载；`private-inputs.json` 仅留服务器。`cases.json` 返回照片 ID、训练阶段审核状态、取景矩形、等比缩放系数、报告/教练来源、自动或自定义文案、异常说明和未生成项。

照片阶段修正仍返回来源成品任务的 `review_target`；本轮不新建另一个阶段审核协议。生成完整案例封面并不等于原有推断/待审标签已获人工确认。

本轮预览：15 位会员，其中 4 位有已核验报告及教练；1 位缺少不同原图的正面前后配对。验证记录见 [validation.json](validation.json)。

71 项测试通过；310 个输入绑定文件核验无变化；30 张封面专用图均为有效原像素矩形、等比缩放，并原样继承阶段行。14 组保持共同肩部基准，何彦霖因原图顶部缺失冲突保留垂直偏移并标记取景待审。原三类成品的 130 张图片 SHA 未变；旧封面路径重新渲染 15 张与 v1 逐字节一致。15 组新旧效果已逐组查看，HTML 选择、筛选、放大及文字配置导出通过离线 jsdom 检查。

远程：`/root/autodl-fs/case-studio/experiments/body-scan-cover-pair-v2-20261107/validated-v2`。本机：`/Users/zhangming/Projects/FP16-Speed/artifacts/body-scan-cover-pair-v2/validated-v2/index.html`；同目录 `comparison.html` 提供新旧封面对比及封面专用双图下载。默认潘艺文；缺报告的案例可在“待补报告”分类查看。v1 和本轮中间版本仍保留，未覆盖。
