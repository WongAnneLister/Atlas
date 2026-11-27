# 27 — Simulated chats can use fixture customers

**What**
The simulator now raises the session allowlist inside its test app. Every scenario customer can open a session, including the time-sensitive fixture customer. The limit lives in config.

**Why**
The chat API only lets the first eight customers open a session. Three refund scenarios use a fixture customer outside that list. Every one of their chats failed before the first message.

**Number**
No number yet. I will measure it in the refund evidence that follows.

**Trade-off**
The test app is now more open than the demo app. That only affects the simulator. The demo keeps its short list.

**Likely follow-up question**
Q: Why did nobody see this before?
A: The nightly subset never picked those three scenarios. The new run-health check flagged them as failed sessions on the first full refund run.
