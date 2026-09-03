export type ModelStatus = 'ready' | 'adapter' | 'planned'

export interface ModelInfo {
  id: string
  name: string
  family: string
  milestone: string
  description: string
  detail: string
  status: ModelStatus
  psnr: string
  robustness: string
  accent: string
}

export interface DatasetInfo {
  id: string
  name: string
  source: string
  size: string
  split: string
  status: string
  progress: number
  license: string
}

export interface AttackInfo {
  id: string
  name: string
  category: string
  description: string
  strength: string
}

export interface ExperimentRecord {
  id: string
  model: string
  dataset: string
  attack: string
  status: '完成' | '运行中' | '排队'
  bitAccuracy: number
  psnr: number
  ssim: number
  ber: number
  detectionRate: number
  createdAt: string
}

export interface ApiModelInfo {
  id: string
  stage: string
  role: string
  available: boolean
  reason?: string | null
}

export interface ApiExperimentResult {
  id: string
  created_at: string
  image_name: string
  model: string
  message_bits: number
  expected_message: string
  decoded_message: string
  attack: string
  attack_parameters: Record<string, unknown>
  detected: boolean
  detection_confidence: number
  bit_accuracy: number
  ber: number
  complete_recovery: boolean
  embed_psnr_db: number | null
  embed_ssim: number
  post_attack_psnr_db: number | null
  post_attack_ssim: number
  encode_ms: number
  decode_ms: number
  original_image_data_url: string
  embedded_image_data_url: string
  attacked_image_data_url: string
  metadata: Record<string, unknown>
}

export interface RunExperimentPayload {
  image: File
  model: string
  message: string
  strength: number
  attack: string
  attackParameter: number
  device?: string
}
