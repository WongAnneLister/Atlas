from support_agent.orders.models import CustomerSummary


def test_parity_detects_a_different_customer(seeded) -> None:
    from eval.orders_parity import compare_orders

    settings, service = seeded
    assert compare_orders(service, service, settings.orders.n_orders) == (4, 30, [])

    class RenamedCustomer:
        def list_customers(self, limit: int) -> list[CustomerSummary]:
            return [CustomerSummary(customer_id="CUST-0001", name="Different name")]

    _, _, differences = compare_orders(service, RenamedCustomer(), settings.orders.n_orders)
    assert differences == ["customers"]
