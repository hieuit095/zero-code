#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║             ZeroCode IDE — One-Click Developer Setup                ║
# ║  Verifies dependencies, bootstraps .env, installs packages,        ║
# ║  spins up infrastructure, and prints next-steps.                   ║
# ╚══════════════════════════════════════════════════════════════════════╝
set -e

# ─── Color Codes ──────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

PASS="${GREEN}✔${NC}"
FAIL="${RED}✘${NC}"
WARN="${YELLOW}⚠${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

errors=0

# ─── Helper ───────────────────────────────────────────────────────────────────

header() {
  echo ""
  echo -e "${CYAN}${BOLD}━━━ $1 ━━━${NC}"
}

check_command() {
  local cmd="$1"
  local label="$2"
  local min_version="$3"
  local install_url="$4"

  if ! command -v "$cmd" &>/dev/null; then
    echo -e "  ${FAIL} ${BOLD}${label}${NC} — ${RED}not found${NC}"
    echo -e "     Install: ${CYAN}${install_url}${NC}"
    errors=$((errors + 1))
    return 1
  fi

  local version
  version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)

  if [ -n "$min_version" ]; then
    local major_have minor_have major_need minor_need
    major_have=$(echo "$version" | cut -d. -f1)
    minor_have=$(echo "$version" | cut -d. -f2)
    major_need=$(echo "$min_version" | cut -d. -f1)
    minor_need=$(echo "$min_version" | cut -d. -f2)

    if [ "$major_have" -lt "$major_need" ] 2>/dev/null || \
       { [ "$major_have" -eq "$major_need" ] && [ "$minor_have" -lt "$minor_need" ]; } 2>/dev/null; then
      echo -e "  ${FAIL} ${BOLD}${label}${NC} v${version} — ${RED}need ${min_version}+${NC}"
      echo -e "     Upgrade: ${CYAN}${install_url}${NC}"
      errors=$((errors + 1))
      return 1
    fi
  fi

  echo -e "  ${PASS} ${BOLD}${label}${NC} ${DIM}v${version}${NC}"
  return 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE A — Environment Verification
# ═══════════════════════════════════════════════════════════════════════════════

header "Phase A: Environment Verification"

check_command python3  "Python"          "3.11" "https://www.python.org/downloads/"
check_command node     "Node.js"         "18.0" "https://nodejs.org/"
check_command npm      "npm"             ""     "https://nodejs.org/"
check_command docker   "Docker"          ""     "https://docs.docker.com/get-docker/"

# docker-compose can be a standalone binary OR a docker plugin
if command -v docker-compose &>/dev/null; then
  echo -e "  ${PASS} ${BOLD}Docker Compose${NC} ${DIM}(standalone)${NC}"
elif docker compose version &>/dev/null 2>&1; then
  echo -e "  ${PASS} ${BOLD}Docker Compose${NC} ${DIM}(plugin)${NC}"
else
  echo -e "  ${FAIL} ${BOLD}Docker Compose${NC} — ${RED}not found${NC}"
  echo -e "     Install: ${CYAN}https://docs.docker.com/compose/install/${NC}"
  errors=$((errors + 1))
fi

if [ "$errors" -gt 0 ]; then
  echo ""
  echo -e "${RED}${BOLD}✘ $errors missing dependency(ies). Please install them and re-run this script.${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}${BOLD}All dependencies verified.${NC}"

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE B — Environment Variables
# ═══════════════════════════════════════════════════════════════════════════════

header "Phase B: Environment Variables"

bootstrap_env() {
  local target="$1"
  local example="$2"
  local label="$3"

  if [ -f "$target" ]; then
    echo -e "  ${PASS} ${label} ${DIM}(already exists)${NC}"
  elif [ -f "$example" ]; then
    cp "$example" "$target"
    echo -e "  ${WARN} ${BOLD}${label}${NC} created from example."
  else
    echo -e "  ${DIM}  ${label} — no .env.example found, skipping${NC}"
  fi
}

bootstrap_env ".env"         ".env.example"         "Root .env"
bootstrap_env "backend/.env" "backend/.env.example"  "Backend .env"

echo ""
echo -e "${YELLOW}${BOLD}  ⚠️  .env files created. Please open them and add your LLM API Keys before running the app!${NC}"

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE C — Backend Setup (Python)
# ═══════════════════════════════════════════════════════════════════════════════

header "Phase C: Backend Setup (Python)"

if [ ! -d "backend/venv" ]; then
  echo -e "  ${DIM}Creating virtual environment…${NC}"
  python3 -m venv backend/venv
  echo -e "  ${PASS} Virtual environment created at ${BOLD}backend/venv${NC}"
else
  echo -e "  ${PASS} Virtual environment ${DIM}(already exists)${NC}"
fi

echo -e "  ${DIM}Activating venv & installing dependencies…${NC}"
# shellcheck disable=SC1091
source backend/venv/bin/activate

pip install --upgrade pip --quiet
pip install -r backend/requirements.txt --quiet

echo -e "  ${PASS} ${BOLD}Python dependencies installed${NC}"

deactivate 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE D — Frontend Setup (Node.js)
# ═══════════════════════════════════════════════════════════════════════════════

header "Phase D: Frontend Setup (Node.js)"

echo -e "  ${DIM}Running npm install…${NC}"
npm install --silent 2>/dev/null || npm install

echo -e "  ${PASS} ${BOLD}Node.js dependencies installed${NC}"

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE E — Infrastructure (Docker)
# ═══════════════════════════════════════════════════════════════════════════════

header "Phase E: Infrastructure (Docker)"

COMPOSE_FILE="infra/staging/docker-compose.yml"

if [ -f "$COMPOSE_FILE" ]; then
  echo -e "  ${DIM}Starting Redis via Docker Compose…${NC}"

  # Detect compose command style
  if command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    COMPOSE_CMD="docker compose"
  fi

  $COMPOSE_CMD -f "$COMPOSE_FILE" up -d redis 2>/dev/null && \
    echo -e "  ${PASS} ${BOLD}Redis${NC} container running" || \
    echo -e "  ${WARN} Could not start Redis — is Docker running?"
else
  echo -e "  ${WARN} ${DIM}docker-compose.yml not found at ${COMPOSE_FILE}. Skipping.${NC}"
  echo -e "  ${DIM}  Make sure Redis is available at localhost:6379${NC}"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE F — Success Handoff
# ═══════════════════════════════════════════════════════════════════════════════

clear 2>/dev/null || true

echo ""
echo -e "${CYAN}"
cat << 'EOF'
 ╔══════════════════════════════════════════════════════════════╗
 ║                                                              ║
 ║    ███████╗███████╗██████╗  ██████╗  ██████╗ ██████╗ ███████╗║
 ║    ╚══███╔╝██╔════╝██╔══██╗██╔═══██╗██╔════╝██╔═══██╗██╔══╝║
 ║      ███╔╝ █████╗  ██████╔╝██║   ██║██║     ██║   ██║█████╗ ║
 ║     ███╔╝  ██╔══╝  ██╔══██╗██║   ██║██║     ██║   ██║██╔══╝ ║
 ║    ███████╗███████╗██║  ██║╚██████╔╝╚██████╗╚██████╔╝██████╗║
 ║    ╚══════╝╚══════╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═════╝╚═════╝║
 ║                                                              ║
 ║              ✅  SETUP COMPLETE — Ready to Code               ║
 ║                                                              ║
 ╚══════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

echo -e "${BOLD}Next Steps:${NC}"
echo ""
echo -e "  ${CYAN}1.${NC} ${BOLD}Edit your .env file${NC} with your LLM API keys:"
echo -e "     ${DIM}nano .env${NC}"
echo ""
echo -e "  ${CYAN}2.${NC} ${BOLD}Start the Backend${NC} (Terminal 1):"
echo -e "     ${DIM}source backend/venv/bin/activate${NC}"
echo -e "     ${DIM}cd backend && python -m uvicorn app.main:app --reload --port 8000${NC}"
echo ""
echo -e "  ${CYAN}3.${NC} ${BOLD}Start the Worker${NC} (Terminal 2):"
echo -e "     ${DIM}source backend/venv/bin/activate${NC}"
echo -e "     ${DIM}cd backend && python -m worker${NC}"
echo ""
echo -e "  ${CYAN}4.${NC} ${BOLD}Start the Frontend${NC} (Terminal 3):"
echo -e "     ${DIM}npm run dev${NC}"
echo ""
echo -e "  ${GREEN}${BOLD}Open http://localhost:5173 and start building! 🚀${NC}"
echo ""
