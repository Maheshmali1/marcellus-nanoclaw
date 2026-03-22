# NanoClaw on Android — Complete Setup Guide

This document covers everything needed to run NanoClaw on Android without Docker.
It documents what was done, what broke, how it was fixed, and how to operate it day-to-day.

---

## What This Is

`nanoclaw-android` is a fork of NanoClaw modified to run **without Docker**.
Instead of spawning Docker containers per message, it runs the agent-runner directly
as a Node.js child process. This makes it work on Android where Docker is not available.

**Device used:** Redmi Note 6 Pro (Snapdragon 636, ARM64, Android)
**Environment:** Termux + proot-distro Ubuntu 24.04
**Node version:** v20.19.4

---

## Architecture

### Original NanoClaw (with Docker)

```
node dist/index.js                         ← main process
└── on message: docker run nanoclaw-agent  ← isolated container per message
    └── node agent-runner/dist/index.js    ← runs inside container
        └── node ipc-mcp-stdio.js          ← MCP server
```

### nanoclaw-android (no Docker)

```
node dist/index.js                              ← main process
└── on message: spawn directly →
    node container/agent-runner/dist/index.js   ← agent process (per message)
    └── node ipc-mcp-stdio.js                   ← MCP server (dies with agent)
```

No Docker. No containers. All processes run natively on the host.

### What Changed (3 files)

| File | Change |
|------|--------|
| `container/agent-runner/src/index.ts` | Replaced 5 hardcoded `/workspace/*` paths with env vars (`WORKSPACE_GROUP`, `WORKSPACE_IPC`, `WORKSPACE_GLOBAL`, `WORKSPACE_EXTRA`) |
| `src/container-runner.ts` | Replaced `docker run` spawn with direct `node container/agent-runner/dist/index.js`. Credentials injected from `.env` directly into child process env. |
| `src/container-runtime.ts` | Made `ensureContainerRuntimeRunning()` and `cleanupOrphans()` no-ops — Docker check skipped entirely. |

### Env Vars Passed to Agent Process

```
WORKSPACE_GROUP   → groups/telegram_main/         (agent working directory)
WORKSPACE_IPC     → data/ipc/telegram_main/        (message passing)
WORKSPACE_GLOBAL  → groups/global/                 (shared memory)
WORKSPACE_EXTRA   → (empty string)
HOME              → data/sessions/telegram_main/   (.claude/ sessions live here)
CLAUDE_CODE_OAUTH_TOKEN → read from .env, injected directly
```

### Why Non-Root User Is Required

Claude CLI refuses `--allow-dangerously-skip-permissions` and `--permission-mode bypassPermissions`
when running as root. The original Docker setup runs as the `node` user inside the container.
On Android we replicate this by creating a `nanoclaw` Linux user and running everything as that user.

---

## Prerequisites

On the Android device:
1. **Termux** installed from F-Droid (not Play Store — Play Store version is outdated)
2. **SSH server** running in Termux: `pkg install openssh && sshd`
3. **proot-distro** installed: `pkg install proot-distro`
4. **Ubuntu** installed via proot-distro: `proot-distro install ubuntu`
5. **tmux** in Termux: `pkg install tmux`

Inside proot-distro Ubuntu:
```bash
apt-get update
apt-get install -y curl git sqlite3
# Install Node.js v20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
# Install Claude CLI
npm install -g @anthropic-ai/claude-code
```

---

## First-Time Setup

### 1. Clone the android branch

```bash
# Inside proot-distro Ubuntu
git clone -b android https://github.com/mahesh-mali-01/nanoclaw.git nanoclaw-android
cd nanoclaw-android
```

### 2. Install dependencies

TypeScript compiler (`tsc`) segfaults on ARM/proot so the `dist/` directories are
pre-compiled on Mac and committed to the android branch. You only need to install
runtime dependencies.

```bash
# Main project
npm install --ignore-scripts --omit=optional

# Rebuild native SQLite binding (must be compiled for this platform)
npm rebuild better-sqlite3

# Agent-runner (has its own node_modules)
cd container/agent-runner
npm install --ignore-scripts --omit=optional
cd ../..
```

> **Why `--omit=optional`?** The dependency tree includes `@img/sharp-darwin-arm64`
> (a macOS binary) as an optional dep. It segfaults on ARM Linux. Omitting optional deps
> skips it cleanly.

> **Why `--ignore-scripts`?** Prevents native modules from trying to compile during install,
> which can fail or segfault on proot.

### 3. Create .env

```bash
cat > .env << 'EOF'
CLAUDE_CODE_OAUTH_TOKEN=<your_claude_oauth_token>
TELEGRAM_BOT_TOKEN=<your_telegram_bot_token>
CREDENTIAL_PROXY_PORT=3002
EOF
chmod 600 .env
```

> **CREDENTIAL_PROXY_PORT=3002** avoids conflict if Mac NanoClaw is also running on port 3001.

> **Never commit .env** — it contains secrets. It is in `.gitignore`.

### 4. Create non-root user

```bash
# Inside proot-distro Ubuntu as root
useradd -m -s /bin/bash nanoclaw
cp -r /root/nanoclaw-android /home/nanoclaw/
chown -R nanoclaw:nanoclaw /home/nanoclaw/nanoclaw-android
```

### 5. Register your Telegram chat

```bash
cd /home/nanoclaw/nanoclaw-android
npx tsx setup/index.ts --step register -- \
  --jid "tg:<your_chat_id>" \
  --name "Mahesh" \
  --folder "telegram_main" \
  --trigger "@mahi" \
  --channel telegram \
  --no-trigger-required \
  --is-main
```

To get your chat ID: send `/chatid` to your bot on Telegram after starting the service once.

### 6. Start the service

```bash
# From Termux (not inside proot)
termux-wake-lock
tmux new-session -d -s nc "proot-distro login ubuntu -- su nanoclaw -s /bin/bash -c 'cd /home/nanoclaw/nanoclaw-android && CREDENTIAL_PROXY_PORT=3002 node dist/index.js >> /tmp/nc.log 2>&1'"
```

---

## How the SCP Transfer Worked (If Setting Up From Mac)

If you have NanoClaw already running on Mac, the fastest way to get it onto Android
is to zip the entire directory (with `node_modules` included) and SCP it over.
This avoids all npm install issues.

```bash
# On Mac — zip it up
cd ~/Desktop/ai-experiments
zip -r nanoclaw-android.zip nanoclaw-android/ --exclude "*.git*"

# SCP to Termux home
scp -P 8022 nanoclaw-android.zip ubuntu@ANDROID_IP:~/

# In Termux — copy to proot Ubuntu
cp ~/nanoclaw-android.zip \
  /data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root/

# In proot Ubuntu
cd /root && unzip nanoclaw-android.zip
npm rebuild better-sqlite3
```

Then follow steps 4–6 from First-Time Setup above.

> **Note:** Termux `~/` and proot Ubuntu `/root/` are NOT the same directory.
> Termux home: `/data/data/com.termux/files/home/`
> proot Ubuntu root: `/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/root/`

---

## Day-to-Day Operations

### Restart NanoClaw

```bash
# From Mac via SSH (one command)
ssh -p 8022 ANDROID_IP 'proot-distro login ubuntu -- bash -c "sqlite3 /home/nanoclaw/nanoclaw-android/store/messages.db \"DELETE FROM sessions;\"" && tmux new-session -d -s nc "proot-distro login ubuntu -- su nanoclaw -s /bin/bash -c '"'"'cd /home/nanoclaw/nanoclaw-android && CREDENTIAL_PROXY_PORT=3002 node dist/index.js >> /tmp/nc.log 2>&1'"'"'"'
```

### Check logs

```bash
# From Termux (or SSH)
proot-distro login ubuntu -- bash -c "tail -50 /tmp/nc.log"

# Follow live
ssh -p 8022 ANDROID_IP 'proot-distro login ubuntu -- bash -c "tail -f /tmp/nc.log"'
```

### Check if running

```bash
ssh -p 8022 ANDROID_IP 'tmux ls'
# Should show: nc: 1 windows
```

### Attach to the session (to see live output)

```bash
# From Termux app on the device
tmux attach -t nc
# Detach: Ctrl+B then D
```

### Kill everything

```bash
ssh -p 8022 ANDROID_IP 'tmux kill-server; proot-distro login ubuntu -- bash -c "pkill -f \"node dist/index.js\""'
```

### Clear stale sessions (if you see "No conversation found" errors)

```bash
ssh -p 8022 ANDROID_IP 'proot-distro login ubuntu -- bash -c "sqlite3 /home/nanoclaw/nanoclaw-android/store/messages.db \"DELETE FROM sessions;\""'
```

---

## Data Backup

### What Can Be Lost

All data lives inside Termux's app data directory:
```
/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/home/nanoclaw/nanoclaw-android/
```

| Event | Data Safe? |
|-------|-----------|
| Android reboot | ✅ Yes |
| Termux crash | ✅ Yes |
| NanoClaw crash | ✅ Yes — SQLite is transactional |
| tmux session killed | ✅ Yes |
| **Termux "Clear Data" / uninstall** | ❌ **Total loss** |
| **Hardware failure (old device)** | ❌ **Total loss** |
| **proot-distro reinstall** | ❌ **Total loss** |
| Android storage full during write | ⚠️ Possible corruption |

Android's cloud backup excludes Termux app data by default — there is **no automatic backup**.

The Redmi Note 6 Pro is a 2018 device. NAND flash has limited write cycles. Hardware failure
is a real possibility with no warning.

### Backup to Mac via SCP

Run from Mac to snapshot agent data:

```bash
# Create backup directory
mkdir -p ~/Desktop/nanoclaw-backup

# Backup agent memory and documents
scp -r -P 8022 ANDROID_IP:"/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/home/nanoclaw/nanoclaw-android/groups" ~/Desktop/nanoclaw-backup/

# Backup SQLite database (messages, sessions, registered groups)
scp -P 8022 ANDROID_IP:"/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/home/nanoclaw/nanoclaw-android/store/messages.db" ~/Desktop/nanoclaw-backup/
```

Or a single dated archive (stop NanoClaw first for a clean database snapshot):

```bash
ssh -p 8022 ANDROID_IP \
  'tar czf /tmp/nc-backup.tar.gz \
    -C /data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/ubuntu/home/nanoclaw/nanoclaw-android \
    groups store data/sessions' \
  && scp -P 8022 ANDROID_IP:/tmp/nc-backup.tar.gz ~/Desktop/nc-backup-$(date +%Y%m%d).tar.gz
```

### Restore from Backup

```bash
# On Android device (inside proot Ubuntu as nanoclaw)
cd /home/nanoclaw/nanoclaw-android

# Restore groups and store directories
tar xzf /tmp/nc-backup.tar.gz

# Clear stale sessions after restore (they reference the old device's Claude history)
sqlite3 store/messages.db "DELETE FROM sessions;"
```

---

## Telegram Configuration

| Field | Value |
|-------|-------|
| Bot name | @mahi_nanobot |
| Bot token | stored in `.env` as `TELEGRAM_BOT_TOKEN` |
| Chat JID | `tg:<your_chat_id>` |
| Trigger | `@mahi` |
| Folder | `telegram_main` |
| Is main channel | yes |

> Only ONE instance should run at a time. If both Mac and Android are running with the same
> bot token, they will fight over messages and both will behave erratically.

---

## GitHub

- Fork: `github.com/mahesh-mali-01/nanoclaw`
- Android branch: `android`
- Upstream: the original NanoClaw repo

The `android` branch contains:
- All no-docker source changes
- Pre-compiled `dist/` (main project)
- Pre-compiled `container/agent-runner/dist/` (agent runner)
- This setup guide

---

## Issues Encountered and How They Were Solved

### tsc segfaults on ARM/proot

**Problem:** TypeScript compiler crashes on ARM64 Linux inside proot-distro.

**Solution:** Compile `dist/` on Mac, then `git add -f dist/` and commit to the android branch.
The compiled JS is shipped in the repo and pulled on Android.

```bash
# On Mac
npm run build
cd container/agent-runner && npm run build
cd ../..
git add -f dist/ container/agent-runner/dist/
git commit -m "build: commit dist for Android"
git push origin android
```

### npm install segfaults / ENOENT rename errors

**Problem:** npm install crashes with segfault (`@img/sharp-darwin-arm64`) or fails with
`ENOENT rename` errors because proot doesn't support cross-directory rename syscalls reliably.

**Solutions tried:**
- `--cache /tmp/npm-cache` → still crashes (sharp)
- `--no-cache` → still ENOENT
- `TMPDIR=/root npm install` → helped but sharp still segfaulted
- **`--omit=optional --ignore-scripts`** → works, skips sharp and other optional native deps

### Claude refuses --allow-dangerously-skip-permissions as root

**Problem:** Claude CLI returns:
```
--dangerously-skip-permissions cannot be used with root/sudo privileges for security reasons
```

The main NanoClaw process and agent-runner were running as root inside proot-distro.

**Solution:** Create a non-root Linux user (`nanoclaw`) and run everything as that user.

### agent-runner node_modules missing

**Problem:** `Cannot find package '@anthropic-ai/claude-agent-sdk'` — the agent-runner
has its own `package.json` and `node_modules` separate from the root project.

**Solution:** Either:
1. Run `npm install` inside `container/agent-runner/` on Android (use `--omit=optional --ignore-scripts`)
2. Or ship `node_modules` from Mac in the zip transfer (fastest — avoids all install issues)

### Stale session IDs after move from Mac

**Problem:** After copying the database from Mac to Android, the `sessions` table contains
session IDs that reference claude conversation history that only exists on Mac.
Claude returns: `No conversation found with session ID: <uuid>`

**Solution:**
```bash
sqlite3 store/messages.db "DELETE FROM sessions;"
```

### "Unexpected end of input" — corrupted node_modules file

**Problem:** Node crashes with `SyntaxError: Unexpected end of input` in a `node_modules` file.
This happens when npm install is interrupted mid-download.

**Solution:**
```bash
npm install whatwg-url --ignore-scripts --cache /tmp/npm-cache
# or full reinstall:
rm -rf node_modules && npm install --ignore-scripts --omit=optional
```

### Port conflict (CREDENTIAL_PROXY_PORT)

**Problem:** If Mac NanoClaw is running, it occupies port 3001. Android nanoclaw starting
on the same network gets a conflict.

**Solution:** Set `CREDENTIAL_PROXY_PORT=3002` in `.env` or in the start command.

### proot process dies when SSH disconnects

**Problem:** Running `node dist/index.js` directly in an SSH session kills it on disconnect.
`nohup` doesn't work because proot itself exits when the shell session ends.

**Solution:** Run from Termux's `tmux` (not inside proot's tmux). The tmux server lives
in Termux's process space and persists after SSH disconnects.

```bash
# From Termux SSH session:
termux-wake-lock   # prevents Android from killing Termux in background
tmux new-session -d -s nc "proot-distro login ubuntu -- su nanoclaw ..."
```

### Telegram bot token accidentally committed

**Problem:** During an early session, the real bot token was included in ANDROID_SETUP.md
and pushed to a public GitHub repo.

**Actions taken:**
1. Revoked the token immediately via BotFather (`/revoke`)
2. Generated a new token
3. Rewrote git history with `git filter-branch` to remove the token from all commits
4. Force-pushed the cleaned branch: `git push --force origin android`

**Prevention:** Always scan before pushing:
```bash
git diff HEAD | grep -iE "token|secret|key|password|sk-ant"
```

---

## Files You Should Know About

| Path | Purpose |
|------|---------|
| `.env` | Secrets — never commit |
| `store/messages.db` | SQLite: messages, sessions, registered groups |
| `/tmp/nc.log` | Runtime log (inside proot Ubuntu) |
| `groups/telegram_main/` | Agent working directory, memory, conversation history |
| `data/sessions/telegram_main/.claude/` | Claude session files (HOME for the agent) |
| `data/ipc/telegram_main/` | IPC between main process and agent |
| `container/agent-runner/dist/index.js` | The agent that runs claude per message |

---

## Mac vs Android — Running Both

Both use the same Telegram bot so only one should be active at a time.

| | Mac | Android |
|--|-----|---------|
| Location | `~/Desktop/ai-experiments/nanoclaw` | `/home/nanoclaw/nanoclaw-android` |
| Credential proxy port | 3001 | 3002 |
| Container mode | Docker | Direct Node.js |
| Process manager | launchd | tmux in Termux |
| Start | `launchctl load ~/Library/LaunchAgents/com.nanoclaw.plist` | see restart command above |
| Stop | `launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist` | `tmux kill-server` |
