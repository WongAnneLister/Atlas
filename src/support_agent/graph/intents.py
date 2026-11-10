"""The single intent-to-path routing contract."""

from enum import StrEnum


class Intent(StrEnum):
    ORDER_STATUS = "order_status"
    SHIPPING_DELIVERY = "shipping_delivery"
    TALK_TO_HUMAN = "talk_to_human"
    PRODUCT_QUESTION = "product_question"
    POLICY_QUESTION = "policy_question"
    REFUND_REQUEST = "refund_request"
    RETURN_EXCHANGE = "return_exchange"
    COMPLAINT = "complaint"
    CHITCHAT_OTHER = "chitchat_other"


class Path(StrEnum):
    TOOLS = "A"
    KNOWLEDGE = "B"
    AFTER_SALES = "C"
    COMPLAINT = "D"
    FIXED = "E"


INTENT_TO_PATH: dict[Intent, Path] = {
    Intent.ORDER_STATUS: Path.TOOLS,
    Intent.SHIPPING_DELIVERY: Path.TOOLS,
    Intent.TALK_TO_HUMAN: Path.TOOLS,
    Intent.PRODUCT_QUESTION: Path.KNOWLEDGE,
    Intent.POLICY_QUESTION: Path.KNOWLEDGE,
    Intent.REFUND_REQUEST: Path.AFTER_SALES,
    Intent.RETURN_EXCHANGE: Path.AFTER_SALES,
    Intent.COMPLAINT: Path.COMPLAINT,
    Intent.CHITCHAT_OTHER: Path.FIXED,
}

PATH_NODES: dict[Path, str] = {
    Path.TOOLS: "tools",
    Path.KNOWLEDGE: "knowledge",
    Path.AFTER_SALES: "after_sales",
    Path.COMPLAINT: "complaint",
    Path.FIXED: "fixed",
}
