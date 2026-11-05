# 网格体测照权威快照：最大矩形有效区域 v5

用户已确认这一版为权威脚本。原文件及旧实验保留，此目录是独立副本。

- 来源提交：`06d968a2585cf09e47d092427fb01ac3399f9035`。
- 唯一处理入口：[tools/grid_shoulder_frame_max_rectangle.py](tools/grid_shoulder_frame_max_rectangle.py)。它与来源文件逐字节一致。
- 其余 9 个 `tools` 模块是原入口导入链的冻结依赖，不代表这些历史模块的全部 CLI 都是权威入口。
- 原 14 项测试原样复制到 `tests`；运行脚本仅将工作目录改为相对于自身定位。
- [manifest.json](manifest.json) 记录每个副本的来源、作用及 SHA256。

## 输入和边界

本入口是完整图像流程的**最终取景阶段**，不是从 ZIP 或原始照片直接完成检测、网格校正的一键入口。

需要已经通过 v4 处理的目录，包含 `config.json`、`summary.json`、`groups.json`，以及每张图的 `aligned.png`、`content_mask.png`、肩髋点和几何变换报告。上游方案与数据契约见 [原方案 18](../../docs/solutions/会员案例素材生产方案/18-最大矩形有效区域.md)。

对每张图取真实有效区域内面积最大的轴对齐矩形，确保包含肩髋标定点。输出继续使用原画布、比例和肩线，不再次缩放或采样；矩形外补浅色。当前批准配置为 768 × 1792、肩髋占高度 27%、肩线高度 23%。

冻结依赖中保留了原文件的历史函数，但此入口不会调用它们的模型/API 功能。只支持上述最终取景任务；直接运行其他依赖模块可能需要未打包的上游环境，不属于此快照的独立运行承诺。

## 远程运行

部署目录：`/root/apps/case-studio/best-practices/grid-portrait`。

```bash
bash /root/apps/case-studio/best-practices/grid-portrait/scripts/run_grid_shoulder_max_rectangle.sh

# 指定输入、输出；输出必须不存在且不能位于输入目录内
CASE_MAX_RECT_PREVIOUS=/path/to/approved-v4 \
CASE_MAX_RECT_OUT=/path/to/new-output \
bash /root/apps/case-studio/best-practices/grid-portrait/scripts/run_grid_shoulder_max_rectangle.sh

/root/apps/portrait-studio/.venv/bin/python -m unittest discover \
  -s /root/apps/case-studio/best-practices/grid-portrait/tests \
  -p test_shoulder_frame_max_rectangle.py -v
```

运行路径只依赖这个副本中的代码，不依赖 `case-studio/tools`。沿用服务器已有 Python 环境，不上传模型、密钥、字体或用户照片到 Git。字体可沿用服务器现有 Noto Sans SC，仅影响预览文字。

`requirements.verified.txt` 记录远程实际验证的三个第三方依赖版本；Python 验证版本为 3.11.18。此最终取景阶段不加载 GPU 模型，也不调用外部 API。

## 独立副本验收

从服务器 `/tmp` 启动，验证全部 10 个本地模块都来自这个目录；12 个代码/测试/启动文件的 SHA256 与清单一致。原 14 项测试通过。

用副本重跑批准批次，12 张处理、2 张跳过；12 张的 72 个图片/掩码/诊断文件与批准的 v5 逐字节一致，几何报告也完全相同。验收记录见 [validation.json](validation.json)，验证输出位于 `/root/autodl-fs/case-studio/experiments/best-practices-grid-portrait-v5-verification/`。

## 更新约定

后续非网格方案独立开发，不能修改这份网格基线。若用户确认新的权威版本，更新本目录、`manifest.json`、验收说明及 `best-practices/README.md`，然后提交并推送。原实验源码不再被视为当前权威入口。
