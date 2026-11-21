# 22a — A release check for new indexes

**What**
I built a check that compares search results for the same questions.
I also checked questions that should never get a knowledge answer.

**Why**
An index change can hide useful evidence or surface misleading text.
I wanted to catch both changes before sending traffic to it.

**Number**
No number yet. I will measure it in commit 22b.

**Trade-off**
I used search and the evidence check without calling a language model.
This saves model calls and leaves rewritten questions for separate tests.

**Likely follow-up question**
Q: Can I release a build that passes a question with no answer?
A: I require every such question to fail the evidence check.
A written exception only applies to paired quality regressions.
