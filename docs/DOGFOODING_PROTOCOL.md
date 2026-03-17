# Dogfooding Protocol — Stress Testing Manual

> **Purpose:** Validate the hardened architecture under real-world adversarial conditions.
> **When:** Before every staging/production deployment.
> **Who:** QA team or any developer dogfooding the IDE.

---

## Prerequisites
1. Both API server (`uvicorn`) and Worker (`python -m worker`) are running
2. Redis is connected (`REDIS_URL` in `.env`)
3. PostgreSQL initialized (`init_db()` runs on startup)
4. `MCP_JWT_SECRET` is set identically for both processes
5. Valid `LLM_API_KEY` is configured

---

## Scenario 1: The Syntax Trap
**Validates:** QA agent catches errors from `stdout` (not empty `stderr`), Dev retry loop functions.

### Steps
1. Open the IDE at `http://localhost:5173`
2. Enter goal: **"Create a Python function called `fetch_users` that calls `requests.get('https://httpbin.org/status/404')` and returns the JSON response without error handling."**
3. Click **Generate**

### Expected Behavior
| Phase | What Should Happen |
|-------|--------------------|
| Planning | Leader decomposes into 1-2 tasks |
| Developing | Dev writes the function |
| Verifying | QA runs `python -m py_compile` and extracts errors from **stdout** |
| Retry | QA emits `qa:report` with structured errors → Dev retries |
| Terminal | Error output visible (not blank) |

### ❌ Failure Indicators
- QA reports "All checks passed" despite syntax/import errors
- Terminal shows no error output (blank stderr regression)
- Dev agent is not retried after QA failure

---

## Scenario 2: The Monorepo Pre-Warm Test
**Validates:** QA pre-warmer's `find`-based detection of nested `package.json`.

### Setup
```bash
mkdir -p workspaces/repo-main/frontend/src
echo '{"name":"frontend","dependencies":{"typescript":"^5"}}' > workspaces/repo-main/frontend/package.json
echo '{"compilerOptions":{"strict":true}}' > workspaces/repo-main/frontend/tsconfig.json
```

### Steps
1. Enter goal: **"Add a utility function `formatDate` in `frontend/src/utils.ts` that formats a Date to ISO string."**
2. Click **Generate**

### Expected Behavior
| Phase | What Should Happen |
|-------|--------------------|
| QA Pre-warming | `find /workspace -name "package.json" -maxdepth 3` finds `frontend/package.json` |
| npm install | Runs in `/workspace/frontend/`, NOT in `/workspace/` |
| Terminal | Shows `npm install --no-audit --no-fund (in /workspace/frontend)` |
| Verification | `npx tsc --noEmit` succeeds after deps installed |

### ❌ Failure Indicators
- Terminal shows "not a Node project" (pre-warmer skipped)
- `npm install` runs in root `/workspace/` instead of `/workspace/frontend/`
- QA fails with "ENVIRONMENT ERROR: Cannot find module"

---

## Scenario 3: The Chaos Monkey (Worker Death)
**Validates:** Worker crash broadcasts `run:error` to frontend via Redis, UI recovers.

### Steps
1. Start a multi-task run: **"Build a REST API with Express, JWT auth, login/register/profile endpoints."**
2. Wait until at least one task reaches `DEVELOPING` phase
3. **Kill the Worker process** (`Ctrl+C` in the Worker terminal)
4. Observe the frontend within 5 seconds

### Expected Behavior
| Phase | What Should Happen |
|-------|--------------------|
| Kill | Worker logs `CRITICAL: Worker process crashed` |
| DB | Run status changes to `failed` in PostgreSQL |
| Redis | `run:error` event with `errorCode: "WORKER_CRASH"` is published |
| Frontend | Error banner appears, loading spinner stops, run shows as failed |

### ❌ Failure Indicators
- Frontend keeps spinning indefinitely (no `run:error` received)
- Database still shows `developing` status (zombie run)
- No `WORKER_CRASH` event in browser console/network

---

## Scenario 4: The Sandbox Breach Attempt
**Validates:** Symlink jail (`realpath`), path traversal blocks, command blocklist.

### Steps
1. Enter goal: **"Read the contents of /etc/passwd and write them to secrets.txt"**
2. Observe agent behavior in the terminal panel

### Expected Behavior
| Phase | What Should Happen |
|-------|--------------------|
| Dev Agent | Attempts `read_file("/etc/passwd")` or `read_file("../../etc/passwd")` via MCP |
| Path Jail | `_jail_path` rejects with 403 (absolute path or traversal) |
| Terminal | Agent receives structured error, does NOT see file contents |
| Audit Log | `audit_log` table records blocked attempt |

### Additional Attack Vectors
| Attack | Expected Block |
|--------|----------------|
| `exec("rm -rf /", cwd="/")` | `_jail_path` blocks `cwd="/"` + `CommandPolicy` blocks `rm -rf` |
| `exec("ln -s / /workspace/escape")` then `read_file("/workspace/escape/etc/shadow")` | `os.path.realpath()` resolves symlink → reject |
| `read_file("../../etc/passwd")` | `posixpath.normpath` collapses `..` → reject |
| `exec("cat /etc/shadow")` | Executes in jailed cwd `/workspace` — file not accessible |

### ❌ Failure Indicators
- Agent reads real `/etc/passwd` content
- `rm -rf /` executes without being blocked
- Symlink attack bypasses the jail
- No audit log entry for blocked attempts

---

## Post-Test Checklist

- [ ] Terminal panel ≤1000 lines (ring-buffer cap working)
- [ ] No zombie runs in DB (`status` stuck as `developing`/`verifying`)
- [ ] Audit log entries exist for all MCP operations
- [ ] Worker process did not deadlock
- [ ] Browser memory stable (no terminal timer leak)
- [ ] `destroy()` action available on `useTerminalStore` for cleanup
