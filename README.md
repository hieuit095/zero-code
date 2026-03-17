<div align="center">
  <h1>🌌 ZeroCode: Autonomous Multi-Agent IDE</h1>
  <p><b>Eliminating verification fatigue with an auto-healing, multi-agent development environment.</b></p>

  [![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](#)
  [![License](https://img.shields.io/badge/license-MIT-blue)](#)
  [![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#)
  [![React](https://img.shields.io/badge/react-18.x-blue.svg)](#)
</div>

---

## 📖 The Origin Story (The Pain Point)

Modern AI coding tools are mostly glorified single-shot generators or advanced autocomplete. When building complex applications, the AI writes the code, but the human developer is forced to become the AI's debugger. The human has to run the code, find the terminal errors, copy-paste the logs back to the LLM, and pray it fixes them without breaking something else. This creates immense **"Verification Fatigue"**.

The vision for ZeroCode was born from this frustration: *What if the AI didn't just write the code, but actually compiled, tested, and fixed its own bugs inside a secure sandbox before ever presenting it to the human?*

> **Architectural Invariant:** The system must verify its own work inside a sandbox and fix itself when verification fails. The user receives a completed, passing result, not a raw terminal output of failures.

---

## 🔄 The Non-Linear Auto-Healing Loop (The Deep Dive)

ZeroCode is not a simple chain, but a self-correcting loop. Here is the flow of our State Machine:

1. **Planning:** The Leader (High-Reasoning LLM) decomposes the human's goal into atomic tasks.
2. **Execution:** The Dev (High-Coding LLM) writes the code using Sandbox MCP tools.
3. **4-Dimensional Verification:** The QA Agent runs linters/tests in the same sandbox and scores the code on Quality, Requirements, Robustness, and Security (0-100).
4. **The Iterative Loop:** If QA fails (e.g., Security < 90), it outputs a `critique_report.md`. The Dev agent reads this and retries.
5. **The Mentorship Escalation:** If the Dev agent fails 2 times, the loop pauses. The Leader steps in, analyzes the broken code, and outputs a high-level `leader_guidance.md` architectural fix. The Dev gets a final attempt armed with this guidance.

---

## ✨ Key Innovations

<details>
<summary><b>Click to expand our core innovations</b></summary>
<br>

*   **LLM Economic Routing:** We dynamically distribute tasks across specialized models based on cost and capability to optimize performance and economics.
    *   **Leader:** High-cost, high-reasoning (Gemini 3.1 Pro, GPT-4o) for task decomposition and mentorship.
    *   **Dev:** Low-cost, high SWE-Bench (DeepSeek Coder, Minimax m2.5) for code implementation.
    *   **QA:** Mid-cost, high-logic (GLM 5, Claude 3.5 Sonnet) for robust testing and critique.
*   **The Mentorship Loop:** When a Dev agent fails a QA check twice, the task doesn't simply fail. The orchestrator intercepts the failure and invokes the Leader in a targeted *Mentorship Mode*. The Leader analyzes the `critique_report.md` and broken code to output architectural guidance (`leader_guidance.md`). The Dev agent uses this `LLMSummarizingCondenser`-optimized guidance for a final, high-probability attempt.
*   **Impenetrable Sandbox:** Code execution is strictly isolated. We use the OpenHands SDK behind a 12-hour JWT-secured MCP (Model Context Protocol) facade. All file operations pass through an impenetrable `_jail_path()` function utilizing eager `os.path.realpath` symlink resolution to prevent directory traversal and symlink escapes.
*   **QA Dimensional Scoring:** QA failures no longer collapse into raw terminal text. Our QA agents emit a structured `qa:report` evaluating four key dimensions out of 100: Code Quality, Requirements, Robustness, and Security. This dimensional scoring drives precise, actionable feedback for the Dev agent's retry loop.

</details>

---

## 🏗️ The Technology Stack

ZeroCode runs as a multi-process topology, maintaining zero in-memory authoritative state. All reads and writes flow through PostgreSQL to ensure durability and crash-safety.

| Layer | Technologies | Role |
| :--- | :--- | :--- |
| **Frontend** | React, Zustand, Xterm.js, Monaco | Renders the UI shell, streams terminal output, and visualizes code/file state via backend events. |
| **Backend** | FastAPI, Redis (Pub/Sub), Python Async Worker, PostgreSQL | Orchestrates run lifecycles, WebSocket event streaming, retry policies, and acts as the single source of truth. |
| **Brain** | Nanobot (Cognition & Prompting) | Drives agent reasoning, prompting, skill usage, and consumes MCP tools. |
| **Muscle** | OpenHands SDK (Execution Sandbox & MCP Tools) | Provides the secure execution substrate and restricted filesystem/process tools exposed through the MCP facade. |

> **Strict Anti-Pattern:** The React frontend MUST NEVER interact directly with OpenHands or the MCP layer. Nanobot agents MUST NEVER use local host shell tools in production.

---

## ⚙️ Architecture Diagram

The control path is rigorously defined to enforce isolation and predictable state management:

```mermaid
flowchart LR
    A[React UI] -->|REST / WebSockets| B[FastAPI Orchestrator]
    B -->|Task Dispatch| C[Redis Pub/Sub & Queue]
    C -->|Dequeues| D[Python Async Worker]
    D -->|Instantiates Roles| E[Nanobot Agents]
    E -->|Tool Calls| F[JWT MCP Facade]
    F -->|Secure Actions| G[OpenHands SDK Sandbox]

    classDef ui fill:#61dafb,stroke:#333,stroke-width:2px,color:#000;
    classDef api fill:#009688,stroke:#333,stroke-width:2px,color:#fff;
    classDef queue fill:#e0245e,stroke:#333,stroke-width:2px,color:#fff;
    classDef worker fill:#ff9800,stroke:#333,stroke-width:2px,color:#fff;
    classDef brain fill:#9c27b0,stroke:#333,stroke-width:2px,color:#fff;
    classDef mcp fill:#607d8b,stroke:#333,stroke-width:2px,color:#fff;
    classDef sandbox fill:#f44336,stroke:#333,stroke-width:2px,color:#fff;

    class A ui;
    class B api;
    class C queue;
    class D worker;
    class E brain;
    class F mcp;
    class G sandbox;
```

---

## 🚀 Getting Started

To get ZeroCode running locally, follow these steps to initialize the database, configure your environment, and spin up the multi-process architecture.

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

Your autonomous Multi-Agent IDE is now ready.
