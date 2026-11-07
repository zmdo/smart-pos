# 生活照原图成品

2026-11-07 按用户要求新增，与其他成品一起维护。第一步分类筛选出的生活照直接作为独立成品，不做前后对比，不判断训练阶段，不裁剪、不缩放、不调色、不加框、不改遮挡。

## 输入与筛选

- 输入原始项目目录及 `classification-comparison.json`，复用已有 Qwen 分类；没有 Qwen 结果时才使用 DeepSeek，再回退旧分类。已有 Qwen 的非生活照结果不会被旧标签覆盖。
- 只读取 `xxx店/会员目录/图片`，排除参考模板、说明文件及 `reference_material`。保留同目录会员分组和原分类依据，不重新调用模型、识别人脸或猜训练前后。
- 所有 `life_photo` 图片均输出，没有评分门槛、取景规则或每会员数量限制。视频及不支持的文件格式返回未输出原因；同素材被不同资产记录选中时，各记录分别保留，不擅自删掉已筛选结果。
- 输出为逐字节复制的原文件，保留尺寸、格式、EXIF、原有贴纸与遮挡；图片的显示大小只由 HTML 页面响应式排版控制，不改下载的文件。

## 运行

从整个成品包根目录执行。该节点只需 Python 标准库及包内数据契约，不导入 Pillow、OpenCV 或模型客户端。

```bash
./life_photos/run.sh --input /path/to/私教会员案例项目 \
  --audit /path/to/classification-comparison.json \
  --out /path/to/new-lifestyle-products
```

也可通过根命令 `./run.sh life-photos ...`。输出目录必须全新；源文件缺失、越界或 SHA 与分类记录不同会报错，不能假装已完成输出。输入核验通过后才创建输出目录。

## 输出

- `index.html`：按门店/会员浏览独立生活照和下载原文件，支持按有无成品筛选。直接显示原图，不制作重新编码的缩略图；浏览器不支持的 TIFF、HEIC 等原始格式提供下载提示。
- 每会员目录：原图成品及 `result.json`，输出文件以资产编号命名并保留原扩展名，下载建议名使用原文件名，避免同名素材互相覆盖。
- `results.json` / `counts.json`：成品清单、原分类提供方与依据、来源及输出 SHA、实际输出数量，`processing_applied=false`。
- `review.json`：没有生活照或文件类型不支持的会员及原因；`sources.json` 和 `bundle.json` 绑定分类文件及原图，协议 `life-photo-originals-v1`。

根 `create` / `restyle` 不自动编排本节点。后续工作流直接消费本节点的数据包和文件，无需依赖体测标准化、体测报告或训练阶段分类。

全量验证见 [validation.json](validation.json)：复用 179 张门店素材的分类结果，筛选 19 张生活照，覆盖 12 位会员，19 个成品均与原文件 SHA 一致；6 组没有生活照。本机预览为工作区 `artifacts/life-photos-v1/validated/index.html`。
