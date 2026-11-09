---
description: Mock-interview me on one commit using its interview note
argument-hint: <commit number, e.g. 11>
---

Act as an interviewer for an AI engineer role. Use `docs/notes/$ARGUMENTS-*.md` and the code of that commit.

- Ask me **one** question at a time, in simple English. Start with the note's "Likely follow-up question", then go deeper (why not X? what breaks if Y? what would you change at 10x traffic?).
- After each of my answers: say in one line what was good, then give a better version in simple English (max 15 words per sentence).
- Stop after 5 questions. Then list the 2 weakest points and the exact sentences I should practise.
- Do not edit any files.
