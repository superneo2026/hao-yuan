# neo-tts v2

研究用途的中文 TTS v2：**CFM 流匹配声学模型 + 24 kHz 单级 HiFT 声码器**，单卡 RTX 5060 Ti 16GB 训练与推理。

- **v1 → v2 换掉的三件事**：L1 回归 → 流匹配随机生成；Griffin-Lim 三级级联 → 单级神经声码器；0.975h 合成语音 → AISHELL-3 19.24h 真实多说话人。
- **不做形式化 RL**：没有 DPO / GRPO / GSPO / PPO。CFM 无显式似然、无可靠奖励、无真人偏好边界。
- **训练方案**：`test/plan/neo-tts-v2-pretrain-plan.html`（30h 全量配方 + 本机缩时 pilot 校准）
- **评测报告**：`test/testing/neo-tts-v2-eval-report.html`（v1 推理接口 vs v2 推理接口）
- **实时监控**：`http://127.0.0.1:8002`（Vue3）

## 快速启动

```powershell
# 训练监控 + 推理 API + 静态页面（8002）
cd D:\Env\git\neo-tts\v2\api
python -m uvicorn main:app --host 127.0.0.1 --port 8002
# 浏览器打开 http://127.0.0.1:8002/

# 前端开发模式（可选，代理 /api 到 8002）
cd ..\web
npm run dev      # http://127.0.0.1:5174
npm run build    # 产物 dist/ 由 8002 直接托管

# v1 对照服务（训练前基线，8001）
cd D:\Env\git\neo-tts\v1
python -m uvicorn src.serve.api:app --host 127.0.0.1 --port 8001
```

## 数据与训练

```powershell
# 1) 24k / 80-band / hop480 / fmax12k 特征 + 复合音素 + 50fps 时长
python tools\prepare_v2_data.py --workers 10
python tools\precompute_spk.py          # CAM++ 说话人向量 + 参考音频

# 2) 吞吐标定（torch 计时，不调用 nvidia-smi，避免 WDDM 阻塞）
python src\train\train_cfm.py --smoke 200 --batch 32 --workers 4

# 3) 训练（约 10.5 it/s @ 16GB；写 logs/train_status.json 供监控）
python src\train\train_cfm.py --steps 26000 --batch 32 --workers 6 --lr 1.2e-4 `
  --warmup 600 --val-every 1000 --probe-every 2000 --save-every 1000
```

产物：`checkpoints/cfm/{best,last,ema}.pt`、`logs/train_{status,metrics,log}`、`logs/probes/*.wav`。

## 评测

```powershell
python tools\evaluate_v2.py --limit 20   # T1 未见说话人 / T2 域内 / T3 难例
python tools\make_report.py              # test/testing/neo-tts-v2-eval-report.html
```

指标：SenseVoice CER、CAM++ 音色相似度、F0 中位/半音跨度、8k/10k 能量占比、时长比、RTF、SQUIM PESQ/STOI。

## 目录

```
src/audio/mel.py       # 唯一 mel 口径（24k/80/hop480/fmax12k）
src/text/frontend.py   # pypinyin → 声母 + 韵母/声调复合 token
src/models/cfm.py      # Transformer 编码器 + 时长预测 + CFM 1D-UNet + 内容锚定回归
src/data/dataset.py    # 24k mel manifest 数据集
src/train/train_cfm.py # 训练循环、EMA、探针、监控状态
src/infer/engine.py    # 推理引擎（CFM + HiFT + CAM++ 零样本音色）
api/                   # FastAPI：/api/monitor/* /api/tts/* /api/eval/*
web/                   # Vue3 + Vite 实时监控台
tools/                 # 数据构建 / 说话人向量 / 评测 / 报告
```

## 许可与用途

仅用于研究。AISHELL-3（Apache-2.0）真实录音训练；声码器来自本机 CosyVoice-3 HiFT 预训练权重（权重许可以上游为准）；代码为本项目原创。模型权重、语料与生成音频不随源码发布。
