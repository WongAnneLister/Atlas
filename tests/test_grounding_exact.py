import pytest

from support_agent.grounding.exact import missing_literals


@pytest.mark.parametrize(
    ("claim", "evidence"),
    [
        ("The 30-day return window applies.", "Returns are accepted within 30 days."),
        ("Delivery takes 2 business days.", "Allow a 2-business-day delivery window."),
        ("The fee is $1,250.50.", "The fee is USD 1250.5."),
        ("The INR 349.00 fee applies.", "The fee is Rs. 349."),
        ("The discount is 5.5 percent.", "Get 5.50% off."),
        ("The model BHD-340/10 is covered.", "We cover model bhd340/10."),
        ("The weight is 1.25 kilograms.", "Weight: 1.250kg."),
        ("The motor draws 1600 watts.", "Motor rating: 1,600 W."),
        ("The display reads -2.5.", "Readout: \u22122.50."),
        ("There are 3 settings.", "There are 03 settings."),
        ("The fee is CAD 40.", "The fee is C$40."),
        ("Rate is up 5 percentage points.", "The rate rose 5 pp."),
        ("The limit is INR 100000.", "The limit is ₹1,00,000."),
        ("The balance is -$150.", "A USD -150 balance is recorded."),
    ],
)
def test_accepts_equivalent_literals(claim: str, evidence: str) -> None:
    assert missing_literals(claim, [evidence]) == ()


@pytest.mark.parametrize(
    ("claim", "evidence", "missing"),
    [
        ("The refund window is 30 days.", "Returns are allowed within 130 days.", "30 days"),
        ("Delivery takes 2 business days.", "Delivery takes 2 calendar days.", "2 business days"),
        ("Delivery takes 2 days.", "Delivery takes 2 hours.", "2 days"),
        ("The discount is 5 percent.", "The discount is $5.", "5 percent"),
        ("The fee is £5.", "The fee is €5.", "£5"),
        ("It costs Rs. 349.", "The item ID is 349.", "Rs. 349"),
        ("The discount is 4.50%.", "The discount is 4.05%.", "4.50%"),
        ("The weight is 1.25 kg.", "Weight: 1.25 pounds.", "1.25 kg"),
        ("This covers BHD340/10.", "This covers BHD340/100.", "BHD340/10"),
        ("The display reads -25.", "The display reads 25.", "-25"),
        ("There are 3 settings.", "The product ID is BHD3/10.", "3"),
        ("The discount is 5%.", "We show [5] discounts.", "5%"),
        ("The fee is CAD 40.", "The fee is USD 40.", "CAD 40"),
        ("The fee is USD 40.", "The fee is CAD $40.", "USD 40"),
        ("Rate is up 5%.", "The rate rose 5 percentage points.", "5%"),
        ("A1 is covered.", "Only A2 is covered.", "A1"),
        ("There are 50 modes.", "We show 5[1]0 modes.", "50"),
        ("The balance is -$150.", "A USD 150 balance is recorded.", "-$150"),
    ],
)
def test_exact_literals_preserve_values_qualifiers_and_model_identity(
    claim: str, evidence: str, missing: str
) -> None:
    assert missing_literals(claim, [evidence]) == (missing,)


def test_only_cited_text_can_cover_literals_and_chunks_do_not_join() -> None:
    assert missing_literals("There are 25 days.", ["Returns take 25", "days apply."]) == (
        "25 days",
    )
    assert missing_literals("The fee is $15 and the model is BHD340.", []) == ("$15", "BHD340")
    assert missing_literals("There are 2 modes and 3 nozzles.", ["There are 2 modes."]) == ("3",)
    assert missing_literals("A dryer is included.", ["No dryer is included."]) == ()


def test_multiple_missing_literals_keep_surface_order_without_duplicates() -> None:
    claim = "Model BHD340/10 costs $25 for 12 weeks, with $25 due up front."
    assert missing_literals(claim, ["Model BHD340/100 costs $30 for 12 months."]) == (
        "BHD340/10",
        "$25",
        "12 weeks",
    )
