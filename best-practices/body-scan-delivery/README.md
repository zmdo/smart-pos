# 体测成品生成最佳实践

2026-11-06 归档三种体测成品，来源为开发版 `6d6e20f3767a24ff7d2f26e82abbdf3586183316`。2026-11-07 加入用户确认的会员案例封面，来源为 `eaf9964b24ed85e52b70dfaae348ef54c572996c`。2026-11-07 正式确认报告对比成品 v5，来源为 `f1320dd32b3a2d3bec451ab9e2520058b15b3506`。2026-11-07 加入已确认的会员感言 v5，来源为 `4ae1d98aef16ca6a2ccf65b6927c23522d90a152`。2026-11-07 归档训练日常 v2（来源 `ba42b69`），并按用户要求加入生活照原图成品。同一目录下分别维护八类成品，保留已确认的照片、配对、版式和审核规则。

| 子目录 | 成品 | 绘图入口 |
| --- | --- | --- |
| [three_views](three_views/README.md) | 完整三视图，前后各正／侧／背 | `three_views/render.py:seamless_grid` |
| [view_comparison](view_comparison/README.md) | 各朝向训练前后 VS | `view_comparison/render.py:draw_vs` |
| [single_view](single_view/README.md) | 训练前／训练后的各朝向单图 | `single_view/render.py:draw_single` |
| [report_comparison](report_comparison/README.md) | 前后报告与九项五列表格；无报告图则紧凑表格 | `report_comparison/render.py:render` |
| [member_cover](member_cover/README.md) | 会员案例封面，专用正面双图与报告故事 | `member_cover/render.py:draw_cover` |
| [testimonial_album](testimonial_album/README.md) | 会员感言，固定红框、统一标题区、图片隐私遮盖 | `testimonial_album/render.py:render_page` |
| [training_daily](training_daily/README.md) | 无框训练日常；过窄截图仅去黑边、主体不明原图直出 | `training_daily/run.sh` |
| [life_photos](life_photos/README.md) | 已筛选生活照原文件直接输出 | `life_photos/run.sh` |

`scripts/body_scan_delivery/` 是本目录冻结的公共配对、配置、渲染调度、版本、审核和预览代码；体测图调度直接调用三个原有体测图子目录。`scripts/body_scan_contracts/` 只包含离线数据契约，不含模型客户端。封面目录另外消费现有任务和封面专用双图包，复用本目录的公共工具。这些子目录不能将其中一个子目录单独搬走；部署时复制整个 `body-scan-delivery`。

## 环境与独立性

在远程服务器运行，默认 Python 为 `/root/apps/non-grid-calibration/.venv/bin/python`；可用 `CASE_PYTHON` 指定。渲染使用 Pillow，SVG Logo 需要 CairoSVG 和系统 Cairo；会员感言的独立识别与隐私标注入口使用 NumPy、OpenCV、httpx；可选 API 适配器及其测试使用 FastAPI/httpx，已验证版本见 [requirements.verified.txt](requirements.verified.txt)。字体、Logo、照片、报告包和配置均由外部数据路径提供，不归档用户素材或密钥。

`run.sh` 清空外部 `PYTHONPATH`，固定到本快照目录，从 `manifest.json` 校验全部文件及 Python 模块集合。所有 `scripts.*` 导入均来自本目录，不依赖开发树或其他最佳实践。体测成品输入是已完成的阶段分类包，或既有成品任务；封面还需对应的专用双图包。训练日常消费动作证据包，生活照直接消费已有图片分类与原文件。成品排版不运行拆分、标准化、OCR 或大模型。感言的 `evidence.sh` / `annotate.sh` 和训练照的 `evidence.sh` 是另行显式运行的模型准备节点，不由渲染隐式调用。

```bash
./run.sh check
./run_tests.sh
```

## 一次生成三类成品

```bash
./run.sh create \
  --phase /path/to/classification \
  --out /path/to/delivery-new \
  --font /path/to/NotoSansSC.ttf \
  --presentation /path/to/presentation.json
```

`--phase` 必须为 `body-scan-phase-labels-v1` 包。报告沿用分类时绑定的独立报告包；不重新提取或改写数据。VS 配置可从 [presentation.example.json](view_comparison/presentation.example.json) 复制到数据目录后填写。本次确认的页眉声明由 `consent_text` 提供，地址可配置为 `UP 健身私教馆`，Logo 从用户图片目录 `logo/` 选择。

输出为 `current.json`、`revisions/rNNNN/`、私有输入绑定，以及版本内的图片、报告 HTML/JSON、审核页、审核 JSON 和 ZIP。输出目录必须全新；审核版本不可覆盖。缺少不同原图的前后配对时不生成该朝向 VS，六个槽位不齐时不生成完整三视图，原因写入 `gaps`；每张输入仍有单图。

```bash
./run.sh restyle --delivery /path/to/existing-delivery --out /path/to/delivery-restyled
./run.sh verify --delivery /path/to/delivery-new
./run.sh review --delivery /path/to/delivery-new --request /path/to/review-request.json
```

`restyle` 可额外传入新 `--presentation`。人工修正只更新明确确认的图片，保留旧版并重生成受影响成品；照片推断/待审状态始终保留在数据中。

## 单独生成某一类

```bash
./three_views/run.sh --delivery /path/to/existing-delivery --out /path/to/three-views-new
./view_comparison/run.sh --delivery /path/to/existing-delivery --out /path/to/vs-new
./single_view/run.sh --delivery /path/to/existing-delivery --out /path/to/singles-new
```

这些入口读取包含 `current.json` 和 `private-inputs.json` 的完整成品根目录，核验输入 SHA，使用该版本已选好的配对、照片、字体、报告和配置，仅重绘指定类型；不重新选择训练阶段，也不复制旧成品冒充重新绘制。三个入口可以用于独立验证和后续工作流节点。

类别输出包含 `outputs/`、`result.json`、`review.json`，协议为 `body-photo-category-v1`，不是完整生产版本；其中 `review_target` 指向来源任务和版本。审核修正仍提交原任务，再按新版本重新生成类别输出，不能把类别目录直接交给完整任务的 `review` 或 `verify`。类别本身不重复生成整套 HTML／ZIP，完整交付使用根入口。

## 会员案例封面

```bash
./member_cover/run.sh --delivery /path/to/existing-delivery \
  --cover-frames /path/to/approved-cover-frames --out /path/to/member-covers-new
```

`member_cover` 归档已确认的头胯构图封面、报告文案、Logo、用户文字配置和 HTML 展示，强制使用 v2 封面双图数据。它与三类体测图并列维护，通过独立入口运行；根 `create` / `restyle` 不会自动生成封面。用户可增加 `--config` 覆盖文案。准备双图请求及旧/新对比使用 `member_cover/prepare.sh`、`member_cover/compare.sh`；也可用根命令 `cover`、`cover-prepare`、`cover-compare`。

取景本身仍由 `body-scan-group-display-v3/run_cover.sh` 负责。两个节点通过数据连接，不互相导入代码；已有双图包时，成品包可独立排版。具体输入输出和审核关系见[封面说明](member_cover/README.md)。封面重绘及独立运行验证另存 [member_cover/validation.json](member_cover/validation.json)，保留以下原三类验收历史。

封面归档后的完整成品包共 57 项测试通过；在独立目录重新生成的 15 张封面及 `cases.json` 与获准版逐字节一致，自定义文案仅改变指定会员，原 130 张体测成品保持不变。

## 冻结与验收

`manifest.json` 记录来源提交、各文件 SHA、原文件 SHA 与拆分说明；[source-validation.json](source-validation.json) 保留用户已确认 v5 版式的验证记录。归档验收另见 [validation.json](validation.json)：在无开发代码的独立目录运行测试，并用三个类别入口从真实已批准数据重新绘制，与原成品逐字节比较。

2026-11-06 归档时 43 项测试通过。三个类别入口重新绘制 9 张完整三视图、39 张 VS 和 82 张单图，共 130 张，图片 SHA 与归档前完全一致，配对、标签和审核信息保持不变。根入口另行验证完整不可变版本，复用 130 张成品，核验 269 个绑定文件及 183 个预览链接；0 次模型调用。

服务器部署：`/root/apps/case-studio/best-practices/body-scan-delivery`。独立验证目录：`/root/autodl-fs/case-studio/experiments/body-scan-delivery-best-practice-20261106`。

更新时在开发目录实验，经用户确认后更新本快照、来源清单与验证记录。当前八类成品均有独立入口；根 `create` / `restyle` 仍负责原三类体测图，其余分支通过独立命令运行，尚未自动编排全部八类。

## 报告对比成品

```bash
./report_comparison/run.sh --tables TABLES --crops CROPS --font FONT \
  --width 2160 --out NEW_OUTPUT
```

当前权威版本为 `report-comparison-product-v5`。独立消费 `body-report-five-column-v1` 数据包和报告原图矩形取景，不调用模型或重新判断照片阶段。九项按有值展示，表格总高 860px；有报告图输出 2160×2700，无报告图输出 2160×1068 紧凑表格。根 `create` / `restyle` 尚不自动编排该入口，部署时复制整个成品包。

当前规则、缺失及审核约定见 [报告成品说明](report_comparison/README.md)。已确认效果与验证保存在 [validation-compact-v5.json](report_comparison/validation-compact-v5.json)，正式独立归档验证见 [validation-approved-v5.json](report_comparison/validation-approved-v5.json)。

## 会员感言成品

```bash
# 复用已完成主要内容和隐私复核的证据，无模型调用。
./testimonial_album/run.sh --input /path/to/私教会员案例项目 \
  --evidence /path/to/testimonial-layout-evidence --font /path/to/NotoSansSC.ttf \
  --config testimonial_album/presentation.example.json --out /path/to/new-testimonials
```

会员感言与其余五类成品并列维护，根 `create` / `restyle` 不自动编排它。固定 1080×1440、红边框，整个标题模块位置与大小统一；使用已确认的对称心形。每张截图只使用一次，主要内容完整、等比取景；不合格或缺素材返回原因。

只遮会员头像与人物照片，保留对话名字、文字和右侧教练头像。当前隐私政策与复核状态是渲染输入的硬性条件。HTML 提供已遮盖预览、下载及审核数据。独立的 `evidence.sh`、`annotate.sh` 可准备评分、内容框和隐私复核数据，详见[会员感言说明](testimonial_album/README.md)。提示词与客户端随该节点冻结，其他成品不依赖这些模型准备模块。

归档验证见 [testimonial_album/validation.json](testimonial_album/validation.json)，已确认版的历史效果验证保留在 [source-validation.json](testimonial_album/source-validation.json)。

会员感言归档后，完整成品包 87 项测试通过；在无开发树的隔离目录重绘 15 张感言成品，图片及结果共 69 个文件与获准版逐字节一致，0 次模型调用。其他五类成品及共享模块的 71 个文件保持不变。

## 训练日常与生活照

```bash
./training_daily/run.sh --input /path/to/私教会员案例项目 \
  --evidence /path/to/training-evidence --config training_daily/presentation.example.json \
  --out /path/to/new-training-products

./life_photos/run.sh --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json --out /path/to/new-lifestyle-products
```

训练照采用已确认的无框 v2：普通训练照保留动作、轻度美化；过窄截图仅去黑边，整块照片保持原像素；主体不明确则原文件直接输出。独立 `training_daily/evidence.sh` 可准备动作证据，本次归档复用已完成证据，不重新调用模型。归档同时修复模型失败记录缺少尺寸时中断批次的问题，失败素材正常返回待审。

生活照直接复用 `life_photo` 分类，不做对比、不判断阶段、不添加图片处理。所有筛选出的生活照保持原文件字节、格式和尺寸，无数量限制。两个分支分别提供 HTML 下载、成品清单和未生成原因。

两类独立验证分别见 [训练日常](training_daily/validation.json) 与 [生活照](life_photos/validation.json)；先前六类成品及共享契约保持不变。

归档后完整成品包共 108 项测试通过。独立目录中禁止模型/网络模块导入，重绘的 12 张训练成品及配套结果共 69 个文件与批准版逐字节一致；19 张生活照全部与原文件 SHA 一致，覆盖 12 位会员。先前六类成品及共享模块的 88 个文件保持不变。训练日常的 `sources.json` 仅因独立部署时配置文件路径不同而重新绑定，不计入逐字节对照。
