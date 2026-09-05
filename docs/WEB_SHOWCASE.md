# Watermark Lab 本地展示与 Web 开发指南

更新时间：2026-09-05。本文描述 v0.2 本地展示平台及研究证据增量；研究实验的完整复现仍以
`docs/REPRODUCIBILITY.md` 为准。

模型库与首页现已突出 Budget-WAM 的 geometry-v3 独立验证，并自动同步当前服务的
模型目录与运行状态。页面版本范围、刷新机制及验证结果见
[前端对齐检查](WEB_ALIGNMENT_REVIEW.md)。

## 1. 一键展示

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1
```

默认依次寻找 `.venv-wam-formal`、`.venv-wam-gpu` 和 `.venv-wam`，构建 React 生产
版本，由 FastAPI 在同一个 `8000` 端口提供页面和 API，并自动打开浏览器。按 `Ctrl+C`
结束服务，同时回收 API 管理的 TrustMark 子进程。

默认 `auto` 模式会发现仓库中的 `.venv-trustmark`：主 API 使用 WAM 环境时，TrustMark
在其既有独立环境中运行，由同一个 API 调度，不需要额外端口。主环境和独立环境的依赖
均就绪时，六个模型可以在同一页面进行交互实验。启动时会探测 TrustMark 运行时，首次
嵌入或提取加载权重，后续请求复用子进程中的模型。

其他运行时：

```powershell
# 演示 TrustMark-Q、DWT-DCT 和 LSB
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -Runtime trustmark

# 已构建前端时跳过 npm build
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -SkipBuild

# 指定其他已有的 TrustMark Python 环境，仍以 WAM 运行主 API
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -TrustMarkPython "D:\watermark-envs\trustmark\Scripts\python.exe" -TrustMarkMode isolated
```

WAM 系列与 TrustMark 继续使用隔离环境。模型库和实验下拉框依据 API 路由后的实际
运行能力启用模型；TrustMark 子进程不可用时会给出原因，同一页面仍可查看冻结研究结果。
`-TrustMarkMode` 支持 `auto`、`isolated`、`local`、`disabled`；不传对应参数时保留已有
的环境变量设置。配置、故障恢复与环境边界见 [TrustMark 独立推理进程](TRUSTMARK_WORKER.md)。

## 2. 展示前验收

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_showcase_windows.ps1
```

该命令依次运行 Python Ruff、完整 pytest、前端 ESLint 和生产构建。任何一步失败都会以
非零状态退出。

## 3. 推荐演示顺序

1. 在“总览”说明 690 张 test、140 张 calibration、44 条攻击和 121,440 条正式记录；
2. 在“模型库”说明当前运行时与四种正式对比方法；
3. 在“攻击协议”展示 44 条冻结流水线，而不是只展示概念分类；
4. 在“数据集”展示 manifest 数量，并点击 SHA-256 校验；
5. 在“水印实验”上传一张至少 128×128 的图片，优先演示 AM-WAM + 10° 旋转；
6. 在“实验结果”展示三张产物、消息比特、PSNR/SSIM/BER/Bit Accuracy，并下载 CSV；
7. 在“实验结果”补充展示 clean 正负检测：默认 AM-WAM 规则有 6.81% FPR，冻结阈值后
   test FPR 为 1.74%，避免把正样本恢复率误称为低误报检测；
8. 展示 robustness-v2 的 24 条新攻击与 3,840 条验证，说明几何外推提升 20.25 pp，
   同时陈述强模糊、额外耗时和多水印小区域仍是研究边界。

## 4. 数据与持久化

交互实验保存在：

```text
artifacts/web/watermark_lab.sqlite3
artifacts/web/experiments/<experiment-id>/original.png
artifacts/web/experiments/<experiment-id>/embedded.png
artifacts/web/experiments/<experiment-id>/attacked.png
```

该目录已被 Git 忽略。可以用环境变量覆盖位置：

```powershell
$env:WATERMARK_LAB_STORAGE_DIR = "D:\watermark-lab-runtime"
```

不要把交互实验数据库误当作 formal-v1 原始结果。正式结果仍位于 `results/formal_v1/`，
并由 `configs/showcase.yaml` 提供可版本控制的只读快照回退。

## 5. 前后端开发模式

后端：

```powershell
# 使用已准备好的 WAM 主环境；TrustMark 由 API 自动发现并在独立环境执行
.\.venv-wam-gpu\Scripts\python.exe -m uvicorn watermark_lab.api.app:app --reload
```

环境准备仍按 `docs/REPRODUCIBILITY.md` 进行；跨环境路由不要求把 TrustMark 安装到
WAM 环境，也不需要调整既有 NumPy 或 Python 版本。

另开终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

Vite 会把 `/api` 代理到 `127.0.0.1:8000`。生产展示不需要 Vite 开发服务器。

## 6. 当前 API

- `GET /api/health`：服务、持久化和前端构建状态；
- `GET /api/catalog`：模型、数据集、攻击协议与冻结正式结果；
- `POST /api/datasets/verify`：逐文件 SHA-256 校验；
- `GET /api/datasets/{id}/manifest/{split}`：下载固定 manifest；
- `GET /api/experiments`：持久化实验摘要；
- `GET /api/experiments/{id}`：实验详情和产物 URL；
- `GET /api/experiments/export.csv`：导出交互实验；
- `POST /api/experiments/single`：嵌入、攻击、提取和评价闭环；
- `POST /api/watermarks/embed`：独立嵌入；
- `POST /api/watermarks/decode`：独立盲提取。

交互文档位于 `http://127.0.0.1:8000/docs`。

## 7. 常见问题

- 页面显示“API 未连接”：确认 8000 端口未被占用，并点击顶部连接状态重试；
- 模型不可选：查看模型库中 API 返回的运行原因；TrustMark 需要可用的独立解释器和依赖，
  或当前解释器中可用的本地运行时，不代表正式结果缺失；
- TrustMark 请求返回 503：独立进程启动、模型加载或推理失败时不会让整个 API 退出；
  修复配置或环境后可重试，详情见 [TrustMark 故障排查](TRUSTMARK_WORKER.md#故障排查)；
- WAM 首次实验较慢：首次请求会加载官方权重，后续复用同一 GPU 后端；
- 前端改动未显示：去掉 `-SkipBuild` 重新启动；
- 数据校验失败：按 `docs/REPRODUCIBILITY.md` 恢复原图，不能用同名替代图片。

## 8. 2026-09-05 研究证据增量

结果页现可交叉筛选四数据集与 44 条攻击，展示四模型指标、AM-WAM−WAM 图像级
Bootstrap 区间、救回/退化，以及排除 10° 旋转的敏感性分析。新接口为
`GET /api/research/evidence` 和 `GET /api/research/evidence/export.json`。
`configs/research_evidence.json` 是可随源码分发的冻结再分析快照，不需要恢复
原图与模型即可展示。生成命令、统计差异与边界见 [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md)。

## 9. Budget-WAM 与 geometry-v3

模型库新增 `budget_wam`。使用 WAM GPU 环境启动后，单图实验可选择新模型及
黑色填充、反射填充、裁边缩放旋转，角度步长 0.1°。结果页展示候选执行顺序、
预算、停止原因与校准检测阈值；模型运行时核验策略源码摘要及阈值一致性。

结果页的 geometry-v3 面板展示 80 张新 test 图的六方法对照、按攻击家族或数据集
切换的恢复差值与区间、停止原因分析，以及单独的真实在线计时。新证据端点：

- `GET /api/research/geometry-v3`
- `GET /api/research/geometry-v3/export.json`

便携快照为 `docs/evidence/geometry_v3.json`，原始轨迹和计时在
`results/geometry_v3/`。缺失或无效证据返回 503。详细结果见
[GEOMETRY_V3_RESULTS.md](GEOMETRY_V3_RESULTS.md)。

本轮校准/计时使用 `.venv-wam-gpu`，需要直接复现该环境时在仓库根目录运行：

```powershell
.\.venv-wam-gpu\Scripts\python.exe -m uvicorn watermark_lab.api.app:app --host 127.0.0.1 --port 8001
```

服务启动后可运行 `scripts/verify_geometry_v3_web.py`：它使用预定首张 calibration
图做旧/新方法演示，核验两者的嵌入和攻击像素相同、结果可读取、盲提取不需要
预期消息，以及证据下载一致。该演示不计入独立 test 指标。
