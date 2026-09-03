# 项目状态与新对话交接

更新时间：2026-09-03。研究总方针以根目录 `PROJECT_GUIDELINE.md` 为准，完整环境、
权重、数据与结果恢复命令以 `docs/REPRODUCIBILITY.md` 为准。

## 1. 一句话现状

项目已完成 M1–M4.2：DWT-DCT、TrustMark-Q、WAM 和改进方法 AM-WAM 已在统一接口下
运行；几何同步、内容自适应强度和多水印软聚类均已实现并有固定实验。formal-v1 已固定
140 张 calibration、690 张独立 test 和 44 条攻击，四模型正式比较已完成 121,440 条。
研究型 Web 前端 MVP 和最小 FastAPI 已可用；完整实验管理后端、Windows 安装包、
论文和答辩材料尚未完成。

## 2. 前后端现状

当前是“研究内核 + CLI + 实验脚本 + Web MVP”，还不是完整的实验管理应用。

| 层 | 状态 | 已有内容 | 下一步 |
|---|---|---|---|
| 算法内核 | 可用 | 统一模型接口、4 个研究模型、攻击与指标 | 继续做失败案例和论文消融 |
| 实验后端 | 可用 | manifest、校准、可恢复运行器、统计与绘图 | 固化正式结果快照 |
| CLI | 可用 | 状态、自检、协议和批量实验 | 保持为研发入口 |
| HTTP API | MVP 可用 | 健康检查、模型状态、单图真实实验、内存历史 | 持久任务状态、文件管理 |
| Web 前端 | MVP 可用 | React/Vite/TypeScript Dashboard、实验与结果页 | 扩大真实 API 覆盖、结果导出 |
| Windows 打包 | 未开始 | 无 | Web 版稳定后再评估 PyInstaller/桌面壳 |

目标调用链：

```text
React 前端 -> FastAPI 后端 -> watermark_lab 研究内核
                             -> 当前内存结果 / 后续 artifacts + SQLite 元数据
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
| M5.2 系统/论文 | 进行中 | Web/FastAPI MVP 已完成；持久化、报告和答辩材料待完成 |

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

## 5. 固定实验资产

```text
configs/                    冻结攻击、校准、M4 和 formal-v1 配置
data/manifests/             Debug10 与 formal-v1 固定清单、尺寸和 SHA-256
docs/                       实现、结果、复现和交接文档
scripts/                    数据恢复、校准、可恢复运行、统计和绘图入口
src/watermark_lab/models/   DWT-DCT、TrustMark-Q、WAM、AM-WAM
src/watermark_lab/api/      单图真实实验 FastAPI 适配层
src/watermark_lab/innovations/
                            几何同步、内容自适应和多水印软聚类
frontend/                   React/Vite/TypeScript 研究型 Dashboard
tests/                      单元、协议、模型与恢复运行测试
```

`data/raw/`、`checkpoints/`、`third_party/`、`results/` 和 `.venv*` 不进入 Git。共创者
必须按复现指南恢复；不得从聊天附件或来源不明的网盘文件替换正式资产。

## 6. 下一步优先级

### P0：正式结果维护

1. 论文和答辩数字只从 `docs/FORMAL_RESULTS.md` 与冻结统计 CSV 获取；
2. 需要共享原始结果时，打包 `results/formal_v1/` 并记录 SHA-256，不提交 Git；
3. 不在 formal-v1 test 上继续调参；新候选剪枝方案另建 calibration/test 协议。

### P1：系统后端

FastAPI MVP 已提供 `GET /api/health`、`GET /api/models`、`GET /api/experiments` 和
`POST /api/experiments/single`。下一步补充：

- `POST /api/watermarks/embed`、`POST /api/watermarks/decode`；
- `GET /api/experiments/{id}`；
- `GET /api/experiments/{id}/artifacts`。

后续持久化使用本机任务执行器和 SQLite/JSON，不提前引入 Redis/Celery。模型实例继续
复用，耗时任务不能阻塞 HTTP 请求线程。

### P2：Web 前端

React、Vite、TypeScript MVP 已提供环境状态、单图实验、固定攻击配置、模型/数据集
概览和结果展示。下一步将剩余 Mock 概览接入真实统计，并补充持久任务历史和结果导出。
前端只读取后端统计产物，不重写指标算法。

### P3：交付

Windows 一键启动脚本、可选安装包、课程报告、PPT、演示视频、引用/许可证清单、最终
Release 与结果压缩包 SHA-256。

## 7. 风险与边界

1. Web/FastAPI MVP 可运行不等于完整实验管理系统已完成。
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

已完成 M1–M4.2，以及 formal-v1 的 121,440 条正式比较和统计图。不要覆盖冻结
manifest、攻击、校准或 held-out 配置，不要把 Debug10 写成最终结论。开始修改前检查
git status；修改后运行 ruff check . 和 pytest。当前任务是：<在此写明任务>。
```

## 9. 最合适的开发入口

系统开发从 `src/watermark_lab/api/` 和 `frontend/` 继续，优先实现持久任务、独立
`embed/decode` 端点和结果导出；若先写论文，则直接使用 `docs/FORMAL_RESULTS.md`
中的正式数字和 `results/formal_v1/figures/` 中的图。
