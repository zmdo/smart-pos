# 体测成品与阶段审核

消费训练阶段分类节点已经补齐的标签包，生成单图、同朝向 VS、完整三视图，并附带独立报告节点的标准 HTML 对比表和 JSON。此节点不调用模型、不重新判断阶段、不读取原始体检文档。

推断/待审标签按输入原样渲染并进入审核返回；用户确认后移除对应标记，保留旧版本，仅重生成受影响的成品。

完整协议与流程：[工作流文档](../../docs/workflows/body-scan-delivery-review.md)。

## 远程运行

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_delivery create \
  --phase /path/to/phase-run/classification \
  --out /root/autodl-fs/case-studio/productions/body-review-example \
  --font /root/autodl-fs/case-studio/fonts/NotoSansSC.ttf
```

输出目录须不存在。阶段输入必须为 `body-scan-phase-labels-v1`，旧分析目录或未补齐标签会被拒绝。报告从分类包的绑定读取；可用 `--reports` 提供相同指纹的报告包。成品入口不再接受 `--settings/--cache/--provider`。

审核后重生成也可通过命令行执行：

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_delivery review \
  --delivery /root/autodl-fs/case-studio/productions/body-review-example \
  --request /path/to/review-corrections.json
```

## 服务入口

集成到现有6008 Case Studio，沿用工作台访问码和登录Cookie：

- `/review`：任务列表/登录。
- `GET /api/productions`：生成任务。
- `GET /api/productions/{id}`：完整生成结果、审核项、下载与预览地址。
- `POST /api/productions/{id}/review`：提交部分修正并返回新版本。
- `/api/productions/{id}/files/r0001/...`：受登录保护的版本文件，禁止访问私有输入与模型审计缓存。

`CASE_DELIVERIES`可设置输出根目录。生成节点的`create()`供上游调度调用；现有ZIP上传体检尚未自动串起全套标准化节点。本次接通的是已批准阶段结果到体测成品及人工审核重生成。

## 文件

`private-inputs.json`仅留服务器，绑定原图、等比/展示图、上游结果与字体SHA。模型排序审计已移至分类节点的 `audits/`；成品节点不产生模型审计。

每个`revisions/rNNNN`含：

- `result.json`：所有82/当前输入图片的标签、所有成品依赖、需要审核的图片和成品、未生成原因。
- `review.json`：包含所有推断/待审项及其影响的输出。
- `review-template.json`：带源版本和指纹的空修正请求。
- `index.html`：逐图选择前后、确认、导出/导入JSON，在线可提交后重新生成；本地仅导出。
- `outputs/{店}/{会员_组}/`：单图为 1080×1440 JPEG，VS 为固定宽度、可变高度 JPEG；三视图为六张已批准展示图按原尺寸无缝拼接的 PNG。每张输入保留一张单图；槽位完整才生成VS、三视图，未选中为VS代表的图仍保留单图。
- `reports/`：标准报告 HTML、JSON 和覆盖清单，来源包指纹及表单待审项记录于 `result.report_comparison`。
- `products.zip`：成品、表单对比、离线审核页和机器可读返回。

成品等比放入画布，不重裁人体，不新增人物拉伸；沿用批准展示图的既有处理和遮罩。本节点实现体测成品基础版式，不含其他生活照/感言/封面/报告图片模板及新贴纸库。

## 审核保障

以`base_revision`和`source_manifest_sha256`拒绝旧版本误覆盖；每个请求有`request_id`，同请求重试幂等。文件锁串行提交，临时目录生成完成后发布；失败保留当前版本。只有`confirm:true`的明确图片修改生效，支持部分确认和修正原规则标签。人工确认优先于AI，不自动翻转同组其他图。

依赖未变化的成品逐字节复用；修正不调用模型、不重跑标准化。旧版本可下载，当前版本指针只在完整生成后更新。

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s scripts/body_scan_delivery/tests -v
```

## 本轮结果

82张/16人全部赋阶段：29规则、31推断、22待审；输出82单图、39同朝向VS、9三视图，共130张。审核返回包括53张图片及88张关联成品。

27项测试、252个源文件不变和181个预览链接检查通过。真实素材副本中修正2图，只重生成4张关联成品，复用126张，模型调用为0。公网登录、预览、审核JSON和下载已验证。生产初版在 `productions/body-review-20261106-v1/revisions/r0001`，完整记录见[validation.json](validation.json)。

## 三视图无缝版 v2

完整三视图现在直接将六张同规格展示图按三列两行拼接，不加文字、红条、留白，不裁切或拉伸。上排训练前、下排训练后；每排依次正面、侧面、背面。输出为无损 PNG，宽高为单张展示图的三倍宽、两倍高。推断/待审信息继续保留在结果 JSON 和审核页面，三视图图片本身不绘制标签。该轮只修改三视图；VS 后续更新见下文。

只重绘已有成品，不运行上游流程：

```bash
python -m scripts.body_scan_delivery.restyle --delivery /path/to/existing-delivery --out /path/to/new-delivery
```

输出到全新目录，复用既有图片、标签和审核状态。旧三视图渲染缓存失效；单图与 VS 可以原样复用。新版三视图只改变审核标记时可复用图片，因为标签已与其像素分离。核验器会逐像素检查六个区域与输入帧一致。


## 同朝向参考版 v3

参照用户提供的红白版式：品牌 logo、居中悬浮标题、两图无缝并排、中央 VS、Before/After 与箭头、姓氏称谓及地址、体测单变化胶囊。图片保留推断/待审标记，结果 JSON 与审核队列继续返回不确定项。三视图与单图不受此次改版影响。

宽度默认 1080，可配置为 540–4320。两张照片统一显示高度 `H = W / (w1/h1 + w2/h2)`，分别等比缩放，整数像素舍入误差不超过一像素；不裁剪、不新增人物拉伸。总高度为照片高度加按宽度缩放的页眉页脚，不再固定 1440。标题、VS、阶段胶囊是参照图要求的覆盖元素。

复制 [presentation.example.json](presentation.example.json) 到数据目录后填写：

- `image_root`：用户图片根目录。自动寻找其 `logo` 目录里的 PNG/JPG/WebP；只有一个文件时自动选择，多个时必须用 `logo_file` 指定相对路径。不会从参考成品抠取 logo。缺少时使用 `brand_name` 文字占位，并在返回中标记。
- `width`：成品宽度；`metrics`：页脚项目，支持 waist/hip/arm/chest/weight/fat，最多六项、每行三项。
- `address`：默认地址；`stores[店名].address`：按门店配置；`members[店名/会员].address` 可单独覆盖。未配置仅显示门店名称。
- `members[店名/会员].gender`：来自报告明确文字或用户资料的“男/女”；或用 `honorific` 明确指定“先生/女士/会员”，复姓及特殊姓名可用 `surname`。不从人物外貌、名字猜性别。缺少依据用“某会员”。报告数据将来提供明确 `gender` 字段时也可直接读取。
- `members[店名/会员].report_id`：同名同店存在多份报告时明确选用哪份；否则仅自动使用唯一一份可用报告。
- `consent_text`：可选已确认声明，默认空，不自动生成“经本人同意”等声明。

```bash
python -m scripts.body_scan_delivery create \
  --phase /path/to/approved-classification \
  --out /path/to/new-delivery \
  --font /path/to/NotoSansSC.ttf \
  --presentation /path/to/presentation.json \
  --reuse-renders /path/to/previous-delivery/revisions/r0001
```

只消费已绑定的报告 JSON，不访问原始 PDF/DOCX、不重新 OCR 或判断训练前后。报告须姓名、门店完全匹配、转录已核验且时间顺序无问题；指标须 `usable`，变化值再次校验为后减前。多份报告未选定、单元格缺失或不可靠时显示“未提供”，不写成 0。双侧数值分别保留在返回中；变化相同时合并显示，不同时按原表顺序显示两值，不臆定左右侧。报告日期不视为照片拍摄日期。

`output.presentation` 返回展示文字、选中报告与原文件 SHA、各指标前后值/变化/页码、数据缺失原因和未核实的照片关联状态。品牌、地址、称谓、指标和 logo SHA 均进入 VS 缓存键。配置文件和 logo 绑定到本次生成；修改配置时先复制为新配置文件，再新建版本，可用 `restyle --presentation ...`，不原地替换已发布成品。`restyle` 沿用原任务已绑定报告，不给旧任务偷偷补入不同报告；旧任务没有报告时应使用已绑定报告的分类包通过 `create` 生成新任务。

本轮远程验证：82 张照片、16 位会员，重绘 39 张 VS，91 张单图/三视图逐字节复用；41 项测试通过。11 张 VS 有可用报告指标，其余明确显示未提供。全部成品宽 1080，高度 1277–1952。预览收录 9 个完整三视图案例的 27 张 VS。当前输入未发现 logo，未配置完整地址，分别使用品牌文字和门店名称占位。详见 [validation-reference-v3.json](validation-reference-v3.json)。
