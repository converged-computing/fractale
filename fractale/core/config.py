import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider: str
    model_name: str
    api_key: str = None
    base_url: str = None

    @classmethod
    def from_context(cls, context: dict = None):
        """
        Extracts config from the Blackboard Context (YAML Inputs).
        """
        context = context or {}

        # The llm provider is the backend
        provider = context.get("backend") or os.environ.get("LLM_PROVIDER", "gemini")
        model = context.get("model") or os.environ.get("LLM_MODEL")

        # I'm not sure I like this approach yet. The model config here would discover
        # credentials from the environment each time is it init'd. Is that something
        # we can (and should) rely on? Are there any security issues?
        api_key = None
        base_url = None

        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL")
        elif provider == "llama":
            api_key = os.environ.get("LLAMA_API_KEY")
            base_url = os.environ.get("LLAMA_BASE_URL")
        elif provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")

        return cls(provider=provider.lower(), model_name=model, api_key=api_key, base_url=base_url)
