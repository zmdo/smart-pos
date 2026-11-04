# 四向 · Portrait Studio

远程 GPU 人物素材处理网站。源代码只在服务器实现，监听 6006。
公开入口：https://u55868-7936f251bb5f.westd.seetacloud.com:8443

## 路径
- 应用：/root/apps/portrait-studio
- 独立 Python 3.11 环境：/root/apps/portrait-studio/.venv
- 模型、任务、结果和日志：/root/autodl-fs/portrait-studio
- 服务端配置（权限 0600）：/root/autodl-fs/portrait-studio/settings.json
- 原始素材和结果：数据目录 jobs/<id>/{input,output}
- 应用日志：数据目录 logs/{app,error}.log

## 启动、停止、检查
运行 /root/apps/portrait-studio/start.sh 启动或重启网站。
Supervisor 保证 SSH 断开后继续运行，进程异常退出自动重启。
服务器整机关机后，需要重新执行 start.sh；可将它配置到 AutoDL 的开机启动命令。
不修改机器既有服务和开机配置。

查看：
cd /root/apps/portrait-studio
.venv/bin/supervisorctl -c supervisord.conf status
.venv/bin/supervisorctl -c supervisord.conf stop portrait-studio
.venv/bin/python -m pytest tests -q

## 使用
1. 用访问码进入工作台，模型设置中可修改 API Key/Base URL/模型名。
2. 上传 ZIP/TAR/TAR.GZ。目录可以嵌套，每个直接父目录独立分组。
3. 设置单张尺寸、留白、拼接间距、背景色、检测阈值、遮罩图片与覆盖倍率。
4. 实时查看任务状态。网页关闭后任务继续，刷新可恢复。
5. 下载拼图 PNG 或全部结果 ZIP；metadata.json 记录人物、面部坐标及处理状态。
6. 任务记录中可删除上传素材和所有结果。默认保留直到手动删除。

## 真实处理流程
- YOLO11n（COCO person 类）检测人物；无人立即跳过该图片，不调用视觉 API。
- 多人图片记录所有检测框，选择最大人物，以其框提示 Meta 官方 SAM 2.1 Base+。
- SAM 2 分割精确人物区域，保存分割掩码与全分辨率人物 bbox。
- DeepSeek V4.1 Flash（官方模型 ID deepseek-flash）读取人物裁切图并分类朝向。
- 前、左、右先跑 CPU 人脸检测器 YuNet（OpenCV DNN，0.75 阈值，脸中心必须落在人物掩码上）。
  命中就用它给的面部框；未命中（侧脸、遮挡、小人脸）才让视觉模型定位面部。
  背面严格不请求面部定位，face_bbox 为 null。记录里 face_source 标明 detector / vision。
- 面部框交给 SAM 2 以「框 + 中心点」再分割，掩码 bbox 裁到检测框 1.15 倍内，
  避免 SAM 2 顺着头发的边界扩到整个头部；裁掉太多或不可信时退回原框。
- 左右指朝向图像左/右边缘，不是人物的解剖学左右。
- 朝向 unknown 不参与拼接；开启遮罩但未定位面部的图片也不导出，并标记待检查。
- 保留原图背景，以 SAM bbox 中心做等比变换，人物完整适配固定画布，不拉伸。
- 面部遮罩：默认**不缩放**，遮罩图按原始像素贴到面部框中心（内置默认遮罩为 192×192）；
  勾选“按脸部大小缩放遮罩图”后才把遮罩图缩放到面部框 × 覆盖倍率。透明遮罩底部会补实色。
  两条路径都记录在 metadata 的 `transform.mask_mode`（native / scaled）。
- 每个目录按前/后/左/右固定四列。同向多图按文件名自然顺序（img2 在 img10 前）占用后续行。
- 缺失朝向留空，单页限制内存，很多图片自动分多个拼图。
- 所有坐标均以 EXIF 纠正后的原图像素为基准，xyxy 格式。
- 分割掩码最大边 2048，其实际分辨率写入 segmentation_size。面部掩码另存 face-*.png。
- 一张图失败不会阻止其他图片。API 鉴权、余额、持续超时错误终止任务并保留已完成结果。
- 每个任务最多 3 张图并发走视觉 API，GPU 推理仍串行，日志与 job.json 由锁保护。
- 不执行身份识别。一个目录应放同一主体的不同朝向；不自动关联多人身份。

## 显存与耗时（RTX 4090 48GB，实测 38 张）
- 服务常驻显存 1589 MiB（YOLO11n + SAM 2.1 Base+ + YuNet），峰值也是 1589 MiB；
  GPU 利用率峰值 16%，瓶颈在视觉 API 而不是 GPU。
- 38 张图端到端约 30 秒（3 并发视觉调用 + CPU 人脸检测），单张人脸检测约 50 ms。
- 若换 SAM 2.1 Large 权重（+575 MB）显存预计 2.2 GB 以内，未实测。

## 限制
压缩包 <= 1GB；解压声明总大小 <= 2GB；<= 500 图片、10000 条目；
单图 <= 64MB / 3000 万像素；输出单边 128–2048px；任务队列最多 4 项。
支持 JPG/JPEG/PNG/WebP/BMP。其他文件忽略，不执行。
拒绝绝对路径、路径穿越、符号链接、设备文件、重复文件及加密 ZIP。
无 UTF-8 标记的 ZIP 条目名会按 UTF-8/GBK/Big5 还原，兼容 Windows 中文压缩包。
GPU 串行任务避免显存竞争。服务重启会把未结束任务标记中断，不重复计费调用。

## 凭证与网络
访问码经常量时间比较，浏览器获得 HttpOnly/SameSite 会话 Cookie。
API Key 只保存于服务端受限文件，不写日志，不返回前端，不写入导出元数据。
人物裁切图通过 HTTPS 发给所配置的 DeepSeek 视觉服务。
Base URL 限制 HTTPS 公网域名。
当前 6008 未占用，未运行开发服务器。

## 模型来源
https://github.com/facebookresearch/sam2
https://github.com/ultralytics/ultralytics
https://api-docs.deepseek.com/guides/vision/
SAM 2 上游快照记录于 MODEL_VERSIONS.txt。YOLO11n 使用上游预训练权重。
实际依赖版本保存在 requirements.lock.txt。


## 2026-11-04 公网代理登录修复
AutoDL 的代理转发会移除 Host 中的公网 :8443 端口。来源校验现通过 origins.py
显式识别公网入口，不依赖任意 X-Forwarded-Host。直接同源请求仍正常支持，
其他来源、错误端口、错误协议及无效 Origin 仍被拒绝。
若迁移域名，可设置 PORTRAIT_PUBLIC_ORIGINS 为逗号分隔的完整公网 Origin。

新增 14 项来源与代理登录回归用例，总计 33 项通过；
已在实际内置浏览器中提交登录表单并验证工作台正常显示。


## 2026-11-04 接手复查与增强
复查：公网入口登录、上传 6 MB 压缩包、38 张图全流程、结果 ZIP 下载均通过。
改进（测试 33 -> 38 项全部通过）：

1. 面部改用 SAM 2 分割。视觉模型只给面部框，SAM 2 以框 + 中心点再分割，
   用掩码 bbox 贴合遮罩；掩码另存 face-*.png，导出 ZIP 一并提供。
   新增并发下 SAM 2 图像 embedding 被其他线程覆盖的竞态修复（分割前重新 set_image），
   修复前面部分图拿不到掩码，修复后 30 张有面部图中 28 张用上 SAM 2 掩码。
2. 视觉 API 改为 3 并发，GPU 推理仍串行（INFER_LOCK）。
   38 张图端到端 39-40 秒（此前单线程同批约 3 分半）。
3. 单张图的 JSON 解析失败不再中断整个任务；鉴权、余额、持续超时仍立即终止。
4. ZIP 文件名编码回退（UTF-8/GBK/Big5/Shift-JIS），兼容中文 Windows 压缩包。
5. 文件按自然顺序排序（img2 在 img10 前），同一朝向内顺序稳定。
6. 前端：支持 ?job=<id> 深链直达任务；修复尺寸输入框标签换行、
   拼图图片被压成 640px 高导致看不清的问题；记录表标注 SAM 2 面部来源。
7. 回归用例新增 GBK 文件名、自然排序、SAM 2 面部框生效、SAM 2 失败回退、
   掩码被拒时记录原因，共 38 项。

已知取舍：面部掩码取面部/头部分割框放大 1.35 倍，特写人像上遮罩会覆盖整个头部，
这是遮罩倍率参数（默认 1.35）决定的效果，可在“更多设置”里调小。


## 2026-11-04 加入真实人脸检测器（YuNet）
动机：面部框只靠视觉模型估算，缺少像素级依据，且侧脸会漂。
做法：新增 face.py（cv2.FaceDetectorYN，模型 yunet_2023mar.onnx，232 KB），
在人物分割之后、视觉模型之前跑；脸中心必须落在 SAM 2 人物掩码上才采纳，
未命中才回落视觉模型。检出的框交给 SAM 2 再分割，掩码 bbox 裁到检测框 1.15 倍内。

实测（同一批 38 张图，30 张有脸）：
- 人脸来源：检测器 28 张，视觉模型 2 张（其中 1 张检测器被人物掩码校验拒掉）。
- 面部框面积占整图比例：中位数 0.0720 -> 0.0636（约 -12%），均值 -16%，遮罩更贴脸。
- 端到端 40 秒 -> 30 秒（少了一次视觉调用）；CPU 人脸检测 30 张共 1.6 秒。
- 单元测试 38 -> 42 项通过。
- 显存常驻/峰值 1589 MiB，GPU 利用率峰值 16%。

仍保留的短板：侧脸（b15 类）检测器虽能出框但偏松，视觉模型给的框在侧脸上会偏上；
极端遮挡仍可能两侧都失败，此时图片标记待检查而不是乱贴。


## 2026-11-04 遮罩尺寸模式
需求：遮罩图片默认保持原始大小、不缩放，中心对齐面部框；是否缩放做成可配置项。
- 新增选项 `mask_scaled`（默认 false）。false = 原始像素贴图，中心对齐 face 框中心；
  true = 旧行为，缩放到 face 框 × mask_scale。
- 内置默认遮罩在 native 模式下固定 192×192；上传的自定义图按自身像素大小贴。
- 前端新增开关“按脸部大小缩放遮罩图”，关闭时“遮罩覆盖倍率”输入自动禁用。
- 实测 38 张图：30 张 native 模式，耗时 29.3 秒；单元测试 42 -> 44 项通过。
