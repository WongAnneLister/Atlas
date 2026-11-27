# 28 — Evidence for asking the key fact first

**What**
I tested the new answer prompts against the old ones on dev. I wrote the adoption rule before any run. Dev tied on every metric. So the rule turned to a replay of the failing turn.

**Why**
A prompt change touches every answer. I needed proof that it fixes the failing turn without hurting dev. The safety numbers, like false accepts, had to stay at zero.

**Number**
With the new prompts, the warranty answer came through in four of five replays. One run still handed off for low grounding. Before the change, it failed in all five runs.

Source: eval/reports/answer_lead_replay.md

**Trade-off**
Dev did not improve, because few dev items hit this pattern. So the case for the change rests on one replayed turn. The other two parts of that turn still go to a human.

**Likely follow-up question**
Q: Is one replayed turn enough to adopt a prompt change?
A: Only because dev tied, and the rule said so in advance. Test and the release gate also passed. I would still watch the low-grounding rate on new runs.
