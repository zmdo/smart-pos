# 同一人物尺度校准实验

用户已批准本方案，当前权威入口为[同组展示v3最佳实践](../../best-practices/body-scan-group-display-v3/README.md)，来源`1370541`。以下保留独立实验及其验证记录，开发代码未因归档改变。

独立节点：在已批准的相机几何之后，重新估计每张照片的**等比尺度**，再调用原有同组取景程序。不会修改最佳实践、旧成品、原图或镜头校正矩阵。

## 规则

1. Qwen只判断同一背景、是否贴近墙、抬臂/中立姿势、哪些身体分段可信，不输出缩放数字。
2. 每人至少两张自然站立的正/背图构成共同参考。头发、脸部贴纸、腰宽和衣服外轮廓不参与定标。
3. 身体关键点必须通过置信度、方向和双侧一致性检查。裤装遮住腿部时，舍弃腿长证据，但可保留清楚的中立肩髋参考。
4. 同一网格板使用已校正坐标里的真实格距；同一墙面使用背景特征配准。不同背景不能直接比格距或配准；跨背景由同人的可靠身体分段建立共同单位。
5. 两张背景参考一致，或背景与身体证据互相支持，或多个身体分段一致时才采用。尺度差小于2%保留；参考支持不足、冲突或变化超过范围则保留并待复核。5%是复核提示，不是强制拉伸的目标。
6. 定标与定位分开：自然站立用真实肩部；抬臂用髋部与整组中立躯干长度推算取景锚点。网格/非网格使用相同规则，不抹平真实高低肩。
7. 若新取景会切掉旧成品中已确认完整的头或脚，则保留旧尺度，记录原因。这个检查消费与输入指纹完全一致的旧展示结果；SAM以肩髋正向提示实测主体轮廓，不能直接把大模型粗框边缘当作头顶/脚底。
8. 下游仍一人一画幅；尺度节点本身没有非等比拉伸。原有展示节点允许的轻微纵向调整仍按整组共享，并另存等比参考。

## 远程复现

在 `/root/apps/case-studio` 中使用 `/root/apps/non-grid-calibration/.venv/bin/python`，计算和模型调用均在服务器运行。`--out` 必须是输入目录之外的新目录。

```bash
python -m scripts.body_scan_person_scale \
  --input /path/to/approved-standardized \
  --baseline-display /path/to/matching-previous-display \
  --settings /path/to/private-qwen-settings.json \
  --out /path/to/new-experiment/standardized

python -m scripts.body_scan_person_scale.verify \
  --out /path/to/new-experiment/standardized

python -m scripts.body_scan_group_display \
  --input /path/to/new-experiment/standardized \
  --out /path/to/new-experiment/display

python -m scripts.body_scan_person_scale.report \
  --standardized /path/to/new-experiment/standardized \
  --before /path/to/matching-previous-display \
  --after /path/to/new-experiment/display \
  --out /path/to/new-experiment/comparison \
  --focus a0101 a0107

python -m unittest discover -s scripts/body_scan_person_scale/tests -v
```

`--focus`仅选择报告展示图片，不影响处理算法。没有店名、人名或图片ID特例。模型缓存绑定原图像素、提示词、模型和请求选项；凭据不进入报告或仓库。

## 输出与边界

- `summary.json`：兼容现有标准化格式，增加每张`person_scale`，含原取景、尺度候选、采用/保留原因、语义证据和边界保护。
- `scale-groups.json`：共同参考、目标分段像素和模型追踪。
- `input-manifest.json`、`verification.json`：输入未变、镜头几何未变、关键点未变、等比矩阵、真实矩形及保留图像逐字节检查。
- `comparison/index.html`：各组前后对比和缩放变化；`metrics.json`区分尺度校准状态与最终出图状态。

已出图不表示尺度已校准：证据不足的图继续保留旧尺度供查看。网格间距一致也不等于真实身高一致；人物离墙距离、透视、姿势和关键点误差仍可能影响结果。该实验不做真实人体测量，不作为体型变化判断的替代品。

## 本轮验证结果

5组28张全部生成展示图：6张采用尺度校准、11张处于2%内保留、11张因证据不足/冲突/头脚余量不足保留并待复核。22张标准化图逐字节保留，17张最终展示图也与旧版逐字节一致；其他保留图可能随整组共同取景调整。

黎国萍a0107等比放大约11.5%，与a0101的二维肩髋长度差由14.36%降至2.57%；同背景3张图的输出网格尺度差由12.71%降至2.19%。这些是画面一致性指标，不是真实身高误差。张小飞4张因证据不足保留，已有方向修正未受影响。

64项测试通过；143个输入指纹、28张矩形来源、28组原始关键点/镜头矩阵和56张最终派生图验证通过。最终远程目录为`experiments/body-scan-person-scale-v1-20261106/final-validated`，此前目录都是中间试跑。

验证数据见[validation.json](validation.json)，流程见[工作流](../../docs/workflows/person-scale-calibration.md)。
