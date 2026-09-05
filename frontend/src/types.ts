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
  execution_backend?: 'local' | 'isolated'
  runtime_label?: string
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
  detection: {
    suite_id: string
    complete: boolean
    records: number
    calibration_negative_images: number
    test_positive_images: number
    test_negative_images: number
    target_calibration_fpr: number
    source: string
    models: Record<string, {
      score_resolution: 'continuous' | 'binary'
      threshold: number
      tpr: number
      fpr: number
      roc_auc: number
      intrinsic_fpr: number
    }>
  }
  robustness_v2: {
    suite_id: string
    complete: boolean
    records: number
    images: number
    attack_cases: number
    bootstrap_iterations: number
    source: string
    wam: Pick<FormalModelMetrics, 'bit_accuracy' | 'complete_recovery' | 'decode_ms'>
    am_wam: Pick<FormalModelMetrics, 'bit_accuracy' | 'complete_recovery' | 'decode_ms'>
    innovation: {
      bit_accuracy_gain_pp: number
      complete_recovery_gain_pp: number
      decode_overhead_ms: number
      off_grid_geometry_recovery_gain_pp: number
    }
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
  status: 'ready' | 'not_prepared' | 'partial' | 'mismatch'
}

export interface ResearchEvidenceRow {
  dataset: string
  attack: string
  category: string
  images: number
  paired_records: number
  models: {
    id: string
    bit_accuracy: number
    complete_recovery: number
    embed_psnr_db: number
    decode_ms: number
  }[]
  comparison: {
    bit_accuracy_gain_pp: number
    recovery_gain_pp: number
    recovery_ci95_pp: [number, number]
    rescued: number
    regressed: number
    both_recovered: number
    both_failed: number
    decode_overhead_ms: number
  }
}

export interface ResearchEvidence {
  version: number
  suite_id: string
  source: string
  records: number
  images: number
  attacks: number
  generated_at: string
  bootstrap_iterations: number
  notes: string[]
  datasets: { id: string; label: string; images: number }[]
  rows: ResearchEvidenceRow[]
  sensitivity: {
    excluded_attack: string
    images: number
    paired_records: number
    recovery_gain_pp: number
    recovery_ci95_pp: [number, number]
  }[]
  provenance: { path: string; sha256: string }[]
}

export interface GeometryPair {
  baseline: string
  image_units: number
  paired_records: number
  recovery_gain_pp: number
  ci95_pp: [number, number]
  rescued: number
  regressed: number
  budget_recovery: number
  baseline_recovery: number
}

export interface GeometryEvidence {
  suite_id: 'geometry-v3'
  complete: true
  generated_at: string
  calibration_images: number
  test_images: number
  attack_cases: number
  negative_attack_cases: number
  max_input_side: number
  positive_records_per_method: number
  negative_records_per_method: number
  policy: { max_candidates: number; detection_fraction_threshold: number }
  calibration_targets_met: boolean
  test_criteria: {
    recovery_tolerance_pp: number
    recovery_point_target_met: boolean
    noninferiority_ci_supported: boolean
    candidate_target_met: boolean
  }
  methods: {
    method: string
    label: string
    complete_recovery: number
    bit_accuracy: number
    mean_candidates: number
    mean_psnr_db: number
    threshold: number
    tpr: number
    fpr: number
    false_positive_images: number
    negative_images: number
    false_positive_image_ci95: [number, number]
  }[]
  paired: GeometryPair[]
  by_family: (GeometryPair & { family: string })[]
  by_dataset: (GeometryPair & { dataset: string })[]
  decision_audit: {
    stop_reason: string
    records: number
    mean_candidates: number
    complete_recovery: number
    rescued_vs_full_best: number
    regressed_vs_full_best: number
  }[]
  timing: {
    image_units: number
    measured_conditions: number
    repetitions: number
    device: string
    live_replay_bitwise_verified: boolean
    methods: { method: string; runs: number; mean_ms: number; p50_ms: number; p95_ms: number; mean_candidates: number; peak_cuda_allocated_mb: number }[]
  }
  notes: string[]
  provenance: { path: string; sha256: string }[]
}
