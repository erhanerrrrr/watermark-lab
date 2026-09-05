import { useEffect, useMemo, useState } from 'react'
import { ImagePlus, Info, Play, RotateCcw, UploadCloud } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { ApiRequired, PageHeader, StatusBadge } from '../components/Layout'
import { runExperiment } from '../services/api'
import { useApi } from '../services/ApiContext'
import type { ApiCatalog } from '../types'

const MAX_UPLOAD_BYTES = 15 * 1024 * 1024

function defaultModel(catalog: ApiCatalog) {
  return catalog.models.find((model) => model.id === 'budget_wam' && model.available)
    ?? catalog.models.find((model) => model.id === 'am_wam' && model.available)
    ?? catalog.models.find((model) => model.available)
}

export function ExperimentPage() {
  const navigate = useNavigate()
  const { catalog, connection, refreshExperiments } = useApi()
  const [selectedModel, setSelectedModel] = useState('')
  const [selectedAttack, setSelectedAttack] = useState('jpeg')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [message, setMessage] = useState('WATERMARK-LAB · 2026')
  const [strength, setStrength] = useState(2)
  const [attackParameter, setAttackParameter] = useState(80)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!catalog) return
    const preferred = defaultModel(catalog)
    if (!selectedModel && preferred) {
      setSelectedModel(preferred.id)
      setStrength(preferred.default_strength)
    }
  }, [catalog, selectedModel])

  useEffect(() => {
    if (!file) { setPreview(''); return undefined }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const attack = useMemo(() => catalog?.interactive_attacks.find((item) => item.id === selectedAttack), [catalog, selectedAttack])
  const model = catalog?.models.find((item) => item.id === selectedModel)
  if (!catalog) return <ApiRequired />

  const selectModel = (modelId: string) => {
    setSelectedModel(modelId)
    const selected = catalog.models.find((item) => item.id === modelId)
    if (selected) setStrength(selected.default_strength)
  }
  const selectAttack = (attackId: string) => {
    setSelectedAttack(attackId)
    const selected = catalog.interactive_attacks.find((item) => item.id === attackId)
    if (selected) setAttackParameter(selected.default)
  }
  const reset = () => {
    const preferred = defaultModel(catalog)
    setSelectedModel(preferred?.id ?? '')
    setStrength(preferred?.default_strength ?? 2)
    setSelectedAttack('jpeg'); setAttackParameter(80); setMessage('WATERMARK-LAB · 2026'); setFile(null); setError('')
  }
  const run = async () => {
    setError('')
    if (connection !== 'connected') { setError('本地 API 未连接。'); return }
    if (!file) { setError('请先上传一张图片。'); return }
    if (file.size > MAX_UPLOAD_BYTES) { setError('图片不能超过 15 MB。'); return }
    if (!message.trim()) { setError('水印消息不能为空。'); return }
    if (!model?.available) { setError(model?.reason ?? '当前模型不可用。'); return }
    setRunning(true)
    try {
      const result = await runExperiment({ image: file, model: selectedModel, message, strength, attack: selectedAttack, attackParameter, device: 'auto' })
      await refreshExperiments()
      navigate('/results', { state: { experimentId: result.id } })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '实验失败，请检查后端日志。')
    } finally { setRunning(false) }
  }
  return <>
    <PageHeader eyebrow="实验工作台" title="创建真实水印实验" description="上传内容只在本机处理；结果、指标和三张 PNG 产物会持久保存。" action={<StatusBadge tone={connection === 'connected' ? 'green' : 'amber'}>{connection === 'connected' ? '真实 API 已连接' : 'API 未连接'}</StatusBadge>} />
    <div className="experiment-layout">
      <div className="panel upload-panel"><div className="panel-heading"><div><span className="panel-kicker">Step 01</span><h2>输入图像</h2></div><ImagePlus size={18} className="muted" /></div><label className={`dropzone ${preview ? 'has-preview' : ''}`}><input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />{preview ? <img className="upload-preview" src={preview} alt="待处理图片预览" /> : <><UploadCloud size={28} /><strong>拖拽图片到这里，或点击上传</strong><span>PNG / JPG / WebP · 至少 128×128 · 最大 15 MB</span></>}</label>{file && <div className="file-summary"><strong>{file.name}</strong><span>{(file.size / 1024 / 1024).toFixed(2)} MB</span></div>}<div className="upload-note"><Info size={15} /> 图片不会上传至外部服务器；实验产物保存在本机 artifacts/web。</div></div>
      <div className="panel form-panel"><div className="panel-heading"><div><span className="panel-kicker">Step 02</span><h2>模型与攻击配置</h2></div><button className="icon-button" onClick={reset} aria-label="重置实验配置" title="重置"><RotateCcw size={18} /></button></div><label className="field-label">水印模型<select value={selectedModel} onChange={(event) => selectModel(event.target.value)}>{catalog.models.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.display_name} · {item.family}{!item.available ? '（当前不可用）' : ''}</option>)}</select></label>{model?.reason && <div className="form-message warning">{model.reason}</div>}<label className="field-label">水印信息<textarea value={message} maxLength={4096} onChange={(event) => setMessage(event.target.value)} rows={3} /><small>{message.length}/4096 · 文本会确定性映射为 {model?.id === 'trustmark_q' ? '32' : '模型要求的'} bit 消息</small></label><div className="field-grid"><label className="field-label">嵌入强度<input type="number" value={strength} onChange={(event) => setStrength(Number(event.target.value))} min="0.01" max="1000" step="0.1" /></label><label className="field-label">推理运行环境<select value="auto" disabled><option value="auto">{model?.runtime_label ?? "自动选择设备"}</option></select></label></div><label className="field-label">交互攻击<select value={selectedAttack} onChange={(event) => selectAttack(event.target.value)}>{catalog.interactive_attacks.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>{attack && <div className="attack-params"><span>{attack.parameter_label}</span><strong>{attack.description}</strong>{attack.minimum !== attack.maximum ? <div className="range-line"><input type="range" min={attack.minimum} max={attack.maximum} step={attack.step} value={attackParameter} onChange={(event) => setAttackParameter(Number(event.target.value))} /><output>{attackParameter} {attack.unit}</output></div> : <div className="fixed-parameter">固定配置，无可调参数</div>}</div>}{error && <div className="form-message error" role="alert">{error}</div>}<button className="primary-button run-button" onClick={() => void run()} disabled={running || connection !== 'connected' || !model?.available}><Play size={16} /> {running ? '模型运行中，请勿关闭页面…' : '运行并保存真实实验'}</button><p className="runtime-note">首次调用需要加载权重；各推理进程会复用自己的模型实例。</p></div>
    </div>
  </>
}
