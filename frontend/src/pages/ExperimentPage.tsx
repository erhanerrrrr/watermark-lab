import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ImagePlus, Info, Play, RotateCcw, UploadCloud } from 'lucide-react'
import { attacks, models } from '../mock/data'
import { PageHeader, StatusBadge } from '../components/Layout'
import { ApiUnavailableError, listModels, runExperiment } from '../services/api'
import { storeRecentExperiment } from '../services/recentExperiment'
import type { ApiModelInfo } from '../types'

export function ExperimentPage() {
  const navigate = useNavigate()
  const [selectedModel, setSelectedModel] = useState('am_wam')
  const [selectedAttack, setSelectedAttack] = useState('jpeg')
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState('WATERMARK-LAB · 2026')
  const [strength, setStrength] = useState(2)
  const [attackParameter, setAttackParameter] = useState(80)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiModels, setApiModels] = useState<ApiModelInfo[]>([])
  useEffect(() => {
    listModels().then((items) => {
      setApiModels(items)
      setSelectedModel((current) => items.find((item) => item.id === current)?.available ? current : (items.find((item) => item.available)?.id ?? current))
    }).catch(() => setApiModels([]))
  }, [])
  const parameterForApi = () => ['noise', 'crop', 'resize', 'tamper'].includes(selectedAttack) ? attackParameter / (selectedAttack === 'noise' ? 1000 : 100) : selectedAttack === 'rotate' ? attackParameter / 10 : attackParameter
  const run = async () => {
    setError(''); setNotice('')
    if (!file) { setError('请先上传一张图片。'); return }
    setRunning(true)
    try {
      const result = await runExperiment({ image: file, model: selectedModel, message, strength, attack: selectedAttack, attackParameter: parameterForApi() })
      storeRecentExperiment(result)
      setNotice(`实验完成：Bit Accuracy ${(result.bit_accuracy * 100).toFixed(2)}%，PSNR ${result.embed_psnr_db?.toFixed(2) ?? '—'} dB`)
      window.setTimeout(() => navigate('/results'), 700)
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : '实验失败，请检查后端日志。'
      setError(caught instanceof ApiUnavailableError ? `${detail} 当前页面仍可继续作为 Mock 展示。` : detail)
    } finally { setRunning(false) }
  }
  return <><PageHeader eyebrow="实验工作台" title="创建水印实验" description="配置一张输入图像、一个水印模型和攻击协议，调用本地 Python 后端完成单次实验。" action={<StatusBadge tone={apiModels.length ? 'green' : 'slate'}>{apiModels.length ? '真实 API 已连接' : 'Mock 回退模式'}</StatusBadge>} /><div className="experiment-layout"><div className="panel upload-panel"><div className="panel-heading"><div><span className="panel-kicker">Step 01</span><h2>输入图像</h2></div><ImagePlus size={18} className="muted" /></div><label className="dropzone"><input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /><UploadCloud size={28} /><strong>{file?.name || '拖拽图像到这里，或点击上传'}</strong><span>PNG / JPG / WebP · 至少 128×128，最大 15 MB</span></label><div className="upload-note"><Info size={15} /> 图片只发送到本机 FastAPI，不会离开当前设备。</div></div><div className="panel form-panel"><div className="panel-heading"><div><span className="panel-kicker">Step 02</span><h2>实验配置</h2></div><RotateCcw size={18} className="muted" /></div><label className="field-label">选择水印模型<select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>{models.map((model) => { const state = apiModels.find((item) => item.id === model.id); return <option key={model.id} value={model.id} disabled={state?.available === false}>{model.name} · {model.family}{state?.available === false ? '（当前 API 环境不可用）' : ''}</option> })}</select></label><label className="field-label">水印信息<textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} /></label><div className="field-grid"><label className="field-label">消息长度<select value="32" disabled><option>32 bit（文本自动哈希）</option></select></label><label className="field-label">嵌入强度<input type="number" value={strength} onChange={(e) => setStrength(Number(e.target.value))} min="0.1" step="0.1" /></label></div><label className="field-label">攻击协议<select value={selectedAttack} onChange={(e) => setSelectedAttack(e.target.value)}>{attacks.map((attack) => <option key={attack.id} value={attack.id}>{attack.name} · {attack.strength}</option>)}</select></label><div className="attack-params"><span>攻击参数</span><strong>{attacks.find((a) => a.id === selectedAttack)?.description}</strong><div className="range-line"><input type="range" min="0" max="100" value={attackParameter} onChange={(e) => setAttackParameter(Number(e.target.value))} /><output>{attackParameter}{selectedAttack === 'jpeg' ? '（质量）' : '%'}</output></div></div>{error && <div className="form-message error">{error}</div>}{notice && <div className="form-message success">{notice}</div>}<button className="primary-button run-button" onClick={run} disabled={running}><Play size={16} /> {running ? '真实模型运行中…' : '运行真实实验'}</button></div></div></>
}
