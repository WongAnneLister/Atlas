---
description: Write or rewrite the interview note for a commit (What / Why / Number / Trade-off / Likely follow-up) in simple English
argument-hint: <commit number, e.g. 08>
---

Write the interview note for commit $ARGUMENTS.

1. Read `AGENTS.md` §9 and `docs/notes/TEMPLATE.md`. Follow the format and the plain-English rules exactly.
2. Find what the commit **actually did**: the prompt `docs/commits/$ARGUMENTS-*.md`, the git log and diff for that commit (`git log --grep` or the commit that added `docs/notes/$ARGUMENTS-*`), `docs/PROGRESS.md`, and the reports it produced in `eval/reports/` or `eval/runs/`.
3. Take every number from those reports. Cite the path on the `Source:` line. Never invent or round a number into a new one. If there is no number, write "No number yet. I will measure it in commit NN."
4. Write or overwrite `docs/notes/$ARGUMENTS-<slug>.md`, run `make notes-check`, fix until it passes, then run `make notes`.
5. Show me the full note in your reply. Do not commit unless I ask.
