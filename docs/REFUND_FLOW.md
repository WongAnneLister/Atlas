# Refund and return flow

The flow keeps order facts and policy evidence in separate sources.

```mermaid
flowchart TD
    A[Refund or return request] --> B[Identify order]
    B -->|No verified id| C[Interrupt: order picker]
    C -->|Order id or none| B
    B -->|Owned order| D[Load OrderService facts]
    D --> E[Retrieve and rerank policy]
    E --> F{Evidence gate}
    F -->|Fail| H[Hand off: low evidence]
    F -->|Pass| G[Structured decision]
    G --> I{Code checks}
    I -->|Needs human| J[Hand off: policy review]
    I -->|Yes| K[Create pending review request]
    I -->|No| L[Explain with citations]
```

The graph pauses before reading an unclear order choice. `Command(resume=...)` continues the same thread.
The selected order must appear in the customer's recent orders.
The service checks ownership again before loading facts.

## Code checks

- A request needs a verified owned order and a passed evidence gate.
- Every decision reason needs a valid citation marker that points to retrieved policy.
- A `yes` decision needs valid, non-refunded item ids.
- A final-sale `yes` decision needs cited policy text mentioning final sale.
- Non-delivered statuses need cited policy text naming that status.
- Invalid citations or uncertain structured output become `needs_human`.
- Approved requests are stored as `pending_review`; no money moves.

## Seed edge cases

These are expected decision paths for the fixed demo data. Policy evidence still controls each run.

| Case | Order | Expected path |
|---|---|---|
| delivered_5_days | ORD-000001 | eligible if policy supports the window |
| delivered_29_days | ORD-000002 | eligible if policy supports the window |
| delivered_31_days | ORD-000003 | no if the window is thirty days |
| delivered_90_days | ORD-000004 | no if the window is thirty days |
| final_sale | ORD-000005 | needs human unless final-sale policy is cited |
| coupon | ORD-000006 | needs human if coupon policy is unclear |
| partially_refunded | ORD-000007 | needs human unless remaining items are explicit |
| cancelled | ORD-000008 | needs human unless cancellation refund policy is cited |
| refunded | ORD-000014 | needs human because all quantities are already refunded |
| pending, paid, shipped, in_transit | ORD-000010–013 | needs human unless policy covers this status |
