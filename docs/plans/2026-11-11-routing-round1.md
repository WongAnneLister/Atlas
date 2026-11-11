# Routing optimization round one

Goal: measure whether clearer policy/action boundaries improve dev knowledge routing.
The user approved this round after the baseline diagnosis.

Scope: change only the classification prompt in the application.
Keep model roles, intent-to-path mapping, retrieval, gate weights, threshold, and labels fixed.
Use the original prompt as a saved baseline and one candidate prompt.

1. Add an offline-tested, prompt-fingerprinted classification experiment under `eval/`.
   Use all dev questions; count knowledge-path coverage only for answerable retrieval questions.
   Do not invent intent gold for no-answer questions; report their route distribution only.
   Add authored policy/action controls before collecting baseline predictions.
2. Run the original prompt with the real fast model. Inspect dev misses locally.
3. Clarify general guidance versus personal order actions in `classify.md`.
   Preserve greetings, unsupported account actions, complaints, and human requests.
4. Run the candidate once against identical dev items and controls.
   Record changed paths, model failures, original latency, prompt/config/data hashes, and dates.
   This routing experiment does not measure answer accuracy or safety.
5. If dev coverage improves without damaging control routes, freeze the candidate.
   Run the full test graph once in a new output file and compare against `e2e-001`.
   Keep failures and avoid further prompt changes using test outcomes.
6. Run `make check` and `make notes-check`, update progress/results and the interview note.
   Commit the measured outcome locally; do not push without a new request.

Full-graph performance comparisons must retain the baseline's infrastructure limitations.
The draft benchmark's intended knowledge route is not a human-reviewed intent label.
Ambiguous personal wording remains visible; neither labels nor questions are edited.

Execution: steps 1–5 completed with saved reports and a frozen candidate.
The candidate completed the full test set without selective retries or test-driven changes.
The safety checkpoint remains failed; see `docs/RESULTS.md` for the measured comparison.
Step 6 verification passed: `make check`, `make notes-check`, and `git diff --check`.
The local commit includes the measured result, updated progress, and interview note.
No remote push is part of this round.
