export interface ApiHealth {
  status: 'ok'
  mode: 'local'
  version: string
  storage: string
  persisted_experiments: number
  frontend_available: boolean
}

export interface FormalModelMetrics {
  records: number
  detected: number
  bit_accuracy: number
  complete_recovery: number
  embed_psnr_db: number
  encode_ms: number
  decode_ms: number
}

export interface ApiModelInfo {
  id: string
  display_name: string
  stage: string
  role: string
  family: string
  description: string
  detail: string
  robustness: string
  default_strength: number
  accent: string
  available: boolean
  reason?: string | null
  formal_metrics?: FormalModelMetrics | null
}

export interface DatasetSplitCount {
  found: number
  expected: number
}

export interface ApiDatasetInfo {
  id: string
  display_name: string
  source: string
  license: string
  debug_manifest: string
  calibration_manifest: string
  test_manifest: string
  counts: Record<'debug' | 'calibration' | 'test', DatasetSplitCount>
  found_images: number
  expected_images: number
  progress: number
  ready: boolean
}

export interface AttackStepInfo {
  name: string
  parameters: Record<string, unknown>
}

export interface AttackCaseInfo {
  id: string
  category: 'control' | 'single' | 'compound'
  pipeline: AttackStepInfo[]
}

export interface AttackProtocolInfo {
  id: string
  version: number
  seed: number
  cases: AttackCaseInfo[]
}

export interface InteractiveAttackInfo {
  id: string
  display_name: string
  description: string
  parameter_label: string
  minimum: number
  maximum: number
  step: number
  default: number
  unit: string
}

export interface FormalSnapshot {
  suite_id: string
  complete: boolean
  records: number
  expected_records: number
  calibration_images: number
  test_images: number
  attack_cases: number
  target_psnr_db: number
  source: string
  data_source: 'local_formal_results' | 'tracked_snapshot'
  models: Record<string, FormalModelMetrics>
  innovation: {
    bit_accuracy_gain_pp: number
    complete_recovery_gain_pp: number
    rotation_10_gain_pp: number
    perspective_heavy_gain_pp: number
    decode_overhead_ms: number
    unresolved: string
  }
}

export interface ApiCatalog {
  version: number
  updated_at: string
  project: { name: string; subtitle: string; stage: string }
  models: ApiModelInfo[]
  datasets: ApiDatasetInfo[]
  protocol: AttackProtocolInfo
  interactive_attacks: InteractiveAttackInfo[]
  formal: FormalSnapshot
}

export interface ApiExperimentSummary {
  id: string
  created_at: string
  image_name: string
  model: string
  message_bits: number
  attack: string
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
}

export interface ApiExperimentDetail extends ApiExperimentSummary {
  expected_message: string
  decoded_message: string
  attack_parameters: Record<string, unknown>
  metadata: Record<string, unknown>
  artifacts: {
    original: string
    embedded: string
    attacked: string
  }
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

export interface DatasetVerification {
  id: string
  expected: number
  verified: number
  missing: string[]
  mismatched: string[]
  valid: boolean
}
