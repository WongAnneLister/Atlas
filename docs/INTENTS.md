# Intent classification and fixed routing

The workflow is `START → rewrite → classify → one path stub → END`.
The classifier returns an intent and confidence. Python selects the route from
`INTENT_TO_PATH` in `src/support_agent/graph/intents.py`; no model selects a node.
The paths remain placeholders in this commit. They cannot answer policy questions,
perform order actions, approve refunds, or bypass the later evidence gate.

| Project intent | Path | Meaning |
|---|---|---|
| `order_status` | A: tools | An order's status, creation, change, cancellation, or invoice |
| `shipping_delivery` | A: tools | Delivery choices, timing, or delivery addresses |
| `talk_to_human` | A: tools | Contact customer service or request a human |
| `product_question` | B: knowledge | Product features, specifications, compatibility, or use |
| `policy_question` | B: knowledge | General store rules, fees, refund eligibility, or payment methods |
| `refund_request` | C: after-sales | Start or track an individual money-back request |
| `return_exchange` | C: after-sales | Arrange or track returning, replacing, or exchanging an item |
| `complaint` | D: complaint | Dissatisfaction, a complaint, or a payment-problem report |
| `chitchat_other` | E: fixed | Greetings, unrelated requests, or unsupported account/review actions |

An intent names the requested workflow, not a promise that its tools support every
action. Invoice download and order creation, for example, still need real tool
capabilities before the agent can execute them. Those capabilities are outside
this skeleton commit.

## Rewrite, classification, and confidence

The first human turn skips rewriting and keeps its original text. Follow-ups use
at most `intent.rewrite_history_turns` human turns, including the current turn,
with the assistant context following those turns. The prompt asks the fast model
to keep self-contained requests unchanged and resolve references without adding
facts. Empty output or a rewrite error keeps the original request.

`Classifier` uses `with_structured_output` with a Pydantic intent/confidence schema.
Its prompt has separately authored examples for every intent. Examples are checked
against the frozen retrieval questions; benchmark construction also excludes their
normalized exact text. Parsing, validation, and invocation failures return
`chitchat_other` with zero confidence and a failure flag. Logs contain the exception
type instead of raw customer text or provider error bodies.

`intent.min_confidence` only sets `intent_low_confidence` on knowledge and after-sales
requests. A low-confidence prediction still follows its mapped route. This value
has not been calibrated as an answer-safety threshold. The future evidence gate
must independently check evidence before either route can produce an answer.
This commit's stubs always return `[path X not implemented]`.

## Bitext mapping

I inspected real `instruction` values, not only source label names. Neutral `review`
rows ask how to submit feedback; they do not establish dissatisfaction. Unsupported
account, password, registration, and newsletter actions therefore share the fixed
path. Explicit negative feedback remains `complaint` in the classifier prompt.
Payment-problem reports go to complaint handling because no payment-repair tool
exists in the supported domain.

The mapping is implemented once in `src/support_agent/data/intent_map.py`.

| Bitext label | Project intent | Reason |
|---|---|---|
| `cancel_order` | `order_status` | An action on a particular order needs order context. |
| `change_order` | `order_status` | Changing an order belongs with order tools. |
| `change_shipping_address` | `shipping_delivery` | Address changes are delivery-specific requests. |
| `check_cancellation_fee` | `policy_question` | General cancellation charges are policy. |
| `check_invoice` | `order_status` | Inspecting an invoice needs order-specific facts. |
| `check_payment_methods` | `policy_question` | Accepted payment methods are general policy. |
| `check_refund_policy` | `policy_question` | Refund eligibility and timing rules are policy. |
| `complaint` | `complaint` | The user asks to file a complaint or claim. |
| `contact_customer_service` | `talk_to_human` | The request seeks customer-service contact. |
| `contact_human_agent` | `talk_to_human` | The request explicitly seeks a person. |
| `create_account` | `chitchat_other` | Account creation is outside the supported actions. |
| `delete_account` | `chitchat_other` | Account deletion is outside the supported actions. |
| `delivery_options` | `shipping_delivery` | The user asks about delivery methods or areas. |
| `delivery_period` | `shipping_delivery` | The user asks when delivery is expected. |
| `edit_account` | `chitchat_other` | Account editing is outside the supported actions. |
| `get_invoice` | `order_status` | Retrieving an invoice needs order-specific facts. |
| `get_refund` | `refund_request` | The user seeks a refund action, not a general rule. |
| `newsletter_subscription` | `chitchat_other` | Newsletter management is outside the supported actions. |
| `payment_issue` | `complaint` | Payment-problem reports require complaint handling. |
| `place_order` | `order_status` | Order creation requests use the order-action route. |
| `recover_password` | `chitchat_other` | Password recovery is outside the supported actions. |
| `registration_problems` | `chitchat_other` | Registration troubleshooting is outside the supported actions. |
| `review` | `chitchat_other` | Inspected rows ask to submit neutral feedback, not complain. |
| `set_up_shipping_address` | `shipping_delivery` | The request supplies a delivery address. |
| `switch_account` | `chitchat_other` | Account switching is outside the supported actions. |
| `track_order` | `order_status` | The user requests the current order status. |
| `track_refund` | `refund_request` | Refund progress belongs with the refund sub-flow. |

Mapped source labels are draft gold labels, not individual human annotations.
Some source utterances remain ambiguous, particularly general rules versus
individual actions. An eventual label correction must be a separate, explained
change; model misses must not be relabeled to improve this report.

## Checkpoint lifetime and calls

`GraphDeps` accepts injected fast models, retrievers, and order services. The latter
dependencies are reserved for the later path implementations. All real models
still come from `get_chat_model` in `llm.py`.

The default checkpointer is `InMemorySaver`. Set `graph.checkpoint_backend` to
`sqlite` and `graph.checkpoint_path` to use the optional SQLite saver. Keep the
dependency owner open while using the graph; exiting it closes its connections.
The `sqlite` extra is needed for this backend. `make setup` installs all extras.

```python
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from support_agent.config import get_settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps

load_dotenv(".env")
with GraphDeps(settings=get_settings()) as deps:
    graph = build_graph(deps)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Where is my order?")], "customer_id": "demo-customer"},
        {"configurable": {"thread_id": "demo-customer-session"}},
    )
    assert result["trace"] == ["rewrite", "classify", "tools"]
```

Messages persist through the message reducer. Stubs append their assistant reply;
the trace accumulates visited nodes across turns. Rewrite clears prior per-turn
retrieval, gate, order, handoff, answer, citation, and classification fields.
Thread ids must be assigned by a trusted caller and scoped to the customer.
Authentication and customer/thread ownership enforcement are not implemented here.

## Reproduce the experiment

```bash
make setup
make data-download
make data-docs
make eval-build
# Configure .env with LLM_PROVIDER, LLM_FAST_MODEL and the selected provider key.
make eval-intent-build
make eval-intent
```

The intent CLI loads `.env`; credentials never enter configuration hashes or
reports. DeepSeek support is available through the `deepseek` extra. Provider
options, such as disabling thinking, use `SUPPORT_AGENT__LLM__MODEL_KWARGS` JSON.
Model names remain environment/configuration values, not constants in source.

The committed `eval/drafts/intent_extra.yaml` contains separately authored greetings
and frozen model-drafted return requests. `make eval-intent-draft` performs the
one-time generation and refuses to overwrite existing return drafts. Reproduction
uses the committed drafts without another generation call.

Benchmark construction reserves a stable hash-based Bitext holdout, removes
normalized exact duplicates, prompt examples, conflicting mapped labels, and
Bitext utterances already used in retrieval questions. Product extras come only
from retrieval dev questions. Sampling balances target intents and their source
label buckets. Small pools remain small instead of duplicating questions.

The loader verifies the selected items, raw data, frozen retrieval questions,
drafts, prompt, mapping, normalization helpers, input schema, and sampling settings
before inference. Prediction caches also bind execution code, configuration,
provider endpoint, model alias, and runtime versions. A cache hit preserves the
original latency. Use `make eval-intent EVAL_INTENT_ARGS=--report-only` to regenerate
the report from the saved local run without calling a model.

Inputs, review text, and prediction caches remain ignored local artifacts.
The committed report contains metrics, labels, provenance, and source counts.
Full results: `eval/reports/intent.md`.

## Measurement limits

This benchmark has no human-reviewed intent annotations. Product extras reuse the
retrieval dev split, and return drafting shares a provider with the classifier.
Exact duplicates are excluded, but near-paraphrases can cross the Bitext partition.
Published Bitext typos and placeholder tokens remain in the classification inputs.
Source balancing also differs from the natural distribution of customer traffic.
These results measure first-turn classification and route mapping, not multi-turn
rewrite quality, successful actions, answer quality, or no-answer false acceptance.
