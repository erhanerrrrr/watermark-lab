# TrustMark 独立推理进程

主 API 可继续使用 `.venv-wam-gpu` 等 WAM 环境，通过受控子进程调用既有
`.venv-trustmark` 中的 TrustMark-Q。同一个网页可以选择全部六个模型；模型库根据
API 的运行时探测结果显示可用性。模型推理成功仍以实际请求为准，运行时探测不会预先
执行完整的权重加载与推理。

## 运行结构

```text
浏览器 → 同一个 FastAPI API
            ├─ LSB / DWT-DCT / WAM / AM-WAM / Budget-WAM：主 Python 环境
            └─ TrustMark-Q：TrustMark Python 子进程
```

API 与子进程通过标准输入和标准输出交换带请求编号的 JSON 消息，图像使用无损 PNG
传输。子进程不开放额外 HTTP 端口；算法仍调用项目现有 TrustMark 适配器，没有改写
水印算法、冻结实验协议、权重或研究结果。独立环境保留自己的 Python、NumPy、Torch
与 TrustMark 依赖，不需要将两套环境合并。

API 负责子进程的启动、健康探测、请求调度和关闭回收。首次推理加载模型，后续请求
复用进程内模型缓存；子进程顺序执行请求，主 API 保留现有模型推理并发约束。正常结束
API 时会关闭子进程，异常退出、通信故障或超时会使当前请求返回 503，后续请求可重新
启动工作进程。研究结果展示不依赖 TrustMark 推理进程存活。

运行时探测超时为 45 秒，单次通信/推理超时为 180 秒；故障后最少等待 5 秒再由目录
探测触发后台恢复。目录读取使用已探测的状态，避免等待正在执行的推理。TrustMark
请求使用独立进程自己的串行调度，不占用主服务的 GPU 模型锁。

TrustMark 设备由独立环境自动选择，当前既有环境为 CPU。HTTP 的 `device=auto`
使用该实际设备；显式请求不匹配的设备会返回 422。结果元数据分别记录实际 `device`
与 `requested_device`，同时记录独立进程 PID 和 Python 版本。

## 默认启动

两套环境已经按 `REPRODUCIBILITY.md` 准备好后，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -Runtime wam -Port 8001
```

主 API 默认依次选择 `.venv-wam-formal`、`.venv-wam-gpu`、`.venv-wam`。TrustMark
默认使用 `auto` 模式，寻找仓库根目录下的 `.venv-trustmark\Scripts\python.exe`
（Linux/macOS 为 `.venv-trustmark/bin/python`）。解释器与当前 API 不同时启用独立
进程；没有单独的解释器时按本地运行能力判断。需要直接指定主 API 环境时也可以使用：

```powershell
.\.venv-wam-gpu\Scripts\python.exe -m uvicorn watermark_lab.api.app:app --host 127.0.0.1 --port 8001
```

启动后查看 `/api/catalog` 或“模型库”的运行状态。命令行 `python -m watermark_lab status`
检查的是调用它的本地环境，不能代替 API 对跨环境路由的探测。

## 配置

| 环境变量 | 启动脚本参数 | 含义 |
|---|---|---|
| `WATERMARK_LAB_TRUSTMARK_PYTHON` | `-TrustMarkPython` | 指定已有的 TrustMark Python 可执行文件，覆盖自动发现路径 |
| `WATERMARK_LAB_TRUSTMARK_MODE` | `-TrustMarkMode` | `auto`（默认）、`isolated`、`local` 或 `disabled` |

| 模式 | 行为 |
|---|---|
| `auto` | 有不同的 TrustMark 解释器时使用独立进程，否则尝试当前 Python 运行时 |
| `isolated` | 强制使用独立进程；可以显式指定当前 Python 可执行文件，也会创建子进程 |
| `local` | 强制在主 API 的 Python 中执行，适用于原有 TrustMark 单环境运行方式 |
| `disabled` | 禁用 TrustMark 交互推理，保留其研究证据展示 |

例如，使用其他位置已经准备好的环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_showcase_windows.ps1 -Runtime wam -TrustMarkPython "D:\watermark-envs\trustmark\Scripts\python.exe" -TrustMarkMode isolated
```

`-TrustMarkPython` 的相对路径按仓库根目录解析。脚本仅在显式传入相应参数时覆盖对应
环境变量，因此从终端预先设置的配置会被保留。也可先设置环境变量，再直接启动 uvicorn：

```powershell
$env:WATERMARK_LAB_TRUSTMARK_PYTHON = "D:\watermark-envs\trustmark\Scripts\python.exe"
$env:WATERMARK_LAB_TRUSTMARK_MODE = "isolated"
.\.venv-wam-gpu\Scripts\python.exe -m uvicorn watermark_lab.api.app:app --host 127.0.0.1 --port 8001
```

解释器与路由模式属于服务配置；修改后需要重启 API。跨环境调度本身不执行依赖安装
或升级，现有展示启动脚本对主环境的 Web 依赖检查行为保持不变。

## 故障排查

- **模型库显示不可用**：先查看 API 给出的原因，检查指定的 Python 文件是否存在，
  再确认该解释器可导入 `trustmark` 和项目源码。错误路径或缺失依赖不会自动修改环境。
- **首次推理失败**：运行时探测通过不代表权重一定可加载；检查 TrustMark 权重缓存、
  文件权限和主 API 的服务日志。修复后重试实际嵌入或提取。
- **超时或子进程退出**：该请求返回 503；API 回收失效进程，后续请求可重新创建。
  其他模型和已保存实验仍由主 API 提供。
- **CLI 仍提示 TrustMark 未安装**：WAM 主解释器中未安装 TrustMark 是预期隔离状态；
  以 `/api/catalog` 和真实 TrustMark API 请求判断网页能否使用。
- **只想使用原有单环境行为**：启动时传 `-Runtime trustmark -TrustMarkMode local`。

## 验证范围

2026-09-05 完成：

- Python Ruff、207 项完整测试、前端 ESLint 和 TypeScript/Vite 生产构建通过。
- 真实轻量子进程测试覆盖分帧、并发请求、退出恢复、读写超时、错误响应和 Windows
  实际解释器子进程回收；API 测试覆盖三端点路由、故障不保存记录和其他模型仍可用。
- 在同一个 `http://127.0.0.1:8001` 上，六种模型均完成自然图像 clean 嵌入—提取闭环，
  32 bit 消息完整恢复，历史详情、三张 PNG 和 CSV 导出可读取。
- TrustMark 独立嵌入后，只提交水印图执行盲提取，消息逐位一致，事后评价字段为 null。
  后续完整实验复用了同一 worker。示例记录：`EXP-260905-784FA4B15B`。
- 实际版本仍为 WAM 主环境 Python 3.13 / NumPy 2.4.4 / Torch 2.11.0+cu128；
  TrustMark 环境 Python 3.12 / NumPy 1.26.4 / Torch 2.5.1+cpu / TrustMark 0.9.0。
- 六页面 DOM 回归确认 6/6 状态、TrustMark 可选及独立 CPU 标签、导航刷新与证据筛选。
  这不等同于真实浏览器窄屏或截图验收。

真实请求记录见 [qa.json](../artifacts/trustmark-web/qa.json)，前端行为记录见
[client-qa.json](../artifacts/trustmark-web/client-qa.json)。复验命令：

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\verify_trustmark_web.py --image "一张本地自然图像.png"
```

该验证使用一张最长边缩至 512 的图像，耗时包含不同模型的首次加载差异，仅用于工程
验收；不会作为新的 formal-v1 或 geometry-v3 研究指标。
