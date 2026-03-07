from fractale.logger import logger

from .memory import FilesystemBackend, MemoryBackend

DATABASE = None


def get_database(kind="memory"):
    """
    Default to memory for now - we will get back result.
    """
    global DATABASE
    if DATABASE:
        return DATABASE

    # Default to memory for now. We can add other backends when needed
    if kind == "memory":
        logger.info("🌛 memory database")
        DATABASE = MemoryBackend()
    else:
        logger.info("🗄️ filesystem database")
        DATABASE = FilesystemBackend()
    return DATABASE
