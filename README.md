# fractale-mcp

> Agentic Server to support MCP Tools and Science

[![PyPI version](https://badge.fury.io/py/fractale-mcp.svg)](https://badge.fury.io/py/fractale-mcp)

## Design

We create a robust and asynchronous server that can register and load tools of interest. The project here initially contained two "buckets" of assets: tools (functions, prompts, resources) and orchestration (agent frameworks and backends paired with models). Those are now (for the most part) separated into modular projects, and tools are added as needed:

- [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP tools for Flux Framework
- [hpc-mcp](https://github.com/converged-computing/hpc-mcp): HPC tools for a larger set of HPC and converged computing use cases.

### Abstractions

The library here has the following abstractions.

- **Plan** is the YAML manifest that any agent can read and deploy.
- **Engines**: The orchestration engine (native state machine, langchain, autogen) that instantiates agents.

### Environment

The following variables can be set in the environment.

| Name | Description | Default       |
|-------|------------|---------------|
| `FRACTALE_MCP_PORT` | Port MCP server is on, if using http variant | 8089 |
| `FRACTALE_MCP_TOKEN` | Token for server | unset |
| `FRACTALE_LLM_PROVIDER` | LLM Backend to use (gemini, openai, llama) | gemini |
| `OPENAI_API_KEY` | API Key for an OpenAI model | unset |
| `OPENAI_BASE_URL` | Base url for OpenAI | unset |

### Agents

The `fractale agent` command provides means to run build, job generation, and deployment agents.
In our [first version](https://github.com/compspec/fractale), an agent corresponded to a kind of task (e.g., build). For this refactored version, the concept of an agent is represented in a prompt or persona, which can be deployed by a generic MCP agent with some model backend (e.g., Gemini, Llama, or OpenAI).

## Usage

### Server

Let's install [mcp-server](https://github.com/converged-computing/mcp-server) to start a server with the functions we need.

```bash
pip install --break-system-packages git+https://github.com/converged-computing/mcp-server.git#egg=mcp-serve
```

### Docker Build

Let's test doing a build. I'm running this on my local machine that has Docker, and I'm using Gemini.

```bash
export GEMINI_API_TOKEN=xxxxxxxxxx
```

Also install the functions from [hpc-mcp](https://github.com/converged-computing/hpc-mcp):

```bash
pip install hpc-mcp --break-system-packages
pip install -e . --break-system-packages
```

Start the server with the functions and prompt we need:

```bash
mcpserver start --config ./examples/servers/docker-build.yaml
```

And then run the plan. Note that we are currently focusing on AutoGen.

**AutoGen**

```bash
# In the other, run the plan
fractale agent --engine autogen ./examples/plans/build-lammps.yaml
```

To use the state machine, remove the `--engine` flag. Add `langchain` for LangChain.
This works very well in Google Cloud (Gemini). I am not confident our on-premises models will easily choose the right tool. Hence the next design. If you define a `tool` section in any step, that will limit the selection of the LLM to JUST the tool you are interested in. We hope that this will work.

The design is simple in that each agent is responding to state of error vs. success. In the [first version](https://github.com/compspec/fractale) of our library, agents formed a custom graph. In this variant, we refactor to use MCP server tools. It has the same top level design with a manager, but each step agent is like a small state machine governed by an LLM with access to MCP tools and resources.

#### Flux JobSpec Translation

To prototype with Flux, open the code in the devcontainer. Install the library and start a flux instance.

```bash
pip install -e .[all] --break-system-packages
pip install flux-mcp IPython --break-system-packages
flux start
```

We will need to start the server and add the validation functions and prompt. Start the server with the functions and prompt we need:

```bash
mcpserver start --config ./examples/servers/jobspec.yaml
```

**AutoGen**

Note that this needs to be run in an environment with Flux. I run both in the DevContainer.

```bash
fractale agent --engine autogen ./examples/plans/transform-jobspec.yaml
```

### Design Choices

Here are a few design choices (subject to change, of course). I am starting with re-implementing our fractale agents with this framework. For that, instead of agents being tied to specific functions (as classes on their agent functions) we will have a flexible agent class that changes function based on a chosen prompt. It will use mcp functions, prompts, and resources. In addition:

- Each framework is (globally) an "engine" and this means the `Manager` class for each is under engine.py, since that is the entity running the show.
- Tools hosted here are internal and needed for the library. E.g, we have a prompt that allows getting a final status for an output, in case a tool does not do a good job.
- For those hosted here, we don't use mcp.tool (and associated functions) directly, but instead add them to the mcp manually to allow for dynamic loading.
- Tools that are more general are provided under extral libraries (e.g., flux-mcp and hpc-mcp)
- The function docstrings are expose to the LLM (so write good ones!)
- We can use mcp.mount to extend a server to include others, or the equivalent for proxy (I have not tested this yet).
- Async is annoying but I'm using it. This means debugging is largely print statements and not interactive.
- The backend of FastMCP is essentially starlette, so we define (and add) other routes to the server.


## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
