<div align="center">
  <h1>🌌 ZeroCode: Autonomous Multi-Agent IDE</h1>
  <p><b>Eliminating verification fatigue with an auto-healing, multi-agent development environment powered by Alibaba OpenSandbox.</b></p>

  [![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](#)
  [![License](https://img.shields.io/badge/license-MIT-blue)](#)
  [![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#)
  [![React](https://img.shields.io/badge/react-18.x-blue.svg)](#)
</div>

---

## 📖 The Origin Story: Why ZeroCode?

Modern AI coding tools are advanced autocomplete. The human developer is forced to become the AI's debugger—running code, copying terminal errors, and pasting them back to the LLM. This constant context-switching creates immense **Verification Fatigue**.

Our solution: An autonomous loop where AI writes code, an independent AI agent tests it inside a secure, containerized sandbox, and the system intelligently fixes its own bugs before ever presenting it to the human.

> **Architectural Invariant:** The system must verify its own work inside a sandbox and fix itself when verification fails. The user receives a completed, passing result, not a raw terminal output of failures.

---

## ✨ Key Innovations (The Enterprise Architecture)

*   **LLM Economic Routing:** We dynamically distribute tasks across specialized models based on cost and capability to optimize performance and economics.
    *   **Leader:** High-cost, high-reasoning (Gemini 3.1 Pro, GPT-4o) for task decomposition, planning, and mentorship.
    *   **Dev:** Low-cost, high SWE-Bench (DeepSeek Coder, Minimax m2.5) for fast, iterative code implementation.
    *   **QA:** Mid-cost, high-logic (GLM 5, Claude 3.5 Sonnet) for robust testing and multi-dimensional critique scoring.

*   **The Mentorship Loop:** When a Dev agent fails a QA check twice, the task doesn't simply fail. The `TaskDelegator` intercepts the failure and invokes the Leader in a targeted *Mentorship Mode*. The Leader analyzes the `critique_report.md` and outputs architectural guidance (`leader_guidance.md`). The Dev agent receives a final, mentored attempt armed with this guidance, optimized by our `LLMSummarizingCondenser` to prevent token explosion.

*   **Enterprise Sandboxing (Alibaba OpenSandbox):** True isolation and safety.
    *   **CGroup Resource Limits:** Strict CPU and memory limits prevent rogue regexes or infinite loops from triggering node OOMs.
    *   **Zero-Trust Network Isolation:** Sandboxes are provisioned without egress, preventing Dev agents from executing rogue API calls or exfiltrating codebase secrets.
    *   **Fast Snapshots:** When QA fails catastrophically, we leverage instant container rollbacks, restoring the environment before the Dev agent’s broken attempt to avoid spaghetti-code untangling.

*   **QA Dimensional Scoring:** QA failures no longer collapse into raw terminal text. Our QA agents emit a structured `qa:report` evaluating four key dimensions out of 100: **Code Quality, Requirements, Robustness, and Security**. This multi-dimensional scoring provides precise, actionable feedback for the Dev agent's retry loop via `DB-Before-Emit`.

---

## 🏗️ The Technology Stack

ZeroCode runs as a multi-process topology, maintaining zero in-memory authoritative state.

| Component | Technologies | Role |
| :--- | :--- | :--- |
| **Frontend** | React, Zustand, Xterm.js, Monaco | Renders the UI shell, streams terminal output, and visualizes code/file state via backend events. |
| **Backend** | FastAPI, Redis (Pub/Sub), Python Async Worker, PostgreSQL | Orchestrates run lifecycles, WebSocket event streaming, retry policies, and acts as the single source of truth (`DB-Before-Emit`). |
| **Brain** | Nanobot | Drives agent cognition, planning, skill usage, and consumes run-scoped HTTP MCP tools. |
| **Muscle** | Alibaba OpenSandbox | Provides secure, containerized execution, instant snapshotting, and robust resource/network isolation. |

---

## ⚙️ Architecture Diagram

Our control path is strictly enforced for predictable state management and security:

```mermaid
flowchart LR
    A[React UI] -->|REST / WebSockets| B[FastAPI Orchestrator]
    B -->|DB-Before-Emit| C[Redis Queue / PubSub]
    C -->|Dequeues| D[Async Worker]
    D -->|Instantiates| E[Nanobot Agents]
    E -->|MCP Tool Calls| F[Alibaba OpenSandbox Container]

    classDef ui fill:#61dafb,stroke:#333,stroke-width:2px,color:#000;
    classDef api fill:#009688,stroke:#333,stroke-width:2px,color:#fff;
    classDef queue fill:#e0245e,stroke:#333,stroke-width:2px,color:#fff;
    classDef worker fill:#ff9800,stroke:#333,stroke-width:2px,color:#fff;
    classDef brain fill:#9c27b0,stroke:#333,stroke-width:2px,color:#fff;
    classDef sandbox fill:#f44336,stroke:#333,stroke-width:2px,color:#fff;

    class A ui;
    class B api;
    class C queue;
    class D worker;
    class E brain;
    class F sandbox;
```

---

## 🚀 Getting Started

To get ZeroCode running locally:

### 1. Clone the Repository
```bash
git clone https://github.com/hieuit095/zero-code.git
cd zerocode
```

### 2. Configure Environment Variables
Copy the example environment file and set up your multi-provider LLM keys for Economic Routing.
```bash
cp .env.example .env

# Open .env and ensure the following keys are set:
# LEADER_LLM_API_KEY=your_gemini_or_openai_key
# DEV_LLM_API_KEY=your_deepseek_or_minimax_key
# QA_LLM_API_KEY=your_glm_or_claude_key
# MCP_JWT_SECRET=generate_a_secure_random_string
```

### 3. Boot the Backend & Worker
Start the FastAPI server and the asynchronous worker process. They will communicate via Redis and persist state to PostgreSQL.
```bash
# Terminal 1: Start the FastAPI API Server
cd backend
python -m uvicorn main:app --reload --port 8000

# Terminal 2: Start the Python Async Worker
cd backend
python -m worker
```

### 4. Boot the Frontend
Start the React Vite development server to render the UI shell.
```bash
# Terminal 3: Start the Vite server
npm install
npm run dev
```