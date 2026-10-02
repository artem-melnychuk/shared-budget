# Sandbox rules

These rules apply only inside this container and win over the repo's
CLAUDE.md wherever they conflict.

You are running in an isolated container on a clone of shared_budget, on
branch `agent`. A human reviews your work on the host and decides what
reaches `master`.

- Work on branch `agent`. Never create git worktrees, never switch to or merge
  into `master`, never run `git push` and never add a git remote.
- Commit to `agent` only when `python -m unittest discover -s tests` is fully
  green. Commit with plain `git add <files>` for the files you changed.
- Tests run offline: fake Telegram updates, saved model responses, synthetic
  receipt images. Do not call the Telegram or Gemini APIs unless the task
  explicitly asks for a live check. If a task needs one and no key is set,
  say so and stop.
- Free tools only. Do not add a dependency or service that needs payment or
  a credit card; if the task seems to need one, write the options in NOTES.md
  and stop.
- The repo is public and your commits get pushed to GitHub after review.
  Never commit real receipts, photos, bank exports, `.env`, tokens or `*.db`
  files, and keep names and real amounts out of fixtures and commit messages.
  Test fixtures must be made up.
- New dependencies go into `requirements.txt`; install them with
  `pip install --user -r requirements.txt`.
- When something is unclear, decide it yourself, write the decision down in
  NOTES.md and carry on.
- Do not edit `.sandbox/` or `sandbox.ps1`. If the sandbox gets in your way,
  describe the change you need in NOTES.md.
- Do not read, print or copy anything under ~/.claude except CLAUDE.md.
