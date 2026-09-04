# Watermark Lab 本地展示与 Web 开发指南

更新时间：2026-09-04。本文描述 v0.2 本地展示平台；研究实验的完整复现仍以
`docs/REPRODUCIBILITY.md` 为准。

## 1. 一键展示

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1
```

默认使用 `.venv-wam-gpu`，构建 React 生产版本，由 FastAPI 在同一个 `8000` 端口提供
页面和 API，并自动打开浏览器。按 `Ctrl+C` 结束服务。

其他运行时：

```powershell
# 演示 TrustMark-Q、DWT-DCT 和 LSB
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -Runtime trustmark

# 已构建前端时跳过 npm build
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -SkipBuild
```

WAM/AM-WAM 与 TrustMark 继续使用隔离环境。同一页面始终显示全部冻结正式结果，但交互
实验下拉框只启用当前 Python 环境真正可运行的模型。

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
7. 最后陈述强模糊、额外耗时和多水印小区域仍是研究边界。

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
.\.venv-trustmark\Scripts\python.exe -m pip install -e ".[api,dev]"
.\.venv-trustmark\Scripts\python.exe -m uvicorn watermark_lab.api.app:app --reload
```

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
- 模型不可选：当前虚拟环境缺少该模型运行时，不代表正式结果缺失；
- WAM 首次实验较慢：首次请求会加载官方权重，后续复用同一 GPU 后端；
- 前端改动未显示：去掉 `-SkipBuild` 重新启动；
- 数据校验失败：按 `docs/REPRODUCIBILITY.md` 恢复原图，不能用同名替代图片。
