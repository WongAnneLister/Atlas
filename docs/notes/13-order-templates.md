# 13 — Order replies written by code, not by the model

**What**
I stopped the order model from writing replies. It now only picks order lookups. Then it says if the order data answers the question. Code writes the reply from the data with fixed sentences.

**Why**
My quote check on order answers did not work. The model often skipped the invented sentence, or called it not a fact. It also blocked most correct answers. A model cannot reliably check its own made-up text.

**Number**
The quote check passed 26 of 120 real answers. It caught 59 of 80 invented claims. Template replies answered 45 of 48 order questions with every expected fact. On v1, one no-answer question got an answer, through the knowledge path.
Source: eval/reports/order_replies.md

**Trade-off**
Replies are longer and less natural now. A policy question can still get an order list instead of an answer. I accepted that. The order path can no longer state a rule it never read.

**Likely follow-up question**
Q: Why was there still one wrong answer on v1?
A: It came from the knowledge path, not the order path. The gate passed it because "USB" matched, though the model number did not. I will make model numbers required, then re-run the sweep.
