# 四向 · Portrait Studio（远程 GPU 实现）

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
