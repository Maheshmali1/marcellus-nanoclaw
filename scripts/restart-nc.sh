#!/data/data/com.termux/files/usr/bin/bash

# Kill existing session and processes
tmux kill-session -t nc 2>/dev/null
sleep 1
proot-distro login ubuntu -- bash -c "pkill -f 'node dist/index.js' 2>/dev/null; sqlite3 /home/nanoclaw/nanoclaw-android/store/messages.db 'DELETE FROM sessions;'"
sleep 2

# Start NanoClaw
tmux new-session -d -s nc "proot-distro login ubuntu -- su nanoclaw -s /bin/bash -c 'cd /home/nanoclaw/nanoclaw-android && CREDENTIAL_PROXY_PORT=3002 node dist/index.js >> /tmp/nc.log 2>&1'"

# Watchdog: checks every 5 min, restarts NanoClaw if it dies
tmux new-window -t nc -n watchdog "while true; do sleep 300; proot-distro login ubuntu -- bash -c \"pgrep -f 'node dist/index.js' > /dev/null || (echo [\$(date)] Watchdog: restarting >> /tmp/nc.log && su nanoclaw -s /bin/bash -c 'cd /home/nanoclaw/nanoclaw-android && CREDENTIAL_PROXY_PORT=3002 node dist/index.js >> /tmp/nc.log 2>&1')\"; done"

echo "Done. Checking tmux..."
tmux ls
