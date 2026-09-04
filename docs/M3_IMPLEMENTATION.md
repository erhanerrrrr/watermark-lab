# M3 WAM 接入说明

## 1. 固定的官方版本

本项目使用 Meta 官方 [Watermark Anything](https://github.com/facebookresearch/watermark-anything)
实现与 SA-1B 训练的 MIT 权重：

| 项目 | 固定值 |
|---|---|
| 官方仓库提交 | `2c08af04d037d5667c02f6ddebbda9ff04581c3e` |
| 权重 | `wam_mit.pth` |
| 权重大小 | 377,825,938 bytes |
| SHA-256 | `90ef232384e023bd63245eb0c131abd69d2afc7b8f17a71ccedceb542bf009e2` |
| 消息长度 | 32 bit |
| 检测输入 | 256×256 |
| 许可证 | 代码和 `wam_mit.pth` 均为 MIT |

官方仓库在 2026-09-01 已处于 archived 状态，因此项目同时固定提交哈希、权重哈希和
依赖版本，避免未来主分支或下载地址变化影响复现。完整机器可读配置位于
`configs/wam_official.yaml`。论文统一引用键为 `sander2025watermark`，见
[`REFERENCES.bib`](../REFERENCES.bib) 与
[`REFERENCES_AND_LICENSES.md`](REFERENCES_AND_LICENSES.md)。

## 2. Windows 环境

推荐执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_wam_windows.ps1
```

脚本执行以下工作：

1. 创建独立 `.venv-wam`；
2. 安装 PyTorch 2.5.1 CPU、Torchvision 0.20.1 和最小推理依赖；
3. 检出固定官方提交；
4. 下载 MIT 权重并验证 SHA-256；
5. 检查统一模型注册状态。

当前实测环境为 Windows 11、Python 3.12.10、PyTorch 2.5.1 CPU。CUDA 不是运行
课程实验的强制条件；如使用 GPU，可在创建 `WamModel` 时传入 `device="cuda"`，但需
自行安装匹配的 CUDA PyTorch。

## 3. 统一适配器

适配器位于 `src/watermark_lab/models/wam_adapter.py`，并注册为模型名 `wam`。

### 编码

- 输入为任意分辨率 RGB `uint8` 图像和 32 bit 消息；
- 采用官方 ImageNet 标准化；
- 官方嵌入器在 256×256 上预测水印残差，再恢复到原图尺寸；
- `strength` 直接控制官方 `scaling_w`；
- 输出恢复为原始尺寸 RGB `uint8`。

### 解码与定位

官方检测器输出 `[1, 33, 256, 256]`：

- 第 0 通道经 sigmoid 后为像素级水印检测概率；
- 第 1–32 通道为逐像素 bit logits；
- 在检测概率大于 0.5 的像素上平均 bit logits；
- 按官方 notebook 的 0.5 logit 阈值恢复 32 bit 消息。

统一 `DecodeResult` 同时返回：

- 聚合后的 32 bit 消息；
- 图像级检测布尔值与置信度；
- 256×256 像素级检测概率图；
- 检测面积、概率统计和 bit margin 元数据。

软检测概率和 bit logits 通过 `predict_spatial()` 保留，不提前丢失，供 M4 的多尺度
概率融合与软聚类直接使用。

## 4. 公平强度校准

WAM 与 M2 方法使用相同 Debug10 图像和平均 40 dB 目标。每个数据集冻结一个强度，
不按单张测试图像调参：

| 数据组 | WAM 强度 | 校准平均 PSNR/dB |
|---|---:|---:|
| COCO | 1.58203125 | 40.088 |
| DIV2K | 1.82421875 | 39.910 |
| DiffusionDB | 1.763671875 | 40.138 |
| W-Bench | 2.1875 | 39.911 |

完整攻击运行中的 WAM 平均嵌入 PSNR 为 40.019 dB；DWT-DCT 和 TrustMark-Q 分别为
40.031 dB 与 39.989 dB。

## 5. 复现命令

```powershell
# 真实权重小规模管线验收
.\.venv-wam\Scripts\python.exe -m watermark_lab self-check `
  --model wam `
  --output-dir results\m3_wam_smoke

# 只校准 WAM，保留已有 M2 校准结果
.\.venv-wam\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --models wam `
  --iterations 7

# 40 张图像 × 44 条攻击，并保存空间诊断指标
.\.venv-wam\Scripts\python.exe scripts\run_wam_debug_diagnostics.py `
  --device cpu

# 无水印负样本检测
.\.venv-wam\Scripts\python.exe scripts\run_wam_negative_controls.py `
  --device cpu

# 与 M2 两个基线做同 PSNR 分组比较
.\.venv-wam\Scripts\python.exe scripts\analyze_m3_results.py

# 针对内容、强度和 bit 阈值的失败探针
.\.venv-wam\Scripts\python.exe scripts\probe_wam_failures.py `
  --device cpu
```

定量结果与创新方向见 [M3_DEBUG_RESULTS.md](M3_DEBUG_RESULTS.md)。
