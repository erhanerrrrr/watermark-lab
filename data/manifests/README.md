# 数据集 Manifest

正式实验不直接扫描数据目录，而是读取固定 CSV manifest。每行保存数据集、
划分、样本 ID、相对路径、尺寸、格式和 SHA-256，以保证不同模型使用完全相同的图像。

在 Windows PowerShell 中生成示例：

```powershell
watermark-lab build-manifest `
  --dataset coco2017 `
  --split val `
  --root D:\datasets\coco2017\val2017 `
  --limit 200 `
  --output data\manifests\coco2017_val_200.csv
```

项目计划使用的文件名已经写入 `configs/experiment_plan.yaml`。manifest 可以提交，
原始数据集、缓存和模型权重不可提交。

仓库当前包含两级固定清单：

- `*_debug10.csv`：M2–M4 开发与诊断，每来源 10 张；
- `*_formal_cal*.csv` 与 `*_formal_test*.csv`：formal-v1 的 140 张校准和 690 张测试。

formal-v1 由 `scripts/prepare_formal_datasets.py` 确定性生成，显式排除全部 Debug10
文件，并将 calibration/test 写到不同根目录。实验读取时使用 `verify_sha256=True`；文件
缺失、字节变化或哈希不一致都会停止运行，不允许静默换图。
