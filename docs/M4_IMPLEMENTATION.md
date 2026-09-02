# M4 第一阶段：几何同步恢复与内容自适应强度

## 1. 本阶段范围

M4 第一阶段实现两个可独立消融的模块：

1. 解码前的盲几何同步恢复前端；
2. 嵌入前的内容自适应、质量约束强度控制器。

两者封装为统一模型 `am_wam`，原始 WAM、单模块和组合模型使用完全相同的
32-bit 消息、图像与攻击随机种子。多水印软聚类不包含在本阶段，继续保留为 M4
第二阶段任务。

## 2. 内容自适应强度控制

### 2.1 动机

M3 使用数据集级固定强度时，虽然数据集平均 PSNR 约为 40 dB，但单图 PSNR 范围为
36.67--44.07 dB。这会同时造成：

- 部分图像水印过强，质量损失过大；
- 部分图像水印过弱，攻击后更容易失败；
- 相同平均 PSNR 掩盖逐图比较不公平。

### 2.2 控制流程

控制器先按基础强度嵌入一次。对近似线性水印残差，利用

`new_strength = old_strength * 10 ** ((measured_psnr - target_psnr) / 20)`

估计达到目标 PSNR 所需的逐图强度，再进行最多两次质量反馈修正。目标配置为：

- 目标 PSNR：40 dB；
- 允许的最低 PSNR：38 dB；
- 目标误差：0.15 dB；
- 强度范围：0.25--8.0。

达到目标质量后，控制器使用已知嵌入消息执行干净解码自检。如果整串恢复失败或最小
bit margin 小于 0.20，则在 40--38 dB 的有限质量预算内搜索更强嵌入；候选按
“整串恢复、Bit Accuracy、最小 margin、PSNR”顺序选择。该反馈只发生在嵌入端，
不会把攻击标签或测试消息提供给最终解码器。

每张图同时记录亮度标准差、梯度能量、Laplacian 方差和归一化亮度熵。当前控制决策
使用真实质量与解码反馈；这些特征保留给后续训练无反馈的轻量强度预测器。

## 3. 盲几何同步恢复

### 3.1 候选分支

同步前端不使用原图或真实攻击参数。它对待解码图像构造下列逆变换候选：

- identity；
- 旋转校正：`-10, -6, -3, +3, +6, +10` 度；
- 透视校正：`0.03, 0.06, 0.10` 三档。

每个候选分别运行 WAM 空间检测器，得到检测概率图和 32 个 bit logit 图。

### 3.2 无标签候选评分

候选分支评分为：

`0.30 * detection_confidence + 0.30 * spatial_bit_agreement`

`+ 0.30 * tanh(mean_bit_margin / 2) + 0.10 * detected_coverage`

最高分的三个分支使用温度 0.15 的 softmax 权重融合 pooled bit logits。该评分不读取
真实消息，因此属于盲同步。

### 3.3 保守接管

首版无门控搜索在 clean 和 blur 上会偶尔选择错误变换。因此最终版增加两级保护：

1. 比较四个角落与中心区域的中值填充色比例，边界几何证据低于 0.02 时只运行
   identity；
2. 非 identity 最高分相对 identity 的增益不足 0.006 时回退 identity，并禁止其他
   候选参与融合。

这不是隐藏失败样本：无门控首版结果保留在 `results/m4_ablation`，最终门控版结果位于
`results/m4_ablation_v2`。

## 4. 统一模型与消融

`AmWamModel` 通过组合原始 `WamModel`、`ContentAdaptiveStrengthController` 和
`GeometrySyncDecoder` 实现统一接口：

- `encode(image, message)`：可开关自适应强度；
- `decode(image)`：可开关几何同步；
- metadata 保存强度搜索轨迹、内容特征、候选分支得分、接管原因和融合权重。

消融组定义：

| 编号 | 嵌入 | 解码 |
|---|---|---|
| A0 | 数据集固定强度 | 原始 WAM |
| A1 | 数据集固定强度 | WAM + 几何同步 |
| A2 | 内容自适应强度 | 原始 WAM |
| A3 | 内容自适应强度 | WAM + 几何同步 |

## 5. Windows 复现命令

```powershell
.\.venv-wam\Scripts\python.exe scripts\run_m4_ablation.py --device cpu
.\.venv-wam\Scripts\python.exe scripts\analyze_m4_results.py
.\.venv-wam\Scripts\python.exe -m pytest
```

实验配置见 `configs/m4_ablation.yaml`，默认读取 M2/M3 的固定 Debug10 manifest、WAM
强度校准和 44 条攻击协议。

冻结主实验参数后的未见连续几何协议位于 `configs/m4_heldout_attacks.yaml`，对应运行
配置为 `configs/m4_heldout_ablation.yaml`。结果见 `docs/M4_HELDOUT_RESULTS.md`。
