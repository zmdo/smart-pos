# 非网格墙面体测图：独立相机校正实验

本轮只测试几何校正，不接入 `scripts/body_scan`，不执行肩髋对齐、人物比例统一或最大矩形取景。网格权威副本和主流程的 `normal_transform()` 均保持原状。

## 先修正素材筛选

`case-studio/classify.py` 升级为 `cls-v3-wall`：体测图必须是**主体紧邻墙面、静态站立展示体态**；墙面海报、木纹墙、网格墙可以，身后主要是开放器械区/走道/倒影不可以。靠墙锻炼仍是训练图；体测中的抬臂、抱臂不单独作为训练证据。

分类响应新增 `wall_background`、`body_scan_pose`、`training_activity`、`wall_evidence`，规范化阶段也检查必要条件。缺少证据或响应自相矛盾时，不将图片当体测图。缓存版本升级后不会命中旧 `cls-v2` 分类缓存。

`audit.py` 对指定图片重新分类，使用独立实验缓存；原 `job.json`、旧分类缓存和旧成品不自动改写。原网站进程没有为本次实验重启，重新部署/重载后才会使用新的分类模块；已有 job 内的旧标签仍需重新分类。实验直接使用复核结果，不使用旧 job 的 `class` 来决定入选。

37 张复核包括：32 张非网格候选、3 张网格控制和2张对比控制。潘艺文 `a0169` 被重新判为 `daily_training`，依据是身后开放器械区而非墙面；其余31张非网格候选符合墙面体测条件。3张网格和2张对比图在几何实验中跳过。

## 相机模型方案

采用 [GeoCalib 官方实现](https://github.com/cvg/GeoCalib)（[ECCV 2024 论文](https://www.ecva.net/papers/eccv_2024/papers_ECCV/html/5636_ECCV_2024_paper.php)）估计焦距、重力方向、侧倾/俯仰及不确定性。它使用单张照片的视觉线索估计相机，不是生成式修图。模型假设主点位于图像中心；已裁切照片和弱纹理背景可能不满足假设。

每张保留两个候选：

1. **pinhole：相机侧倾/俯仰校正。** 将原图通过 `K · Rᵀ · K⁻¹` 重投影到水平相机视角。整张照片遵循同一相机变换，不通过拉平人体肩膀或分别拉伸横竖轴来制造一致性。
2. **radial：相机校正 + 径向校正。** 使用专门的 distorted 权重估计 `k1`，采用 `rd = ru × (1 + k1 × ru²)`；反解采用 Newton 迭代，并检查映射单调性。径向变换属于非线性映射，报告中不会伪装成单应矩阵。

几何层将完整源边界密集采样以确定输出范围，在主体框中心保持局部面积尺度不变；通过反向映射只采样原图一次。无来源区域以浅色显示，并单独保存有效遮罩，不补画背景或身体。此阶段故意保留变换后的完整轮廓，矩形取景留到后续整合时处理。

源图黑边使用已有的低层内容遮罩工具排除；上一轮报告只提供与原图 SHA 绑定的主体框，用来控制局部变形，不调用上一轮处理管线或姿态模型。

这一步解决相机侧倾和俯仰造成的投影变化，**未估计墙面绕竖直轴的左右朝向，不等于把所有墙面完整变成正视平面**。径向参数也是单图推断，不是已知相机的真实标定。人物/墙面比例不能作为相机参数的真值。

## 验证和结果

远程输出：`/root/autodl-fs/case-studio/experiments/non-grid-camera-v1-20261105`。

- 31张符合条件的非网格照片：30张各生成2个候选，共60张；`a0136` 两种模型均估计约25–26°俯仰，超出25°实验限值，保留待复核。
- 6张跳过：`a0169` 训练图，`a0018/a0180` 对比图，以及3张网格控制图。
- `a0034/a0134/a0136` 两种相机模型分歧明显，报告和对照图单独提示。海报样本 `a0034` 的俯仰估计约为 +1.1° 与 -16.0°，不能默认采用更复杂的径向模型。
- **全部候选至少存在一项角度或焦距不确定性提示**。`candidate` 表示实验图已生成，绝不表示质量验收通过；所有记录都禁止自动采用。
- 10项几何/路由测试通过，包含独立三维投影构造、横竖方向及比例恢复、径向往返映射、源像素保持、错误参数拒绝、训练照推理前跳过及模型分歧标记。分类与原核心回归29项通过。
- 原图哈希、60张候选有效遮罩、旋转矩阵及非线性报告类型均通过核对。详细参数、检查结果、模型和候选文件哈希见 `validation.json`。

当前建议：优先审阅 pinhole 候选，径向校正保留为对照；弱参照照片、模型分歧和裁切照片仍需可靠墙面结构约束或真实标定，不应直接接入自动成品流程。

## 运行

代码：`/root/apps/case-studio/scripts/non_grid_camera`。

独立环境：`/root/apps/non-grid-calibration/.venv`，通过 `--system-site-packages` 复用已有 torch 2.5.1/CUDA；新增 kornia 0.7.4、kornia-rs 0.1.9 和 GeoCalib 安装在此环境，未升级网站环境依赖。

GeoCalib 源码位于 `/root/apps/non-grid-calibration/GeoCalib`，固定官方提交 `1dedb29f94fc11b896c5f572005978aeebccd67f`。两个官方权重保存在 `/root/autodl-fs/case-studio/models/geocalib/`，不进入 Git；SHA见 `validation.json`。代码遵循上游 Apache-2.0，模型权重遵循 CC BY 4.0，归属 GeoCalib 作者 Alexander Veicht、Paul-Edouard Sarlin 和 Philipp Lindenberger。

```bash
cd /root/apps/case-studio

# 独立复核；输出目录必须新建，API配置只读取服务器已有设置。
PYTHONUTF8=1 /root/apps/portrait-studio/.venv/bin/python -m scripts.non_grid_camera.audit \
  --job /root/autodl-fs/case-studio/batches/287a8a82df2f2fca2c22299b/job.json \
  --asset-id a0104 a0133 a0169 \
  --out /root/autodl-fs/case-studio/experiments/wall-audit-new

# 使用已完成的37张复核；可不传 --asset-id 运行全部。
bash scripts/run_non_grid_camera.sh \
  --audit /root/autodl-fs/case-studio/experiments/non-grid-camera-v1-wall-audit/classification.json \
  --baseline /root/autodl-fs/case-studio/experiments/body-scan-unified-v1-20261105 \
  --out /root/autodl-fs/case-studio/experiments/camera-test-new \
  --asset-id a0104 a0140 a0166 a0169
```

所有输出目录必须不存在，不覆盖旧实验。分类缓存和相机估计缓存独立，后者绑定模型哈希、算法版本、相机类型、内容范围和源像素。

每张输出 `original.png`、`pinhole.png`、`radial.png`、对应有效遮罩和参考线叠加、三列 `comparison.jpg`、`report.json`。长背景边缘仅作可视诊断，未假定这些候选线必然同平面或用于验收准确率；径向分支用曲线叠加显示真实非线性映射。

默认完整结果包为 `camera-experiment.zip`。本次另整理 `camera-review.zip`（约7MB），包含全部对照图和报告，便于先看效果。
