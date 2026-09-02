# M4 未见连续几何攻击泛化结果

## 1. 冻结测试原则

主消融完成并冻结候选角度、分支评分、边界门控和阈值后，另建 held-out 协议。下列
攻击参数均未出现在几何同步候选表中：

- 旋转：`+5°`、`+7°`、`-7°`；
- 透视幅度：`0.05`、`0.08`；
- 组合：`+7° rotation + 0.80 resize + JPEG Q70`。

测试过程中没有根据结果新增候选或修改门控。4 个数据集各 10 张，4 个消融组、6 条
攻击，共生成并验证 960 条记录。

## 2. 总体结果

| 消融组 | Bit Accuracy | 完整恢复率 | 平均解码时间 |
|---|---:|---:|---:|
| A0 固定+原始 | 97.34% | 86.67% | 198 ms |
| A1 固定+同步 | 98.80% | 89.58% | 2432 ms |
| A2 自适应+原始 | 98.32% | 87.08% | 190 ms |
| A3 自适应+同步 | **99.19%** | **92.08%** | 2446 ms |

A3 相比 A0：

- Bit Accuracy：+1.85 个百分点，配对 Bootstrap 95% CI 为 +0.04～+4.67；
- 完整恢复率：+5.42 个百分点，95% CI 为 +0.83～+12.08。

置信区间仍为正，但提升小于协议内几何攻击的 +13.5 个百分点。这一泛化差距应保留在
论文结论中。

## 3. 逐攻击完整恢复率

| 未见攻击 | A0 | A1 | A2 | A3 |
|---|---:|---:|---:|---:|
| rotation +5° | 92.5% | 92.5% | 92.5% | 95.0% |
| rotation +7° | 87.5% | 92.5% | 87.5% | 92.5% |
| rotation -7° | 82.5% | 85.0% | 82.5% | 90.0% |
| perspective 0.05 | 90.0% | 90.0% | 90.0% | 92.5% |
| perspective 0.08 | 87.5% | 90.0% | 85.0% | 92.5% |
| rotation 7° + resize + JPEG | 80.0% | 87.5% | 85.0% | 90.0% |

非 identity 分支被接受时，5°/7° 旋转主要由相邻的 6° 或 10° 分支恢复，0.05/0.08
透视主要由 0.06 或 0.10 分支恢复。大量样本仍回退 identity，说明保守门控只在分支
评分给出足够证据时接管。

## 4. 结论与限制

本轮支持“离散候选在相邻连续参数上具有一定泛化能力”，但不能推出任意仿射或投影
变换都能恢复。下一步正式实验应采样连续随机角度和随机四点单应性矩阵，并将参数划分为
calibration/test 两个互斥区间。

复现命令：

```powershell
.\.venv-wam\Scripts\python.exe scripts\run_m4_ablation.py `
  --config configs\m4_heldout_ablation.yaml --device cpu

.\.venv-wam\Scripts\python.exe scripts\analyze_m4_results.py `
  --results-dir results\m4_heldout_geometry `
  --geometry-attacks rotation_5_unseen rotation_7_unseen `
  rotation_minus7_unseen perspective_05_unseen perspective_08_unseen `
  rotation7_resize80_jpeg70_unseen
```
