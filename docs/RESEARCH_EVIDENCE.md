# 可筛选的研究证据

结果页新增“研究证据”面板，支持四个数据集和 44 条攻击交叉筛选，比较四方法，
同时显示 AM-WAM 与 WAM 的配对收益、95% CI、救回与退化数量。完整快照保存
225 行：全部数据集/四个单数据集 × 全部攻击/44 个单攻击。

## 数据与统计

- 来源：`results/formal_v1/{model}/{dataset}.csv` 的 121,440 条冻结正式记录。
- 输出：随源码保存的 `configs/research_evidence.json`，包含源文件 SHA-256。
- 校验：每模型的键必须严格等于 manifest 图像 × 冻结攻击全集；拒绝重复、错位、
  缺配对及非有限指标，仅记录数相等不能通过校验。
- 统计：同图同攻击配对，先对图像内攻击求均值，再按数据集分层进行 2,000 次
  Bootstrap；各数据集保持原图像数，总体按图像数加权。
- 解释：CI 衡量固定协议中的图像抽样不确定性，不包含未知攻击分布；单项探索
  区间没有多重比较校正，筛出的亮点不能当作新增确证性实验。
- 敏感性：逐个移除全部 44 个攻击，各自重新计算平均收益与 CI；Web 展示
  `rotation_10` 对照，完整列表可下载 JSON。原正式攻击和结果均不删除。

原报告使用未分层的 1,000 次图像 Bootstrap，本快照使用分层的 2,000 次，均值
一致、区间略有差异。新分析属于旧结果的事后描述性再分析，不增加独立测试样本。

## 生成与服务

```powershell
.\.venv-trustmark\Scripts\python.exe scripts/build_research_evidence.py
powershell -ExecutionPolicy Bypass -File scripts/start_showcase_windows.ps1
```

生成脚本仅读取冻结 CSV、manifest 与配置，写入独立证据文件。生成需要 research
依赖；显示证据只需 API 环境和快照，不加载模型、不下载数据、不在请求中 Bootstrap。

| 接口 | 内容 |
|---|---|
| `GET /api/research/evidence` | 已校验的完整证据 JSON |
| `GET /api/research/evidence/export.json` | 相同证据的附件下载 |

如果快照缺失、JSON 损坏或包含非有限值，接口返回 503，前端提供重试信息。
证据源固定为版本化快照，不混入本地交互实验；JSON 中的哈希描述生成时的来源，
并不意味着缺少完整资产的另一台机器已经核验了原始 CSV。

## 本轮数值

完整恢复平均增益 +1.604 pp，95% CI [+1.370, +1.871]；救回 594 条、退化 107 条。
移除 10° 旋转后 +0.492 pp，95% CI [+0.266, +0.752]。详细研究判断见
[完整性与创新深度评估](RESEARCH_DEPTH_AUDIT.md)。

当前展示的是修复前冻结结果。定位回投影和空检测分支融合修复后，没有重新生成
全量 formal-v1；后续实验须用新版本输出目录，详见
[几何输出修复记录](GEOMETRY_OUTPUT_CORRECTIONS.md)。
