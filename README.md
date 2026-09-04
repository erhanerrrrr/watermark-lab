# Watermark Lab

面向复合攻击与局部篡改的数字图像水印课程设计项目。

研究总方针见 [PROJECT_GUIDELINE.md](PROJECT_GUIDELINE.md)。新成员应先阅读：

- [项目状态与新对话交接](docs/PROJECT_STATUS.md)
- [Windows 共创复现指南](docs/REPRODUCIBILITY.md)
- [本地展示与 Web 开发指南](docs/WEB_SHOWCASE.md)
- [数据来源与许可证](data/SOURCES.md)
- [论文引用与第三方许可清单](docs/REFERENCES_AND_LICENSES.md)

## 当前状态

- 已建立统一模型、攻击、数据集、指标和实验接口。
- 已提供轻量 LSB 自检模型，用于验证完整实验管线。
- 已实现盲提取 DWT-DCT 传统基线，并达到目标 PSNR 区间。
- 已实现固定 CSV/SHA-256 数据集 manifest 和版本化复合攻击协议。
- 已接入 TrustMark-Q 适配器；官方运行时和权重通过可选依赖安装。
- 已完成 4 个数据集各 10 张、2 个模型、44 条攻击的 3520 条 M2 调试实验，
  并在每个数据集上将两种方法校准到平均 PSNR 约 40 dB。
- 已接入官方 WAM MIT 权重，在同 PSNR Debug10 上完成 1760 条攻击诊断、负样本检测
  和内容/强度失败探针。
- 已完成 M4 第一阶段 AM-WAM：加入保守门控的盲几何同步恢复和质量约束的内容自适应
  强度控制；40 张图、4 组消融、7 条重点攻击共生成 1120 条记录，并追加 960 条冻结
  参数后的未见连续几何攻击记录。
- 已完成 M4.2 多水印自适应软聚类：40 张图、4 个消息布局、8 条攻击和 2 个盲解码器
  共 2560 条记录；总体消息计数准确率由 59.22% 提升到 67.97%，同时如实保留低消息数
  过分裂和 5% 小区域恢复失败。
- 已完成 formal-v1 扩大数据正式比较：140 张 calibration、690 张独立 test、44 条攻击、
  4 个模型共 121,440 条完整记录；AM-WAM 相对 WAM 的 Bit Accuracy 提高 0.188 个
  百分点、完整恢复率提高 1.604 个百分点，同时平均解码增加约 914 ms。
- 已完成 P0 正式结果审计和独立检测评价：121,440 条结果与冻结快照审计通过；四模型
  clean 正/负检测共 6,640 条，使用 140 张 calibration 负样本冻结阈值，并在 690 组
  test 正负样本上报告 TPR、FPR、ROC-AUC 与 Wilson 置信区间。
- 已完成 P1 robustness-v2 扩展验证：新增 24 条离网格几何、空间随机局部、光度与
  打印/屏摄代理攻击；40 张固定 test 图、4 个模型共 3,840 条记录。AM-WAM 相对 WAM
  的 Bit Accuracy 提升 1.989 pp，完整恢复率提升 8.542 pp，额外解码约 801 ms。
- 已完成 v0.2 本地展示平台：React 六个页面全部接入真实 API/冻结配置，FastAPI 支持
  SQLite 历史、PNG 产物、详情查询、CSV 导出、独立嵌入/提取、manifest 下载与 SHA-256
  校验；生产前端由 FastAPI 同端口提供，Windows 脚本可一键构建并启动。

M2 的算法、参数和命令详见 [docs/M2_IMPLEMENTATION.md](docs/M2_IMPLEMENTATION.md)。
本轮数据、校准结果和攻击结论见 [docs/M2_DEBUG_RESULTS.md](docs/M2_DEBUG_RESULTS.md)。
WAM 接入与 Windows 复现见 [docs/M3_IMPLEMENTATION.md](docs/M3_IMPLEMENTATION.md)，
M3 定量结果和失败模式见 [docs/M3_DEBUG_RESULTS.md](docs/M3_DEBUG_RESULTS.md)。
M4 算法实现见 [docs/M4_IMPLEMENTATION.md](docs/M4_IMPLEMENTATION.md)，第一阶段消融与
Bootstrap 结果见 [docs/M4_DEBUG_RESULTS.md](docs/M4_DEBUG_RESULTS.md)。
冻结参数后的几何泛化结果见 [docs/M4_HELDOUT_RESULTS.md](docs/M4_HELDOUT_RESULTS.md)。
M4.2 的算法与边界见
[docs/M4_MULTI_MESSAGE_IMPLEMENTATION.md](docs/M4_MULTI_MESSAGE_IMPLEMENTATION.md)，定量结果见
[docs/M4_MULTI_MESSAGE_RESULTS.md](docs/M4_MULTI_MESSAGE_RESULTS.md)。扩大数据与正式比较协议见
[docs/FORMAL_EXPERIMENT.md](docs/FORMAL_EXPERIMENT.md)，121,440 条正式结果、置信区间、
正负结论和耗时权衡见 [docs/FORMAL_RESULTS.md](docs/FORMAL_RESULTS.md)。
独立检测结果见 [docs/FORMAL_DETECTION_RESULTS.md](docs/FORMAL_DETECTION_RESULTS.md)，
新攻击外推结果见 [docs/ROBUSTNESS_V2_RESULTS.md](docs/ROBUSTNESS_V2_RESULTS.md)，P0/P1
收口清单见 [docs/P0_P1_COMPLETION.md](docs/P0_P1_COMPLETION.md)。
论文统一使用根目录 [REFERENCES.bib](REFERENCES.bib) 中的引用键；模型、权重、数据集的
版本和许可边界以 [docs/REFERENCES_AND_LICENSES.md](docs/REFERENCES_AND_LICENSES.md) 为准。

## Windows 快速开始

推荐使用 Python 3.12；基础代码支持 Python 3.10–3.13，TrustMark 固定使用 Python 3.12
与 NumPy 1.x，不能与 WAM 正式兼容环境混装：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[research,data,dev]"
python -m watermark_lab status
python -m watermark_lab self-check --model dwt_dct
python -m watermark_lab protocol-status
pytest
```

TrustMark 使用独立环境安装：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_trustmark_windows.ps1
```

WAM/AM-WAM 使用另一个独立环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_wam_windows.ps1
```

精确恢复 formal-v1 记录的 WAM 核心运行时使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_formal_wam_windows.ps1
```

首次创建 `trustmark_q` 模型时会下载 Adobe 官方权重。TrustMark 0.9.0 要求
NumPy `<2.0`，因此不要直接安装到其他项目共用的全局 Python 环境。

模型权重、原始数据、完整结果和虚拟环境不进入 Git。恢复全部本地资产和按阶段复现实验
时，严格按照 [共创者复现指南](docs/REPRODUCIBILITY.md) 执行。

## 本地 Web 实验平台

展示模式只需一条命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1
```

脚本默认使用 WAM GPU 环境，构建前端、启动 FastAPI 并打开 `http://127.0.0.1:8000`。
TrustMark 展示使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -Runtime trustmark
```

展示前完整验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_showcase_windows.ps1
```

API 文档位于 `http://127.0.0.1:8000/docs`。启动 API 的 Python 环境决定交互实验当前
可用模型；全部正式比较数据始终从冻结结果加载。TrustMark-Q 与 WAM/AM-WAM 因固定依赖
不同继续使用隔离环境。开发模式、持久化位置与完整接口见
[本地展示与 Web 开发指南](docs/WEB_SHOWCASE.md)。

## 项目结构

```text
configs/                 实验配置
docs/                    研究与工程文档
frontend/                React/Vite/TypeScript 实验平台
artifacts/web/           SQLite 与交互实验 PNG（Git 忽略）
src/watermark_lab/
  api/                   FastAPI、真实数据目录、持久化与模型编排
  attacks/               统一攻击实现
  core/                  类型、接口和注册表
  datasets/              数据清单和读取
  experiments/           实验运行与结果导出
  metrics/               图像质量与消息指标
  models/                水印模型适配器
tests/                   自动测试
```

FastAPI 适配层直接位于 `src/watermark_lab/api/`，因此不另设 `backend/` 目录；它只
编排现有 Python 研究接口，不复制或修改模型算法。完整实验管理后端的后续路线见
[项目状态与新对话交接](docs/PROJECT_STATUS.md)。

## 设计原则

- 所有模型使用同一接口和同一攻击协议。
- 每次正式实验保存随机种子、配置和样本清单。
- 不隐藏失败样本，不用主观挑图替代统计结果。
- 先完成可复现的最小闭环，再接入重量级模型。
