# M2 实施说明

## DWT-DCT 基线

当前实现是无需原图的盲水印传统基线：

1. RGB 转换到 YCbCr，在亮度通道执行一级 Haar DWT。
2. 在 LL 子带划分 8×8 块，并按固定密钥选择块。
3. 对两个中频 DCT 系数执行差分调制。
4. 嵌入 16 bit 同步字和 32 bit 消息；空间足够时重复 5 次并多数投票。
5. 解码端只需要待测图像、相同密钥和参数，不需要原图。

默认参数为 `strength=60`、`max_repetition=5`、固定 seed，目标 PSNR 为 38–42 dB。
检测同步字默认至少匹配 15/16 bit。正式比较时只能在
预实验集上调整强度，随后冻结参数，禁止针对测试集逐图调整。

## 数据集清单

CSV manifest 固定以下字段：

```text
dataset,split,sample_id,relative_path,width,height,image_format,sha256
```

样本按相对路径排序后截取，因此同一个数据目录和 limit 会生成相同清单。
正式实验建议启用 `--verify-sha256`，防止图片被替换、重新压缩或尺寸发生变化。

## 攻击协议

正式协议为 `configs/attacks.yaml` 中的 `wm-course-v1`。当前包含：

- 1 个无攻击控制组；
- 35 个单一攻击条件；
- 8 个复合攻击条件。

协议的每条 pipeline 都保持输出尺寸不变。随机攻击统一使用协议 seed，运行器把完整
pipeline 写入逐图结果 CSV，后续不得只保留表现较好的攻击强度。

## TrustMark-Q

适配器使用 Adobe 官方 Python 实现的 Q 变体、二进制模式和 BCH_5：

- 项目统一比较前 32 bit；TrustMark BCH_5 的剩余容量由官方数据层补零。
- 默认强度为 1.0，不加载局部框检测器，不启用旋转搜索。
- 官方 API 只返回检测布尔值，不提供概率，因此当前置信度记录为 0/1 并在元数据注明。
- 首次初始化会从官方地址下载编码器和解码器权重。

参考实现和配置依据：

- https://github.com/adobe/trustmark
- https://github.com/adobe/trustmark/blob/main/python/CONFIG.md
- 论文统一引用键：`bui2025trustmark`，见
  [`REFERENCES.bib`](../REFERENCES.bib) 与
  [`REFERENCES_AND_LICENSES.md`](REFERENCES_AND_LICENSES.md)。

TrustMark 0.9.0 要求 NumPy `<2.0`。必须使用独立的 Python 3.10–3.12 虚拟环境，
通过 `pip install -e ".[trustmark,research,data,dev]"` 安装，避免污染其他 Python 项目。
中文 Windows 在构建 PyPI 源码包时还需要先设置 `$env:PYTHONUTF8='1'`，否则其
`setup.py` 可能按 GBK 读取 UTF-8 README 并报 `UnicodeDecodeError`。

项目提供了可重复执行的 CPU 环境脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_trustmark_windows.ps1
```

### 已完成的真实权重验收

2026-09-01 已在 Windows、Python 3.12、PyTorch 2.5.1 CPU、NumPy 1.26.4、
TrustMark 0.9.0 环境完成官方 Q 权重下载和真实推理。256×256 合成图结果如下：

| 条件 | Bit Accuracy | 完整恢复 | 检测 | 水印图 PSNR |
|---|---:|---:|---:|---:|
| 无攻击 | 1.000 | 是 | 是 | 47.58 dB |
| JPEG Q=80 | 1.000 | 是 | 是 | 47.58 dB |
| 高斯噪声 σ=0.01 | 1.000 | 是 | 是 | 47.58 dB |

该结果只证明适配器和官方权重可运行，不能代替正式自然图像多数据集实验。

## 命令

```powershell
# 验证传统基线
watermark-lab self-check --model dwt_dct --output-dir results\m2_smoke

# 检查固定攻击协议
watermark-lab protocol-status --config configs\attacks.yaml

# 使用固定清单运行传统基线
watermark-lab run-manifest `
  --model dwt_dct `
  --manifest data\manifests\coco2017_val_200.csv `
  --dataset-root D:\datasets\coco2017\val2017 `
  --verify-sha256 `
  --output results\dwt_dct\coco2017_val.csv

# TrustMark 使用同一命令，仅替换模型
watermark-lab run-manifest `
  --model trustmark_q `
  --manifest data\manifests\coco2017_val_200.csv `
  --dataset-root D:\datasets\coco2017\val2017 `
  --verify-sha256 `
  --output results\trustmark_q\coco2017_val.csv

# 小样本真实权重验收
watermark-lab self-check --model trustmark_q --output-dir results\m2_trustmark_smoke
```

## Debug10 完整实验

4 个数据集各 10 张图像的固定清单、平均 40 dB 强度校准以及完整 44 条攻击协议
已于 2026-09-01 跑通，共生成 3520 条逐图结果。复现命令、定量结果、局限性和
下一阶段改进方向见 [M2_DEBUG_RESULTS.md](M2_DEBUG_RESULTS.md)。
