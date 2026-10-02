#!/bin/bash
# Smoke test of the sandbox: who am I, does the project work, and what can this container reach?
echo "--- identity"
echo "user=$(whoami) uid=$(id -u) home=$HOME"
echo "python=$(python --version 2>&1)"
echo "claude=$(claude --version 2>&1 | head -1)"
echo "git identity=$(git config --global user.name) <$(git config --global user.email)>"
echo "branch=$(git -C /work branch --show-current)"
echo "--- unit tests"
python -m unittest discover -s tests 2>&1 | tail -3
echo "--- git status (should list only real edits, not every file)"
git -C /work status --short | head -5
echo "--- can this container push anywhere? (must FAIL)"
git -C /work remote -v | head -2
GIT_TERMINAL_PROMPT=0 timeout 30 git -C /work push --dry-run origin agent 2>&1 | tail -1
echo "--- host credentials visible? (all of these should be empty or missing)"
ls -A ~/.ssh 2>&1 | head -2
git config --global --get-regexp 'credential' 2>&1 | head -2
env | grep -iE 'token|secret|api_key|password' | sed 's/=.*/=<set>/' | head -3
ls /var/run/docker.sock 2>&1 | head -1
echo "--- filesystem: only /work should be host-backed"
mount | grep -E ' /work ' | head -3
touch /work/.write_test && rm /work/.write_test && echo "write to /work: ok"
echo "--- network (allowed: anthropic, pypi; blocked: everything else)"
for url in https://api.anthropic.com https://pypi.org/simple/ https://example.com https://github.com; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url")
    echo "$url -> $code"
done
echo "--- capabilities (CapEff should be 0000000000000000)"
grep CapEff /proc/self/status
