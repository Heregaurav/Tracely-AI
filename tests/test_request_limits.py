"""Exercise the ASGI body boundary before downstream multipart/JSON parsing."""
import asyncio

from src.api.limits import RequestBodyLimit


def exercise(chunks, headers=()):
    called = []
    sent = []

    async def downstream(scope, receive, send):
        message = await receive()
        called.append(message["body"])

    async def run():
        iterator = iter(chunks)

        async def receive():
            return next(iterator)

        async def send(message):
            sent.append(message)

        await RequestBodyLimit(downstream, max_bytes=8)(
            {"type": "http", "path": "/api/inference/import", "headers": headers},
            receive,
            send,
        )

    asyncio.run(run())
    return called, sent


def test_declared_oversize_rejected_before_body_is_read():
    called, sent = exercise([], [(b"content-length", b"9")])
    assert not called
    assert sent[0]["status"] == 413


def test_streamed_oversize_rejected_without_content_length():
    called, sent = exercise([
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"6789", "more_body": False},
    ])
    assert not called
    assert sent[0]["status"] == 413


def test_exact_boundary_reaches_downstream_with_original_bytes():
    called, sent = exercise([
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"678", "more_body": False},
    ])
    assert called == [b"12345678"]
    assert not sent


def test_invalid_content_length_rejected():
    for value in (b"-1", b"invalid"):
        called, sent = exercise([], [(b"content-length", value)])
        assert not called
        assert sent[0]["status"] == 400
