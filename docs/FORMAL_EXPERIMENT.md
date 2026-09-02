# formal-v1 正式对比实验协议

## 1. 目标

formal-v1 用独立于 Debug10 和算法开发样本的扩大数据，公平比较：

- `dwt_dct`：盲提取传统 DWT-DCT 基线；
- `trustmark_q`：固定 TrustMark 0.9.0 Q 模型、32-bit 有效消息；
- `wam`：Meta 官方 WAM MIT 固定权重；
- `am_wam`：WAM + M4.1 内容自适应强度 + 盲几何同步。

HiDDeN 不列入本轮正式比较，原因仍是仓库没有满足固定官方实现、可验证权重、统一
32-bit 盲提取和 Windows 可复现要求的可靠适配器。用来源不明的非官方权重补数会降低
对比可信度，不能为了增加方法数量而接入。

执行状态：已于 2026-09-02 完成 121,440/121,440 条，完整性检查无缺失；最终统计见
`docs/FORMAL_RESULTS.md`。

## 2. 数据划分

四个来源共 140 张 calibration 与 690 张 test：

| 数据集 | calibration | test |
|---|---:|---:|
| COCO 2017 val | 40 | 200 |
| DIV2K | 20 | 90 |
| DiffusionDB 2M | 40 | 200 |
| W-Bench DET_INVERSION_1K | 40 | 200 |
| 合计 | 140 | 690 |

两个划分和 Debug10 互不重叠。八个 manifest 固定文件名、相对路径、字节数与 SHA-256，
读取时强制校验。选择规则和许可证见 `data/SOURCES.md`。

## 3. 公平强度校准

每个模型在每个数据集的 calibration 子集上单独校准到平均 PSNR 40 dB。搜索先评估
上下界，再做 7 次二分，共 9 个强度点；最终选择平均 PSNR 与 40 dB 绝对误差最小者。
AM-WAM 继承 WAM 的数据集级基础强度，然后在每张图内执行质量约束的内容自适应控制。

校准只读取 calibration，不读取 test 的恢复率。所有搜索轨迹写入
`configs/formal_calibrated_strengths.json`。

## 4. 固定攻击与记录规模

正式测试沿用 `configs/attacks.yaml` 的 44 条冻结协议，包括：

- 1 条 clean 控制；
- JPEG、模糊、噪声、亮度/对比度、缩放等单一数值攻击；
- 旋转、透视、裁剪/删除、局部篡改等几何或局部攻击；
- 8 条复合攻击。

每个模型的预期记录数为 `690 × 44 = 30,360`，四模型合计 `121,440`。每条记录保存
检测、bit accuracy、BER、完整恢复、嵌入/攻击后 PSNR、编码/解码时间和模型 metadata。

## 5. 可中断复现

正式运行器按“模型/数据集/图像”生成独立检查点。每张图的随机种子由协议种子、数据集
ID 和图像 ID 做 SHA-256 派生，因此分片、顺序或中断恢复不会改变消息与随机攻击。
最终 CSV 由检查点原子合并，并验证每个 `(image_id, attack)` 恰好出现一次。

```powershell
# 1. 恢复扩大数据
.\.venv-trustmark\Scripts\python.exe scripts\prepare_formal_datasets.py

# 2. 公平强度校准
.\.venv-trustmark\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --config configs\formal_calibration.yaml `
  --models dwt_dct trustmark_q --iterations 7

.\.venv-wam\Scripts\python.exe scripts\calibrate_m2_strengths.py `
  --config configs\formal_calibration.yaml `
  --models wam --device cuda --iterations 7

# 3. 正式比较；重复同一命令会自动复用完整检查点
.\.venv-trustmark\Scripts\python.exe scripts\run_formal_benchmark.py `
  --models dwt_dct trustmark_q --device cpu

.\.venv-wam\Scripts\python.exe scripts\run_formal_benchmark.py `
  --models wam am_wam --device cuda

# 4. 汇总与按图像单元配对 Bootstrap 95% CI
.\.venv-trustmark\Scripts\python.exe scripts\analyze_formal_results.py
```

44 条攻击共享同一图像，彼此并非独立样本。正式 Bootstrap 因此先在每张图内平均配对
差值，再重采样 690 个图像单元，避免把 30,360 行错误当作 30,360 个独立样本。

## 6. 运行环境口径

准确率可跨 CPU/GPU 比较，但耗时只在相同运行时与设备内解释。本机正式 WAM 运行使用
RTX 4070 Laptop GPU；最终结果文档必须同时记录驱动、PyTorch/CUDA、Python、NumPy、
官方提交和权重 SHA-256。标准共创环境仍以 `setup_wam_windows.ps1` 固定的 Python 3.12、
PyTorch 2.5.1 为复现基准。

8 GB 显存机器建议同时最多运行 3 个 WAM/AM-WAM 进程。实测更高并发会触发 CUDA
illegal memory access；该错误只终止当前进程，逐图检查点可复用，但应先降低并发再恢复。
高分辨率 DIV2K 可使用 `--shard-index I --shard-count N` 分片；分片只补齐共享
`.partials`，全部分片结束后必须再运行一次不带分片参数的命令，验证 90×44 完整记录并
生成最终 CSV。

## 7. 统计与图表产物

`analyze_formal_results.py` 生成四类原始汇总表，以及两类图像级 Bootstrap 表：

- `summary_overall.csv`、`summary_by_dataset.csv`、`summary_by_category.csv`、
  `summary_by_attack.csv`：记录均值和标准差；
- `bootstrap_summary.csv`：每个模型在总体、数据集和攻击类别范围内的均值与 95% CI；
- `paired_comparisons.csv`：AM-WAM 与每个对比方法在同图同攻击上的配对差值与 95% CI；
- `analysis_status.json`：记录是否达到 121,440 条及缺失文件，不完整时默认拒绝正式分析。

44 条攻击共享同一张图，Bootstrap 会先在图像内聚合，再对图像单元重采样。图表同样只
读取上述统计文件，不另写一套指标公式：

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\plot_formal_results.py
```

该命令在 `results/formal_v1/figures/` 输出总体性能、分数据集完整恢复率、分攻击类别
Bit Accuracy 和 AM-WAM/WAM 配对森林图的 PNG 与 PDF。原始 CSV 和图像默认不进入 Git；
论文中引用的最终数字固化在 `docs/FORMAL_RESULTS.md`。
