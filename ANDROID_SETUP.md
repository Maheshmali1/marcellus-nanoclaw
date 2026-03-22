# NanoClaw Android Setup — Session Notes

## What This Repo Is

`nanoclaw-android` is a fork of NanoClaw modified to run **without Docker**.
Instead of spawning Docker containers, it runs the agent-runner directly as a Node.js process.
This makes it work on Android (proot-distro Ubuntu) where Docker is not available.

## Key Architectural Decision: No-Docker Mode

### What Changed (3 files)

| File | Change |
|------|--------|
| `container/agent-runner/src/index.ts` | Replaced 5 hardcoded `/workspace/*` paths with env vars (`WORKSPACE_GROUP`, `WORKSPACE_IPC`, `WORKSPACE_GLOBAL`, `WORKSPACE_EXTRA`) |
| `src/container-runner.ts` | Replaced `docker run` spawn with direct `node container/agent-runner/dist/index.js` spawn. Credentials read from `.env` and injected directly into child process env. |
| `src/container-runtime.ts` | Made `ensureContainerRuntimeRunning()` and `cleanupOrphans()` no-ops — Docker check skipped. |

### How It Works Now

```
node dist/index.js                          ← main process (always running)
└── on message: spawns directly →
    node container/agent-runner/dist/index.js   ← agent process (per message)
    └── node ipc-mcp-stdio.js                   ← MCP server (dies with agent)
```

No Docker. No containers. All processes run natively on the host.

### Env Vars Passed to Agent

```
WORKSPACE_GROUP   → groups/telegram_main/         (agent working directory)
WORKSPACE_IPC     → data/ipc/telegram_main/        (message passing)
WORKSPACE_GLOBAL  → groups/global/                 (shared memory)
WORKSPACE_EXTRA   → (empty)
HOME              → data/sessions/telegram_main/   (.claude/ sessions live here)
CLAUDE_CODE_OAUTH_TOKEN → read from .env and injected directly
```

## Telegram Setup

- Bot name: **@mahi_nanobot**
- Bot token: stored in `.env` as `TELEGRAM_BOT_TOKEN`
- Registered chat JID: `tg:1133180883` (Mahesh's personal chat)
- Assistant name: **Andy**
- Folder: `telegram_main`
- Main channel: yes (no trigger required, responds to all messages)

## GitHub

- Fork: `github.com/mahesh-mali-01/nanoclaw`
- Android branch: `android` (contains all no-docker changes)
- Upstream: `github.com/qwibitai/nanoclaw`

## Android Device Setup

- Device: Redmi Note 6 Pro (Snapdragon 636, ARM64)
- Environment: Termux + proot-distro Ubuntu
- Node version: v20.19.4
- No Docker (not possible on this kernel)
- Use `tmux` to keep processes alive when SSH drops

## Mac Setup (Original NanoClaw)

- Location: `/Users/maheshmali/Desktop/ai-experiments/nanoclaw`
- Running as: launchd service (`com.nanoclaw.plist`)
- Credential proxy port: 3001
- Uses Docker for containers (unchanged)

## Android Install Steps (Resume Here)

```bash
# Inside proot-distro Ubuntu, inside tmux

# 1. Clone (already done)
git clone -b android https://github.com/mahesh-mali-01/nanoclaw.git nanoclaw-android
cd nanoclaw-android

# 2. Install deps (already done)
npm install --ignore-scripts --cache /tmp/npm-cache
npm rebuild better-sqlite3

# 3. Build agent-runner (in progress)
cd container/agent-runner && npm install && npm run build && cd ../..

# 4. Build main project
npm run build

# 5. Create .env
cat > .env << 'EOF'
CLAUDE_CODE_OAUTH_TOKEN=<your_oauth_token>
TELEGRAM_BOT_TOKEN=<TELEGRAM_BOT_TOKEN>
CREDENTIAL_PROXY_PORT=3002
EOF

# 6. Register Telegram chat
npx tsx setup/index.ts --step register -- \
  --jid "tg:1133180883" \
  --name "Mahesh" \
  --folder "telegram_main" \
  --trigger "@Andy" \
  --channel telegram \
  --no-trigger-required \
  --is-main

# 7. Sync env to container dir
mkdir -p data/env && cp .env data/env/env

# 8. Start
CREDENTIAL_PROXY_PORT=3002 node dist/index.js
```

## Process Management on Android

```bash
# Check if running
pgrep -a node | grep "dist/index.js"

# Watch logs
tail -f logs/nanoclaw.log

# Kill everything cleanly
pkill -f "nanoclaw"

# Keep running after SSH disconnect — use tmux
tmux attach   # reconnect to existing session
```

## Important Notes

- Only ONE instance should run at a time (Mac OR Android) — both use the same Telegram bot token and will fight for messages
- If you get "No conversation found with session ID" error: `sqlite3 store/messages.db "DELETE FROM sessions;"`
- Mac nanoclaw service is currently STOPPED — restart with: `launchctl load ~/Library/LaunchAgents/com.nanoclaw.plist`
- Android uses port 3002 for credential proxy to avoid conflict with Mac's 3001
