# ZeroCode Features

ZeroCode is an Autonomous Multi-Agent IDE that focuses on auto-healing and removing verification fatigue for developers. Below is the comprehensive list of its features, classified into main and secondary features.

## 🌟 Main Features

1. **Multi-Agent Orchestration Engine**
   - **Leader Agent:** Handles high-level reasoning, task decomposition, and mentorship.
   - **Dev Agent:** Focuses on writing code and implementing features.
   - **QA Agent:** Evaluates code logically and safely before presenting it to the user.

2. **Non-Linear Auto-Healing Loop**
   - **Iterative Retry System:** The Dev agent reads critique reports from QA and retries automatically if tests or checks fail.
   - **Mentorship Escalation:** If the Dev agent fails twice, the loop pauses, and the Leader intervenes with architectural guidance (`leader_guidance.md`) for a final, high-probability attempt.

3. **4-Dimensional Verification Scoring**
   - QA evaluates the codebase across 4 key dimensions (0-100 scores):
     - Quality
     - Requirements
     - Robustness
     - Security

4. **Impenetrable Sandbox Execution Engine**
   - **OpenHands SDK Integration:** Isolated environment for all commands and file operations.
   - **JWT MCP Facade:** Strict, secure entry point ensuring the model execution protocol is safely constrained. Directory traversal prevention via `_jail_path()`.

5. **LLM Economic Routing**
   - Dynamic task distribution across specialized LLMs (e.g., Gemini/GPT-4 for Leadership, DeepSeek/Minimax for Dev coding, GLM/Claude for QA) to balance cost and capability.

6. **Real-time Event Streaming & Orchestration**
   - **WebSocket Event Streaming:** Live updates of terminal outputs, file changes, and agent thoughts sent from backend to frontend.
   - **Redis Pub/Sub & FastAPI Queue:** Highly scalable, asynchronous job queue for handling multi-agent lifecycle events.

---

## 🛠 Secondary Features

1. **Interactive Web Workspace UI**
   - Complete browser-based IDE built with React, Vite, and Zustand.
   - **Monaco Code Editor:** Rich code editing experience integrated directly in the browser.
   - **Xterm.js Terminal:** Real-time visibility into the sandbox execution environment.

2. **Project & Workspace Management**
   - Visual File Explorer.
   - Task progression overview.
   - Database-backed persistence using PostgreSQL to save run states, tasks, and configurations safely.

3. **Agent & API Configuration Panel**
   - Dynamic settings page for users to configure API keys for different model providers securely.
   - Ability to modify default profiles for each agent role.

---

## 📋 Complete List of Features

### Core AI & Agents
- **Leader Agent** (High-reasoning task breakdown)
- **Dev Agent** (Code writing & sandbox manipulation)
- **QA Agent** (Systematic testing & code verification)
- **Economic Routing** (Multi-LLM per-task utilization)
- **Mentorship Mode** (Leader step-in for blocked Dev agent)
- **Auto-Healing Retry Loop** (Self-correcting code generation)
- **4-D QA Scoring** (Quality, Requirements, Robustness, Security verification)

### Environment & Security
- **Secure File Manipulations** (`_jail_path` resolution against traversal)
- **OpenHands Sandbox** (Dockerized workspace execution)
- **JWT MCP (Model Context Protocol) Facade** (12-hour session security)
- **Zero In-Memory State** (Postgres/Redis backed durability)

### User Interface (Frontend)
- **React-Vite SPA**
- **Xterm.js Interactive Terminal**
- **Monaco Rich Code Editor** (Syntax highlighting, integrated view)
- **Resizable IDE Panels**
- **Real-Time Agent Chatter Box**
- **File System Explorer**
- **Settings Dashboard** (API management, Provider choices)
- **Task Progression Tracker**

### Backend & Orchestration
- **FastAPI Transport Layer**
- **WebSocket Streaming** (Bi-directional realtime IDE feedback)
- **PostgreSQL Database** (Run persistence & State storage)
- **Redis Event Broker** (Pub/Sub message queuing for worker tasks)
- **Python-based Async Worker Processes**
