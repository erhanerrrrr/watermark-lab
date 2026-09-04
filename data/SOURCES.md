# 数据来源

本目录仅提交来源说明和 manifest，原始图像位于 `data/raw/` 并被 Git 忽略。
论文引用键、模型与数据集许可边界统一见
[`docs/REFERENCES_AND_LICENSES.md`](../docs/REFERENCES_AND_LICENSES.md)；可直接导入的
BibTeX 位于 [`REFERENCES.bib`](../REFERENCES.bib)。

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

## formal-v1 扩大数据集

正式协议在同一四个公开来源上固定独立的 calibration/test 子集，并显式排除上述
Debug10 文件。选择规则由 `scripts/prepare_formal_datasets.py` 固定，最终 manifest
逐文件保存相对路径、字节数和 SHA-256：

| 来源 | calibration | test | 选择规则 |
|---|---:|---:|---|
| COCO 2017 val | 40 | 200 | 固定归档顺序，排除 Debug10 |
| DIV2K | 20（train HR） | 90（validation HR） | test 排除 0801–0810 |
| DiffusionDB 2M | 40 | 200 | 固定文件名顺序，排除 Debug10 |
| W-Bench DET_INVERSION_1K | 40 | 200 | 固定索引顺序，排除 Debug10 |
| 合计 | 140 | 690 | calibration 与 test 不重叠 |

恢复命令：

```powershell
.\.venv-trustmark\Scripts\python.exe scripts\prepare_formal_datasets.py
```

正式子集仍遵循上表各原始数据集的许可证和使用条款。原图不进入 Git；八个
`*_formal_*.csv` manifest 进入版本控制，实验时强制逐文件校验 SHA-256。
