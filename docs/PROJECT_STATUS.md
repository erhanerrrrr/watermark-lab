# 项目状态与新对话交接

更新时间：2026-09-04。研究总方针以根目录 `PROJECT_GUIDELINE.md` 为准，完整环境、
权重、数据与结果恢复命令以 `docs/REPRODUCIBILITY.md` 为准。

## 1. 一句话现状

项目已完成 M1–M4.2：DWT-DCT、TrustMark-Q、WAM 和改进方法 AM-WAM 已在统一接口下
运行；几何同步、内容自适应强度和多水印软聚类均已实现并有固定实验。formal-v1 已固定
140 张 calibration、690 张独立 test 和 44 条攻击，四模型正式比较已完成 121,440 条。
v0.2 本地展示平台已完成真实数据接入、持久化、导出与 Windows 一键启动。P0/P1 已补齐
formal-v1 审计、6,640 条独立正负检测和 3,840 条 robustness-v2 外推验证；课程论文、
答辩 PPT、演示视频和最终 Release 尚未完成。

## 2. 前后端现状

当前是“研究内核 + CLI + 批量实验脚本 + 可展示的本地 Web 平台”。Web 覆盖单图交互
实验；formal-v1 等长时批量任务仍通过可恢复 CLI 运行，不在 HTTP 请求中重复实现。

| 层 | 状态 | 已有内容 | 下一步 |
|---|---|---|---|
| 算法内核 | 可用 | 统一模型接口、4 个研究模型、攻击与指标 | 继续做失败案例和论文消融 |
| 实验后端 | 可用 | manifest、校准、可恢复运行器、统计与绘图 | 固化正式结果快照 |
| CLI | 可用 | 状态、自检、协议和批量实验 | 保持为研发入口 |
| HTTP API | 展示版完成 | 真实 catalog、SQLite 历史、PNG 产物、实验/嵌入/提取、CSV、数据校验 | 后续可选长任务队列 |
| Web 前端 | 展示版完成 | 六页真实 API、正式快照、实验、历史、产物、导出、错误状态 | 课程展示内容微调 |
| Windows 启动 | 完成 | 一键构建、单端口服务、浏览器启动、四段验收脚本 | 最终 Release 验证 |

目标调用链：

```text
React 前端 -> FastAPI 后端 -> watermark_lab 研究内核
                             -> artifacts/web PNG + SQLite 元数据
                             -> 冻结配置 / manifest / formal-v1 结果
```

API 层只编排现有 Python 接口，不复制模型算法。第一版面向单机 Windows 演示。

## 3. 已完成里程碑

| 阶段 | 状态 | 证据 |
|---|---|---|
| M1 框架 | 完成 | 统一接口、CLI、LSB 自检、自动测试 |
| M2 基线 | 完成 | DWT-DCT、TrustMark-Q、4×Debug10×44 攻击及公平强度校准 |
| M3 WAM | 完成 | 官方 MIT 权重接入、全协议诊断、负样本和失败探针 |
| M4.1 AM-WAM | 完成 | 盲几何同步、内容自适应强度、消融与 held-out 几何测试 |
| M4.2 多水印 | 完成 | 自适应软聚类、官方硬 DBSCAN 对比、2,560 条固定记录 |
| M5.1 正式比较 | 完成 | 690 test×44 攻击×4 模型，共 121,440 条，完整性检查通过 |
| M5.2 展示系统 | 完成 | v0.2 单端口 Web/API、真实数据源、SQLite/PNG、CSV、SHA-256、一键启动 |
| P0 正式审计/检测 | 完成 | 121,440 条审计通过；140 calibration + 690 test 正负检测，共 6,640 条 |
| P1 扩展鲁棒性 | 完成 | 24 条新攻击、40 张固定 test 图、4 模型，共 3,840 条与 2,000 次 Bootstrap |
| M5.3 课程交付 | 进行中 | 引用/许可清单已完成；课程论文、答辩 PPT、演示视频和最终 Release 待完成 |

## 4. 已确认研究结论

- 四种正式比较方法均按数据集在独立 calibration split 上校准到平均 PSNR 约 40 dB。
- M4.1 把 Debug10 逐图 PSNR 标准差从 1.517 dB 降到 0.224 dB；冻结参数后的未见
  连续几何测试中，完整恢复率由 86.67% 提高到 92.08%。
- M4.2 总体水印数量识别准确率由官方硬 DBSCAN 的 59.22% 提高到 67.97%；四水印
  场景由 50.31% 提高到 99.69%。
- M4.2 不是全面胜出：两/三水印会过分裂，5% 小水印区域仍无法全部恢复，匹配 Bit
  Accuracy 小幅下降，聚类平均增加约 403 ms。这些负结果已保留。
- formal-v1 中，AM-WAM 相对 WAM 的 Bit Accuracy 提高 0.188 个百分点（95% CI
  0.162–0.218），完整恢复率提高 1.604 个百分点（1.357–1.874）；10° 旋转完整恢复
  提高 49.42 个百分点，但平均解码增加约 914 ms，强模糊仍未改善。
- formal-v1 的完整结论以 `docs/FORMAL_RESULTS.md` 为准，不能用 Debug10 数字替代。
- clean 正负检测显示：WAM/AM-WAM 默认规则 FPR 为 3.91%/6.81%；冻结 1% calibration
  目标阈值后，独立 test FPR 为 1.30%/1.74%，TPR 均为 100%。TrustMark 的公开二值
  分数不能在本轮 1% 约束下同时保留 TPR。
- robustness-v2 中 AM-WAM 相对 WAM 的 Bit Accuracy 提升 1.989 pp、完整恢复率提升
  8.542 pp；非候选网格几何攻击提升 20.25 pp，但额外解码约 801 ms。

## 5. 固定实验资产

```text
configs/                    冻结攻击、校准、M4 和 formal-v1 配置
data/manifests/             Debug10 与 formal-v1 固定清单、尺寸和 SHA-256
docs/                       实现、结果、复现和交接文档
scripts/                    数据恢复、校准、可恢复运行、统计和绘图入口
src/watermark_lab/models/   DWT-DCT、TrustMark-Q、WAM、AM-WAM
src/watermark_lab/api/      FastAPI、展示目录、SQLite/PNG 持久化与模型编排
src/watermark_lab/innovations/
                            几何同步、内容自适应和多水印软聚类
frontend/                   React/Vite/TypeScript 研究型 Dashboard
artifacts/web/              本地交互实验数据库与图片产物（Git 忽略）
tests/                      单元、协议、模型与恢复运行测试
```

`data/raw/`、`checkpoints/`、`third_party/`、`results/` 和 `.venv*` 不进入 Git。共创者
必须按复现指南恢复；不得从聊天附件或来源不明的网盘文件替换正式资产。

## 6. P0/P1 完成状态与下一步

### P0：正式结果审计与检测（已完成）

1. `audit_formal_v1.py` 已验证结果键、manifest 隔离、环境、汇总和 Web 快照；
2. 已完成 6,640 条 clean 正负检测并冻结 1% calibration 目标阈值；
3. formal-v1 历史环境不一致和原始 dirty worktree 已如实固化，没有事后改写来源。

### P1：扩展鲁棒性与结果表达（已完成）

1. 新增 24 条 robustness-v2 攻击并完成 3,840 条四模型验证；
2. Web 结果页同时显示正式恢复、clean 检测误报和扩展几何外推；
3. 创新表述限定为几何失配收益，并同时报告误报、强模糊和解码开销。

### P2：课程交付

引用/许可证清单与 `REFERENCES.bib` 已完成。后续完成课程论文、答辩 PPT、演示视频、
最终 GitHub Release 与正式结果压缩包 SHA-256。Web 展示流程见 `docs/WEB_SHOWCASE.md`。

## 7. 风险与边界

1. v0.2 Web 已覆盖现场单图实验，但 formal-v1 批量运行仍属于 CLI 研究工作流。
2. 运行时间只在相同硬件/环境内比较；本次 WAM/AM-WAM 用 GPU，传统方法与 TrustMark
   用 CPU，不能把四者耗时画成统一硬件排名。
3. formal-v1 test 已冻结，看到结果后不得回改强度、阈值、样本或攻击；改进必须另建
   calibration/test 版本。
4. 多水印 5% 小区域、低消息数过分裂和组合攻击退化仍是明确未解决问题。
5. HiDDeN 因缺少满足官方实现、可验证权重、32-bit 盲提取和 Windows 可复现要求的
   可靠适配器，不进入本轮正式对比。

## 8. 新对话交接提示

```text
这是 Watermark Lab（数字图像水印课程设计）项目。先完整阅读：
1. PROJECT_GUIDELINE.md
2. docs/PROJECT_STATUS.md
3. docs/REPRODUCIBILITY.md
4. docs/FORMAL_RESULTS.md
5. 与任务相关的 M2/M3/M4 实现和结果文档

已完成 M1–M4.2、formal-v1 的 121,440 条正式比较、6,640 条独立检测、3,840 条
robustness-v2 验证和 v0.2 本地展示平台。不要覆盖冻结 manifest、攻击、校准或 held-out
配置，不要把 Debug10 写成最终结论。开始修改前检查 git status；修改后运行
scripts/verify_showcase_windows.ps1。当前任务是：<在此写明任务>。
```

## 9. 最合适的开发入口

系统展示从 `docs/WEB_SHOWCASE.md` 进入；若写论文，直接使用 `docs/FORMAL_RESULTS.md`
中的正式数字和 `results/formal_v1/figures/` 中的图。后续工程扩展优先考虑长任务进度、
实验删除/归档和 Release 打包，但这些不是当前现场展示的阻塞项。
