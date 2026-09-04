# formal-v1 独立正负样本检测结果

完成时间：2026-09-04。本实验补齐 formal-v1 只含加水印正样本、不能正式报告误报率的
缺口。它不修改原 121,440 条攻击结果，而是使用相同的独立 calibration/test 划分执行
clean 原图负样本与 clean 水印正样本检测。

## 1. 协议与完整性

- 模型：DWT-DCT、TrustMark-Q、WAM、AM-WAM；
- calibration：每模型 140 张无水印负样本，只用于冻结检测阈值；
- test：每模型 690 张无水印负样本与对应的 690 张水印正样本；
- 总记录：`4 × (140 + 690) × 2 = 6,640`，完整性状态为通过；
- 阈值规则：在 calibration 负样本上选择满足经验 FPR 不高于 1% 的最低 tie-safe 阈值；
- test 指标：TPR、FPR、Wilson 95% CI、ROC-AUC 和正样本完整恢复率；
- 输入图、消息和随机种子均固定，calibration/test manifest 互斥并强制 SHA-256 校验。

140 张 calibration 负样本不足以可靠校准 0.1% FPR，因此本轮预先采用可被当前样本量
支持的 1% 目标。test FPR 是独立估计，不要求机械等于 calibration FPR。

## 2. 总体 test 结果

| 模型 | 检测分数 | 冻结阈值 | TPR | FPR (95% CI) | ROC-AUC | 默认规则 FPR |
|---|---|---:|---:|---:|---:|---:|
| DWT-DCT | 同步字匹配率 | >0.8125 | 100.00% | 0.00% (0.00–0.55) | 1.0000 | 0.00% |
| TrustMark-Q | 官方布尔标志 | >1.0 | 0.00% | 0.00% (0.00–0.55) | 0.9877 | 2.32% |
| WAM | 检测面积比例 | 0.02643 | 100.00% | 1.30% (0.69–2.46) | 1.0000 | 3.91% |
| AM-WAM | 检测面积比例 | 0.02643 | 100.00% | 1.74% (1.00–3.02) | 1.0000 | 6.81% |

四模型 clean 正样本完整恢复率分别为 100.00%、99.86%、99.42% 和 99.71%。这些数值
只表示 clean 检测与恢复，不能替代 44 条攻击下的 formal-v1 鲁棒性结果。

## 3. 解释与负结果

1. WAM/AM-WAM 的 clean 正负分数完全可排序，所以 ROC-AUC 为 1；但 140 张 calibration
   尾部估计不足，冻结阈值在 test 上得到 1.30%/1.74% FPR。这说明 AUC 很高不等于任意
   工作阈值都达到目标误报率。
2. AM-WAM 默认检测规则的 FPR 高于 WAM。几何候选搜索会在部分无水印图上选出伪几何
   证据，因此部署时不能直接沿用默认 `detected` 布尔值。
3. TrustMark 0.9.0 只暴露布尔检测标志。calibration 中 2/140 个负样本被标为正，无法在
   不超过 1% FPR 的约束下选择仍保留正样本的阈值；`>1.0` 阈值因此得到 TPR=0。这不是
   TrustMark 完全不能检测，而是说明其公开二值接口不足以做目标 FPR 校准。表中 AUC 是
   二值分数的粗粒度结果，不能与连续分数模型作精细 ROC 排名。
4. 若课程论文必须报告 `TPR@0.1%FPR`，需要另建至少数千张负样本的 detection-v2
   calibration/test，不能从本轮 140 张 calibration 外推一个虚假的 0.1% 数字。

## 4. 复现入口

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\run_formal_detection.py `
  --models dwt_dct trustmark_q --device cpu

.\.venv-wam-formal\Scripts\python.exe scripts\run_formal_detection.py `
  --models wam am_wam --device cuda

.\.venv-trustmark\Scripts\python.exe scripts\analyze_formal_detection.py
```

逐图检查点、阈值、汇总与运行元数据位于忽略目录 `results/formal_detection/`。论文应同时
引用本文件与 `docs/FORMAL_RESULTS.md`，不能再把正样本 `detected` 均值表述成低误报检测率。
