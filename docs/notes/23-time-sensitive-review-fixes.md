# 23a review — One refund case per date

**What**
I gave each refund test a different order date.
I kept price drops in general policy questions.
I added more ways to ask about the current rules.

**Why**
The refund search asks the same return question for every test order.
Changing the question text made copies of the same test.
I gave each test set its own dates.

**Number**
No number yet. I will measure it in commit 23b.

**Trade-off**
I kept the order facts simple so the date is the only policy difference.
This tests the change in policy clearly.
Other order types still need separate tests.

**Likely follow-up question**
Q: Why leave price drops out of the refund cases?
A: The refund search builds a return question from the order.
I test price drops where the search reads the question.
