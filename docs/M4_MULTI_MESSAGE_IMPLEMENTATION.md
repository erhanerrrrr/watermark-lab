# M4.2 多水印自适应软聚类

## 1. 任务定义

一张图像的不同非重叠区域可嵌入 2–4 个独立的 32-bit WAM 消息。解码端不知道消息
数量、区域形状和消息内容，只能读取 WAM 输出的像素检测概率与 32 个 bit logit 图，
同时完成：

1. 消息数量估计；
2. 多个 32-bit 消息恢复；
3. 各消息的像素级定位。

当前版本聚焦同一空间坐标系内的多水印聚类。几何攻击会进入测试，但不会先应用 M4.1
几何同步，因为几何校正会改变局部掩膜坐标；二者的联合对齐作为后续扩展单独报告。

## 2. 对比方法

`official_hard_dbscan` 按 WAM 官方多水印示例实现：检测概率阈值 0.5、bit logit
阈值 0、Hamming 空间 DBSCAN `eps=1`、`min_samples=500`。实现先压缩重复的 32-bit
硬签名，再以签名像素计数作为 `sample_weight`，数学判定与逐像素 DBSCAN 等价，但避免
直接构造 65,536 像素的两两距离矩阵。

该方法是 M4.2 的直接对比基线，不使用真实消息数量或区域标签。

## 3. 创新方法：Adaptive Soft Message Clustering

创新解码器由四部分组成：

1. **自适应支持度**：最小簇支持取 `max(96, 0.5% × detected_pixels)`，避免固定
   3000 像素阈值直接丢弃小水印区域。
2. **加权密度候选**：按像素支持度保留最多 512 个唯一硬签名，在动态阈值、500、
   1000、2000、3000 的密度日程上搜索稳定候选；消息间至少相隔 5 bit。
3. **软证据迭代**：对 bit logit 做 sigmoid，按 bit 可靠度计算软 Hamming 距离；使用
   温度化责任度和检测概率权重迭代更新质心，而不是只投票 0/1 硬标签。
4. **稳定性保护**：初始密度簇以先验强度 2.0 约束软更新；若更新导致消息质心塌缩，
   回退到可分离的种子消息及其定位，避免把多个真实消息合并为一个。

实现位于 `src/watermark_lab/innovations/multi_message.py`，统一模型通过
`AmWamModel.decode_multiple()` 暴露该能力。

## 4. 嵌入场景与指标

冻结配置 `configs/m4_multi_message.yaml` 包含：

- 均衡 2、3、4 水印区域；
- 一个主区域加 5% 小区域的 2 水印场景；
- clean、JPEG 80/50、blur 1/3、noise 0.01、resize 0.75 和一条组合攻击；
- 四个 Debug10 数据集的 40 张固定图像。

WAM 强度沿用各数据集约 40 dB 的 M2/M3 校准值。每张图、每个场景的消息由固定种子
和样本 ID 生成，任意两消息至少相隔 12 bit。

由于消息输出无顺序，评估会穷举不超过 4 个消息的最佳一一匹配，并报告：消息计数
准确率、precision/recall、匹配 bit accuracy、全部消息恢复率和匹配区域 mIoU。
穷举在本任务的小 K 下等价于最优二分匹配，且不引入额外依赖。

## 5. 可复现运行

推荐按数据集分片，运行器每完成一张图就原子写入检查点，可在中断后精确续跑：

```powershell
$Datasets = @(
  "coco2017_val_debug10",
  "div2k_valid_hr_debug10",
  "diffusiondb_2m_debug10",
  "w_bench_det_inversion_debug10"
)

foreach ($Dataset in $Datasets) {
  .\.venv-wam\Scripts\python.exe scripts\run_m4_multi_message.py `
    --device cuda --datasets $Dataset `
    --output-dir "results\m4_multi_message_parts\$Dataset"
}

.\.venv-trustmark\Scripts\python.exe scripts\merge_m4_multi_results.py
.\.venv-trustmark\Scripts\python.exe scripts\analyze_m4_multi_results.py
```

完整记录数应为 `40 图 × 4 场景 × 8 攻击 × 2 解码器 = 2560`。逐条 CSV、分片
SHA-256、运行设备、耗时和 Bootstrap 图像单元数均保存在 `results/m4_multi_message/`。

## 6. 研究边界

M4.2 参数开发使用 Debug10，不将其结果冒充扩大测试集的泛化结论。formal-v1 的 690 张
独立测试图用于 DWT-DCT、TrustMark-Q、WAM 与完整 AM-WAM 的单水印公平对比；多水印
扩大测试需在本版本冻结后另建 formal-multi 协议，不能看到当前测试结果后回改阈值。
