# fractale-mcp

> Agentic state-machine orchestrator to support MCP Tools and Science

[![PyPI version](https://badge.fury.io/py/fractale-mcp.svg)](https://badge.fury.io/py/fractale-mcp)

## Design

We create a robust and asynchronous orchestrator for scientific workloads. It interacts with an [mcp-server](https://github.com/converged-computing/mcp-server) to register and load tools of interest. Tools of interest come from:

- [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP tools for Flux Framework
- [hpc-mcp](https://github.com/converged-computing/hpc-mcp): HPC tools for a larger set of HPC and converged computing use cases.

### Abstractions

The library here has the following abstractions.

- **Plan**: a YAML, human generated manifest that any agent can read and deploy. ([fractale/core/plan](fractale/core/plan))
- **Step**: Units of work in a plan. A step can be of type:
  - **plan**: An instruction to go to a manager to generate a larger plan
  - **agen**t: a sub-agent task that is a specialized expert at a specific function. Sub-agents call tools, prompts, and other sub-agents (and can recurse)
  - **tool**: an explicit tool call that includes inputs and outputs.
  - **prompt**: an explicit prompt endpoint that includes inputs, and an output prompt for an LLM
- **Engine**: The orchestration engine (native state machine) that instantiates agents ([fractale/engines/native](fractale/engines/native))
- **Agents**: are independent units of a state machine, a sub- or helper- agent that can be run under a primary orchestrating (state machine) agent. Optional agents that are exposed to the LLM as possible steps are under ([fractale/agents](fractale/agents)), and agents that are essential to the top level orchestration are part of [fractale/engines/native/agent](fractale/engines/native/agent).

### Client

The client (high level) includes these calls:

```bash
# Run a specific, human generated plan
fractale run ./examples/plans/<plan.yaml>

# Run a specific sub-agent, first discovering and inspecting the environment to generate a more detailed prompt for it.
fractale agent optimize <Describe high level optimization task>

# Ask a random task (not necessarily an expert at anything, but access to all tools)
# This is a convenience wrapper to calling fractale agent ask_question
fractale prompt <General task to use server tools and prompts>

# Show all sub-agents available
fractale list

# Come up with plan for larger state machine
fractale plan <Describe high level general task>
```

### Environment

The following variables can be set in the environment.

| Name | Description | Default       |
|-------|------------|---------------|
| `FRACTALE_MCP_PORT` | Port MCP server is on, if using http variant | 8089 |
| `FRACTALE_MCP_TOKEN` | Token for server | unset |
| `FRACTALE_LLM_PROVIDER` | LLM Backend to use (gemini, openai, llama) | gemini |
| `OPENAI_API_KEY` | API Key for an OpenAI model | unset |
| `OPENAI_BASE_URL` | Base url for OpenAI | unset |
| `GEMINI_API_KEY` | API key to use Google Gemini |

Note that for provider, you can also designate on the command line. The default is Gemini (`gemini`). To change:


```bash
fractale run --backend openai ./examples/plans/transform-retry.yaml
```

### Agents

The `fractale agent` command provides means to request orchestration by a sub-agent. A sub-agent is an independent expert that is given access to all MCP endpoints and can orchestrate calls and user interaction to get to a desired outcome. Currently, sub-agent calls are passed through a manager that first inspects the environment to discover resources (compute, software, etc.) and come up with a scoped plan. This may change in the future.

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
pip install flux-mcp hpc-mcp[all] IPython --break-system-packages
flux start
```

Note that this needs to be run in an environment with Flux. I run both in the DevContainer. In a different terminal, export the same `FLUX_URI` from where your server is running. Ensure your credentials are exported.

```bash
export GEMINI_API_TOKEN=xxxxxxxxxx
```

#### Joke Example

Let's ask Gemini to tell us a joke. In one terminal:


```bash
mcpserver start --config ./examples/servers/run-job.yaml
```

```bash
fractale prompt Tell me a joke, and give me choices about the category.
```

#### Result Parser

Let's do an example where we add a one-off, on the fly tool, which is like a local registry. We can start an mcpserver in one terminal:


```bash
mcpserver start --config ./examples/servers/run-job.yaml
```

And then run fractale with our local tool defined (`-r` means registry to add):

```bash
fractale prompt -r ./examples/registry/parser-agents.yaml Write me a flux job that tells a joke, and then ask the result parser tool to derive a regular expression for the punchline.
```

#### LAMMPS Run

This requires LAMMPS (or similar) installed, and running a set of tools that include a database and the optimization agent.

```bash
mcpserver start --config ./examples/servers/run-job.yaml
fractale prompt -r ./examples/registry/analysis-agents.yaml Discover resources and run a LAMMPS job "lmp" with Flux using data in /code. Use the optimization agent step to optimize lammps, and keep retrying the run until the agent decides to stop.
```

#### Flux JobSpec Translation

We will need to start the server and add the validation functions and prompt. Start the server with the functions and prompt we need:

```bash
mcpserver start --config ./examples/servers/flux-gemini.yaml
```

And then:

```bash
fractale agent ./examples/plans/transform-retry.yaml
```

### Spack Install and Run

```bash
git clone --depth 1 https://github.com/spack/spack /tmp/spack
export PATH=/tmp/spack/bin:$PATH
mcpserver start --config ./examples/servers/run-spack.yaml
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


## TODO

- add optimization agent, finish flux-mcp example for dmeo, fractale screenshots
- add saving of graph and transitions to state machine for research.
- where would we add algorithms here?
- get job logs / info needs better feedback for agent
- need to make spack / modules software discovery tools.

## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
