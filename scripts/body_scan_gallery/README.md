# 现有成品的分类样式预览

只读取一个已生成版本的 `result.json` 和成品图片，挑出六个槽位齐全的三视图案例，整理为离线 HTML。按门店/会员筛选，按完整三视图、同朝向对比、单张体测图分类，支持放大与下载。

本入口不导入生成器、分类模型或标准化模块，不改图、不改阶段。每套展示的三张 VS 和六张单图必须与三视图使用同一组素材。复制前后验证图片 SHA，原成品字节保持一致。

```bash
cd /root/apps/case-studio
/root/apps/non-grid-calibration/.venv/bin/python -m scripts.body_scan_gallery \
  --input /root/autodl-fs/case-studio/productions/body-review-20261106-v1/revisions/r0001 \
  --out /root/autodl-fs/case-studio/experiments/body-scan-three-view-style-v1-20261106
```

输出目录必须不存在。生成 `index.html`、本地 CSS/JS、`media/`、`cases.json`、`verification.json` 和可离线解压查看的 `preview.zip`。页面不依赖网络字体、外部资源或 API，可以直接打开 HTML。

当前基线包含 9 套完整案例、27 张同朝向对比、54 张匹配单图。默认展示六张均为规则标签的景田店／董彦琦；其他案例仍保留推断和待审标记。预览用于下一轮版式调整的对照，不更新生成模板或最佳实践。

无缝版三视图支持 PNG 与实际图片尺寸，页面根据成品元数据展示版式说明。v1 历史页面保持不变；新版输出到独立的 v2 预览目录。


同朝向参考版 v3 会自动默认打开 VS 标签页，展示固定宽度、可变高度成品；logo、地址和体检数据的缺失提示显示在图片外。可通过 `--default-case g013 --default-category vs` 指定首个案例和分类。原有无缝三视图、单图及下载保持可用。
