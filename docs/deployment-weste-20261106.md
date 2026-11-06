# 西区算力服务器迁移（2026-11-06）

当前 SSH 入口为 `root@connect.weste.seetacloud.com`，端口 `44023`。凭据沿用私有配置，不写入仓库。部署脚本现要求从环境变量 `DEPLOY_PORT` 读取端口，避免继续连接已到期的旧实例；`DEPLOY_HOST`、`DEPLOY_HOSTKEY`、`DEPLOY_PW` 仍由部署环境提供。

| 服务 | 本机端口 | 当前公网入口 |
| --- | --- | --- |
| 肖像四向拼图 | 6006 | https://u55868-793909b1c426.weste.seetacloud.com:8443 |
| 会员案例工作台 | 6008 | https://uu55868-793909b1c426.weste.seetacloud.com:8443 |

迁移后的 `/root/apps/portrait-studio`、`/root/apps/case-studio`、两套 Python 环境、原始素材、模型、报告/阶段包和历史实验均已找到。数据目录 `/root/autodl-fs/case-studio` 仍解析到 `/autodl-fs/data/case-studio`，本轮成品生成的 266 个绑定文件校验通过。

新实例驱动报告 GPU 为 **NVIDIA GeForce RTX 4080 SUPER，32760 MiB**，驱动 `595.71.05`；PyTorch `2.5.1+cu124`，CUDA 可用。这里记录实例实测信息，不把它当作普通零售卡的标准规格，也不作为全流程最低显存要求。

6006、6008 迁移后初始未运行，现通过各自 `start.sh` 恢复 supervisor 托管。6006 默认允许来源更新为新域名，旧实例域名不再授权；`PORTRAIT_PUBLIC_ORIGINS` 仍可显式覆盖。新代理未提供 HTTPS scheme 时，两服务登录根据浏览器 HTTPS Origin 保持 Secure Cookie；此判断只影响 Cookie 属性，不授予来源访问权限。页面移除固定的旧 4090 型号文字。

检查包括两端口本机/公网健康、首页、新域名登录及登录后读取、未登录 401、6006 旧来源 403、6008 审核页面。没有修改访问码、API Key 或历史审核结果。GPU 组件检查只验证模型在新实例运行，不等于完整工作流显存基准测试。

同时完成前一轮暂停的 Logo 更新：用户提供的四份 SVG 已复制到素材根目录 `logo/`；成品选择 `品牌logo（白色）.svg`，地址统一显示 **UP 健身私教馆**。CairoSVG `2.9.1` 安装在渲染环境。生成新目录 `experiments/body-scan-vs-logo-v4-20261106/delivery-v4`，只重绘 39 张 VS，91 张单图和三视图复用；阶段标签保持 82 张、其中 53 张待审核。9 个完整案例的分类预览在本机 `artifacts/body-scan-vs-logo-v4/index.html`，不覆盖旧预览或生产版本。

成品代码新增 SVG 载入、Illustrator 编辑数据清理、透明留白裁切和原始 Logo SHA 校验，不改照片像素几何；外部 SVG 资源访问被禁用。测试记录见 [validation-logo-v4.json](../scripts/body_scan_delivery/validation-logo-v4.json)。

单样本 GPU 检查：768×1792 已批准图片，YOLO11n → SAM 2.1 Base+ → YOLO11m-pose → GeoCalib 依次执行并保留四模型，PyTorch 最大 allocated 为 1167 MiB、reserved 为 1374 MiB。仅为该进程单张输入的分配器统计，不包含完整 CUDA/驱动占用，不是无缓存全流程或并发峰值。没有调用视觉模型 API。
