# 共创者复现指南（Windows）

本文用于让新的共创者从一个全新克隆开始，恢复项目的 Python 环境、模型权重、固定
Debug10 数据集和 M2–M4 实验结果。研究结论以版本化配置、manifest 和逐图原始记录为
准，不以手工挑选的示例图为准。

## 1. 仓库保存什么

| 内容 | 是否进入 Git | 恢复方式 |
|---|---|---|
| 源代码、测试、配置 | 是 | 克隆仓库 |
| Debug10 manifest 与 SHA-256 | 是 | 位于 `data/manifests/` |
| 原始图像 | 否 | 运行固定下载脚本 |
| TrustMark/WAM 权重 | 否 | 运行环境脚本并校验权重 |
| `results/` 逐图结果 | 否 | 按本文命令重新生成 |
| 汇总结论 | 是 | 位于 `docs/M2_*`、`docs/M3_*`、`docs/M4_*` |
| `.venv*` 虚拟环境 | 否 | 每位开发者在本机重新创建 |

这些目录被忽略是为了避免提交许可证受限的图片、数百 MB 权重、平台相关环境和可重新
生成的实验文件。不要用网盘拷贝他人的 `.venv`；虚拟环境包含本机绝对路径，无法可靠
迁移。

## 2. 前置条件与克隆

参考复现平台为 Windows 10/11 x64、PowerShell、Git、Python 3.12。代码支持 Python
3.10–3.12，但同一次对比实验必须统一 Python 和 PyTorch 版本。CPU 路径是基准路径；
WAM 几何搜索在 CPU 上较慢。建议预留至少 10 GB 磁盘空间。

```powershell
git clone https://github.com/erhanerrrrr/watermark-lab.git
Set-Location watermark-lab
git status
py -0p
```

协作者提交前应使用自己的 GitHub 身份，不要沿用其他人的本地身份：

```powershell
git config user.name "你的 GitHub 用户名"
git config user.email "你的 GitHub noreply 邮箱"
```

## 3. 三类虚拟环境

| 环境 | 用途 | 创建方式 |
|---|---|---|
| `.venv` | DWT-DCT、CLI、快速测试 | 手工创建轻量环境 |
| `.venv-trustmark` | M2 的 DWT-DCT 与 TrustMark-Q | `setup_trustmark_windows.ps1` |
| `.venv-wam` | M3 WAM 与 M4 AM-WAM | `setup_wam_windows.ps1` |

轻量环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[research,data,dev]"
.\.venv\Scripts\python.exe -m watermark_lab status
.\.venv\Scripts\python.exe -m pytest
```

TrustMark 与 WAM 使用不同环境，避免它们的 NumPy/PyTorch 依赖互相污染：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_trustmark_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup_wam_windows.ps1
```

两个脚本默认安装 PyTorch 2.5.1 CPU 和 Torchvision 0.20.1。若正式实验改用 CUDA，须
在运行元数据中记录显卡、驱动和 PyTorch CUDA 构建；不要把 CPU 与 GPU 耗时直接合并
比较。

## 4. 模型权重

### 4.1 DWT-DCT

DWT-DCT 是本仓库实现的确定性传统算法，没有预训练权重。

### 4.2 TrustMark-Q

项目固定 `trustmark==0.9.0`、Q 变体、BCH_5 和 32 bit 有效消息。首次执行下列命令时，
官方包会从 CAI 资源服务器下载文件到
`.venv-trustmark/Lib/site-packages/trustmark/models/`，并使用包内 MD5 表检查文件：

```powershell
.\.venv-trustmark\Scripts\python.exe -m watermark_lab self-check `
  --model trustmark_q --output-dir results\m2_trustmark_smoke
```

本项目验收过的 Q 权重 SHA-256 如下：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `encoder_Q.ckpt` | 17,302,074 | `dc382c3f6b4fd568b27d6fbb763d6ffc2d2587126d84afe9d5ee95b4c5d99826` |
| `decoder_Q.ckpt` | 47,652,460 | `e3d9cea5406a26590735719f8f15cb10802b11852ae69047eaf4cf17214df781` |
| `trustmark_rm_Q.ckpt` | 77,081,406 | `cb23dc28b69104ae551286f63da6e965d269f715a87748e3ae7fe0d790f7dc9a` |

### 4.3 WAM/AM-WAM

WAM 和 AM-WAM 共用 Meta 官方 MIT 权重。安装脚本会检出固定源码提交、下载权重并
强制验证 SHA-256：

| 项目 | 固定值 |
|---|---|
| 官方提交 | `2c08af04d037d5667c02f6ddebbda9ff04581c3e` |
| 权重路径 | `checkpoints/wam/wam_mit.pth` |
| 权重字节数 | 377,825,938 |
| SHA-256 | `90ef232384e023bd63245eb0c131abd69d2afc7b8f17a71ccedceb542bf009e2` |

首次推理验收：

```powershell
.\.venv-wam\Scripts\python.exe -m watermark_lab self-check `
  --model wam --output-dir results\m3_wam_smoke
```

权重哈希不一致时不要绕过校验。删除单个损坏权重后重新运行对应安装脚本。

## 5. 固定原始数据与 manifest

Debug10 包含 COCO 2017 val、DIV2K validation HR、DiffusionDB 2M 和 W-Bench 各 10
张。样本选择和许可证说明见 `data/SOURCES.md`。下载脚本可重复执行，已有完整文件会被
复用：

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\download_debug_datasets.py
```

下载后应存在：

```text
data/raw/debug10/coco2017_val/                 10 张
data/raw/debug10/div2k_valid_hr/               10 张
data/raw/debug10/diffusiondb_2m/               10 张
data/raw/debug10/w_bench_det_inversion/        10 张
```

四个固定 manifest 已进入 Git。校准和实验脚本使用 `verify_sha256=True`，任何缺图、重压缩
或替换都会直接报错。正式扩大数据集时，先固定 calibration/test 划分，再通过
`watermark-lab build-manifest` 生成新的版本化清单；不得在看过测试结果后重新挑图。

## 6. 从零复现 M2–M4

以下命令均从仓库根目录执行。先完成环境、权重、数据和测试，再运行耗时实验。

### 6.1 M2：DWT-DCT 与 TrustMark-Q

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --models dwt_dct trustmark_q --iterations 7

.\.venv-trustmark\Scripts\python.exe scripts\run_m2_debug_benchmark.py `
  --models dwt_dct trustmark_q

.\.venv-trustmark\Scripts\python.exe scripts\analyze_m2_debug_results.py
```

预期主产物是 `results/m2_debug/all_records.csv`，记录数为
`2 模型 × 4 数据集 × 10 图 × 44 攻击 = 3520`。

### 6.2 M3：WAM 诊断

```powershell
.\.venv-wam\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --models wam --iterations 7

.\.venv-wam\Scripts\python.exe scripts\run_wam_debug_diagnostics.py --device cpu
.\.venv-wam\Scripts\python.exe scripts\run_wam_negative_controls.py --device cpu
.\.venv-wam\Scripts\python.exe scripts\analyze_m3_results.py
.\.venv-wam\Scripts\python.exe scripts\probe_wam_failures.py --device cpu
```

WAM 的完整 44 攻击主记录数为 `4 × 10 × 44 = 1760`，输出位于
`results/m3_wam_debug/`。

### 6.3 M4：几何同步与内容自适应强度

```powershell
.\.venv-wam\Scripts\python.exe scripts\run_m4_ablation.py `
  --config configs\m4_ablation.yaml --device cpu

.\.venv-wam\Scripts\python.exe scripts\analyze_m4_results.py `
  --results-dir results\m4_ablation_v2
```

Debug10 主消融为 `4 组 × 40 图 × 7 攻击 = 1120` 条。冻结参数后的未见连续几何测试：

```powershell
.\.venv-wam\Scripts\python.exe scripts\run_m4_ablation.py `
  --config configs\m4_heldout_ablation.yaml --device cpu

.\.venv-wam\Scripts\python.exe scripts\analyze_m4_results.py `
  --results-dir results\m4_heldout_geometry `
  --geometry-attacks rotation_5_unseen rotation_7_unseen `
  rotation_minus7_unseen perspective_05_unseen perspective_08_unseen `
  rotation7_resize80_jpeg70_unseen
```

该测试应产生 `4 组 × 40 图 × 6 攻击 = 960` 条记录。

## 7. 结果验收基准

不同 CPU/GPU 的耗时会变化，浮点指标允许有微小差异；记录数、输入哈希、协议版本和
总体趋势必须一致。

| 阶段 | 关键验收值 | 详细依据 |
|---|---|---|
| M2 | 两个模型平均嵌入 PSNR 均约 40 dB；3520 条 | `M2_DEBUG_RESULTS.md` |
| M3 | WAM 平均嵌入 PSNR 40.019 dB；1760 条 | `M3_DEBUG_RESULTS.md` |
| M4 主消融 | A3 几何攻击完整恢复率 95.5%；1120 条 | `M4_DEBUG_RESULTS.md` |
| M4 未见参数 | A3 完整恢复率 92.08%；960 条 | `M4_HELDOUT_RESULTS.md` |

若指标不一致，先比较 `git rev-parse HEAD`、manifest SHA-256、攻击配置、校准 JSON、权重
哈希和设备，不要直接修改阈值来“对齐”结果。

## 8. 保存和共享实验产物

每次要共享的正式运行至少保留：

- Git 提交哈希和未提交改动状态；
- 配置文件副本、随机种子、数据 manifest；
- 逐图 CSV、汇总 CSV/JSON 和 `run_metadata.json`；
- Python/PyTorch/设备信息以及 `pip freeze`；
- 失败样本，不只保留成功样本。

```powershell
git rev-parse HEAD
git status --short
.\.venv-wam\Scripts\python.exe -m pip freeze `
  | Out-File -Encoding utf8 results\environment-wam.txt
$ResultArtifact = Join-Path (Split-Path -Parent (Get-Location)) `
  "watermark-lab-results-debug10.zip"
Compress-Archive -Path results\* -DestinationPath $ResultArtifact
Get-FileHash -Algorithm SHA256 $ResultArtifact
```

`results/` 默认不进入 Git。需要交换完整快照时，使用带提交哈希和 SHA-256 的压缩包或
GitHub Release 附件；汇总表和最终论文图表经过确认后再选择性版本化。

## 9. 共创开发约定

1. 从 `main` 新建功能分支，提交只包含一个清晰目的。
2. 修改模型时同时增加测试，并运行 `ruff check .` 与 `pytest`。
3. `configs/attacks.yaml`、Debug10 manifest 和 held-out 配置属于冻结证据；若协议变化，
   新建版本，不覆盖旧版本。
4. 不提交原始数据、权重、虚拟环境、缓存、临时结果或密钥。
5. 提交信息和 Git 作者使用实际开发者身份，便于课程项目确认贡献。

常见问题：PowerShell 阻止脚本时使用本文的 `-ExecutionPolicy Bypass`；路径或第三方包在
中文目录下报错时，可把仓库重新克隆到短的 ASCII 路径；WAM CPU 内存不足时先用
`--limit-per-dataset 1` 验证 M4 管线，但该结果不能替代完整实验。
