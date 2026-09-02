# Watermark Lab

面向复合攻击与局部篡改的数字图像水印课程设计项目。

研究总方针见 [PROJECT_GUIDELINE.md](PROJECT_GUIDELINE.md)。新成员应先阅读：

- [项目状态与新对话交接](docs/PROJECT_STATUS.md)
- [Windows 共创复现指南](docs/REPRODUCIBILITY.md)
- [数据来源与许可证](data/SOURCES.md)

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
- 当前研究内核和 CLI 可用；HTTP API、前端界面和 Windows 安装包尚未开始。

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

## Windows 快速开始

推荐使用 Python 3.12；当前支持 Python 3.10–3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[research,data,dev]"
python -m watermark_lab.cli status
python -m watermark_lab.cli self-check --model dwt_dct
python -m watermark_lab.cli protocol-status
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

首次创建 `trustmark_q` 模型时会下载 Adobe 官方权重。TrustMark 0.9.0 要求
NumPy `<2.0`，因此不要直接安装到其他项目共用的全局 Python 环境。

模型权重、原始数据、完整结果和虚拟环境不进入 Git。恢复全部本地资产和按阶段复现实验
时，严格按照 [共创者复现指南](docs/REPRODUCIBILITY.md) 执行。

## 项目结构

```text
configs/                 实验配置
docs/                    研究与工程文档
src/watermark_lab/
  attacks/               统一攻击实现
  core/                  类型、接口和注册表
  datasets/              数据清单和读取
  experiments/           实验运行与结果导出
  metrics/               图像质量与消息指标
  models/                水印模型适配器
tests/                   自动测试
```

目前没有 `frontend/` 或 `backend/` 目录。计划采用 React/Vite/TypeScript 前端和
FastAPI 后端，API 直接复用现有 Python 研究内核，路线图见
[项目状态与新对话交接](docs/PROJECT_STATUS.md)。

## 设计原则

- 所有模型使用同一接口和同一攻击协议。
- 每次正式实验保存随机种子、配置和样本清单。
- 不隐藏失败样本，不用主观挑图替代统计结果。
- 先完成可复现的最小闭环，再接入重量级模型。
