# Sandbox for running Claude Code unattended on a clone of shared_budget.
#
# What this container can reach: only the clone mounted at /work, its own
# ~/.claude volume, and (through the squid proxy) the domains listed in
# squid/squid.conf. It has no host credentials: no ssh agent, no git
# credential helper, no host gitconfig, no git remote it can push to.
#
# Built by .sandbox/compose.yaml; run it through ..\sandbox.ps1.

FROM python:3.13-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 ripgrep jq less \
    && rm -rf /var/lib/apt/lists/*

# Claude Code refuses --dangerously-skip-permissions as root, so run as a normal user.
RUN useradd --create-home --shell /bin/bash agent

# Strip CR in case Windows git checked these out with CRLF line endings.
COPY agent-rules.md /opt/agent-rules.md
COPY start.sh check.sh /opt/
RUN sed -i 's/\r$//' /opt/start.sh /opt/check.sh /opt/agent-rules.md \
    && chmod 755 /opt/start.sh /opt/check.sh

USER agent
ENV HOME=/home/agent \
    PATH=/home/agent/.local/bin:$PATH \
    CLAUDE_CONFIG_DIR=/home/agent/.claude \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /work

# Claude Code, official installer (installs to ~/.local/bin).
RUN curl -fsSL https://claude.ai/install.sh | bash

# Commits made in here are attributed to the sandbox, not to the host user.
# The bind mount from Windows shows every file as executable and may carry
# CRLF, so git must ignore file modes and leave line endings alone.
RUN git config --global user.name "sandbox-agent" \
 && git config --global user.email "sandbox-agent@localhost" \
 && git config --global --add safe.directory /work \
 && git config --global core.filemode false \
 && git config --global core.autocrlf false \
 && mkdir -p /home/agent/.claude

CMD ["/opt/start.sh"]
