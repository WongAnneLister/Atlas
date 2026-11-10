"""Map inspected Bitext source labels to the supported workflow vocabulary."""

from support_agent.graph.intents import Intent

_ROWS: dict[str, tuple[Intent, str]] = {
    "cancel_order": (Intent.ORDER_STATUS, "An action on a particular order needs order context."),
    "change_order": (Intent.ORDER_STATUS, "Changing an order belongs with order tools."),
    "check_invoice": (Intent.ORDER_STATUS, "Inspecting an invoice needs order-specific facts."),
    "get_invoice": (Intent.ORDER_STATUS, "Retrieving an invoice needs order-specific facts."),
    "place_order": (Intent.ORDER_STATUS, "Order creation requests use the order-action route."),
    "track_order": (Intent.ORDER_STATUS, "The user requests the current order status."),
    "change_shipping_address": (
        Intent.SHIPPING_DELIVERY,
        "Address changes are delivery-specific requests.",
    ),
    "delivery_options": (
        Intent.SHIPPING_DELIVERY,
        "The user asks about delivery methods or areas.",
    ),
    "delivery_period": (Intent.SHIPPING_DELIVERY, "The user asks when delivery is expected."),
    "set_up_shipping_address": (
        Intent.SHIPPING_DELIVERY,
        "The request supplies a delivery address.",
    ),
    "contact_customer_service": (
        Intent.TALK_TO_HUMAN,
        "The request seeks customer-service contact.",
    ),
    "contact_human_agent": (Intent.TALK_TO_HUMAN, "The request explicitly seeks a person."),
    "get_refund": (Intent.REFUND_REQUEST, "The user seeks a refund action, not a general rule."),
    "track_refund": (Intent.REFUND_REQUEST, "Refund progress belongs with the refund sub-flow."),
    "check_cancellation_fee": (Intent.POLICY_QUESTION, "General cancellation charges are policy."),
    "check_payment_methods": (
        Intent.POLICY_QUESTION,
        "Accepted payment methods are general policy.",
    ),
    "check_refund_policy": (
        Intent.POLICY_QUESTION,
        "Refund eligibility and timing rules are policy.",
    ),
    "complaint": (Intent.COMPLAINT, "The user asks to file a complaint or claim."),
    "payment_issue": (Intent.COMPLAINT, "Payment-problem reports require complaint handling."),
    "create_account": (Intent.CHITCHAT_OTHER, "Account creation is outside the supported actions."),
    "delete_account": (Intent.CHITCHAT_OTHER, "Account deletion is outside the supported actions."),
    "edit_account": (Intent.CHITCHAT_OTHER, "Account editing is outside the supported actions."),
    "newsletter_subscription": (
        Intent.CHITCHAT_OTHER,
        "Newsletter management is outside the supported actions.",
    ),
    "recover_password": (
        Intent.CHITCHAT_OTHER,
        "Password recovery is outside the supported actions.",
    ),
    "registration_problems": (
        Intent.CHITCHAT_OTHER,
        "Registration troubleshooting is outside the supported actions.",
    ),
    "switch_account": (
        Intent.CHITCHAT_OTHER,
        "Account switching is outside the supported actions.",
    ),
    "review": (
        Intent.CHITCHAT_OTHER,
        "Inspected rows ask to submit neutral feedback, not complain.",
    ),
}

BITEXT_INTENT_MAP: dict[str, Intent] = {label: row[0] for label, row in _ROWS.items()}
MAPPING_REASONS: dict[str, str] = {label: row[1] for label, row in _ROWS.items()}


def mapping_markdown() -> str:
    lines = ["| Bitext label | Project intent | Reason |", "|---|---|---|"]
    for label, (intent, reason) in sorted(_ROWS.items()):
        lines.append(f"| `{label}` | `{intent.value}` | {reason} |")
    return "\n".join(lines)
