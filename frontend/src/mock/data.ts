import type { AttackInfo, DatasetInfo, ExperimentRecord, ModelInfo } from '../types'

export const models: ModelInfo[] = [
  { id: 'lsb_reference', name: 'LSB Reference', family: '空间域基线', milestone: 'M1', description: '最低复杂度的管线自检模型，用于验证端到端流程。', detail: '逐像素最低有效位嵌入，速度快但鲁棒性有限。', status: 'ready', psnr: '≈ 51 dB', robustness: '低', accent: '#64748b' },
  { id: 'dwt_dct', name: 'DWT-DCT', family: '传统频域', milestone: 'M2', description: '小波变换结合离散余弦变换的可解释基线。', detail: '在中频系数中嵌入消息，兼顾视觉质量和压缩鲁棒性。', status: 'ready', psnr: '40.18 dB', robustness: '中', accent: '#0ea5e9' },
  { id: 'trustmark_q', name: 'TrustMark-Q', family: '深度学习', milestone: 'M2', description: 'Adobe TrustMark Q 变体，全局深度水印基线。', detail: 'ResNet50 解码器 + BCH-5 纠错编码，容量 32 bit。', status: 'ready', psnr: '40.12 dB', robustness: '高', accent: '#8b5cf6' },
  { id: 'wam', name: 'WAM', family: '前沿模型', milestone: 'M3', description: 'Watermark Anything 官方模型，支持空间检测与盲解码。', detail: 'ViT 编码器与密集预测解码器，适合多区域水印。', status: 'ready', psnr: '40.05 dB', robustness: '很高', accent: '#10b981' },
  { id: 'am_wam', name: 'AM-WAM', family: '研究改进', milestone: 'M4', description: '几何同步与内容自适应的 WAM 改进方案。', detail: '通过几何搜索和自适应强度，提升旋转场景恢复率。', status: 'ready', psnr: '39.99 dB', robustness: '很高', accent: '#f59e0b' },
]

export const datasets: DatasetInfo[] = [
  { id: 'coco2017', name: 'COCO 2017 val', source: 'Microsoft COCO', size: '10 / 240 张', split: 'Debug10 · Formal 200', status: '已就绪', progress: 100, license: 'COCO 条款' },
  { id: 'div2k', name: 'DIV2K validation HR', source: 'ETH Zürich', size: '10 / 110 张', split: 'Debug10 · Formal 90', status: '已就绪', progress: 100, license: '学术研究' },
  { id: 'diffusiondb', name: 'DiffusionDB 2M', source: 'Hugging Face', size: '10 / 240 张', split: 'Debug10 · Formal 200', status: '部分下载', progress: 35, license: 'CC0 / Stability AI' },
  { id: 'wbench', name: 'W-Bench DET_INVERSION', source: 'Shilin-LU/W-Bench', size: '10 / 240 张', split: 'Debug10 · Formal 200', status: '待下载', progress: 0, license: 'MIT' },
]

export const attacks: AttackInfo[] = [
  { id: 'jpeg', name: 'JPEG 压缩', category: '单项攻击', description: '模拟有损图像压缩，测试频域信息保持能力。', strength: '质量 50 / 80' },
  { id: 'noise', name: '高斯噪声', category: '单项攻击', description: '叠加随机噪声，检验消息在传输扰动下的稳定性。', strength: 'σ = 0.01' },
  { id: 'crop', name: '随机裁剪', category: '几何攻击', description: '裁剪图像局部区域，观察定位与恢复能力。', strength: '保留 80%' },
  { id: 'resize', name: '缩放', category: '几何攻击', description: '改变图像分辨率后恢复原尺寸。', strength: '0.75×' },
  { id: 'rotate', name: '旋转', category: '几何攻击', description: '模拟拍摄或编辑产生的角度偏移。', strength: '±5° / 10°' },
  { id: 'tamper', name: '局部篡改', category: '内容攻击', description: '对局部区域进行替换或涂抹。', strength: '5% 区域' },
  { id: 'compound', name: '组合攻击', category: '复合攻击', description: '串联多种攻击，贴近真实发布链路。', strength: '8 条协议' },
]

export const experiments: ExperimentRecord[] = [
  { id: 'EXP-240902-001', model: 'AM-WAM', dataset: 'COCO 2017 val', attack: '旋转 10°', status: '完成', bitAccuracy: 99.58, psnr: 39.99, ssim: 0.982, ber: 0.42, detectionRate: 96.21, createdAt: '今天 09:42' },
  { id: 'EXP-240902-002', model: 'WAM', dataset: 'COCO 2017 val', attack: 'JPEG Q80', status: '完成', bitAccuracy: 99.40, psnr: 40.05, ssim: 0.984, ber: 0.60, detectionRate: 94.60, createdAt: '昨天 18:16' },
  { id: 'EXP-240901-018', model: 'TrustMark-Q', dataset: 'DIV2K', attack: '高斯噪声 σ=.01', status: '完成', bitAccuracy: 82.22, psnr: 40.12, ssim: 0.979, ber: 17.78, detectionRate: 64.04, createdAt: '09-01 22:31' },
  { id: 'EXP-240901-017', model: 'DWT-DCT', dataset: 'DiffusionDB 2M', attack: '组合攻击', status: '完成', bitAccuracy: 84.94, psnr: 40.18, ssim: 0.976, ber: 15.06, detectionRate: 57.46, createdAt: '09-01 20:08' },
  { id: 'EXP-240901-016', model: 'AM-WAM', dataset: 'W-Bench', attack: '裁剪 20%', status: '运行中', bitAccuracy: 0, psnr: 0, ssim: 0, ber: 0, detectionRate: 0, createdAt: '09-01 19:54' },
]

export const comparisonData = [
  { name: 'DWT-DCT', bitAccuracy: 84.94, recovery: 57.46, psnr: 40.175 },
  { name: 'TrustMark-Q', bitAccuracy: 82.22, recovery: 64.04, psnr: 40.123 },
  { name: 'WAM', bitAccuracy: 99.40, recovery: 94.60, psnr: 40.047 },
  { name: 'AM-WAM', bitAccuracy: 99.58, recovery: 96.21, psnr: 39.986 },
]

export const trendData = [
  { name: 'M1', accuracy: 67, psnr: 51.2 }, { name: 'M2', accuracy: 84, psnr: 40.1 }, { name: 'M3', accuracy: 99.4, psnr: 40.0 }, { name: 'M4', accuracy: 99.6, psnr: 40.0 },
]
