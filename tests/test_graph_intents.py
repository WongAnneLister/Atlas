from support_agent.graph.intents import INTENT_TO_PATH, PATH_NODES, Intent, Path


def test_all_nine_intents_have_one_of_five_routes() -> None:
    assert len(Intent) == 9
    assert len(Path) == 5
    assert set(INTENT_TO_PATH) == set(Intent)
    assert set(INTENT_TO_PATH.values()) == set(Path)
    assert set(PATH_NODES) == set(Path)
    assert len(set(PATH_NODES.values())) == 5


def test_routes_match_the_domain_contract() -> None:
    expected = {
        Path.TOOLS: {Intent.ORDER_STATUS, Intent.SHIPPING_DELIVERY, Intent.TALK_TO_HUMAN},
        Path.KNOWLEDGE: {Intent.PRODUCT_QUESTION, Intent.POLICY_QUESTION},
        Path.AFTER_SALES: {Intent.REFUND_REQUEST, Intent.RETURN_EXCHANGE},
        Path.COMPLAINT: {Intent.COMPLAINT},
        Path.FIXED: {Intent.CHITCHAT_OTHER},
    }
    for path, intents in expected.items():
        assert {intent for intent in Intent if INTENT_TO_PATH[intent] == path} == intents
