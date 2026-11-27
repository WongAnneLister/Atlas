# 28 — The official index now lives on this machine

**What**
I moved the official vector index from the remote server to this machine. Then I released the split catalog index there through the normal gated release. The live alias now points to the new build.

**Why**
The remote index had been down for over a day, and nobody noticed. Its SSH host key had changed, and its containers did not restart after a reboot. Every eval already used the local copy, so the remote one only added risk.

**Number**
The release check matched the old build on every metric. Hit at five stayed at 160 of 160.

Source: eval/runs/official-index-28i/index-release.md

**Trade-off**
The index now depends on this laptop being on. That is fine for a demo and for evals. A real deployment would need a hosted copy with health alerts.

**Likely follow-up question**
Q: How would you notice the next outage sooner?
A: Alert when the vector store fails its health check for a few minutes. The app should also refuse to start without it.
