# 27 — Making the simulated customer reach its recall turns

**What**
I changed the simulated customer for scripted chats. It now gets the script line for each turn. It may not end the chat before the last recall checkpoint. A handoff no longer ends a scripted chat early either.

**Why**
The simulated customer often skipped ahead and said goodbye. A single handoff on a side question also ended the chat. So the recall questions were rarely asked, and fact retention could not be measured.

**Number**
No number yet. I will measure it in the dev comparison that follows.

**Trade-off**
Scripted chats now run longer, so they cost more model calls. Forcing the script makes the customer less free. Only scenarios with recall checkpoints change, so other results stay comparable.

**Likely follow-up question**
Q: Doesn't forcing the script make the test less realistic?
A: A little. But a recall test must ask the recall question. I log every goodbye I overrode, so a reviewer can see how often it happened.
