from .memory import MemoryBackend

DATABASE = None


def get_database():
    global DATABASE
    if DATABASE:
        return DATABASE

    # Default to memory for now. We can add other backends when needed
    DATABASE = MemoryBackend()
    return DATABASE
