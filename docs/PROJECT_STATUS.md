# 项目状态与新对话交接

更新时间：2026-09-02。本文是面向共创者和后续 AI 对话的单一状态入口；研究总方针仍
以根目录 `PROJECT_GUIDELINE.md` 为准，环境与完整复现命令以
`docs/REPRODUCIBILITY.md` 为准。

## 1. 一句话状态

项目已经完成 M1–M3 和 M4 第一阶段的可运行研究闭环：DWT-DCT、TrustMark-Q、WAM、
AM-WAM 可在统一数据/攻击协议下比较；尚未完成 M4 多水印软聚类、正式大样本实验、
后端 API、前端界面和最终交付包装。

## 2. 当前前后端现状

当前代码是“研究内核 + 命令行工具”，不是完整的前后端应用。

| 层 | 当前状态 | 已有内容 | 缺口 |
|---|---|---|---|
| 算法内核 | 可用 | 统一模型接口、4 个核心模型、攻击、指标 | M4 第二阶段仍待完成 |
| 实验后端 | 可用 | manifest、实验运行器、CSV/JSON、分析脚本 | 缺少任务队列和持久任务状态 |
| CLI | 可用 | 状态、自检、manifest、协议、批量实验 | 适合研发，不是最终用户界面 |
| HTTP API | 未开始 | 无 | 需要 FastAPI 接口、校验、错误模型和任务管理 |
| 前端 | 未开始 | 无 | 需要上传、嵌入/提取、攻击对比、图表与任务进度页 |
| 桌面/安装包 | 未开始 | 无 | 可在 Web 版稳定后再做 Windows 打包 |

现有执行链：

```text
PowerShell / CLI / scripts
          ↓
watermark_lab 研究内核
          ↓
模型 + 数据 manifest + 攻击 + 指标
          ↓
results/ CSV / JSON
```

推荐目标架构：

```text
React + Vite + TypeScript 前端
              ↓ HTTP
FastAPI 后端（参数校验、任务状态、文件管理）
              ↓ 直接调用
现有 watermark_lab 研究内核
              ↓
本地 artifacts/ + SQLite 元数据
```

API 层不得复制模型算法；它只负责把请求转换为现有 Python 接口。第一版面向单机
Windows 演示，FastAPI 与前端分别启动，稳定后再评估 PyInstaller/桌面壳。

## 3. 已完成里程碑

| 阶段 | 状态 | 已完成证据 |
|---|---|---|
| M1 框架 | 完成 | 统一接口、CLI、LSB 自检、测试 |
| M2 基线 | Debug10 完成 | DWT-DCT + TrustMark-Q，4 数据集，44 攻击，3520 条 |
| M3 WAM | Debug10 诊断完成 | 官方固定权重、1760 条主记录、负样本与失败探针 |
| M4.1 AM-WAM | 完成 | 内容自适应强度、盲几何同步、消融和 held-out 测试 |
| M4.2 多水印 | 未完成 | 自适应软聚类、消息计数和配对评估待实现 |
| M5 正式实验/系统 | 未开始 | 大样本、前后端、论文图表、答辩材料待完成 |

当前自动测试共 38 项，最近一次提交前全部通过。项目固定 4 个 Debug10 manifest、每组
10 张图，并使用 1 个控制、35 个单一和 8 个复合攻击条件。

## 4. 已确认的研究结果

- DWT-DCT 与 TrustMark-Q 已校准到跨数据集平均 PSNR 约 40 dB，避免用不同可见强度
  做不公平比较。
- WAM 在相同 PSNR 下对多数数值攻击稳健，主要失败集中在强模糊、旋转/透视失配和
  个别内容相关样本。
- M4 的内容自适应强度把逐图 PSNR 标准差从 1.517 dB 降到 0.224 dB。
- M4 主消融中，组合模型在重点几何攻击上的完整恢复率从 82.0% 提升到 95.5%。
- 冻结参数后的未见连续几何测试中，完整恢复率从 86.67% 提升到 92.08%。
- 粗到细几何候选加速曾导致内容相关错误分流，未纳入最终方案；失败记录保留。

这些结论仍属于 40 张 Debug10 预实验，不能直接冒充最终论文的大样本结论。

## 5. 当前关键目录

```text
configs/                    冻结协议、校准值和消融配置
data/manifests/             已跟踪的固定样本清单和 SHA-256
docs/                       实施、结果、复现和交接文档
scripts/                    环境、下载、实验和分析入口
src/watermark_lab/models/   DWT-DCT、TrustMark、WAM、AM-WAM
src/watermark_lab/innovations/
                            几何同步与内容自适应模块
tests/                      38 项自动测试
```

`data/raw/`、`checkpoints/`、`third_party/`、`results/` 和 `.venv*` 仅存在于开发者本机，
恢复方式见 `REPRODUCIBILITY.md`。

## 6. 后续计划与优先级

### P0：协作基线（本轮）

- 维护复现指南、状态交接和 README 导航。
- 保证新克隆可重建环境、权重、数据和结果。
- 每次合并前运行测试与静态检查。

### P1：M4 第二阶段

- 基于像素级 32 bit 软 logits 实现多水印自适应软聚类。
- 定义多水印数量、消息匹配、局部掩膜真值与 Hungarian 配对指标。
- 增加原始 WAM、单模块和完整 AM-WAM 消融。
- 在独立 calibration/test 参数范围验证，避免对 held-out 反复调参。

### P2：M5 正式实验

- 扩大到预先固定的 COCO、DIV2K、DiffusionDB、W-Bench 样本。
- 冻结强度、检测阈值和攻击协议，运行 DWT-DCT、TrustMark、WAM、AM-WAM。
- 报告均值、标准差、配对 Bootstrap 95% CI、运行时和失败案例。
- 输出论文表格、图、可视化热力图和可审计结果快照。

### P3：后端 API

建议使用 FastAPI，最小端点为：

- `GET /api/health`：环境、模型和权重状态；
- `GET /api/models`：模型能力与参数范围；
- `POST /api/watermarks/embed`：上传图像并嵌入消息；
- `POST /api/watermarks/decode`：提取消息与定位热力图；
- `POST /api/experiments`：创建攻击/对比实验任务；
- `GET /api/experiments/{id}`：任务进度、错误和结果；
- `GET /api/experiments/{id}/artifacts`：CSV、图表和样例列表。

首版用单机后台执行器和 SQLite/JSON 状态即可；不要一开始引入 Redis/Celery。上传文件要
限制类型、尺寸和数量，模型加载应复用，耗时任务不能阻塞 HTTP 请求线程。

### P4：前端

建议使用 React、Vite、TypeScript：

1. 环境/模型状态页；
2. 单图嵌入与提取页，显示原图、水印图、PSNR、消息和定位热力图；
3. 攻击实验页，可选择固定协议而非任意修改正式协议；
4. 对比结果页，展示模型/数据集/攻击筛选、曲线、表格和失败样本；
5. 任务历史与结果导出页。

前端显示的指标必须直接读取后端产物，不能在浏览器里另写一套统计公式。

### P5：交付

- Windows 一键启动脚本和可选安装包；
- 课程报告、演示视频、PPT、引用与开源许可证清单；
- 最终仓库标签、Release 和结果压缩包 SHA-256。

## 7. 风险与不可误判项

1. 当前没有前端和 HTTP API；CLI 可运行不等于前后端已经完成。
2. 当前结果是 Debug10 预实验，正式样本量和独立划分仍未完成。
3. WAM 几何同步在 CPU 上明显增加解码耗时，正式报告必须展示准确率/成本权衡。
4. 局部拼接和 copy-move 的定位真值尚需严格定义，不能混用代理指标作最终结论。
5. 多水印软聚类仍是计划，不应在摘要中写成已经实现。
6. 原始数据、权重和逐图结果未存入 Git，新成员必须按复现指南恢复。
7. 修改冻结攻击或 held-out 配置必须新建版本并说明理由，不能覆盖旧证据。

## 8. 新开对话时可直接使用的交接提示

```text
这是 Watermark Lab（数字图像水印课程设计）项目。请先完整阅读：
1. PROJECT_GUIDELINE.md
2. docs/PROJECT_STATUS.md
3. docs/REPRODUCIBILITY.md
4. 与当前任务相关的 M2/M3/M4 实施和结果文档

当前已完成 M1、M2 Debug10、M3 WAM 诊断和 M4.1（几何同步 + 内容自适应强度）。
M4.2 多水印自适应软聚类、正式大样本实验、FastAPI 后端和 React 前端尚未完成。
不要把 Debug10 结果写成最终结论，不要覆盖冻结 manifest/攻击/held-out 配置。
开始修改前先检查 git status 和现有测试；修改后运行 ruff check . 与 pytest。
本次任务是：<在此写明任务>。
```

## 9. 下一次最合适的开发入口

若以研究创新优先，进入 M4.2，先写多水印数据结构、匹配指标和合成测试，再实现软聚类。
若以课程演示系统优先，先建立 FastAPI 最小骨架和 `health/models/embed/decode` 四个端点，
但必须直接复用现有 `watermark_lab` 内核。两条路线都不应修改已冻结的 M4 held-out 结果。
