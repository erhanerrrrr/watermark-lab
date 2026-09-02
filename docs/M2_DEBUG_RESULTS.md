# M2 调试集实验报告

## 1. 本轮完成范围

本轮已完成以下可复现实验闭环：

- 从 4 个数据集各固定 10 张调试图像，共 40 张；
- 为所有图像生成包含尺寸、格式和 SHA-256 的固定 manifest；
- 在每个“模型 × 数据集”上冻结一个全局强度，以平均嵌入 PSNR 40 dB 为目标；
- 运行 DWT-DCT 与 TrustMark-Q 的完整 44 条攻击协议；
- 生成 `2 × 4 × 10 × 44 = 3520` 条逐图记录和分层汇总。

这是用于检查实现、攻击协议和研究假设的调试实验，不是论文最终统计。正式实验必须扩大样本量，并将强度校准集与最终测试集分开。

## 2. 数据与固定清单

| 数据组 | 固定样本 | 选择规则 | Manifest |
|---|---:|---|---|
| COCO 2017 validation | 10 | 固定的前 10 个图像 ID | `data/manifests/coco2017_val_debug10.csv` |
| DIV2K validation HR | 10 | 0801–0810 | `data/manifests/div2k_valid_hr_debug10.csv` |
| DiffusionDB 2M | 10 | 首个分片中按文件名排序的前 10 张 | `data/manifests/diffusiondb_2m_debug10.csv` |
| W-Bench DET_INVERSION_1K | 10 | 索引 0–9 | `data/manifests/w_bench_det_inversion_debug10.csv` |

官方数据入口与许可说明见 `data/SOURCES.md`。原始图像保存在被忽略的
`data/raw/debug10/`，manifest 和哈希值进入项目版本管理。运行实验时启用
SHA-256 校验，当前 40 张图像全部通过。

## 3. 公平强度校准

### 3.1 规则

1. 统一目标为平均嵌入 PSNR 40 dB，属于预先规定的 38–42 dB 区间。
2. 每个“模型 × 数据集”只选择一个固定强度，不按单张图像调参。
3. 二分搜索只使用无攻击水印图的平均 PSNR；选定后冻结强度，再运行全部攻击。
4. 两种方法都嵌入 32 bit 消息，并使用相同图像、消息随机种子和攻击协议。

按数据集校准是必要的：当前 DWT-DCT 只修改固定数量的 DWT-LL/DCT 块，DIV2K
分辨率更高，局部改动在全图 PSNR 中被明显稀释。因此 DIV2K 所需的 DWT-DCT
强度远高于其他数据集。这同时说明全局 PSNR 无法完整描述水印能量的空间集中程度。

### 3.2 选定强度

| 数据组 | DWT-DCT 强度 | 校准 PSNR/dB | TrustMark-Q 强度 | 校准 PSNR/dB |
|---|---:|---:|---:|---:|
| COCO | 115.15625 | 40.133 | 1.3203125 | 39.928 |
| DIV2K | 396.09375 | 40.018 | 1.07421875 | 39.979 |
| DiffusionDB | 133.28125 | 40.082 | 1.45703125 | 39.934 |
| W-Bench | 115.15625 | 39.914 | 1.51171875 | 40.057 |

校准均成功夹住目标，平均误差不超过 0.134 dB。完整攻击实验因消息内容与校准时不同，
各数据集实际平均 PSNR 为：DWT-DCT 39.854–40.181 dB，TrustMark-Q
39.887–40.065 dB；两种方法的全体平均值分别为 40.031 dB 和 39.989 dB。

## 4. 完整攻击结果

### 4.1 总体结果

以下均为 40 张图像的宏观平均。`全部 44 条`包含无攻击控制组，
`仅攻击 43 条`排除控制组。

| 模型 | 范围 | 检测率 | 平均 Bit Accuracy | 整串恢复率 | 平均嵌入 PSNR/dB |
|---|---|---:|---:|---:|---:|
| DWT-DCT | 全部 44 条 | 68.69% | 84.90% | 58.30% | 40.031 |
| TrustMark-Q | 全部 44 条 | 66.02% | 81.85% | 65.28% | 39.989 |
| DWT-DCT | 仅攻击 43 条 | 67.97% | 84.54% | 57.33% | 40.031 |
| TrustMark-Q | 仅攻击 43 条 | 65.23% | 81.43% | 64.48% | 39.989 |

两种方法在无攻击控制组中均为 100% 检测、100% 比特准确和 100% 整串恢复。
在匹配的平均 PSNR 下，DWT-DCT 的平均比特准确率较高；TrustMark-Q 的整串恢复率
高出约 7 个百分点。这个差异说明只报告 BER 或只报告“是否完整解码”都会遗漏信息，
论文中应同时保留两类指标。

### 4.2 按攻击类别

| 模型 | 类别 | 攻击数 | 检测率 | 平均 Bit Accuracy | 整串恢复率 |
|---|---|---:|---:|---:|---:|
| DWT-DCT | 单一攻击 | 35 | 72.57% | 86.95% | 62.21% |
| TrustMark-Q | 单一攻击 | 35 | 66.64% | 82.13% | 65.86% |
| DWT-DCT | 组合攻击 | 8 | 47.81% | 74.02% | 35.94% |
| TrustMark-Q | 组合攻击 | 8 | 59.06% | 78.37% | 58.44% |

TrustMark-Q 在组合攻击下的整串恢复率比 DWT-DCT 高 22.50 个百分点，是本轮最稳定的
差异。DWT-DCT 在固定网格被破坏时退化明显：中心裁剪、水平翻转、旋转和透视等攻击
会改变嵌入块的位置或方向，其整串恢复率多为 0。

TrustMark-Q 对部分几何攻击更稳定：`crop_075`、`crop75_resize75_jpeg80` 和
`horizontal_flip` 的整串恢复率均为 100%，`perspective_light` 为 77.5%。但它并非
普遍免疫：`perspective_heavy`、`rotation_10`、`crop_05` 的整串恢复率均为 0。

### 4.3 局部篡改中的异常与研究线索

局部篡改结果不是简单的“篡改面积越大，性能越差”。例如：

- `local_splice_10`：DWT-DCT 整串恢复率 95%，TrustMark-Q 为 0%；
- `local_splice_50`：DWT-DCT 为 10%，TrustMark-Q 为 90%；
- `copy_move_10`：DWT-DCT 为 90%，TrustMark-Q 为 27.5%。

这可能来自模型水印能量的空间分布、固定中心掩膜与模型特征区域的重合，以及当前仅
40 张图像造成的方差。它是值得跟进的现象，但不能直接写成“面积反常性”结论。下一轮
应加入随机位置和多形状掩膜，对每张图像重复多个种子，并报告均值与置信区间。

### 4.4 运行时间

当前 Windows CPU 环境中的逐图平均时间如下：

| 模型 | 编码 | 解码 |
|---|---:|---:|
| DWT-DCT | 106.8 ms | 53.6 ms |
| TrustMark-Q | 275.9 ms | 219.5 ms |

该时间受图像尺寸、CPU 和深度学习运行时影响，只用于本项目工程评估，不应泛化为算法
在所有设备上的速度结论。

## 5. 结果解释边界

- 两个模型的 `detected` 语义不同：DWT-DCT 使用同步字阈值，TrustMark 使用官方检测
  布尔值。当前没有通过无水印负样本把两者校准到相同误报率，因此检测率只作辅助指标；
  公平主指标使用 Bit Accuracy、BER 和整串恢复率。
- 当前公平性是“每个数据集上的平均全局 PSNR 匹配”，不是逐图 PSNR 匹配，也不是
  感知质量或局部伪影完全匹配。正式实验应补充 SSIM、LPIPS 和局部残差热图。
- 调试集同时用于强度校准和攻击评估，只适合工程验证。论文阶段应在独立 calibration
  split 上冻结强度，再对互斥 test split 报告结果。
- 每个攻击当前只有一个固定协议实例。含随机性的噪声与复制移动攻击应在正式实验中使用
  多个种子，以估计方差。

## 6. 对后续创新实现的直接结论

M3/M4 不应只做简单的“换一个新模型”，而应针对本轮暴露的问题形成可验证改进：

1. 为传统基线增加几何同步/重定位模块，重点修复裁剪、翻转、旋转、透视导致的固定块失配；
2. 引入内容自适应的强度与嵌入位置选择，在相同 PSNR 下减少水印能量集中并提升局部篡改鲁棒性；
3. 把组合攻击和随机局部掩膜纳入训练或增强流程，而不是仅在测试时出现；
4. 做消融实验：原始模型、仅几何同步、仅自适应强度、两者同时启用；
5. 增加无水印负样本，按固定 FPR 校准检测阈值，再正式比较检测能力。

## 7. 复现入口与产物

```powershell
# 下载/核验 4 × 10 张调试样本并生成固定 manifest
.\.venv-trustmark\Scripts\python.exe scripts\download_debug_datasets.py

# 在 40 张调试图像上进行 40 dB 目标强度校准
.\.venv-trustmark\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --models dwt_dct trustmark_q

# 运行 2 × 4 × 10 × 44 = 3520 条记录
.\.venv-trustmark\Scripts\python.exe scripts\run_m2_debug_benchmark.py `
  --models dwt_dct trustmark_q

# 校验记录数并生成总体、类别和逐攻击对比汇总
.\.venv-trustmark\Scripts\python.exe scripts\analyze_m2_debug_results.py
```

关键产物：

- `configs/debug_suite.yaml`：调试实验总配置；
- `configs/calibrated_strengths_debug10.json`：搜索过程与冻结强度；
- `results/m2_debug/all_records.csv`：3520 条逐图原始结果；
- `results/m2_debug/summary_by_dataset.csv`：按数据集汇总；
- `results/m2_debug/summary_overall.csv`：模型总体汇总；
- `results/m2_debug/summary_by_category.csv`：控制/单一/组合攻击汇总；
- `results/m2_debug/comparison_by_attack.csv`：44 条攻击的模型差异；
- `results/m2_debug/run_metadata.json`：平台、协议、数据和校准元数据。
