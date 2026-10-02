# shared_budget

A Telegram bot that turns receipts (photos, e-receipts, quick text entries) into a shared expense log for two people: who paid, for what, in which category, and who owes whom. Personal project, free tools only. Work in progress.

## Develop

```powershell
python -m unittest discover -s tests
```

## Autonomous development in Docker

Claude Code can work on this repo unattended inside a sandbox: a separate clone, no host credentials, internet only through an allowlist proxy.

```powershell
.\sandbox.ps1            # start the sandbox and open Claude Code
.\sandbox.ps1 check      # smoke test of the isolation
.\sandbox.ps1 review     # see what the agent committed on branch "agent"
.\sandbox.ps1 publish    # merge it into master after a y/N prompt and push to GitHub
```

The agent itself can't push: GitHub only gets what was reviewed on the host.

The first start asks you to sign in to Claude once; the login is kept in a Docker volume. See [CLAUDE.md](CLAUDE.md) for the project context and `.sandbox/` for the setup.
