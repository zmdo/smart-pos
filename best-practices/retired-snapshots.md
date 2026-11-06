# 最佳实践版本清理 · 2026-11-06

用户要求删除被替代的最佳实践，解除旧运行依赖并在服务器验证。当前仅保留拆分、单图v4、同组v3三个目录。

| 已删除目录 | 当前替代 | 清理前最后完整提交 |
| --- | --- | --- |
| `grid-portrait` | 单图v4及同组v3覆盖现行处理用途；旧v5输入契约仅供历史复现 | `ec5dcb4cda00534b7547dbaaa54177b4d5cfe503` |
| `body-scan-wall`（v3） | `body-scan-wall-v4` | 同上 |
| `body-scan-group-display`（v2） | `body-scan-group-display-v3`，自带旧取景代码 | 同上 |

## 迁移边界

拆分算法、提示词、像素裁切、独立子图分类和阶段规则保持原样。冻结拆分改为导入v4中的公共模块，并锁定其来源提交和manifest SHA；开发版拆分的默认下游也改为v4。`--split-only`仅拆分，默认入口继续执行v4完整标准化并校验几何检查标记。工作流分节点时必须使用仅拆分，避免标准化两次。

v4及同组v3仅更新文档、历史来源说明和相应文档指纹，处理代码未改。旧JSON验证中的v3路径是历史证据；`manifest/source-files/provenance`的旧路径表示指定Git提交中的来源，不能当作当前运行路径。当前验证见[拆分迁移验证](body-scan-pairs/validation-migration-v4.json)。

源码在本机编辑，模型、图像处理及测试在远程运行。先在仅包含三个保留快照的隔离目录测试，再同步当前服务器目录；不删除原图、缓存、历史实验和已生成成品，不重启网站。

## 查阅与恢复

历史目录：[网格v5](https://github.com/zmdo/smart-pos/tree/ec5dcb4cda00534b7547dbaaa54177b4d5cfe503/best-practices/grid-portrait)、[单图v3](https://github.com/zmdo/smart-pos/tree/ec5dcb4cda00534b7547dbaaa54177b4d5cfe503/best-practices/body-scan-wall)、[同组v2](https://github.com/zmdo/smart-pos/tree/ec5dcb4cda00534b7547dbaaa54177b4d5cfe503/best-practices/body-scan-group-display)。

如需复现旧版，在独立目录提取，避免混入当前最佳实践：

```bash
git archive ec5dcb4cda00534b7547dbaaa54177b4d5cfe503 best-practices/grid-portrait best-practices/body-scan-wall best-practices/body-scan-group-display | tar -x -C /path/to/empty-history-checkout
```

如需复现迁移前的拆分链，须从同一提交同时提取旧 `body-scan-pairs` 与 `body-scan-wall`，不能与当前v4绑定的拆分清单混用。

## 本轮验证

仅三个保留快照的隔离环境中：拆分21项、单图v4 63项、同组v3 51项，加开发版拆分21项，共156项测试通过。校验并导入的拆分公共模块来自隔离目录内的v4，不依赖服务器原有旧目录。

真实样本包含董彦琦硬拼接、张小飞硬拼接和任胜男待复核图。仅拆分与默认完整入口均得到2张硬拼接、4张无损子图、1张保持待复核；两种入口的子图字节相同。完整处理的4张成品及8张遮罩与已批准结果逐字节相同，父子坐标映射和矩形检查通过。张小飞白墙正面执行v4的 `verified_wall_regression` 回退。292个既有实验/线上成品文件校验未变。

本次验证不代表所有拼接都可自动识别；原不确定样本仍保留待复核。完整机器记录见拆分目录的 `validation-migration-v4.json`。

服务器当前目录已同步为上述三个节点，冻结/开发入口均可启动，6006与6008健康检查正常，未重启网站。部署前源码备份单独存于实验目录，不作为运行依赖。保留的单图v4及同组v3共90个Python文件与清理前一致；本轮改动只涉及拆分下游依赖、相关验收检查和文档。
