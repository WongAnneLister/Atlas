# Order tools, complaints, fixed replies, and handoff

Commit 10 connects paths A, D and E to the fixed rewrite/classify graph.
Knowledge and after-sales remain explicit stubs until commits 11 and 12.

## Order and shipping path

`ToolsPath` lazily obtains the main model through `GraphDeps.model("main")`.
It binds three read-only tools: `get_order`, `list_recent_orders`, and `get_tracking`.
Each tool closes over the trusted `ConversationState.customer_id`.
The schemas do not expose customer identity. Unexpected identity arguments are ignored;
the model cannot choose the customer used by `OrderService`.
The recent-order limit comes from `orders.recent_limit`, not model arguments.
Missing customer identity produces a handoff before model creation.

The model receives the rewritten query and the current turn's tool results.
It must read facts before answering, and list recent orders when an id is ambiguous.
An answer without a successful current-turn lookup, after an unresolved tool error,
or with empty text becomes a handoff. Final prose is still model-generated:
the prompt restricts it to tool facts, but semantic faithfulness is not yet measured.
A missing shipment is a successful null result, not a fabricated delivery status.
No tool writes refunds, changes orders, or contacts a carrier.

`agent.max_steps` bounds model iterations, including a final answer iteration.
`agent.max_tool_calls_per_step` also bounds tool fan-out within each iteration.
Consecutive errors are counted across calls, including calls in the same response.
A successful call resets that streak. `agent.max_consecutive_tool_errors` triggers
the shared tool-error handoff. Exhausting the loop triggers the step-cap handoff.
Provider failures also produce a handoff. Exception bodies are not logged or exposed.

Every executed tool call/result adds a bounded trace entry. Traces retain the tool
name, accepted order argument, and a shortened result. Forged customer arguments
are excluded. Full successful facts are retained in `order_context` by tool name.
Internal model/tool messages stay local to the loop; only the final reply enters
public conversation history. Every turn resets counters, context, and old handoffs.

## Human requests, complaints, and fixed replies

`talk_to_human` creates a handoff immediately inside the tools node without a
main-model call. The fixed-reply node uses local greeting, thanks, goodbye,
capabilities, and fallback templates without creating or invoking a model.
These guarantees concern the path nodes: the full graph still classifies each
turn with the fast model and rewrites follow-ups, as introduced in commit 09.

The complaint node asks the fast model for at most two acknowledgement sentences,
then always appends a handoff template. Empty, overlong, or obviously promissory
acknowledgements fall back to a local apology. The conservative text filter is
not a semantic safety guarantee; output guardrails belong to later commits.
The acknowledgement limit excludes the separately appended handoff sentence.

## Shared handoff record

`HandoffPayload` validates the reason, conversation (including the final reply),
rewritten query, intent, retrieval snapshot, order context, and UTC creation time.
It supports JSON round trips and graph checkpoint serialization.
The record is a state payload, not a persisted human queue or confirmed delivery
to an operator. The operational handoff loop belongs to phase 2.
Caller-supplied customer and thread ids remain trusted inputs; authentication
and customer/thread ownership enforcement are not implemented here.

## Local CLI

Configure `.env` with the LLM provider, fast/main model names, and provider key.
Use `make data-orders` only when intentionally rebuilding the mock database;
it resets existing mock data and pending requests.

```sh
make chat CUSTOMER=CUST-0001
make chat CUSTOMER=CUST-0001 Q="Where is my order ORD-000009?"
```

The prompt's example `1042` is absent from the seed. The named delayed-tracking
case is `ORD-000009`, owned by `CUST-0001`. Use exact ids from the seed or recent
order lookup. The CLI creates a fresh customer-prefixed thread per invocation;
interactive turns share that thread. `/quit` exits.

Offline tests use deterministic model fakes and temporary seeded SQLite databases.
The CLI one-shot test exercises the real graph and service with injected models.
Real-provider acceptance and task-quality metrics must be recorded separately;
offline fixture checks do not establish natural-language task success or safety.
