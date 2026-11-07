# UP 会员案例工作台

基于六个冻结处理节点、八类成品的全新网站，替代旧上传体检网站。三个页面为首页、历史记录、设置；主工作流为上传 ZIP → 预处理 → 五部分人工审核 → 成品生成与下载。

完整设计见 [重构方案](../docs/design/case-studio-workflow-rebuild/README.md)，部署及实际验收见同目录 `IMPLEMENTATION.md`。此前 `tools/` 实验实现已经删除，历史版本保留在 Git；新网站不导入它们。

审核增强见 [设计与验证](../docs/design/case-studio-review-v2/README.md)：身份自动补全、分区手动更新、封面 AI 文案与提示词模板、浏览器预览缓存。

## 部署

- 服务代码：`/root/apps/case-studio`，端口 6008。
- GPU 算法：同目录 `best-practices/`；报告矩形取景使用 `scripts/report_photo_crop` 已确认 v3 实现。
- Python：`/root/apps/non-grid-calibration/.venv/bin/python`，沿用已有模型环境。
- 数据：`/root/autodl-fs/case-studio/website/`，与既有 `batches/`、`experiments/` 分开。
- 设置：`website/settings.json`（0600）。首次启动读取旧访问码和已有 Qwen 配置，API 不返回访问码与 Key。
- 公网：[会员案例工作台](https://uu55868-793909b1c426.weste.seetacloud.com:8443/)。`STUDIO_PUBLIC_URL` 可覆盖。

```sh
cd /root/apps/case-studio
export STUDIO_REPO=/root/apps/case-studio
bash start.sh
# 托管时使用 supervisord.conf；仅运行一个 HTTP worker 和一条 GPU 队列。
```

本机仅开发代码，图片处理、模型调用和验证均在服务器运行。

## 模块与数据

`app.py` 仅承载会话、API 和静态入口。`studio/intake.py` 安全解包并限定门店；`workflow.py` 调用独立子进程，记录节点状态；`classification.py` 保留已验证的完整分类提示词；`rendering.py` 将审核数据适配到冻结绘图函数；`review.py` 管理审核与成品版本；`store.py` 使用 SQLite WAL 保存任务与会话。

每批数据分为原始 ZIP、各节点输出、模型配置快照、审核快照、预览、正式成品版本、下载包。审核修改不写回原图或模型证据；正式版本不可变，旧版本可继续下载。预览和重新生成不调用模型。

`identity.py` 在预处理末尾读取报告和文档的身份依据，性别自动采用阈值默认 0.90（设置页可调）；无直接字段时仅允许有文字依据的指代推理，不使用人物外貌或姓名猜测。教练必须有明确角色标记。界面显示来源、原文、参考置信度与未采用原因；置信度为模型参考值，并非实测正确率。人工填写和人工清空优先。旧批次可运行 `python -m studio.identity backfill <任务ID>` 补全，版本冲突时放弃写入。

三个“更新展示效果”按钮分别更新 VS、封面、表格。文字与取景仍自动保存，只有显式更新或首次缺少预览时才绘图。服务端按关联内容缓存，浏览器通过 IndexedDB 缓存成品图片（最多 160 MB）；切换朝向与刷新可复用，退出清空。浏览器禁止持久存储时退回内存缓存。

`copywriter.py` 只为选择的封面字段生成文案。提示词模板保存于 `website/cover-templates.json`，模型只收到勾选资料；生成结果回填并保存后，仍需点击封面的更新按钮查看图片。生成前后检查审核版本，避免覆盖较新的修改。

封面从既有校正几何及尺度回到原图，使用正面双图专用取景。每张手工框固定 500:478；后端验证采样支持完全位于原图有效范围，直接从原图进行一次组合变换。

未确认照片继续带原推断/待审标记，在 ZIP 的 `审核说明.json` 列出；成品不印该标记。素材不足、不符合规则与运行失败分别保留原因，不伪造成完整输出。旧批次可从历史记录导入新工作流。

## 验证与故障恢复

```sh
cd /root/apps/case-studio
STUDIO_REPO=$PWD OPENBLAS_NUM_THREADS=1 /root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s tests -v
```

失败任务在历史记录重试；完成节点复用，失败节点使用新目录。服务重启把中断任务标为可重试，不会自动重复请求模型。节点日志位于 `website/jobs/<任务>/nodes/*.log`，异常详情位于 `last-error.json`。修改文字过长或手工框越界会拒绝预览；修正后可再次预览。

上传最大 4 GB，解包最大 12 GB、10000 个条目、单文件 512 MB；拒绝路径穿越、符号链接和加密 ZIP。仅扫描 `xxx店/会员目录`，排除模板与说明。Logo 可在设置上传，也可随素材放入 `logo/` 目录。会话有效期 7 天，所有媒体与下载均需登录。

ZIP 文件名支持有标记的 UTF-8、无标记的 UTF-8 及 GBK/GB18030。无法识别时给出编码错误；解码后的路径仍执行安全与重名检查。已修复部分 macOS 压缩包中文目录变乱码、误报缺少门店的情况，见 [ZIP 编码验证](../docs/design/case-studio-review-v2/ZIP_ENCODING.md)。

画面固定宽度与预览布局跟随各最佳实践：VS 等比缩放、三视图无缝、封面 1080×1440、报告默认原图宽度两倍、感言固定相册版式、训练照与生活照保留各自的批准规则。
