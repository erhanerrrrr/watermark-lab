# 论文引用与第三方许可清单

更新时间：2026-09-04。本文件统一论文、README、答辩材料和 Release 中的引用口径。
可直接导入 Word、Zotero 或 LaTeX 的条目位于根目录 `REFERENCES.bib`；数据选样、下载与
manifest 规则仍以 `data/SOURCES.md` 为准。

## 1. 引用规则

1. 介绍 WAM/AM-WAM 时引用 `sander2025watermark`；AM-WAM 是本课程项目基于 WAM
   推理、几何同步和聚类流程的改进，不应写成 Meta 官方模型。
2. 介绍 TrustMark-Q 时引用 `bui2025trustmark`。若讨论其 2023 预印本历史，可改用
   `bui2023trustmark`，正文同一处不必重复引用两个版本。
3. 首次介绍 COCO、DIV2K、DiffusionDB 时分别引用 `lin2014coco`、
   `agustsson2017ntire`、`wang2022diffusiondb`。
4. W-Bench 当前使用 Hugging Face 数据集页面作为可追溯来源，引用
   `wbench_huggingface`；在未核实关联论文前，不为它虚构论文作者或发表信息。
5. DWT-DCT 是本项目自行实现的可复现基线，不宣称复现某一篇具体水印论文。说明其
   变换基础时可引用 `ahmed1974dct` 和 `mallat1989wavelet`。
6. 论文中的所有实验数字必须来自冻结结果文档，不能引用 Debug10 数字代替正式结果。

## 2. 模型、源码与权重

| 资产 | 本项目固定版本 | 上游许可与使用边界 | 论文引用 |
|---|---|---|---|
| Watermark Anything 源码 | commit `2c08af04d037d5667c02f6ddebbda9ff04581c3e` | MIT | `sander2025watermark` |
| `wam_mit.pth` 权重 | SHA-256 `90ef232384e023bd63245eb0c131abd69d2afc7b8f17a71ccedceb542bf009e2` | 官方说明为 MIT；本项目使用 SA-1B 训练的 MIT 权重，不使用另行发布的 COCO 非商业权重 | `sander2025watermark` |
| TrustMark Python 包 | `trustmark==0.9.0` | MIT；权重首次运行时由官方包下载 | `bui2025trustmark` |
| DWT-DCT | 本仓库自行实现 | 无外部权重；仅引用 DWT/DCT 基础文献，不冒充现有论文复现 | `ahmed1974dct`、`mallat1989wavelet` |

WAM 权重 URL、字节数和哈希位于 `configs/wam_official.yaml`；TrustMark 三个 Q 变体权重
哈希位于 `docs/REPRODUCIBILITY.md`。发布产物不得绕过哈希校验，也不得将第三方权重
直接提交到 Git。

## 3. 数据集

| 数据集 | 项目用途 | 许可/权利边界 | 论文引用 |
|---|---|---|---|
| COCO 2017 val | 自然图像 | COCO 标注采用 CC BY 4.0；图片版权和许可由各 Flickr 原作者决定，应遵守 COCO 官方使用条款 | `lin2014coco` |
| DIV2K | 高分辨率图像 | 官方页面限定为学术研究用途；图片版权归原权利人 | `agustsson2017ntire` |
| DiffusionDB 2M | AI 生成图像 | 数据集页面标记 CC0 1.0；仍须注意生成内容可能涉及的第三方权利及数据卡警告 | `wang2022diffusiondb` |
| W-Bench `DET_INVERSION_1K` | 生成式编辑场景 | 本项目采集时数据卡标记 MIT；再分发前须重新核对数据卡当前版本和具体文件条款 | `wbench_huggingface` |

原始图片均位于 Git 忽略的 `data/raw/`，仓库只提交来源说明及包含相对路径、尺寸和
SHA-256 的 manifest。Release 默认不打包原始图片。

## 4. 本仓库许可状态

仓库根目录当前没有项目自身的 `LICENSE`。这意味着 WAM、TrustMark 等第三方资产的
MIT 许可不会自动成为本项目原创代码的许可。课程提交可以继续保留此状态；若要允许
公众复制、修改或再发布本项目原创代码，应由仓库所有者明确选择许可证并单独添加
`LICENSE`。在此之前，不对本项目原创代码作额外授权声明。

## 5. 发布检查

- 论文和 PPT 使用 `REFERENCES.bib` 中统一的标题、作者、年份和引用键；
- Release 说明链接本文件与 `data/SOURCES.md`；
- 不打包 `data/raw/`、`checkpoints/`、`third_party/` 或 `.venv*`；
- 若发布正式结果压缩包，记录 Git 提交、配置版本、环境快照和 ZIP SHA-256；
- 任何新增模型、权重或数据集都必须先补充来源、版本、哈希、许可和引用。
