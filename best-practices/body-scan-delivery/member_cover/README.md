# 会员案例封面

2026-11-07 归档用户确认的 `body-member-cover-v3`，来源提交 `eaf9964b24ed85e52b70dfaae348ef54c572996c`。与完整三视图、朝向 VS、阶段单图并列，绘图入口为 [render.py](render.py) 的 `draw_cover`；输出效果与获准版本相同。

本目录包含封面排版、报告文案、用户文字覆盖、双图数据适配、HTML 展示及测试。部署时复制整个 `body-scan-delivery`，共享字体、Logo、报告和成品契约代码只从本快照导入，不依赖开发目录。

## 直接生成封面

```bash
./run.sh \
  --delivery /path/to/existing-delivery \
  --cover-frames /path/to/approved-cover-frames \
  --out /path/to/NEW-member-covers
```

`--delivery` 指向包含 `current.json`、`private-inputs.json` 的完整成品任务；`--cover-frames` 必须为 `body-scan-cover-frames-v2` 包，与同一阶段结果 SHA 和相同的前后正面素材对应。默认生成该任务所有可用会员封面，缺配对的原因写入 `gaps`。输出必须是新目录。

本入口强制接收已完成取景的双图，不暴露旧六图成品再裁剪的回退选项，不接受旧版允许肩线错位的双图包。内部保留部分旧工具和测试作为依赖及回归参照，旧入口不属于本次推荐方案。

## 尚未准备封面双图时

```bash
# 1. 读取现有阶段标签，按素材 ID 选择正面前后；只准备数据请求。
./prepare.sh --delivery /path/to/existing-delivery --out /path/to/NEW-request.json
# 2. 上游同组展示节点生成专用双图；只通过 JSON 连接，不导入上游代码。
bash ../../body-scan-group-display-v3/run_cover.sh \
  --request /path/to/NEW-request.json --out /path/to/NEW-cover-frames
# 3. 回到本目录运行封面排版。
./run.sh --delivery /path/to/existing-delivery \
  --cover-frames /path/to/NEW-cover-frames --out /path/to/NEW-member-covers
```

上游取景规则仍由同组展示最佳实践维护：以头部到胯部为目标，共用肩部基准和等比缩放；缺头配对统一局部取景；窄图无法容纳头胯时标记限制。本目录消费结果及其审核说明，不重新检测人物、校正镜头或判断训练阶段。已有双图包时无需安装或调用上游运行代码。

## 版式及文案

固定画布 1080×1440，左右双图各 500×478，右上“会员案例”，红色主标题与下划线、棕色副标题、成果标题、Logo／地址栏和底部故事。

报告及教练信息复用任务绑定的已核验结构化数据和现有文本；不重跑 OCR，不调用模型。缺少报告时不补数字成果，日期天数冲突时不写具体天数。自动故事不补造个人经历，用户可以提供自己的文字。

添加 `--config /path/to/cover-config.json` 可覆盖标题、副标题、成果标题、正文、强调文字、教练、地址和品牌。格式见 [cover.example.json](cover.example.json)，优先级为自动值 → `defaults` → `members[店名/会员名]`。HTML 编辑区可导出同一格式，再运行本入口即可更新文案；复用双图包即可，不需重做取景或分类。

## 输出与审核

输出 `media/*.jpg`、`cases.json`、`index.html`、`gallery.css/js` 和服务器私有的 `private-inputs.json`。HTML 支持会员选择、报告筛选、放大、下载和文字配置导出。对外分发预览时不复制 `private-inputs.json`。

`cases.json` 保留每张素材的完整阶段行、置信度、推断/待审、人审信息和来源 `review_target`；取景待审、缺头配对和窄图限制另行记录。阶段修正仍返回原任务，新阶段版本应重新准备双图请求，不混用旧包。

这是一类独立成品及其预览，不是根入口的完整版本目录，不能将本输出直接交给根入口的 `review` / `verify`。原 `create` / `restyle` 仍生成三类体测成品；封面单独接收双图包。

可选的新旧对比（必须为相同素材及标签）：

```bash
./compare.sh --previous /path/to/old-cover-preview \
  --current /path/to/NEW-member-covers --frames /path/to/approved-cover-frames
```

来源效果验证见 [source-validation.json](source-validation.json)，归档后的独立运行与像素一致性验证见 [validation.json](validation.json)。所有图像处理在远程执行。

归档验收：57 项测试通过；独立目录重新生成 15 张封面，与获准 v3 的图片及 `cases.json` 逐字节一致；自定义文案只改变指定会员，其他 14 张一致，原有 130 张体测成品未变。
