#!/bin/bash
# Container entry point: refresh the agent's rules, install the project's
# dependencies from the clone, then idle so `docker compose exec` can attach.

# The rules live outside the volume and are copied in at every start, so
# editing them never needs the volume to be recreated.
cp /opt/agent-rules.md "$CLAUDE_CONFIG_DIR/CLAUDE.md"

# Dependencies come from the clone, not the image, so a requirement the agent
# adds on its branch is picked up by the next restart without a rebuild.
if [ -f /work/requirements.txt ]; then
    pip install --user --quiet -r /work/requirements.txt \
        || echo "WARN: pip install -r requirements.txt failed" >&2
fi

exec tail -f /dev/null
