# 28 — A real switch for the context builder

**What**
I made `context.enabled: false` actually work. It now sends each model call the old layout. That is the task prompt, then the input, and nothing else. I also added a per-node switch, and moved the shared preamble into a prompt file.

**Why**
After the context builder, false rejects rose on the test split. But the switch to turn it off was never read by the code. So I could not compare old and new. Without a switch, the change could not be measured or rolled back.

**Number**
No number yet. I will measure it in the next regression run.

**Trade-off**
The legacy layout skips the shared prefix. So it loses some prefix cache hits. It also drops pinned facts and memory hints from the prompt. I keep it as a switch, so the choice is made by measurement.

**Likely follow-up question**
Q: Why did one shared preamble change answers?
A: I do not know yet. My guess is its rule to escalate when evidence is unclear. That rule may make the model mark more parts as unsupported. I test that guess on the dev split first.
