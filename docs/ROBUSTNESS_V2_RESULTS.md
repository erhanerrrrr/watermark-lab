# robustness-v2 扩展鲁棒性验证

完成时间：2026-09-04。本轮在不修改 formal-v1 的前提下冻结 24 条新攻击，验证 AM-WAM
是否只记住原有的 3°/10° 旋转和对称透视参数。攻击配置在任何结果产生前固定，运行后未
回改参数。

## 1. 协议与完整性

- 图像：四个 formal-v1 test manifest 各取已冻结顺序的前 10 张，共 40 张；
- 模型：DWT-DCT、TrustMark-Q、WAM、AM-WAM；
- 攻击：24 条，共 `40 × 24 × 4 = 3,840` 条完整记录；
- 统计：以 40 张图像为配对 Bootstrap 单元，迭代 2,000 次；
- 攻击族：6 个非候选网格旋转、4 个非对称四点透视、6 个非中心/非方形局部编辑、
  6 个未见光度/像素化攻击、2 个打印扫描/屏摄代理组合链路。

这是冻结参数后的扩展验证，不是新的算法调参集。40 张图足以验证实现和效应方向，但不能
替代 `configs/robustness_v2_benchmark.yaml` 预留的 690 张全量外推实验。

## 2. 总体结果

| 模型 | Bit Accuracy | 完整恢复率 | 嵌入 PSNR | 平均解码时间 |
|---|---:|---:|---:|---:|
| DWT-DCT | 75.84% | 43.85% | 39.817 dB | 53.67 ms |
| TrustMark-Q | 72.83% | 47.92% | 40.545 dB | 58.56 ms |
| WAM | 97.57% | 86.25% | 40.405 dB | 40.85 ms |
| AM-WAM | **99.56%** | **94.79%** | 40.014 dB | 841.48 ms |

AM-WAM 相对 WAM 的图像级配对结果：

| 指标 | 差值 | 95% CI |
|---|---:|---:|
| Bit Accuracy | **+1.989 pp** | +1.589 至 +2.451 pp |
| 完整恢复率 | **+8.542 pp** | +6.667 至 +10.729 pp |
| 嵌入 PSNR | -0.391 dB | -0.894 至 +0.159 dB |
| 解码时间 | +800.63 ms | +587.07 至 +1,030.50 ms |

## 3. 攻击族与边界

| 攻击族 | WAM 完整恢复率 | AM-WAM 完整恢复率 | 差值 |
|---|---:|---:|---:|
| 非候选网格几何 | 70.75% | **91.00%** | **+20.25 pp** |
| 打印/屏摄代理 | 96.25% | 97.50% | +1.25 pp |
| 未见光度/像素化 | 95.00% | 95.00% | 0 pp |
| 非中心局部编辑 | 100.00% | 100.00% | 0 pp |

提升主要来自超出原候选表的旋转：`-12.7°`、`+12.7°` 完整恢复率分别提升 85 和
75 个百分点，`+8.3°` 提升 25 个百分点。非对称透视并非全面改善：
`perspective_quad_c` 下降 2.5 个百分点且置信区间跨零。新光度和局部编辑多数已接近
饱和，不能据此宣称 AM-WAM 全面优于 WAM。

因此更稳妥的创新结论是：

> AM-WAM 的几何同步能力可以外推到一部分候选网格之外的连续旋转和非对称投影，扩展
> 验证中总体恢复提升显著；收益仍主要集中于几何失配，并伴随约 0.8 秒平均解码开销。

## 4. 复现入口

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\run_formal_benchmark.py `
  --config configs\robustness_v2_validation.yaml `
  --models dwt_dct trustmark_q --device cpu

.\.venv-wam-formal\Scripts\python.exe scripts\run_formal_benchmark.py `
  --config configs\robustness_v2_validation.yaml `
  --models wam am_wam --device cuda

.\.venv-trustmark\Scripts\python.exe scripts\analyze_formal_results.py `
  --config configs\robustness_v2_validation.yaml --bootstrap-iterations 2000
```

逐图结果和统计位于 `results/robustness_v2_validation/`。全 690 张版本已配置在
`configs/robustness_v2_benchmark.yaml`，若继续运行必须保留 v2 配置，不得依据当前结果
修改同一协议后仍称其为 held-out test。
