__version__ = "0.0.1"
AUTHOR = "Vanessa Sochat"
AUTHOR_EMAIL = "vsoch@users.noreply.github.com"
NAME = "fractale"
PACKAGE_URL = "https://github.com/converged-computing/fractale"
KEYWORDS = "cluster, orchestration, transformer, jobspec, flux"
DESCRIPTION = "Agentic framework for HPC orchestration"
LICENSE = "LICENSE"


################################################################################
# TODO vsoch: refactor this to use newer pyproject stuff.

INSTALL_REQUIRES = (
    ("jsonschema", {"min_version": None}),
    ("Jinja2", {"min_version": None}),
    ("uvicorn", {"min_version": None}),
    ("mcp", {"min_version": None}),
    ("fastmcp", {"min_version": None}),
    ("fastapi", {"min_version": None}),
    # Yeah, probably overkill, just being used for printing the scripts
    ("rich", {"min_version": None}),
    # Rule and logic expression matching
    ("boolia", {"min_version": None}),
    # We can likely eliminate these.
    ("textual", {"min_version": None}),
    ("nest_asyncio", {"min_version": None}),
)

OPENAI_REQUIRES = (("openai", {"min_version": None}),)
GOOGLE_REQUIRES = (("google-genai", {"min_version": None}),)
TESTS_REQUIRES = (("pytest", {"min_version": "4.6.2"}),)

# The amount of deps / libs here is absolutely ridiculous.
AUTOGEN_REQUIRES = (
    ("ag2[openai]", {"min_version": None}),
    ("ag2[gemini]", {"min_version": None}),
    ("autogen-agentchat", {"min_version": None}),
    ("autogen-agentchat[gemini]", {"min_version": None}),
    ("autogen-ext", {"min_version": None}),
    ("autogen-ext[google]", {"min_version": None}),
    ("google-genai", {"min_version": None}),
    ("vertexai", {"min_version": None}),
)

LANGCHAIN_REQUIRES = (
    ("langchain-core", {"min_version": None}),
    ("langchain-openai", {"min_version": None}),
    ("langchain-google-genai", {"min_version": None}),
    ("langgraph", {"min_version": None}),
)


INSTALL_REQUIRES_ALL = (
    INSTALL_REQUIRES
    + TESTS_REQUIRES
    + GOOGLE_REQUIRES
    + OPENAI_REQUIRES
    + AUTOGEN_REQUIRES
    + LANGCHAIN_REQUIRES
)
