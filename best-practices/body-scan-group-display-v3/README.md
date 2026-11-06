# 同组展示 v3：共同人物尺度与一人一画幅

用户批准的同人尺度校准方案，来源提交 **137054176720ab1b0348364961548a304b4ed754**。复制保留全部尺度算法、提示词、19项测试及原同组展示算法、32项测试；新增入口只负责节点衔接和权威版本标记。

当前推荐链路：**硬拼接拆分 → 单图标准化v4 → 本节点v3**。本节点包含尺度校准与最终共同取景；旧`body-scan-group-display` v2、单图v4和拆分最佳实践保持各自快照，不修改已生成的图片。

## 规则与边界

1. 同人至少两张可靠中立正/背照建立尺度参考；头发、贴纸、腰宽和衣服轮廓不作尺子。
2. 同一背景用实测网格格距或墙面配准，跨背景用可靠身体分段衔接。裤装遮住腿部不自动否定可靠肩髋参考。
3. 每张只采用一个等比倍率，定标和肩部定位分开；抬臂图用髋部与中立躯干参考取景。镜头几何和真实身体倾斜保持不变。
4. 2%内保留；证据不足、冲突、变化过大或头脚余量不足时保留原尺度并待复核。头脚保护结合旧完整度证据和SAM实测轮廓，不拿大模型粗框当精确裁切边界。
5. 最终仍一人一画幅、一个共同取景框。等比参考和展示版分开保存；可选的轻微纵向调整整组共享，默认上限1.1。

所有处理参数和判断门槛与获准实验相同。本轮没有增加镜头径向畸变校正，也没有把人强制拉直。网格线弯曲的检查属于后续独立工作。

尺度待复核与最终取景待复核分开记录；“有成品”不等于尺度已校准。缺少可靠基线完整度/成品时停止并保留记录，不跳过这些素材后声称整组完成。

## 远程入口

服务器目录：`/root/apps/case-studio/best-practices/body-scan-group-display-v3`。数据、模型和私有设置继续使用服务器现有资源，仓库不含照片、权重或凭据。

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display-v3/run.sh \
  --input /path/to/approved-v4-standardized \
  --settings /root/autodl-fs/case-studio/private/qwen3.8-max-eval.json \
  --out /path/to/NEW-group-display-v3
```

默认自动生成基线展示与完整度证据，然后运行尺度校准和最终取景。已有匹配基线时增加`--baseline-display /path/to/previous-display`；会检查原图、标准化像素和取景参数是否一致，不能借用另一批图片的基线。

输入是一个v4结果目录及其原图；旧v2/v3兼容格式也能读取，但不会自动补做海报过滤或几何检查。多个来源应先由v4汇总为同一批标准化结果，不重复素材ID。`--out`必须是输入之外的新目录，不覆盖旧产物。

`--settings`用于Qwen尺度证据；完整度节点仍读取服务器原有设置，可用`--visibility-settings`另行指定。`--width`默认768，`--max-stretch`默认1.1；`--focus`只指定报告重点图，不影响算法。`CASE_PYTHON`可覆盖默认远程Python，`CASE_SAM`/`CASE_SAM_CONFIG`指定已有模型。

## 输出

- `baseline-display/`：未提供旧基线时自动生成；若提供则只读复用。
- `standardized/`：尺度校准后的兼容标准化结果、保留原因及验证；记录`best_practice_version=body-scan-group-display-v3`，原上游版本另存。
- `display/`：一人一画幅成品、等比参考、HTML和下载包。
- `comparison/`：新旧对照；沿用实验报告展示格式，其中“新实验”指本次采用的新方案。
- `workflow.json`：阶段、采用数、尺度待复核、取景待复核；`completed_with_review`明确表示仍有保留项。
- `verification.json`：输入/几何/关键点未改、矩形来源、一人一画幅等检查。
- `index.html`：结果和下载入口。

## 归档验证

```bash
bash /root/apps/case-studio/best-practices/body-scan-group-display-v3/run_tests.sh
```

启动时验证[manifest.json](manifest.json)中的文件指纹；`verify_snapshot.py`验证所有项目导入都来自本目录，不依赖开发目录或相邻快照。SAM、运行库和缓存等外部依赖见[external-resources.json](external-resources.json)、[requirements.verified.txt](requirements.verified.txt)。

获准实验的5组28张记录保存在[source-validation.json](source-validation.json)。本次归档的独立重跑、两种基线入口和像素一致性结果见[validation.json](validation.json)。覆盖范围为这5组，不代表全量数据均已通过尺度校准。

后续改进在开发目录测试，获用户确认后再更新权威版本及指纹。维护流程见[工作流说明](../../docs/workflows/person-scale-calibration.md)。
