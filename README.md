# fractale-mcp

> Agentic state-machine orchestrator to support MCP Tools and Science

[![PyPI version](https://badge.fury.io/py/fractale-mcp.svg)](https://badge.fury.io/py/fractale-mcp)

## Design

We create a robust and asynchronous server that can register and load tools of interest. The project here initially contained two "buckets" of assets: tools (functions, prompts, resources) and orchestration (agent frameworks and backends paired with models). Those are now (for the most part) separated into modular projects, and tools are added as needed:

- [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP tools for Flux Framework
- [hpc-mcp](https://github.com/converged-computing/hpc-mcp): HPC tools for a larger set of HPC and converged computing use cases.

### Abstractions

The library here has the following abstractions.

- **Plan** is the YAML manifest that any agent can read and deploy. ([fractale/core/plan](fractale/core/plan))
- **Engine**: The orchestration engine (native state machine) that instantiates agents ([fractale/engines/native](fractale/engines/native))
- **Agents**: are independent units of a state machine, a sub- or helper- agent that can be run under a primary orchestrating (state machine) agent. Optional agents that are exposed to the LLM as possible steps are under ([fractale/agents](fractale/agents)), and agents that are essential to the top level orchestration are part of [fractale/engines/native/agent](fractale/engines/native/agent).

### Environment

The following variables can be set in the environment.

| Name | Description | Default       |
|-------|------------|---------------|
| `FRACTALE_MCP_PORT` | Port MCP server is on, if using http variant | 8089 |
| `FRACTALE_MCP_TOKEN` | Token for server | unset |
| `FRACTALE_LLM_PROVIDER` | LLM Backend to use (gemini, openai, llama) | gemini |
| `OPENAI_API_KEY` | API Key for an OpenAI model | unset |
| `OPENAI_BASE_URL` | Base url for OpenAI | unset |

Note that for provider, you can also designate on the command line. The default is Gemini (`gemini`). To change:


```bash
fractale agent --backend openai ./examples/plans/transform-retry.yaml
```

### Agents

The `fractale agent` command provides means to run build, job generation, and deployment agents.
In our [first version](https://github.com/compspec/fractale), an agent corresponded to a kind of task (e.g., build). For this refactored version, the concept of an agent is represented in a prompt or persona, which can be deployed by a generic MCP agent with some model backend (e.g., Gemini, Llama, or OpenAI). For the framework, we were prototyping a state machine (native) approach. I started testing LangChain and AutoGen but found the churn and lack of transparency annoying.

## Usage

### Server

Let's install [mcp-server](https://github.com/converged-computing/mcp-server) to start a server with the functions we need.

```bash
pip install --break-system-packages git+https://github.com/converged-computing/mcp-server.git#egg=mcp-serve
```

#### Dependencies

To prototype with Flux, open the code in the devcontainer. Install the library and start a flux instance.

```bash
pip install -e .[all] --break-system-packages
pip install flux-mcp hpc-mcp IPython --break-system-packages
flux start
```

#### Joke Example

Let's ask Gemini to tell us a joke. In one terminal:


```bash
mcpserver start --config ./examples/servers/run-job.yaml
```


```bash
fractale prompt Tell me a joke, and give me choices about the category.
```

#### Flux JobSpec Translation

We will need to start the server and add the validation functions and prompt. Start the server with the functions and prompt we need:

```bash
mcpserver start --config ./examples/servers/flux-gemini.yaml
```

**State Machine**

Note that this needs to be run in an environment with Flux. I run both in the DevContainer. In a different terminal, export the same `FLUX_URI` from where your server is running. Ensure your credentials are exported.

```bash
export GEMINI_API_TOKEN=xxxxxxxxxx
```

And then:

```bash
fractale agent ./examples/plans/transform-retry.yaml
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

**State Machine**

```bash
# In the other, run the plan
fractale agent ./examples/plans/build-lammps.yaml
```

This works very well in Google Cloud (Gemini). I am not confident our on-premises models will easily choose the right tool. Hence the next design.
The design is simple in that each agent is responding to state of error vs. success. In the [first version](https://github.com/compspec/fractale) of our library, agents formed a custom graph. In this variant, we refactor to use MCP server tools. It has the same top level design with a manager, but each step agent is like a small state machine governed by an LLM with access to MCP tools and resources.

### Design Choices

Here are a few design choices (subject to change, of course). I am starting with re-implementing our fractale agents with this framework. For that, instead of agents being tied to specific functions (as classes on their agent functions) we will have a flexible agent class that changes function based on a chosen prompt. It will use mcp functions, prompts, and resources. In addition:

- Tools hosted here are internal and needed for the library. E.g, we have a prompt that allows getting a final status for an output, in case a tool does not do a good job.
- For those hosted here, we don't use mcp.tool (and associated functions) directly, but instead add them to the mcp manually to allow for dynamic loading.
- We are currently focused on autogen (and the others, langchain and native, will need updates)
- Tools that are more general are provided under extral libraries (e.g., flux-mcp and hpc-mcp)
- The function docstrings are expose to the LLM (so write good ones!)
- We can use mcp.mount to extend a server to include others, or the equivalent for proxy (I have not tested this yet).
- Async is annoying but I'm using it. This means debugging is largely print statements and not interactive.
- We use [mcp-server](https://github.com/converged-computing/mcp-server) as the MCP server.


## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
