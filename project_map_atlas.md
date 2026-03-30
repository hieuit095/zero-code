# ATLAS — Adaptive Test-time Learning and Autonomous Specialization
## Project Map v1.0

---

## 1. TỔNG QUAN

**Mục tiêu:** Đạt 74.6% LiveCodeBench pass@1-v(k=3) với model 14B lượng tử hóa (Qwen3-14B-Q4_K_M) trên 1 GPU consumer 16GB — không fine-tune, không API, không cloud.

**Phương pháp cốt lõi:** Bọc model nhỏ trong infrastructure thông minh gồm: constraint-driven generation, energy-based verification, self-verified iterative repair, và adaptive routing.

**Benchmark so sánh:**

| Hệ thống | LCB Score | Chi phí/task |
|---|---|---|
| DeepSeek V3.2 (API, single-shot) | 86.2% | ~$0.002 |
| GPT-5 (API, single-shot) | 84.6% | ~$0.043 |
| **ATLAS V3** | **74.6%** | **~$0.004** (chỉ điện) |
| Claude 4.5 Sonnet (API, single-shot) | 71.4% | ~$0.066 |
| Qwen3-14B Baseline (no pipeline) | 54.9% | — |

---

## 2. TẠI SAO MODEL NHỎ CÓ THỂ ĐẠT 74.6%?

### 2.1 Không phải model mạnh — mà là pipeline thông minh

Baseline Qwen3-14B (không có pipeline) chỉ đạt **54.9%**. Con số 74.6% đến từ:

- **Best-of-3 + Lens Selection** — chọn đáp án tốt nhất từ 3 candidates
- **Self-verified Repair** — tự sửa sai mà không cần ground truth
- **Budget Forcing** — kiểm soát thinking tokens, không over/under think
- **Iterative refinement** — không chấp nhận sai lần đầu

### 2.2 V3 Ablation Breakdown

| Điều kiện | Cấu hình | Pass Rate | Delta |
|---|---|---|---|
| A | Baseline (no V3) | 54.9% | — |
| B | + Phase 1 (PlanSearch + BudgetForcing + DivSampling) | 67.3% | **+12.4pp** |
| C | + Phase 1+2 (Lens routing) | 67.3% | +0.0pp |
| D | + Phase 1+3 (self-verified refinement) | **74.6%** | **+7.3pp** |

**Insight quan trọng:**
- Phase 1 là driver chính (63% tổng improvement)
- Phase 2 (Lens routing) hoàn toàn vô hiệu trong V3
- Phase 3 (self-repair) cứu thêm 7.3pp
- PR-CoT cứu 36/42 tasks thất bại (85.7% rescue rate)

---

## 3. KIẾN TRÚC HỆ THỐNG TỔNG THỂ

```
┌─────────────────────────────────────────────────────────────────┐
│                      MaaS Layer (API + Auth)                     │
│  ┌──────────────────┐    ┌──────────────────────────────────┐  │
│  │   api-portal     │    │          llm-proxy                │  │
│  │  FastAPI :3000   │    │   Reverse proxy + rate limiting   │  │
│  │  JWT, sk-llm-*  │    │       Port 8000                  │  │
│  └──────────────────┘    └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Routing Layer (Confidence Router)              │
│  ┌──────────────┐    ┌────────────────┐    ┌────────────────┐  │
│  │Signal        │───▶│Difficulty      │───▶│Thompson        │  │
│  │Collector     │    │Estimator       │    │Sampling        │  │
│  │4 signals:    │    │Weights:        │    │Beta posteriors│  │
│  │s_p, r_c,     │    │0.30/0.25/      │    │per bin x route│  │
│  │q_c, g_e      │    │0.20/0.25       │    │               │  │
│  └──────────────┘    └────────────────┘    └───────┬────────┘  │
│                                                     │            │
│                                                     ▼            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Adaptive-k Selection                       │ │
│  │  CACHE_HIT k=0 │ FAST k=1 │ STANDARD k=5 │ HARD k=20      │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                Generation + Embedding Layer                       │
│  ┌──────────────────────────┐    ┌───────────────────────────┐ │
│  │     llama-server          │    │     Pattern Cache          │ │
│  │  Qwen3-14B-Q4_K_M        │    │  Redis + Ebbinghaus Decay  │ │
│  │  + Qwen3-0.6B-Q8_0 Draft │    │  STM / LTM tiers           │ │
│  │  Spec decode ON           │    │                           │ │
│  │  5120-dim self-embeddings│    │                           │ │
│  └──────────────────────────┘    └───────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Evaluation Layer (Lens + Sandbox)               │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    Geometric Lens C(x)                        │ │
│  │  ~2.7M params, 5120-dim self-embeddings                   │ │
│  │  Energy-based scoring, sorts candidates by energy          │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    Sandbox (K8s Service)                     │ │
│  │  Isolated code execution + testing                         │ │
│  │  Early exit on first PASS                                 │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Phase 3: Self-Repair                          │
│  ┌──────────────────────────┐    ┌───────────────────────────┐ │
│  │   Self-Test Generation   │───▶│     PR-CoT Repair         │ │
│  │  Model generates I/O     │    │  Multi-perspective        │ │
│  │  pairs for self-verification │  Chain-of-Thought        │ │
│  └──────────────────────────┘    └───────────────────────────┘ │
│                              │                                   │
│              ┌───────────────┴───────────────┐                  │
│              ▼                               ▼                   │
│      (repaired code) ──────────▶ Sandbox (re-test)              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. CHI TIẾT TỪNG THÀNH PHẦN

### 4.1 MaaS Layer (Model-as-a-Service)

**api-portal** (Port 3000)
- User registration/login với JWT
- API key management (format: `sk-llm-*`)
- `/v1/models` endpoint
- Đọc/ghi usage metrics từ Redis

**llm-proxy** (Port 8000)
- Reverse proxy tới llama-server
- API key validation
- Rate limiting per user
- OpenAI-compatible API format

### 4.2 Routing Layer (Confidence Router)

**Signal Collector** — 4 tín hiệu đánh giá độ khó:
```
s_p = pattern cache score (độ khớp với pattern đã biết)
r_c = retrieval confidence (RAG confidence)
q_c = query complexity (độ phức tạp của input)
g_e = geometric energy (Lens energy score)
```

**Difficulty Estimator** — trọng số:
```
w = [0.30, 0.25, 0.20, 0.25]  cho [s_p, r_c, q_c, g_e]
```

**Thompson Sampling** — chọn route dựa trên:
- Beta posteriors cho mỗi bin × route
- Cost-weighted selection (ưu tiên route rẻ hơn nếu similar confidence)

**Adaptive-k Selection** — quyết định số candidates:
```
CACHE_HIT → k=0  (đã có sẵn trong cache)
FAST       → k=1  (dễ, temp=0.0)
STANDARD   → k=5  (trung bình, temp=0.6)
HARD       → k=20 (khó, temp=0.8)
```

### 4.3 Generation Layer

**llama-server** (GPU inference):
- Model: Qwen3-14B-Q4_K_M (lượng tử hóa int4)
- Draft model: Qwen3-0.6B-Q8_0 (speculative decoding)
- Speculative decoding ON (~100 tok/s)
- Self-embedding extraction: 5120-dim vectors

**Pattern Cache** (Redis-backed):
- Ebbinghaus decay: short-term → long-term memory
- STM tier: patterns used frequently recently
- LTM tier: patterns proven reliable over time
- Truyền strategy hints cho generation

### 4.4 Evaluation Layer

**Geometric Lens C(x)** (~2.7M params):
- Dùng 5120-dim self-embeddings từ chính model
- Energy function: C(x) = -log P(model是对的|x)
- Sort candidates theo energy (thấp nhất = tự tin nhất)
- Độ chính xác chọn best candidate: **87.8%**

**Sandbox** (K8s Service):
- Isolated code execution
- Test validation
- Early exit: dừng ngay khi candidate đầu tiên pass
- Return pass/fail + feedback

### 4.5 Phase 3: Self-Repair (V3 mới nhất)

**Self-Test Generation:**
- Model tự tạo test cases (input/output pairs)
- Không nhìn đáp án thật (self-generated)
- Dùng để verify candidate trước khi submit

**PR-CoT Repair:**
- Khi tất cả candidates fail Phase 2
- Chain-of-thought đa góc nhìn (Process Restraint CoT)
- Đưa ra nhiều perspective để tìm lỗi
- **85.7%** tasks được cứu ở Phase 3 là nhờ PR-CoT

### 4.6 Knowledge Layer (Context Retrieval)

**PageIndex RAG:**
- AST Tree Index: phân tích code structure
- BM25: keyword-based retrieval
- LLM-guided Tree Search: tìm context relevant

### 4.7 Feedback & Learning

**Feedback Recorder:**
- Cập nhật Thompson state (Beta posteriors)
- Ghi lại pass/fail feedback

**Lens Retrain:**
- Binary Cross-Entropy on pass/fail embeddings
- Hot-reload weights (cập nhật model không cần restart)
- C(x) được retrain liên tục từ dữ liệu thực

### 4.8 Storage

**Redis:**
- Pattern cache (STM/LTM)
- Thompson sampling state
- Task queue (AOF persistence)
- Rate limits per user
- Usage metrics

---

## 5. PIPELINE THỰC THI (V3)

### 5.1 Phase 1: Generate

```
1. Problem Input
        │
        ▼
2. Signal Collector (4 signals)
        │
        ▼
3. Difficulty Estimator + Thompson Sampling
        │
        ▼
4. Adaptive-k Selection ──────▶ llama-server
        │                              │
        │ (k candidates)                │
        ▼                              ▼
5. PlanSearch                    Budget Forcing
   (constraint extraction)      (thinking token control)
        │                              │
        └──────────┬───────────────────┘
                   ▼
           k=3 candidates
```

**PlanSearch:** Model không generate code ngay — lên kế hoạch trước, extract constraints từ problem statement.

**Budget Forcing:** Kiểm soát số thinking tokens — không over-think (diff thường thêm 50-100 tokens) không under-think.

**Temperature theo mode:**
```
k=1: temp=0.0  (deterministic)
mcq/ifbench: temp=0.3
code k≤5: temp=0.6
code k>5: temp=0.8
```

### 5.2 Phase 2: Verify

```
k candidates ──────────▶ llama-server (extract 5120-dim embeddings)
                                │
                                ▼
                    Geometric Lens C(x) scoring
                    (sort by energy, ascending)
                                │
                                ▼
                    Sandbox execution (lowest energy first)
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
               PASS?                     FAIL?
               (stop)               All candidates fail?
                                        │
                                        ▼
                                   Phase 3
```

### 5.3 Phase 3: Repair

```
All k candidates failed
        │
        ▼
Self-Test Generation (model tự tạo I/O pairs)
        │
        ▼
PR-CoT Repair (multi-perspective chain-of-thought)
        │
        ▼
Sandbox re-test với candidates đã sửa
        │
        ▼
Pass? ──▶ Submit
Fail? ──▶ Final failure (không có đáp án backup)
```

---

## 6. CÔNG NGHỆ SỬ DỤNG

### 6.1 Hardware
| Component | Spec |
|-----------|------|
| GPU | RTX 5060 Ti 16GB |
| Model | Qwen3-14B-Q4_K_M (int4 quantized) |
| Draft Model | Qwen3-0.6B-Q8_0 |
| Speculative Decoding | ON (~100 tok/s) |

### 6.2 Software Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| GPU Inference | llama.cpp + CUDA | Qwen3-14B + spec decode |
| Orchestration | FastAPI | rag-api, api-portal, llm-proxy |
| Code Execution | K8s Sandbox | Isolated execution + testing |
| Storage | Redis | Cache, queue, metrics, state |
| Routing | PyTorch (CPU) | Geometric Lens C(x) |
| Task Worker | Python (ralph-loop) | Async task processor |
| Dashboard | Web UI | Monitoring |

### 6.3 Kubernetes Services

| Pod | Service Name | Port | NodePort |
|-----|-------------|------|----------|
| llama-server | llama-service | 8000 | 32735 |
| rag-api | rag-api | 8001 | 31144 |
| sandbox | sandbox | 8020 | 30820 |
| api-portal | api-portal | 3000 | 30000 |
| llm-proxy | llm-proxy | 8000 | 30080 |
| redis | redis | 6379 | — |
| task-worker | task-worker | 8080 | — |
| dashboard | atlas-dashboard | 3001 | 30001 |

---

## 7. CÁCH TRIỂN KHAI

### 7.1 Yêu cầu

- Kubernetes cluster (K3s hoặc minikube)
- GPU với CUDA support (16GB VRAM)
- Redis instance
- Docker build environment

### 7.2 Các bước cài đặt

```bash
# 1. Clone repo
git clone https://github.com/itigges22/ATLAS.git
cd ATLAS

# 2. Build images
docker build -f images/llama-server/Dockerfile -t atlas-llama:latest
docker build -f images/rag-api/Dockerfile -t atlas-rag:latest
docker build -f images/sandbox/Dockerfile -t atlas-sandbox:latest

# 3. Configure Kubernetes
kubectl apply -f k8s/

# 4. Verify deployment
kubectl get pods -n atlas
kubectl logs -n atlas deployment/llama-server

# 5. Access services
# Dashboard: http://localhost:30001
# API: http://localhost:30000
```

### 7.3 Environment Variables quan trọng

| Variable | Default | Mô tả |
|----------|---------|--------|
| `ATLAS_MODEL_PATH` | — | Path to Qwen3-14B-Q4_K_M model |
| `ATLAS_ENABLE_TRAINING` | `false` | Enable nightly LoRA fine-tuning |
| `REDIS_HOST` | `redis` | Redis hostname |
| `GPU_DEVICE` | `cuda` | CUDA hoặc cpu |

---

## 8. CÁC BÀI HỌC & LIMITATIONS

### 8.1 Bài học quan trọng

1. **Phase 1 là driver chính** — constraint-driven generation chiếm 63% tổng improvement
2. **Phase 2 (Lens routing) vô hiệu** — zero marginal improvement trong V3
3. **PR-CoT cực kỳ hiệu quả** — 85.7% tasks được cứu từ Phase 3
4. **Self-embedding tốt hơn external reward model** — model tự đánh giá chính mình
5. **Competitive programming tasks khó repair** — DP, graph algorithms không decompose được

### 8.2 Known Limitations

1. **Competitive programming tasks** — không factorization được thành testable sub-problems
2. **Phase 2 zero effect** — Lens routing không mang lại improvement trong V3
3. **Abuse page silent failure** — self-test generation có bug silent (0 cases extracted)
4. **SandboxAdapter ignore bug** — stdio mode bỏ qua test_case parameter

### 8.3 Tương lai phát triển

- Phase 2 redesign (Lens routing cần cải thiện)
- Fix Phase 3 self-test generation silent failures
- Competitive programming decomposition strategy mới
- Hybrid approach: kết hợp external solver cho hard problems

---

## 9. SO SÁNH VỚI CÁC PHƯƠNG PHÁP KHÁC

| Phương pháp | Model | LCB Score | Đặc điểm |
|-------------|-------|-----------|-----------|
| ATLAS V3 | Qwen3-14B-Q4_K_M | 74.6% | Self-hosted, no fine-tune |
| DeepSeek V3.2 | DeepSeek V3.2 | 86.2% | API, single-shot |
| GPT-5 | GPT-5 | 84.6% | API, single-shot |
| Claude 4.5 Sonnet | Claude 4.5 | 71.4% | API, single-shot |

**Ưu điểm của ATLAS:**
- Chi phí thấp nhất (~$0.004/task = tiền điện)
- Không phụ thuộc API
- Dữ liệu không rời máy
- Privacy-first

**Nhược điểm:**
- Cần GPU vật lý (16GB VRAM)
- Latency cao hơn API (1h55 cho 599 tasks)
- Không đạt top-tier accuracy

---

## 10. TRIỂN KHAI VỚI MINIMAX M2.7 + QWEN CODER 30B

### 10.1 Architecture đề xuất

```
┌─────────────────────────────────────────────────────────────────┐
│                    MiniMax M2.7 Layer                             │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Geometric Lens (thay vì Qwen self-embedding)              │ │
│  │  Reasoning-based scoring thay vì energy-based               │ │
│  │  Reasoning verification thay vì embedding similarity          │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  PR-CoT Repair (MINIMAX M2.7 mạnh hơn Qwen3-14B ở CoT)     │ │
│  │  Multi-perspective reasoning cực kỳ hiệu quả               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Self-Test Generation (MiniMax reasoning tạo test cases)     │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                Qwen Coder 30B Layer (Code Generation)            │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Qwen Coder 30B-Q4_K_M (code-specialized, mạnh hơn 14B)    │ │
│  │  Baseline ước tính: ~65-70% (tốt hơn Qwen3-14B non-code)   │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Ước tính performance

| Cấu hình | Baseline | +Phase 1 | +Phase 3 | **Final LCB** |
|---|---|---|---|---|
| ATLAS gốc (Qwen3-14B) | 54.9% | +12.4pp | +7.3pp | **74.6%** |
| Qwen Coder 30B + M2.7 (thận trọng) | 65% | +10pp | +8pp | **~83%** |
| Qwen Coder 30B + M2.7 (thực tế) | 68% | +12pp | +10pp | **~90%** ⚡ |

### 10.3 Điểm khác biệt chính

1. **Geometric Lens → Reasoning Lens:** MiniMax M2.7 là reasoning model — dùng chain-of-thought thay vì embedding similarity
2. **Enhanced PR-CoT:** M2.7 mạnh hơn ở multi-perspective reasoning → rescue rate > 85.7%
3. **Self-Test Generation:** MiniMax tạo test cases tốt hơn vì擅长 logical reasoning
4. **Baseline cao hơn:** Qwen Coder 30B specialized on code → baseline ~65-70% (vs 54.9% của Qwen3-14B non-code)

---

## 11. FILES CHÍNH TRONG REPO

```
ATLAS/
├── README.md                          # Tổng quan
├── docs/
│   ├── ARCHITECTURE.md                # Kiến trúc chi tiết (file này)
│   ├── V3_ABLATION_STUDY.md          # Phân tích ablation V3
│   ├── METHODOLOGY.md                # Phương pháp luận
│   └── HARDWARE.md                   # Yêu cầu hardware
├── images/
│   ├── llama-server/                 # GPU inference image
│   ├── rag-api/                      # Orchestration image
│   ├── sandbox/                      # Code execution image
│   └── api-portal/                   # API gateway image
├── k8s/
│   ├── llama-server.yaml
│   ├── rag-api.yaml
│   ├── sandbox.yaml
│   ├── redis.yaml
│   └── task-worker.yaml
├── src/
│   ├── rag-api/                      # Main orchestration
│   │   ├── routing/                  # Signal collector, Thompson sampling
│   │   ├── lens/                     # Geometric Lens C(x)
│   │   ├── repair/                   # PR-CoT repair
│   │   └── cache/                    # Pattern cache
│   ├── llama-server/                 # llama.cpp server
│   ├── sandbox/                      # Isolated execution
│   └── task-worker/                  # Async processor
├── ralph/                            # Ralph loop (task retry logic)
└── tests/                            # E2E tests
```

---

*Document created: 2026-03-29*
*Source: https://github.com/itigges22/ATLAS*
