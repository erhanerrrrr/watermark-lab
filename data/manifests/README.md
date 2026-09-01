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
