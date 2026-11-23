<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import LossChart from './components/LossChart.vue'

const status = ref(null)
const curve = ref([])
const logs = ref([])
const evalSum = ref(null)
const evalRun = ref(null)
const speakers = ref([])
const presets = ref([])
const err = ref('')
let timers = []
let ws = null

const synth = reactive({
  text: '今天的天气真不错，我们出去走走吧。',
  speaker: '',
  n_steps: 2,
  temperature: 0,
  seed: 1234,
  loading: false,
  result: null,
  compare: null,
  compareErr: '',
})

const fmt = (v, d = 3) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d))
const pct = v => (v == null ? '—' : (Number(v) * 100).toFixed(1) + '%')
const dur = s => {
  if (s == null) return '—'
  s = Math.max(0, Math.round(s))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60
  return h ? `${h}h ${m}m` : m ? `${m}m ${x}s` : `${x}s`
}
const int = v => (v == null ? '—' : Number(v).toLocaleString())

const gpu = computed(() => status.value?.gpu || {})
const gpuMemPct = computed(() => {
  const g = gpu.value
  return g.mem_total_mb ? Math.min(100, (g.mem_used_mb / g.mem_total_mb) * 100) : 0
})
const kpis = computed(() => {
  const s = status.value || {}
  return [
    { label: '训练步数', value: `${int(s.step)} / ${int(s.total_steps)}`, sub: `epoch ${s.epoch ?? '—'} · ${pct(s.progress)}`, accent: 'violet' },
    { label: 'CFM loss', value: fmt(s.loss, 4), sub: `cfm ${fmt(s.loss_cfm, 4)} · dur ${fmt(s.loss_dur, 4)}`, accent: 'violet' },
    { label: '验证 loss', value: fmt(s.val_loss ?? s.best_val, 4), sub: `best @${int(s.best_step)}`, accent: 'green' },
    { label: '学习率', value: s.lr ? Number(s.lr).toExponential(2) : '—', sub: `${fmt(s.it_s, 1)} it/s · batch ${s.batch ?? '—'}`, accent: 'cyan' },
    { label: '剩余时间', value: dur(s.eta_s), sub: `已训练 ${dur(s.elapsed_s)}`, accent: 'amber' },
    { label: '显存 / GPU', value: `${fmt(gpu.value.mem_used_mb / 1024, 1)} / ${fmt(gpu.value.mem_total_mb / 1024, 1)} GB`, sub: `util ${fmt(gpu.value.util, 0)}% · ${fmt(gpu.value.temp, 0)}°C · ${fmt(gpu.value.power, 0)}W`, accent: 'violet' },
  ]
})
const dataset = computed(() => status.value?.dataset || {})
const stages = computed(() => status.value?.stages || [])
const probeList = computed(() => {
  const ps = status.value?.probes || []
  const seen = new Set(ps.map(p => p.wav))
  return ps.slice().reverse().slice(0, 8)
})
const live = computed(() => !!status.value?.training)

const metricDefs = [
  { k: 'mean_cer', label: 'CER ↓', fmt: v => (v == null ? '—' : (v * 100).toFixed(2) + '%') },
  { k: 'mean_sim', label: '说话人相似度 ↑', fmt: v => fmt(v, 3) },
  { k: 'mean_f0_median', label: 'F0 中位数 (Hz)', fmt: v => fmt(v, 1) },
  { k: 'mean_f0_span_st', label: 'F0 半音跨度', fmt: v => fmt(v, 2) },
  { k: 'mean_hf8', label: '8kHz+ 能量占比 ↑', fmt: v => pct(v) },
  { k: 'mean_hf10', label: '10kHz+ 能量占比 ↑', fmt: v => pct(v) },
  { k: 'mean_dur_ratio', label: '时长比 (vs GT)', fmt: v => fmt(v, 3) },
  { k: 'mean_rtf', label: 'RTF ↓', fmt: v => fmt(v, 3) },
  { k: 'mean_pesq', label: 'SQUIM PESQ ↑', fmt: v => fmt(v, 3) },
  { k: 'mean_stoi', label: 'SQUIM STOI ↑', fmt: v => fmt(v, 3) },
]

const sys = computed(() => evalSum.value?.systems || {})
const items = computed(() => evalSum.value?.items || [])
const slices = computed(() => evalSum.value?.slices || [])

function delta(k) {
  const a = sys.value.v1?.[k], b = sys.value.v2?.[k]
  if (a == null || b == null) return '—'
  const d = b - a
  return (d >= 0 ? '+' : '') + (Math.abs(d) < 0.01 && Math.abs(a) < 2 ? (d * 100).toFixed(2) + 'pp' : d.toFixed(3))
}

async function j(url, opt) {
  const r = await fetch(url, opt)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

async function refreshStatus() {
  try { status.value = await j('/api/monitor/status'); err.value = '' } catch (e) { err.value = String(e) }
}
async function refreshCurve() {
  try { const d = await j('/api/monitor/curve?limit=1500'); curve.value = d.points } catch (e) {}
}
async function refreshLogs() {
  try { const d = await j('/api/monitor/logs?tail=80'); logs.value = d.lines } catch (e) {}
}
async function refreshEval() {
  try {
    const d = await j('/api/eval/summary')
    if (d.ready) evalSum.value = d
  } catch (e) {}
  try { evalRun.value = await j('/api/eval/status') } catch (e) {}
}
async function refreshSpeakers() {
  try { const d = await j('/api/tts/speakers'); speakers.value = d.speakers || [] } catch (e) {}
}
async function refreshPresets() {
  try { const d = await j('/api/tts/presets'); presets.value = d.items || [] } catch (e) {}
}

function connectWs() {
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/monitor/ws`)
    ws.onmessage = ev => {
      try { status.value = JSON.parse(ev.data); err.value = '' } catch (e) {}
    }
    ws.onclose = () => { ws = null; timers.push(setTimeout(connectWs, 5000)) }
    ws.onerror = () => { try { ws.close() } catch (e) {} }
  } catch (e) {}
}

async function doSynth(compare = false) {
  synth.loading = true
  synth.compareErr = ''
  synth.compare = null
  try {
    const body = JSON.stringify({
      text: synth.text, speaker: synth.speaker || null, n_steps: synth.n_steps,
      temperature: synth.temperature, seed: synth.seed, tag: compare ? 'compare' : 'ui',
    })
    if (compare) {
      const d = await j('/api/tts/compare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
      synth.compare = d
      if (d.v1_error) synth.compareErr = d.v1_error
    } else {
      synth.result = await j('/api/tts/synthesize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    }
  } catch (e) {
    synth.compareErr = String(e)
  } finally {
    synth.loading = false
  }
}

async function startEval() {
  try {
    await j('/api/eval/run?limit=20', { method: 'POST' })
    await refreshEval()
  } catch (e) { err.value = String(e) }
}

function playRef(s) { synth.speaker = s }

onMounted(async () => {
  await refreshStatus()
  await Promise.all([refreshCurve(), refreshLogs(), refreshEval(), refreshSpeakers(), refreshPresets()])
  timers.push(setInterval(refreshStatus, 2500))
  timers.push(setInterval(refreshCurve, 6000))
  timers.push(setInterval(refreshLogs, 5000))
  timers.push(setInterval(refreshEval, 12000))
  connectWs()
})
onUnmounted(() => {
  timers.forEach(t => { clearInterval(t); clearTimeout(t) })
  if (ws) ws.close()
})
</script>

<template>
  <div class="wrap">
    <header class="hdr card">
      <div class="hleft">
        <div class="logo">neo<span>-tts</span> v2</div>
        <div class="htxt">
          <h1>CFM 流匹配声学模型 · 训练实时监控</h1>
          <p>AISHELL-3 真实多说话人语料 · 24 kHz / 80-band / fmax 12k · 单级 HiFT 声码器 · RTX 5060 Ti 16GB</p>
        </div>
      </div>
      <div class="hright">
        <span class="badge"><i class="dot" :class="{ on: live }"></i>{{ live ? '训练中' : '已停止' }}</span>
        <span class="badge">CFM 23.5M</span>
        <span class="badge">HiFT 24k</span>
        <span class="badge">v{{ status?.version || '2.0.0' }}</span>
      </div>
    </header>

    <nav class="topnav">
      <a href="#live">实时总览</a>
      <a href="#curve">损失曲线</a>
      <a href="#probes">训练探针</a>
      <a href="#synth">推理工作台</a>
      <a href="#eval">训练前后评测</a>
      <a href="#logs">训练日志</a>
      <a href="/plan/neo-tts-v2-pretrain-plan.html" target="_blank">训练方案 ↗</a>
      <a href="/report/neo-tts-v2-eval-report.html" target="_blank">评测报告 ↗</a>
    </nav>

    <div v-if="err" class="alert">{{ err }} · 请确认 API 已在 127.0.0.1:8002 运行</div>

    <section id="live">
      <h2 class="sec">实时总览 <span>2.5s 刷新 · WebSocket 优先</span></h2>
      <div class="kpis">
        <div v-for="k in kpis" :key="k.label" class="kp card" :class="k.accent">
          <div class="kl">{{ k.label }}</div>
          <div class="kv">{{ k.value }}</div>
          <div class="ks">{{ k.sub }}</div>
        </div>
      </div>

      <div class="cols">
        <div class="card pad">
          <div class="cardhead"><b>训练阶段</b><span class="tag">{{ status?.stage || 'idle' }}</span></div>
          <div class="stages">
            <div v-for="s in stages" :key="s.key" class="stage" :class="s.state">
              <div class="sk">{{ s.key }}</div>
              <div class="sn">{{ s.name }}</div>
              <div class="sd">{{ s.desc }}</div>
              <div class="sbar"><i :style="{ width: (s.progress * 100) + '%' }"></i></div>
              <div class="sb">{{ s.state === 'done' ? '完成' : s.state === 'running' ? '进行中' : '等待' }} · 预算 {{ s.budget_h }}h</div>
            </div>
          </div>
        </div>

        <div class="card pad">
          <div class="cardhead"><b>GPU / 显存</b><span class="tag cyan">{{ fmt(gpu.util, 0) }}% util</span></div>
          <div class="gaugewrap">
            <div class="gauge">
              <div class="gline"><span>显存</span><b>{{ fmt(gpu.mem_used_mb / 1024, 1) }} / {{ fmt(gpu.mem_total_mb / 1024, 1) }} GB</b></div>
              <div class="bar"><i :style="{ width: gpuMemPct + '%' }" class="v"></i></div>
            </div>
            <div class="gauge">
              <div class="gline"><span>利用率</span><b>{{ fmt(gpu.util, 0) }}%</b></div>
              <div class="bar"><i :style="{ width: Math.min(100, gpu.util || 0) + '%' }" class="c"></i></div>
            </div>
            <div class="minigrid">
              <div><span>温度</span><b>{{ fmt(gpu.temp, 0) }} °C</b></div>
              <div><span>功耗</span><b>{{ fmt(gpu.power, 0) }} W</b></div>
              <div><span>风扇</span><b>{{ fmt(gpu.fan, 0) }} %</b></div>
              <div><span>模型显存</span><b>{{ fmt(status?.vram_gb, 2) }} GB</b></div>
            </div>
          </div>
          <div class="dgrid">
            <div><span>训练语料</span><b>{{ dataset.train_hours ?? '—' }} h</b></div>
            <div><span>utterances</span><b>{{ int(dataset.train) }}</b></div>
            <div><span>说话人</span><b>{{ dataset.speakers_train ?? '—' }}</b></div>
            <div><span>音素词表</span><b>{{ dataset.vocab_size ?? '—' }}</b></div>
            <div><span>mel 均值</span><b>{{ fmt(dataset.mel_stats?.mean, 3) }}</b></div>
            <div><span>mel 标准差</span><b>{{ fmt(dataset.mel_stats?.std, 3) }}</b></div>
          </div>
        </div>
      </div>
    </section>

    <section id="curve">
      <h2 class="sec">损失曲线 <span>CFM 流匹配损失 + 时长 L1</span></h2>
      <div class="card">
        <LossChart :points="curve" />
      </div>
    </section>

    <section id="probes">
      <h2 class="sec">训练探针 <span>训练中每 N 步用冻结声码器渲染，直接听模型进步</span></h2>
      <div class="probes">
        <div v-for="p in probeList" :key="p.wav" class="probe card">
          <div class="phead"><span class="tag">step {{ int(p.step) }}</span><span class="muted small">{{ fmt(p.dur_sec, 2) }}s · RTF {{ fmt(p.rtf, 2) }}</span></div>
          <div class="ptext">{{ p.text }}</div>
          <audio controls preload="none" :src="'/' + p.wav.replace(/^\.?\//, '')"></audio>
        </div>
        <div v-if="!probeList.length" class="empty">首个探针将在训练到达 probe 步数后出现（每 1500 步）。</div>
      </div>
    </section>

    <section id="synth">
      <h2 class="sec">推理工作台 <span>v2 CFM + HiFT，实时与 v1 同文对比</span></h2>
      <div class="synth">
        <div class="card pad">
          <textarea v-model="synth.text" rows="3" placeholder="输入中文文本…"></textarea>
          <div class="chips">
            <button v-for="p in presets" :key="p" class="chip" @click="synth.text = p">{{ p.slice(0, 14) }}…</button>
          </div>
          <div class="row">
            <label>音色
              <select v-model="synth.speaker">
                <option value="">默认（{{ speakers[0]?.id || '—' }}）</option>
                <option v-for="s in speakers.slice(0, 40)" :key="s.id" :value="s.id">{{ s.id }}</option>
              </select>
            </label>
            <label>ODE 步数 <input type="number" v-model.number="synth.n_steps" min="1" max="32" /></label>
            <label>时长温度 <input type="number" v-model.number="synth.temperature" step="0.05" min="0.1" max="1.2" /></label>
            <label>seed <input type="number" v-model.number="synth.seed" /></label>
          </div>
          <div class="row actions">
            <button class="primary" :disabled="synth.loading" @click="doSynth(false)">{{ synth.loading ? '合成中…' : '合成 v2' }}</button>
            <button :disabled="synth.loading" @click="doSynth(true)">与 v1 对比</button>
          </div>
        </div>

        <div class="card pad resultbox">
          <template v-if="synth.result">
            <div class="cardhead"><b>v2 输出</b><span class="tag green">{{ synth.result.duration_sec }}s · RTF {{ synth.result.rtf }}</span></div>
            <audio controls :src="synth.result.audio_url"></audio>
            <div class="metagrid">
              <div><span>checkpoint</span><b>{{ synth.result.checkpoint }}</b></div>
              <div><span>step</span><b>{{ int(synth.result.ckpt_step) }}</b></div>
              <div><span>音色</span><b>{{ synth.result.speaker }}</b></div>
              <div><span>帧数</span><b>{{ synth.result.n_frames }}</b></div>
              <div><span>延迟</span><b>{{ synth.result.latency_sec }}s</b></div>
              <div><span>采样率</span><b>{{ synth.result.sample_rate }} Hz</b></div>
            </div>
          </template>
          <template v-else-if="synth.compare">
            <div class="vs">
              <div class="vscol">
                <div class="cardhead"><b>v1 · V0.01</b><span class="tag red">22.05k · GL 级联</span></div>
                <template v-if="synth.compare.v1">
                  <audio controls :src="'http://127.0.0.1:8001' + synth.compare.v1.audio_url"></audio>
                  <div class="metagrid">
                    <div><span>时长</span><b>{{ synth.compare.v1.duration }}s</b></div>
                    <div><span>RTF</span><b>{{ synth.compare.v1.rtf }}</b></div>
                  </div>
                </template>
                <div v-else class="empty">{{ synth.compareErr || 'v1 服务未启动（127.0.0.1:8001）' }}</div>
              </div>
              <div class="vscol">
                <div class="cardhead"><b>v2 · CFM + HiFT</b><span class="tag green">24k · 单级声码器</span></div>
                <audio controls :src="synth.compare.v2.audio_url"></audio>
                <div class="metagrid">
                  <div><span>时长</span><b>{{ synth.compare.v2.duration_sec }}s</b></div>
                  <div><span>RTF</span><b>{{ synth.compare.v2.rtf }}</b></div>
                </div>
              </div>
            </div>
          </template>
          <div v-else class="empty">输入文本后合成。v2 走本机 16GB GPU；对比模式会调用 v1 推理服务。</div>
        </div>
      </div>
    </section>

    <section id="eval">
      <h2 class="sec">训练前后评测 <span>v1 推理接口 vs v2 推理接口 · 同文本 / 同评测集</span></h2>
      <div class="card pad">
        <div class="evalhead">
          <div>
            <b>{{ evalSum ? `已生成 · n=${evalSum.n}` : '尚未生成评测结果' }}</b>
            <div class="muted small">{{ evalSum?.generated_at || '使用 POST /api/eval/run 或在命令行运行 tools/evaluate_v2.py' }}</div>
          </div>
          <div class="row">
            <button class="primary" :disabled="evalRun?.running" @click="startEval">{{ evalRun?.running ? '评测运行中…' : '运行评测' }}</button>
            <span class="tag" v-if="evalRun?.running">{{ dur(evalRun.elapsed_s) }}</span>
          </div>
        </div>

        <template v-if="evalSum">
          <div class="evalsys">
            <div class="syscard">
              <div class="cardhead"><b>v1 · V0.01</b><span class="tag red">22.05 kHz · Griffin-Lim 级联</span></div>
              <div class="sysgrid">
                <div v-for="m in metricDefs.slice(0, 8)" :key="m.k"><span>{{ m.label }}</span><b>{{ m.fmt(sys.v1?.[m.k]) }}</b></div>
              </div>
            </div>
            <div class="syscard v2">
              <div class="cardhead"><b>v2 · CFM + HiFT</b><span class="tag green">24 kHz · fmax 12k</span></div>
              <div class="sysgrid">
                <div v-for="m in metricDefs.slice(0, 8)" :key="m.k"><span>{{ m.label }}</span><b>{{ m.fmt(sys.v2?.[m.k]) }}</b></div>
              </div>
            </div>
          </div>

          <div class="tablewrap">
            <table>
              <thead><tr><th>指标</th><th>v1</th><th>v2</th><th>Δ (v2-v1)</th></tr></thead>
              <tbody>
                <tr v-for="m in metricDefs" :key="m.k">
                  <td><b>{{ m.label }}</b></td>
                  <td class="mono">{{ m.fmt(sys.v1?.[m.k]) }}</td>
                  <td class="mono">{{ m.fmt(sys.v2?.[m.k]) }}</td>
                  <td class="mono" :class="m.k === 'mean_cer' || m.k === 'mean_rtf' ? 'down' : 'up'">{{ delta(m.k) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="slices.length" class="slices">
            <div v-for="s in slices" :key="s.name" class="slice card">
              <div class="cardhead"><b>{{ s.name }}</b><span class="muted small">n={{ s.n }}</span></div>
              <div class="slicegrid">
                <div><span>CER v1 → v2</span><b>{{ pct(s.v1?.mean_cer) }} → {{ pct(s.v2?.mean_cer) }}</b></div>
                <div><span>相似度</span><b>{{ fmt(s.v1?.mean_sim) }} → {{ fmt(s.v2?.mean_sim) }}</b></div>
                <div><span>8k+ 能量</span><b>{{ pct(s.v1?.mean_hf8) }} → {{ pct(s.v2?.mean_hf8) }}</b></div>
                <div><span>RTF</span><b>{{ fmt(s.v1?.mean_rtf) }} → {{ fmt(s.v2?.mean_rtf) }}</b></div>
              </div>
            </div>
          </div>

          <div class="tablewrap">
            <table>
              <thead><tr><th>#</th><th>文本</th><th>v1 CER</th><th>v2 CER</th><th>v1 RTF</th><th>v2 RTF</th><th>试听</th></tr></thead>
              <tbody>
                <tr v-for="(it, i) in items.slice(0, 30)" :key="it.id">
                  <td>{{ i + 1 }}</td>
                  <td class="txt">{{ it.text }}</td>
                  <td class="mono">{{ pct(it.v1?.cer) }}</td>
                  <td class="mono">{{ pct(it.v2?.cer) }}</td>
                  <td class="mono">{{ fmt(it.v1?.rtf, 2) }}</td>
                  <td class="mono">{{ fmt(it.v2?.rtf, 2) }}</td>
                  <td class="aud">
                    <a v-if="it.v1?.audio" :href="'/api/eval/audio/v1/' + it.v1.audio" target="_blank">v1</a>
                    <a v-if="it.v2?.audio" :href="'/api/eval/audio/v2/' + it.v2.audio" target="_blank">v2</a>
                    <a v-if="it.gt_audio" :href="'/api/eval/audio/gt/' + it.gt_audio" target="_blank">GT</a>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <div v-else class="empty">
          评测内容：T1 未见说话人、T2 域内、T3 难例（数字/日期/长句/疑问），指标含 CER、CAM++ 音色相似度、F0 统计、
          8k/10k 高频能量、时长比、RTF、SQUIM PESQ/STOI。
        </div>
      </div>
    </section>

    <section id="logs">
      <h2 class="sec">训练日志 <span>logs/train.log</span></h2>
      <pre class="console card">{{ logs.join('\n') || '暂无日志' }}</pre>
    </section>

    <footer class="foot">
      neo-tts v2 · 研究用途 · CFM flow matching + HiFT 24 kHz · 单卡 RTX 5060 Ti 16GB · 训练全程可复现
    </footer>
  </div>
</template>

<style scoped>
.hdr { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 20px 24px; background: linear-gradient(135deg, #0f172a 0%, #312e81 45%, #6d28d9 80%, #be185d 100%); border: none; color: #fff; flex-wrap: wrap; }
.hleft { display: flex; align-items: center; gap: 16px; }
.logo { font-size: 1.5em; font-weight: 900; letter-spacing: -.5px; }
.logo span { color: #c4b5fd; }
.hdr h1 { font-size: 1.12em; font-weight: 800; }
.hdr p { font-size: .78em; color: rgba(255, 255, 255, .78); }
.hright { display: flex; gap: 8px; flex-wrap: wrap; }
.badge { display: inline-flex; align-items: center; gap: 6px; font-size: .72em; font-weight: 700; padding: 5px 11px; border-radius: 20px; background: rgba(255, 255, 255, .1); border: 1px solid rgba(255, 255, 255, .22); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #94a3b8; }
.dot.on { background: #4ade80; box-shadow: 0 0 0 0 rgba(74, 222, 128, .7); animation: pulse 1.6s infinite; }
@keyframes pulse { 70% { box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); } 100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); } }
.topnav { position: sticky; top: 0; z-index: 40; display: flex; gap: 8px; padding: 10px 2px; margin-bottom: 6px; background: rgba(240, 242, 245, .9); backdrop-filter: blur(10px); overflow-x: auto; }
.topnav a { font-size: .78em; font-weight: 700; color: #475569; padding: 6px 13px; border-radius: 9px; border: 1px solid #e2e8f0; background: #fff; white-space: nowrap; }
.topnav a:hover { color: var(--violet); border-color: #c4b5fd; background: #f5f3ff; text-decoration: none; }
.alert { margin-top: 10px; padding: 10px 14px; border-radius: 10px; border: 1px solid #fecaca; background: #fef2f2; color: #b91c1c; font-size: .84em; }
.kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 14px; }
.kp { padding: 14px 15px; border-left: 3px solid #ddd6fe; }
.kp.violet { border-left-color: #7c3aed; } .kp.green { border-left-color: #10b981; } .kp.cyan { border-left-color: #0ea5e9; } .kp.amber { border-left-color: #f59e0b; }
.kl { font-size: .72em; color: var(--muted); font-weight: 700; }
.kv { font-size: 1.32em; font-weight: 900; margin: 2px 0; color: #1e293b; font-variant-numeric: tabular-nums; }
.ks { font-size: .7em; color: #94a3b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cols { display: grid; grid-template-columns: 1.45fr 1fr; gap: 14px; }
.pad { padding: 16px 18px; }
.cardhead { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; font-size: .92em; }
.stages { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.stage { border: 1px solid var(--line); border-radius: 11px; padding: 10px 11px; background: #fbfcfe; }
.stage.running { border-color: #c4b5fd; background: #f5f3ff; box-shadow: 0 0 0 3px rgba(124, 58, 237, .07); }
.stage.done { border-color: #a7f3d0; background: #ecfdf5; }
.sk { font-size: .68em; font-weight: 900; color: #7c3aed; }
.sn { font-weight: 800; font-size: .84em; }
.sd { font-size: .7em; color: var(--muted); line-height: 1.45; min-height: 30px; }
.sbar { height: 5px; border-radius: 4px; background: #eef1f5; overflow: hidden; margin: 6px 0 4px; }
.sbar i { display: block; height: 100%; background: linear-gradient(90deg, #7c3aed, #4f46e5); border-radius: 4px; transition: width .4s; }
.stage.done .sbar i { background: linear-gradient(90deg, #10b981, #059669); }
.sb { font-size: .66em; color: #94a3b8; }
.gaugewrap { display: flex; flex-direction: column; gap: 10px; }
.gline { display: flex; justify-content: space-between; font-size: .76em; color: var(--muted); margin-bottom: 4px; }
.gline b { color: var(--ink); }
.bar { height: 9px; border-radius: 6px; background: #eef1f5; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 6px; transition: width .5s; }
.bar i.v { background: linear-gradient(90deg, #7c3aed, #be185d); }
.bar i.c { background: linear-gradient(90deg, #0ea5e9, #06b6d4); }
.minigrid, .dgrid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
.dgrid { grid-template-columns: repeat(3, 1fr); border-top: 1px dashed #e8ecf0; padding-top: 12px; }
.minigrid div, .dgrid div { background: #f8fafc; border-radius: 8px; padding: 7px 9px; }
.minigrid span, .dgrid span { display: block; font-size: .66em; color: var(--muted); }
.minigrid b, .dgrid b { font-size: .84em; }
.probes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.probe { padding: 12px 13px; }
.phead { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.ptext { font-size: .78em; color: #334155; min-height: 34px; margin-bottom: 6px; }
.probe audio { width: 100%; height: 30px; }
.empty { color: #94a3b8; font-size: .84em; padding: 20px 6px; text-align: center; grid-column: 1 / -1; }
.synth { display: grid; grid-template-columns: 1.05fr 1fr; gap: 14px; }
textarea { width: 100%; resize: vertical; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 9px 0; }
.chip { font-size: .72em; padding: 4px 9px; border-radius: 8px; color: #64748b; }
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.row label { display: flex; flex-direction: column; gap: 3px; font-size: .72em; color: var(--muted); font-weight: 700; }
.row input, .row select { width: 104px; padding: 6px 8px; }
.actions { margin-top: 12px; }
.resultbox audio { width: 100%; }
.metagrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 10px; }
.metagrid div { background: #f8fafc; border-radius: 8px; padding: 7px 9px; }
.metagrid span { display: block; font-size: .65em; color: var(--muted); }
.metagrid b { font-size: .82em; }
.vs { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.vscol { border: 1px solid var(--line); border-radius: 11px; padding: 11px; }
.vscol audio { width: 100%; }
.evalhead { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.evalsys { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
.syscard { border: 1px solid #fecaca; background: #fff7f7; border-radius: 12px; padding: 13px 14px; }
.syscard.v2 { border-color: #a7f3d0; background: #f3fdf8; }
.sysgrid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.sysgrid div { background: rgba(255, 255, 255, .75); border-radius: 8px; padding: 7px 9px; }
.sysgrid span { display: block; font-size: .64em; color: var(--muted); }
.sysgrid b { font-size: .84em; }
.tablewrap { overflow-x: auto; margin: 12px 0; }
.mono { font-variant-numeric: tabular-nums; }
.up { color: #047857; font-weight: 700; } .down { color: #b45309; font-weight: 700; }
.txt { max-width: 420px; }
.aud { display: flex; gap: 8px; }
.slices { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 14px 0; }
.slice { padding: 12px 14px; }
.slicegrid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.slicegrid div { background: #f8fafc; border-radius: 8px; padding: 6px 8px; }
.slicegrid span { display: block; font-size: .64em; color: var(--muted); }
.slicegrid b { font-size: .8em; }
.console { padding: 14px 16px; background: #0f172a; color: #cbd5e1; font-family: Consolas, monospace; font-size: .76em; line-height: 1.6; max-height: 340px; overflow: auto; white-space: pre-wrap; border: 1px solid #1e293b; }
.foot { text-align: center; color: #94a3b8; font-size: .78em; margin-top: 46px; }
@media (max-width: 1180px) {
  .kpis { grid-template-columns: repeat(3, 1fr); }
  .cols, .synth, .evalsys { grid-template-columns: 1fr; }
  .probes { grid-template-columns: repeat(2, 1fr); }
  .slices { grid-template-columns: 1fr 1fr; }
  .stages { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 700px) {
  .kpis, .probes, .slices, .stages, .sysgrid, .metagrid { grid-template-columns: 1fr 1fr; }
  .hdr { padding: 16px; }
}
</style>
