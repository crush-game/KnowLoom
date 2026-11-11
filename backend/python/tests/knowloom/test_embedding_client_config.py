from app.knowloom.config import KnowLoomSettings
from app.knowloom.indexes import embedding as embedding_module
from app.knowloom.indexes.embedding import KnowLoomEmbeddingClient


class RecordingOpenAI:
    kwargs = {}

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs


def test_embedding_client_uses_embedding_specific_credentials(monkeypatch) -> None:
    monkeypatch.setattr(embedding_module, "AsyncOpenAI", RecordingOpenAI)
    config = KnowLoomSettings(
        _env_file=None,
        api_base_url="https://chat.example/v1",
        api_key="chat-key",
        embedding_api_base_url="https://embed.example/v1",
        embedding_api_key="embedding-key",
        embedding_model="text-embedding-3-large",
    )

    KnowLoomEmbeddingClient(config)

    assert RecordingOpenAI.kwargs["base_url"] == "https://embed.example/v1"
    assert RecordingOpenAI.kwargs["api_key"] == "embedding-key"


def test_embedding_client_falls_back_to_chat_credentials_when_embedding_credentials_are_empty(monkeypatch) -> None:
    monkeypatch.setattr(embedding_module, "AsyncOpenAI", RecordingOpenAI)
    config = KnowLoomSettings(
        _env_file=None,
        api_base_url="https://chat.example/v1",
        api_key="chat-key",
        embedding_model="text-embedding-3-large",
    )

    KnowLoomEmbeddingClient(config)

    assert RecordingOpenAI.kwargs["base_url"] == "https://chat.example/v1"
    assert RecordingOpenAI.kwargs["api_key"] == "chat-key"



if __name__ == "__main__":
    pass

