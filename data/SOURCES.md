# 调试数据来源

本目录仅提交来源说明和 manifest，原始图像位于 `data/raw/` 并被 Git 忽略。

| 本地子集 | 官方来源 | 调试样本选择 |
|---|---|---|
| COCO 2017 val | https://cocodataset.org/#download | validation 中按固定图像 ID 的 10 张 |
| DIV2K validation HR | https://data.vision.ee.ethz.ch/cvl/DIV2K/ | 0801–0810 |
| DiffusionDB 2M | https://huggingface.co/datasets/poloclub/diffusiondb | part-000001 ZIP 中按文件名排序的前 10 张 |
| W-Bench | https://huggingface.co/datasets/Shilin-LU/W-Bench | DET_INVERSION_1K 中索引 0–9 |

DIV2K 仅允许学术研究使用；DiffusionDB 图片为 CC0，同时应遵守 Stability AI
相关使用条款；W-Bench 数据集页面标记为 MIT；COCO 图像须遵守 COCO 官方使用条款。

下载命令：

```powershell
python scripts\download_debug_datasets.py
```
