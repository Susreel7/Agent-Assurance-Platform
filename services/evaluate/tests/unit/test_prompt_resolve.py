from evaluate.worker.prompt_resolve import apply_example_to_messages


def test_apply_example_variables() -> None:
    msgs = [{"role": "user", "content": "Hello {{name}}"}]
    out = apply_example_to_messages(msgs, {"name": "world"})
    assert out[0]["content"] == "Hello world"
