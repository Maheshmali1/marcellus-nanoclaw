#!/data/data/com.termux/files/usr/bin/bash
# Place this file at: ~/.termux/boot/start-nanoclaw.sh
# Requires Termux:Boot installed from F-Droid and opened once to activate.
# Auto-starts NanoClaw 30 seconds after Android boots.

sleep 30
termux-wake-lock
~/restart-nc.sh
