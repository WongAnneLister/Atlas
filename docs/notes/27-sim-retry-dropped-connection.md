# 27 — The simulated customer retries a dropped connection

**What**
The simulated customer now retries its model call when the connection drops. It uses the same retry policy as the agent's own calls. Every eval that drives the simulator passes that policy in.

**Why**
My test rerun of the simulator crashed after two minutes. One customer-side call hit a connection error. Nothing retried it, so the whole run exited and saved nothing.

**Number**
No number yet. I will measure it in the test rerun that follows.

**Trade-off**
A retried call can make one turn slower, so turn latency gets a little noisier. A crashed run costs far more time. Errors that are not transient still stop the run at once.

**Likely follow-up question**
Q: Why not count the failed customer call as a dependency error instead?
A: The customer side is part of the test rig, not the agent. A blip there says nothing about the agent. So I retry it, and the agent's own errors are still counted.
