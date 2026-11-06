# Case Studio · 素材体检与体测成品审核

远程 GPU 机上的第一批实现：**上传压缩包 → 解包 → 归一 → 去重 → 质量 → 分类 → 报告解析 → 产出决策 → 体检报告**。
上传管线仍只出体检报告。另已接入**已批准阶段结果→体测单图/VS/三视图→人工审核重生成**，入口 `/review`；完整ZIP上传到标准化/阶段/成品的调度尚未接通。协议见[工作流](../docs/workflows/body-scan-delivery-review.md)，实现见[生成节点](../scripts/body_scan_delivery/README.md)。

- 公网地址：https://uu55868-793909b1c426.weste.seetacloud.com:8443
- 访问令牌：`/root/autodl-fs/case-studio/settings.json` 里的 `access_token`
- 端口：6008（supervisord 托管，`/root/apps/case-studio/start.sh` 重启）
- 数据：`/root/autodl-fs/case-studio/{batches,cache,logs}`

## 已实现（对应方案 12 步里的 1–10）

| 步 | 实现 | 说明 |
| --- | --- | --- |
| 1 解包 | `archives.py` | zip/tar.gz、拒穿越/符号链接/加密/炸弹、跳过 `__MACOSX`/`.DS_Store`/`._*`、GBK 文件名回退 |
| 2 包识别 | `app.package_kind` | 标准包 / 门店包 / 模板包 / 混合包；模板与标准目录不计入生产 |
| 3 归一化 | `preprocess.py` | magic bytes 判型、HEIC(pillow-heif)、EXIF 方向、三档图（full/work/thumb） |
| 4 去重 | `preprocess.phash` + `app` | sha256 精确；pHash(≤4 + 同类 + 同宽高比) 近似；报告/感言成对不去重 |
| 5 质量评分 | `preprocess.process` + `app` | 清晰度(512px Laplacian var)、曝光(均值/截断)、短边、人物占比；**默认丢弃**并记录原因 |
| 6 素材分类 | `classify.py` | DeepSeek-V4.1-Flash 视觉，7 类 + **左/右侧面** + 前后 + **拍摄背景** + 是否已贴纸 + 置信度；按 sha256 缓存 |
| 8 结构抽取 | `facts.py` | docx/pdf → 门店/教练/会员/指标表 + 一致性校验（体重差、BMI 推算） |
| 9 会员归并 | `plan.split_member` + `app` | `店/会员`、`教练-会员`（后者为会员）、`（缺X）` 备注、非生产目录剔除 |
| 10 产出决策 | `plan.py` | 17 类成品依赖矩阵 + 缺口清单 + 待确认项（前后顺序、左右、前后背景不一致） |

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/login` | `{"token": "..."}` → HttpOnly Cookie |
| POST | `/api/batches` | multipart：`archive` + `mode=dryrun` |
| GET | `/api/batches` | 批次列表 |
| GET | `/api/batches/{id}` | 状态 + 汇总 + 每会员计划 + 素材（含缩略图路径） |
| GET | `/api/batches/{id}/report.md` | Markdown 体检报告 |
| GET | `/api/batches/{id}/thumb/{asset}` | 素材缩略图（需登录） |
| POST | `/api/batches/{id}/cancel` | 取消 |
| GET | `/api/productions` | 已生成的体测任务 |
| GET | `/api/productions/{id}` | 成品、全部标签、审核清单与预览/下载地址 |
| POST | `/api/productions/{id}/review` | 部分确认/修正、增量重生成并返回新版本 |
| GET | `/api/productions/{id}/files/{revision}/{filename}` | 受登录保护的版本成品、审核页和下载包 |

前端：`/`（上传 → 进度 → 会员卡片 + 缩略图 + 缺口/待确认），`?batch=<id>#token=<token>` 可直达。

## 实测（demo 数据：`/root/autodl-fs/qa/demo-cases.zip`）

| 指标 | 结果 |
| --- | --- |
| 文件 | 231 个（跳过 269 个 macOS 垃圾文件） |
| 图片 | 209 张（含 4 个重复、8 个低质丢弃） |
| 会员 | 18 人（1 宝安 + 9 景田 + 8 石厦） |
| 可出成品 | 232 张（人均 12.9） |
| 缺口 | 59 项 |
| 待确认 | 51 项（几乎都是"训练前/后顺序待确认"） |
| 视频 | 13 个，本期只登记不处理 |
| 耗时 | 首次 ~3 min（含 209 次视觉调用），缓存后 ~55 s |

分类抽样核对：健身房训练照→`daily_training`、微信聊天截图→`testimonial`、InBody 翻拍→`body_report`、网格墙全身照→`body_scan`，与肉眼一致。

体测图细分（本轮新增）：
- **对比图（一张里前后两人）**：识别为 `phase=both`，用 YOLO 两人框找中缝切成 before/after 两张
  （中缝优先级：两人框间隙 → 两人中心均值 → 画面中线；且必须落在 30%–70% 区间），
  报告里标注"来源：对比图切分"，界面徽标显示"·对比图"。demo 里 26 张对比图全部切分成功。
- `view`：`front` / `side_left` / `side_right` / `side`（分不清左右）/ `back`
- `background`：`grid_board` 网格板 / `white_wall` 白墙 / `wood` 木板墙 / `mirror` 镜面 / `outdoor` 户外 / `other`
- 报告里每个会员有一张「体测视图 | 训练前 | 训练后 | 背景」明细表；同一视图前后背景不一致会进待确认（例：郑远晨、黎国萍 前后分别在网格板和木板墙前拍摄）。
- 侧视优先用左侧（符合拍摄标准），只有右侧时用右侧并标注；成品文件名仍严格对齐模板（不把"左/右"写进文件名）。

## 已知问题 / 下一步

1. **阶段核验与完整调度**：独立局部分析及成品生成已覆盖82张/16人；31张推断、22张待审仍需人工确认。上传体检的旧计划不会自动调用这些新节点。
2. **封面的指标数据**：只有 docx/pdf 才有 `facts`；翻拍体测报告的读数（OCR）还没做，所以「会员案例封面」目前多数缺指标。
3. **质量阈值**：已从"误杀 30%"调低到 4%，但只在 demo 上校准过；建议先用"仅标记"跑两批再定死。
4. **渲染范围**：当前提供体测单图、同朝向VS和完整三视图的1080×1440基础版式，共130张；其他模板及新增贴纸库待实现。
5. 环境：复用 `portrait-studio` 的 venv（装了 python-docx / pypdf / pillow-heif），后续应拆独立 venv。

## 运维

```bash
cd /root/apps/case-studio
./start.sh                                  # 启动/重启
/root/apps/portrait-studio/.venv/bin/supervisorctl -c supervisord.conf status
/root/apps/portrait-studio/.venv/bin/python -m pytest tests -q     # 15 passed
```

部署必须同时包含 `case-studio/`（放到远程应用根目录）与 `scripts/body_scan_delivery/*.py`（保留到应用根下同名scripts路径）；审核API按需调用渲染模块，重生成不依赖模型服务。模型初次创建任务仍需仓库其他阶段模块及已有远程处理环境。Windows辅助脚本 `scripts/deploy-case.ps1` 已包含审核运行时模块；该脚本不会复制历史模型/数据目录。

2026-11-06已在现有服务器直接同步模块、备份入口并重启6008。公网 `/review` 登录及受保护的预览/审核JSON已验证；27项节点测试和真实素材2图修正闭环通过，4张重生成、126张逐字节复用。完整记录见 `scripts/body_scan_delivery/validation.json`。
