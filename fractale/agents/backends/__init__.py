BACKENDS = {}

# Attempt import of each
# This is ugly, but it works!
try:
    from .gemini import GeminiBackend

    BACKENDS["gemini"] = GeminiBackend
except ImportError:
    pass

try:
    from .openai import OpenAIBackend

    BACKENDS["openai"] = OpenAIBackend
except ImportError:
    pass

try:
    from .llama import LlamaBackend

    BACKENDS["llama"] = LlamaBackend
except ImportError:
    pass
