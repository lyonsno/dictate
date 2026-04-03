import json


def test_build_openai_payload_maps_model_and_messages():
    import gemini_shim

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": "previous"}]},
        ]
    }

    payload = gemini_shim.build_openai_payload(
        "/v1beta/models/gemini-2.5-flash:generateContent",
        body,
    )

    assert payload["model"] == "Qwen3p5-122B-A10B-mlx-mixedp"
    assert payload["stream"] is False
    assert payload["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "previous"},
    ]


def test_translate_openai_response_wraps_gemini_candidate_shape():
    import gemini_shim

    translated = gemini_shim.translate_openai_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "hello from local model",
                    }
                }
            ]
        }
    )

    assert translated["response"]["candidates"][0]["content"]["role"] == "model"
    assert translated["response"]["candidates"][0]["content"]["parts"] == [
        {"text": "hello from local model"}
    ]
    assert translated["response"]["candidates"][0]["finishReason"] == "STOP"


def test_iter_gemini_stream_events_merges_reasoning_and_content():
    import gemini_shim

    lines = [
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "thinking ",
                            "content": "done",
                        }
                    }
                ]
            }
        ),
        "data: " + json.dumps({"choices": [{"finish_reason": "stop"}]}),
        "data: [DONE]",
    ]

    chunks = list(gemini_shim.iter_gemini_stream_events(lines))

    first = chunks[0].decode("utf-8")
    second = chunks[1].decode("utf-8")
    final = chunks[-1].decode("utf-8")

    assert '"text": "thinking done"' in first
    assert '"finishReason": "STOP"' in second
    assert '"finishReason": "STOP"' in final
