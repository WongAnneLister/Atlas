from eval.memory_long_eval import recall_scores


def test_a_memory_in_the_prompt_is_not_counted_as_used_unless_the_reply_uses_it() -> None:
    used, loaded, redundant = recall_scores(
        "Which model do you own?", "Owns a Philips W40.", [], ["w40"]
    )
    assert (used, loaded) == (False, True)
    assert redundant

    used, loaded, _ = recall_scores(
        "Your W40 has a two-year warranty.", "", ["Owns a W40"], ["W40"]
    )
    assert (used, loaded) == (True, True)
