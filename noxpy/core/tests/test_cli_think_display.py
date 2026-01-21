from central.cli.app import _extract_visible_reply


def test_extract_visible_reply_removes_think_block():
    visible, had_think = _extract_visible_reply("<think>plan</think>Final answer")
    assert visible == "Final answer"
    assert had_think is True


def test_extract_visible_reply_without_think():
    visible, had_think = _extract_visible_reply("Just answer")
    assert visible == "Just answer"
    assert had_think is False

