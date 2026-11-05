# 训练前后标注节点

版本 `body-scan-phase-v1`，独立消费 `body-scan-group-display-v2` 的成功结果。只增加标签、依据、候选槽位和复核预览；原图、已批准的成品及冻结最佳实践保留，尚未接入网站。

用户规则：左右对比图拆出的左图为训练前、右图为训练后；其余先用可靠文字标记，没有标记则在同店同名、同朝向内比较体形、体态和肌肉外观。较胖/体态偏差更明显为前，较瘦/体态偏差减轻/肌肉更明显为后。模型推断记录来源，不冒充经过核实的拍摄时间。

## 运行

仅在远程服务器运行，复用现有虚拟环境和模型设置，无新增依赖：

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_phase \
  --input /root/autodl-fs/case-studio/experiments/body-scan-poster-filter-v1-20261105/display \
  --out /root/autodl-fs/case-studio/experiments/body-scan-phase-v1-20261105
```

`--out` 必须是新目录。可传 `--settings` 指定现有服务配置文件；不把密钥写入产物。默认 `--confidence .8` 为模型自报置信度门槛，不是统计准确率。缓存按提示词版本、模型、输入像素计算键。

后续新拆分使用开发版 `scripts.body_scan_pairs` 的 `body-scan-pairs-v2-phase`；独立子图分类后写入 `class.phase`、`phase_evidence` 和 `pair_source`。几何算法不变。冻结拆分副本仍保留旧标签规则；本节点根据旧拆分报告补上位置标签，无须重跑几何。

## 输入、判断与输出

1. 校验原图及 `uniform.png` 的 SHA、会员归属和上游来源。当前适配器接收同组展示结果，原始 job 的 `class.phase` 不能在没有证据时直接当作可靠标签。
2. 切分图读取父图报告，检查硬拼接复核通过、两张实际裁切矩形、父子 SHA 和逐像素无损裁切。只有真实 `left_right` 布局才应用左前右后，不能按文件名 `__p01` 猜测。位置规则与可见文字冲突时按用户要求保留位置标签，并记录冲突。
3. 其他照片检查单图文件名中的明确“训练前/后”等标记，以及上游 `explicit_marker` 证据。上下拼图不套用左前右后。含双方标记的文件名不用于单图赋值。
4. 未知项在同店同名、同朝向内两两比较。左右侧不混合，含糊的 `side` 由模型再确认是否同侧、同姿势；单张不猜，同朝向超过6张留待复核。多图两两提议冲突时保留未知，不强制二分，不向其他朝向传播衣着推测的阶段标签。
5. 输入为 `A原图、A等比参考、B原图、B等比参考`，绝不使用非等比的 `display.png`。分别输出体形、体态、肌肉证据；不可比、线索冲突或证据不足时未知。初审通过的比较交换 A/B 再审，结论一致才采用；不重试直到获得满意答案。
6. 优先级：位置规则 > 明确文字 > 模型外观推断。已有可靠标签不会被模型覆盖。模型请求失败的照片仍有记录，不丢弃。

模型给出方向但未达到门槛时，另存 `suggestion` 作为“AI初步建议（未采用）”；它不改变 `phase=unknown`，不进入已采用的成品槽位。换序方向相反或同组建议冲突则不提供单一建议，原始证据仍可查看。

产物：`summary.json` 每张的 `phase/phase_source/confidence/reason/evidence`；`comparisons.json` 两次呈现的原始模型答复；`slots.json` 每人每朝向的 before/after/unknown 候选列表；`sources.json` 输入指纹；`verification.json` 完整性检查；`index.html` 和 `previews/` 离线复核。有多个槽位候选时不擅自挑选。

测试：

```bash
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s scripts/body_scan_phase/tests -v
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s scripts/body_scan_pairs/tests -v
/root/apps/non-grid-calibration/.venv/bin/python -m unittest discover -s scripts/body_scan/tests -t . -v
```

详见 [训练前后标注工作流](../../docs/workflows/training-phase.md)。本次继续使用历史46张输入产生的42张成功图，**不是完整上传包**；黎国萍未进入子集的三张黑衣照不会凭空成为对比项。

## 当前实测

[validation.json](validation.json)：远程85项测试通过（新节点20、拆分18、标准化47）。42张/11人全部保留：2张左右位置规则标签，22张AI初步建议未达到0.8采用门槛，另2张无明确模型方向、16张无同朝向配对。最终正式标签为 before 1、after 1、unknown 40，不把初步建议计为自动标注成功。

最终结果 `/root/autodl-fs/case-studio/experiments/body-scan-phase-v1-final-20261105`。93个输入指纹不变，原有137个成品/预览文件字节一致；新拆分两张PNG也与旧版相同。最初一次接口失败已恢复，最终重放全部命中缓存。当前没有训练时间真值，测试通过不表示语义准确率达到某个数值。
