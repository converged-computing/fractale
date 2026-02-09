import fractale.engines.native.backends as backends
from fractale.core.config import ModelConfig
from fractale.engines.base import AgentBase


class AgentBase(AgentBase):
    """
    State machine agent base
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_backend(self, context=None):
        """
        Create the backend from the model config.
        """
        cfg = ModelConfig.from_context(context)
        if cfg.provider not in backends.BACKENDS:
            raise ValueError(f"Provider '{cfg.provider}' not supported.")
        self.backend = backends.BACKENDS[cfg.provider](config=cfg)
