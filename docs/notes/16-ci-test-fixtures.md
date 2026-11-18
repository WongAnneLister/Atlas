# 16c — CI fix: self-contained graph tests

**What**
I fixed the CI check that had failed on every push for two days.
Four graph tests now build their own small order database.
They no longer read the database file on my laptop.

**Why**
The refund path reads orders before it asks the customer to pick one.
On my machine, the seeded database existed, so the tests passed.
CI never builds that file, so the refund path handed off instead.

**Number**
No number yet. This is a test fix, so there is no eval report.
I pointed the database path at a missing file to copy CI.
Four tests failed before the fix and none after.

**Trade-off**
Each test now seeds a small temporary database, so it runs a bit slower.
I should have caught this earlier, because a fresh clone showed the same failure.
I had written it down as a known issue instead of fixing it.

**Likely follow-up question**
Q: How do you stop tests from depending on local files again?
A: I now run the full suite with the database path pointed at a missing file.
A clean clone check before each release does the same job.
