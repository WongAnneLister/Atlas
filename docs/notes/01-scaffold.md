# 01 — Project scaffold

**What**
I built the empty project skeleton. Every threshold and model name lives in one YAML file. A typed settings object loads it, and env vars can override any key. One factory function creates every chat model, so tests can swap in a fake.

**Why**
Later commits tune many numbers, like top-k and gate weights. Without one config file, those numbers hide inside the code. Nobody could then say which setting produced a result.

**Number**
No number yet. I will measure retrieval quality in commit 08.

**Trade-off**
I spent a full commit on tooling before any feature. I also wrote a checker for these notes. It blocks long sentences and numbers that are not in a report. That is extra work now, but it keeps my claims honest later.

**Likely follow-up question**
Q: Why check the notes with a script?
A: I want every number I say to be real. The script looks for each number in the cited report. If a number is missing there, the build fails.
