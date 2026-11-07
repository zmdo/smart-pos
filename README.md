# UP 会员案例生产系统

上传会员素材 ZIP → 分类、校正与训练阶段识别 → 人工审核 → 八类成品与打包下载。模型和图像处理运行于远程 GPU 服务器，本机用于开发源码。

- [会员案例工作台（6008）](https://uu55868-793909b1c426.weste.seetacloud.com:8443/)
- [重构设计](docs/design/case-studio-workflow-rebuild/README.md) · [实现与验收](docs/design/case-studio-workflow-rebuild/IMPLEMENTATION.md)
- [网站代码与部署](case-studio/README.md) · [最佳实践](best-practices/README.md) · [交接文档](docs/交接文档.md)

网站包含首页、历史记录、设置三个页面。审核支持会员身份、训练前后拖拽、对比图文字、封面双图取景和体测表格编辑；修改后重新生成版本，旧版本仍可下载。成品包括三视图、同朝向对比、阶段单图、会员封面、体测报告、会员感言、训练日常、生活照。

当前服务器 `connect.weste.seetacloud.com:44023`。会员案例代码位于 `/root/apps/case-studio`，新网站数据位于 `/root/autodl-fs/case-studio/website`。密钥仅存服务器私有配置，不写入 Git。详见 [部署与迁移](docs/deployment-weste-20261106.md)。旧网站模块和 `tools/` 已移除，历史代码从 Git 恢复；原素材保留。旧 PowerShell 部署脚本不用于本次新网站部署。

另行运行的 [四向人像服务（6006）](https://u55868-793909b1c426.weste.seetacloud.com:8443/) 保持独立。本次重构不更换其代码、模型环境或进程。

---

以下为四向人像服务的历史项目说明，旧服务器地址仅用于追溯。

# 四向 · Portrait Studio（历史说明）

图片压缩包 → 人物识别 → 朝向判断 → 面部遮罩 → 前/后/左/右拼图 → 下载。

**线上地址**：https://u55868-7936f251bb5f.westd.seetacloud.com:8443
（AutoDL 把服务器 6006 端口映射到这个 HTTPS 域名，服务只跑在远程服务器上。）

## 目录

| 路径 | 说明 |
| --- | --- |
| `portrait-studio/` | 服务端源码镜像（改完用 `scripts/deploy.ps1` 推送到服务器） |
| `scripts/deploy.ps1` | 备份远端旧版 → 上传改动 → 跑远端 pytest |
| `scripts/remote/` | 远端运维/排查脚本（plink -m 执行） |
| `qa/screenshots/` | 验收截图（登录页、工作台结果页、两组拼图） |
| `qa/test-set-38-images.zip` | 回归用测试包（37 张人像/街拍 + 1 张无人图 + 1 个 txt） |
| `case-studio/` | **第二条产品线（会员案例生产）的服务端源码**，跑在 6008，见其 README |
| `docs/solutions/会员案例素材生产方案/` | 会员案例批量生产的方案文档（v0.3，12 步流程） |
| `scripts/deploy-case.ps1` | 部署 case-studio：上传 → 装依赖 → 跑测试 |

## 服务器

- 应用目录 `/root/apps/portrait-studio`，独立 venv：`/root/apps/portrait-studio/.venv`
- 数据目录 `/root/autodl-fs/portrait-studio`：`jobs/<id>/{input,output}`、`models/`、`logs/`
- 服务端配置（0600）`/root/autodl-fs/portrait-studio/settings.json`：API Key / Base URL / 模型名 / 访问码
- 进程由 supervisord 托管，`/root/apps/portrait-studio/start.sh` 启动或重启
- 版本备份：`/root/portrait-studio-backup-<时间戳>.tar.gz`

## 验收与回归

```bash
# 远端
cd /root/apps/portrait-studio && .venv/bin/python -m pytest tests -q    # 38 passed
.venv/bin/supervisorctl -c supervisord.conf status
```

本机 `scripts/deploy.ps1` 会自动备份、上传、跑测试；部署 Python 改动后需 `start.sh` 重启。
