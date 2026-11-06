# 体测成品与阶段审核

消费局部阶段分析结果，为每张合格体测图填充生成用的训练前/训练后标签，并生成单图、同朝向VS和完整三视图成品。原分析结论继续保留；生成标签不是已验证的拍摄日期。

- 明确位置/文字规则继续使用；已采用的AI判断及原有初步建议均标记 `（推断）`。
- 其余按现有稳定方向的支持分，或独立待审排序选择阶段，标记 `（待审）`。
- 生成层保留可靠批次一致性，先确保能以不同原图构成前后配对，再最大化所选阶段的支持分。必要时与某张图的单独最高分不同，会明确记录约束原因。
- 没有有效评分时不伪造置信度；仍给可审核的临时占位标签，分数为null。相同来源不能凑成一对VS。
- 推断和待审都进入审核返回；用户确认后去掉相应标记，保留旧版本和原始依据。

完整协议与流程：[工作流文档](../../docs/workflows/body-scan-delivery-review.md)。

## 远程运行

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_delivery create \
  --phase /path/to/body-scan-phase-regions/final-reviewed \
  --out /root/autodl-fs/case-studio/productions/body-review-example \
  --font /root/autodl-fs/case-studio/fonts/NotoSansSC.ttf \
  --settings /path/to/private-provider.json \
  --cache /path/to/review-ranking-cache --provider qwen
```

输出目录须不存在。`--settings`可省略；此时缺乏已有方向的图片明确标记为无评分占位，而不会声称来自最高置信度。模型排序用一张素材一个编号的原图/参考面板，并反向输入检查位置偏差。评分是主观支持分，不是统计准确率。

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

`private-inputs.json`仅留服务器，绑定原图、等比/展示图、上游结果与字体SHA。`audits/`保留待审模型排序与约束选择，均不通过文件服务公开。

每个`revisions/rNNNN`含：

- `result.json`：所有82/当前输入图片的标签、所有成品依赖、需要审核的图片和成品、未生成原因。
- `review.json`：包含所有推断/待审项及其影响的输出。
- `review-template.json`：带源版本和指纹的空修正请求。
- `index.html`：逐图选择前后、确认、导出/导入JSON，在线可提交后重新生成；本地仅导出。
- `outputs/{店}/{会员_组}/`：1080×1440 JPEG。每张输入保留一张单图；槽位完整才生成VS、三视图，未选中为VS代表的图仍保留单图。
- `products.zip`：成品、离线审核页和机器可读返回。

成品等比放入画布，不重裁人体，不新增人物拉伸；沿用批准展示图的既有处理和遮罩。本节点实现体测成品基础版式，不含其他生活照/感言/封面/报告模板及新贴纸库。

## 审核保障

以`base_revision`和`source_manifest_sha256`拒绝旧版本误覆盖；每个请求有`request_id`，同请求重试幂等。文件锁串行提交，临时目录生成完成后发布；失败保留当前版本。只有`confirm:true`的明确图片修改生效，支持部分确认和修正原规则标签。人工确认优先于AI，不自动翻转同组其他图。

依赖未变化的成品逐字节复用；修正不调用模型、不重跑标准化。旧版本可下载，当前版本指针只在完整生成后更新。

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s scripts/body_scan_delivery/tests -v
```

## 本轮结果

82张/16人全部赋阶段：29规则、31推断、22待审；输出82单图、39同朝向VS、9三视图，共130张。审核返回包括53张图片及88张关联成品。

27项测试、252个源文件不变和181个预览链接检查通过。真实素材副本中修正2图，只重生成4张关联成品，复用126张，模型调用为0。公网登录、预览、审核JSON和下载已验证。生产初版在 `productions/body-review-20261106-v1/revisions/r0001`，完整记录见[validation.json](validation.json)。
