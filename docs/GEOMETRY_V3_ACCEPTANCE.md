# geometry-v3 验收记录

日期：2026-09-05。结果见 [GEOMETRY_V3_RESULTS.md](GEOMETRY_V3_RESULTS.md)，实现与
复现见 [GEOMETRY_V3_IMPLEMENTATION.md](GEOMETRY_V3_IMPLEMENTATION.md)。

## 实验与来源

- 48 calibration / 80 test 图像收集完成；test 1,600 条共享候选轨迹，每条含 10 候选。
- 六方法回放评价 9,600 条记录，其中每方法 1,280 条正样本、320 条负样本。
- test 开始前冻结的协议、源码和策略等 16 个文件 SHA-256 一致；48 份 calibration
  轨迹摘要未改变，导出证据的全部来源摘要核验通过。
- 12 图 × 4 攻击 × 2 轮 × 4 解码方法，共 384 次在线推理；消息与重放逐位一致，
  Budget-WAM 候选数一致，嵌入/攻击像素哈希一致。

## 工程检查

`scripts/verify_showcase_windows.ps1` 通过 Python Ruff、**145 项测试**、前端 ESLint
及 TypeScript/Vite 生产构建。最后追加的深链接滚动与报告格式调整，重新通过其
相关 lint/build/报告生成检查。原 `scripts/audit_formal_v1.py` 再次通过：
**121,440 条原正式记录完整，未混入 geometry-v3**。

单图 API 增加黑色、反射、裁边缩放旋转；12 组横/竖图像与正/负角度测试核对了
交互实现和冻结研究变换逐像素一致。负 SSIM 保存失败的接口缺陷已修复并回归验证。

## 真实 HTTP 闭环

在 `.venv-wam-gpu` 启动的 `http://127.0.0.1:8001/` 上运行
`scripts/verify_geometry_v3_web.py`，结果保存在
[`artifacts/geometry-v3-web/qa.json`](../artifacts/geometry-v3-web/qa.json)。

使用预定首张 calibration/COCO 图，8.3° 黑色填充旋转，同一消息和嵌入强度：

| 项目 | 旧 AM-WAM | Budget-WAM |
|---|---|---|
| 完整消息恢复 | 否，BA 96.875% | 是，BA 100% |
| 实验 ID | EXP-260905-7F192F51E0 | EXP-260905-3C0973B1CC |

两次演示的原图、嵌入图与攻击图逐像素相同。新方法使用 3/7 次候选，选中 −6°
校正分支。随后只提交攻击图、不提交预期消息的独立盲提取也成功；返回的评价字段
为 null，没有把事后真值传入解码器。证据下载 JSON 与 API 返回一致，保存结果可
再次查询。以上是校准图上的演示，不计入独立 test 统计。

## 页面核对

实际 Edge 页面已核对单图结果、3/7 决策轨迹、六方法表、正负收益与误报区间。
页面截图：

- [单图演示](../artifacts/geometry-v3-web/desktop-demo.png)
- [独立研究证据](../artifacts/geometry-v3-web/desktop-evidence.png)

本轮未完成窄屏实机和所有筛选交互的可视验收；这些部分不列为已验证。结果页新增
`#geometry-v3` 深链接，证据加载后定位到对应面板，前端构建检查通过。

科学图的 PNG/PDF 已生成，PNG 已逐图检查；字段与版本化证据一致。原文书生成
脚本和现有 Word/PPT 文件没有被改写。课程材料应引用 geometry-v3 的适用条件、
未通过的统计非劣判断和 4/80 图像误报，不能改写为“零误报”或“无损加速”。
