# 28 — A tool that shows which eval items the budget fit can change

**What**
I wrote a script that reads saved eval rows and needs no model. It bounds the answer prompt size of each item that reached the answer step. It lists the items whose bound is over the answer budget.

**Why**
The budget fit only acts on prompts over the budget. So most eval items get the same prompt before and after. I wanted to prove that from saved data, instead of paying for full reruns.

**Number**
No number yet. I will measure it in the evidence commit that follows.

**Trade-off**
The bound counts every retrieved source, so it can flag items the fit never touches. For whole-route items it uses the longest chunk of each section. That is safe, but loose.

**Likely follow-up question**
Q: Why trust a bound instead of rerunning everything?
A: Below the budget, the fit returns the same prompt by design. A test covers that. I still reran the one flagged item live.
