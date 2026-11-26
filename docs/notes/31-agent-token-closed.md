# 31 — Agent console closed by default

**What**
I removed the default token for the agent console. Without a private token, every agent endpoint now returns 503. The old public token is always refused, even if someone sets it. The console page no longer fills it in.

**Why**
The console shows customer chats and lets a person reply. Its token was written in the config and in the example env file. Anyone who read the repo could open a deployed console. A copied env file would keep that public token.

**Number**
No number yet. I will measure it in the next deploy smoke test.

**Trade-off**
A local demo now needs one extra step: set a token in the env file. That is a small cost. It is much better than a public login to customer data.

**Likely follow-up question**
Q: Why 503 and not 401 when no token is set?
A: 401 means "your token is wrong". Here no token can be right. 503 tells the operator the service is not set up yet.
