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
- `outputs/{店}/{会员_组}/`：1080×1440 JPEG。每张输入保留一张单图；槽位完整才生成VS、三视图，未选中为VS代表的图仍保留单图。
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
