# 几何解码输出修复记录

2026-09-05 的独立代码评估确认了两项输出缺陷，并增加了独立回归测试。

## 定位图坐标

原实现直接返回最佳校正分支的检测图。选中旋转或透视分支时，检测图属于校正后的
图像坐标，叠加在上传图或攻击后图上会错位。

修复后将最佳分支的检测概率映射回本次 `decode(image)` 输入图坐标。输出仍保留
原 WAM detector grid 的尺寸和 `float32` 概率值，供调用方按输入图尺寸缩放、叠加。
当前 Web 尚未展示定位图；本次修复的是研究内核的输出契约。变换先在原图坐标建立，
再按宽、高分别映射到检测网格，避免
将非方形原图的旋转直接作用于方形低分辨率检测图。插值采用浮点双线性，画布外
填 0，概率限制在 `[0, 1]`；identity 分支逐值保留原检测图。

metadata 新增 `localization_coordinate_system=input_image` 和
`localization_grid=detector`。检测面积和候选评分继续使用校正分支的原始概率图；
返回定位图只是空间输出修复，不重新定义历史检测分数。

## 空检测分支的融合

没有任何检测像素的分支使用 `-inf` pooled logits 表示无消息。如果此类分支进入
top-k 加权融合，即使权重很小，也会将有效分支的全部 bit logits 变成 `-inf`，
错误输出全 0 消息。现仅让具有检测像素的分支参与几何融合；所有分支均无检测时
仍回退 identity 并返回 `detected=False`，包括最低检测面积配置为 0 的边界情况。

定位图修复不改变消息选择；空分支修复可能改变上述边界情况下的消息输出。此次
没有重写 formal-v1、robustness-v2 或任何冻结结果，历史数值仍对应原实验实现。
未来新实验应保留运行时代码哈希以区分版本。

## 验证

`tests/test_geometry_localization.py` 覆盖 identity、正负旋转方向、低分辨率
非方图坐标、横图与竖图透视回投影、画布外无证据区域、真实 decode 输出接线、
空分支污染及全部空检测。测试使用确定性空间地标和攻击流水线，无需加载权重。

```powershell
.\.venv-trustmark\Scripts\python.exe -m pytest tests/test_geometry_localization.py tests/test_m4_innovations.py tests/test_wam_adapter.py -q
.\.venv-trustmark\Scripts\python.exe -m ruff check src/watermark_lab/innovations/geometry_sync.py tests/test_geometry_localization.py
```
