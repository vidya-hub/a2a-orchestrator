# A2A Protocol Demo - Agent to Agent Communication

A demonstration of Google's Agent-to-Agent (A2A) protocol with true inter-agent delegation:
- **Research Agent** (DuckDuckGo MCP) can delegate file operations to Writer Agent
- **Writer Agent** (Filesystem MCP) can delegate research to Research Agent
- Both communicate via A2A protocol (JSON-RPC over HTTP)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        External Client                              │
│              (curl, httpie, or any HTTP client)                     │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ A2A Protocol (JSON-RPC/HTTP)
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│   Research Agent        │◄───►│   Writer Agent          │
│   Port: 8001            │ A2A │   Port: 8002            │
│                         │     │                         │
│   Tools:                │     │   Tools:                │
│   - web_search          │     │   - read_file           │
│   - delegate_to_agent   │     │   - write_file          │
│   - list_agents         │     │   - edit_file           │
│                         │     │   - delegate_to_agent   │
│   ┌───────────────┐     │     │   ┌───────────────┐     │
│   │ DuckDuckGo    │     │     │   │ Filesystem    │     │
│   │ MCP Server    │     │     │   │ MCP Server    │     │
│   └───────────────┘     │     │   └───────────────┘     │
└─────────────────────────┘     └─────────────────────────┘
```

## Setup

```bash
cd a2a-demo

# Create virtual environment  
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Configure API key
echo "GOOGLE_API_KEY=your-key-here" > .env
```

## Quick Start

### 1. Start the Servers

```bash
python run.py run --output-dir ./output
```

This starts:
- **Research Agent** on `http://localhost:8001`
- **Writer Agent** on `http://localhost:8002`
- Output directory at `./output` for file operations

### 2. Send a Request

In another terminal, send a task using curl:

```bash
# Search and save to file (demonstrates A2A delegation)
curl -X POST http://localhost:8001/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "1",
    "params": {
      "message": {
        "messageId": "msg-001",
        "role": "user",
        "parts": [{"kind": "text", "text": "Search for Python 3.13 features and save a summary to python_features.txt"}]
      }
    }
  }'
```

### 3. Check Results

```bash
cat ./output/python_features.txt
```

## API Reference

### Send Message to Agent

**Endpoint:** `POST http://localhost:{port}/`

**Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "unique-request-id",
  "params": {
    "message": {
      "messageId": "unique-message-id",
      "role": "user",
      "parts": [{"kind": "text", "text": "Your task here"}]
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "unique-request-id",
  "result": {
    "kind": "task",
    "id": "task-uuid",
    "status": {
      "state": "completed",
      "message": {
        "parts": [{"kind": "text", "text": "Agent response here"}]
      }
    }
  }
}
```

### Get Agent Card (Discovery)

```bash
# Agent metadata and capabilities
curl http://localhost:8001/.well-known/agent-card.json
```

## Example Tasks

### Research Agent (port 8001)
```bash
# Simple search
curl -X POST http://localhost:8001/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": "1",
    "params": {"message": {"messageId": "m1", "role": "user", 
      "parts": [{"kind": "text", "text": "Search for latest AI news"}]}}
  }'

# Search + delegate file save to Writer Agent
curl -X POST http://localhost:8001/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": "2",
    "params": {"message": {"messageId": "m2", "role": "user", 
      "parts": [{"kind": "text", "text": "Search for Rust programming tips and save them to rust_tips.txt"}]}}
  }'
```

### Writer Agent (port 8002)
```bash
# Write a file
curl -X POST http://localhost:8002/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": "1",
    "params": {"message": {"messageId": "m1", "role": "user", 
      "parts": [{"kind": "text", "text": "Write hello world to hello.txt"}]}}
  }'

# Read a file
curl -X POST http://localhost:8002/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": "2",
    "params": {"message": {"messageId": "m2", "role": "user", 
      "parts": [{"kind": "text", "text": "Read the contents of hello.txt"}]}}
  }'

# Research + write (delegates to Research Agent)
curl -X POST http://localhost:8002/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "method": "message/send", "id": "3",
    "params": {"message": {"messageId": "m3", "role": "user", 
      "parts": [{"kind": "text", "text": "Find information about Docker best practices and write it to docker_tips.txt"}]}}
  }'
```

## CLI Options

```bash
# Run with custom ports
python run.py run \
  --host 0.0.0.0 \
  --research-port 9001 \
  --writer-port 9002 \
  --output-dir /tmp/a2a-output

# Use custom MCP servers
python run.py run \
  --research-mcp "uvx ddgs-mcp" \
  --writer-mcp "npx -y @modelcontextprotocol/server-filesystem /custom/path"
```

## Project Structure

```
a2a-demo/
├── run.py                  # Main entry point
├── pyproject.toml          # Dependencies
├── .env                    # GOOGLE_API_KEY
├── output/                 # Writer Agent file operations
└── a2a_demo/
    ├── __init__.py
    ├── core/
    │   └── registry.py     # A2A agent discovery & routing
    ├── mcp/
    │   └── manager.py      # Persistent MCP connections
    └── agents/
        ├── base.py         # Base agent with delegation tools
        ├── research.py     # Research Agent (DuckDuckGo)
        └── writer.py       # Writer Agent (Filesystem)
```

## How It Works Under the Hood

### Startup Sequence

```mermaid
sequenceDiagram
    participant Main as run.py
    participant RA as Research Agent
    participant WA as Writer Agent
    participant DDG as DuckDuckGo MCP
    participant FS as Filesystem MCP
    participant Reg as Agent Registry

    Note over Main: Phase 1: Setup MCP Connections
    Main->>RA: Create Research Agent
    RA->>DDG: Connect (stdio)
    DDG-->>RA: Tools: web_search, news_search
    Main->>WA: Create Writer Agent
    WA->>FS: Connect (stdio)
    FS-->>WA: Tools: read_file, write_file, edit_file...

    Note over Main: Phase 2: Start A2A Servers
    Main->>RA: Start server on :8001
    Main->>WA: Start server on :8002

    Note over Main: Phase 3: Peer Discovery
    Main->>Reg: Register http://localhost:8001
    Reg->>RA: GET /.well-known/agent-card.json
    RA-->>Reg: AgentCard (name, skills, url)
    Main->>Reg: Register http://localhost:8002
    Reg->>WA: GET /.well-known/agent-card.json
    WA-->>Reg: AgentCard (name, skills, url)

    Note over Reg: Agents can now discover & delegate to each other
```

### Simple Request Flow (No Delegation)

```mermaid
sequenceDiagram
    participant Client as curl/HTTP Client
    participant RA as Research Agent<br/>:8001
    participant LLM as Gemini LLM
    participant DDG as DuckDuckGo MCP

    Client->>RA: POST / (message/send)<br/>"Search for AI news"
    RA->>LLM: Process with tools
    LLM-->>RA: Call tool: web_search("AI news")
    RA->>DDG: call_tool("web_search", {query: "AI news"})
    DDG-->>RA: Search results
    RA->>LLM: Tool result
    LLM-->>RA: Final response
    RA-->>Client: JSON-RPC Response<br/>"Found 10 results about AI..."
```

### A2A Delegation Flow (Research → Writer)

```mermaid
sequenceDiagram
    participant Client as curl/HTTP Client
    participant RA as Research Agent<br/>:8001
    participant LLM1 as Gemini (Research)
    participant DDG as DuckDuckGo MCP
    participant Reg as Agent Registry
    participant WA as Writer Agent<br/>:8002
    participant LLM2 as Gemini (Writer)
    participant FS as Filesystem MCP

    Client->>RA: POST / (message/send)<br/>"Search Python 3.13 features<br/>and save to features.txt"
    
    Note over RA,LLM1: Step 1: Research
    RA->>LLM1: Process with tools
    LLM1-->>RA: Call tool: web_search
    RA->>DDG: web_search("Python 3.13 features")
    DDG-->>RA: Search results
    RA->>LLM1: Tool result

    Note over RA,WA: Step 2: A2A Delegation
    LLM1-->>RA: Call tool: delegate_to_agent<br/>("Writer Agent", "Save to features.txt...")
    RA->>Reg: Get Writer Agent URL
    Reg-->>RA: http://localhost:8002
    
    RA->>WA: POST / (message/send)<br/>"Save the following to features.txt..."
    
    Note over WA,FS: Step 3: File Write
    WA->>LLM2: Process with tools
    LLM2-->>WA: Call tool: write_file
    WA->>FS: write_file("features.txt", content)
    FS-->>WA: Success
    WA->>LLM2: Tool result
    LLM2-->>WA: "File saved successfully"
    
    WA-->>RA: A2A Response<br/>"File saved successfully"
    
    Note over RA,Client: Step 4: Return to User
    RA->>LLM1: Delegation result
    LLM1-->>RA: Final response
    RA-->>Client: JSON-RPC Response<br/>"Searched and saved to features.txt"
```

### Bidirectional Delegation (Writer → Research)

```mermaid
sequenceDiagram
    participant Client as curl/HTTP Client
    participant WA as Writer Agent<br/>:8002
    participant LLM2 as Gemini (Writer)
    participant Reg as Agent Registry
    participant RA as Research Agent<br/>:8001
    participant LLM1 as Gemini (Research)
    participant DDG as DuckDuckGo MCP
    participant FS as Filesystem MCP

    Client->>WA: POST / (message/send)<br/>"Find Docker tips and<br/>write to docker.txt"
    
    Note over WA,RA: Step 1: Delegate Research
    WA->>LLM2: Process with tools
    LLM2-->>WA: Call tool: delegate_to_agent<br/>("Research Agent", "Find Docker tips")
    WA->>Reg: Get Research Agent URL
    Reg-->>WA: http://localhost:8001
    
    WA->>RA: POST / (message/send)<br/>"Find Docker best practices"
    RA->>LLM1: Process with tools
    LLM1-->>RA: Call tool: web_search
    RA->>DDG: web_search("Docker best practices")
    DDG-->>RA: Search results
    RA->>LLM1: Tool result
    LLM1-->>RA: "Docker tips: 1. Use multi-stage..."
    RA-->>WA: A2A Response with Docker tips
    
    Note over WA,FS: Step 2: Write File
    WA->>LLM2: Research result
    LLM2-->>WA: Call tool: write_file
    WA->>FS: write_file("docker.txt", tips)
    FS-->>WA: Success
    WA->>LLM2: Tool result
    LLM2-->>WA: Final response
    
    WA-->>Client: JSON-RPC Response<br/>"Wrote Docker tips to docker.txt"
```

### Component Architecture

```mermaid
flowchart TB
    subgraph Client["External Client"]
        curl[curl / HTTP Client]
    end

    subgraph A2A["A2A Layer"]
        subgraph RA["Research Agent :8001"]
            RA_Server[A2A Server<br/>Starlette + JSONRPC]
            RA_Executor[Agent Executor]
            RA_Agent[LangGraph ReAct Agent]
            RA_Tools[Tools]
            RA_Server --> RA_Executor --> RA_Agent --> RA_Tools
        end

        subgraph WA["Writer Agent :8002"]
            WA_Server[A2A Server<br/>Starlette + JSONRPC]
            WA_Executor[Agent Executor]
            WA_Agent[LangGraph ReAct Agent]
            WA_Tools[Tools]
            WA_Server --> WA_Executor --> WA_Agent --> WA_Tools
        end

        Registry[(Agent Registry<br/>URL → AgentCard)]
    end

    subgraph MCP["MCP Layer"]
        MCPMgr[MCP Manager<br/>Connection Pool]
        DDG[DuckDuckGo MCP<br/>stdio process]
        FS[Filesystem MCP<br/>stdio process]
    end

    subgraph LLM["LLM Layer"]
        Gemini[Google Gemini API]
    end

    curl -->|JSON-RPC| RA_Server
    curl -->|JSON-RPC| WA_Server
    
    RA_Tools -->|delegate_to_agent| Registry
    WA_Tools -->|delegate_to_agent| Registry
    Registry -.->|A2A call| WA_Server
    Registry -.->|A2A call| RA_Server

    RA_Tools -->|MCP call| MCPMgr
    WA_Tools -->|MCP call| MCPMgr
    MCPMgr --> DDG
    MCPMgr --> FS

    RA_Agent -->|generate| Gemini
    WA_Agent -->|generate| Gemini
```

### Tool Resolution Flow

```mermaid
flowchart LR
    subgraph Agent["Agent Tool Selection"]
        Query[User Query] --> LLM[Gemini LLM]
        LLM --> Decision{Which tool?}
    end

    subgraph MCP_Tools["MCP Tools"]
        Decision -->|search needed| Search[web_search<br/>news_search]
        Decision -->|file needed| File[read_file<br/>write_file<br/>edit_file]
    end

    subgraph A2A_Tools["A2A Tools"]
        Decision -->|need other agent| Delegate[delegate_to_agent]
        Decision -->|discover agents| List[list_available_agents]
    end

    Search --> DDG[(DuckDuckGo<br/>MCP Server)]
    File --> FS[(Filesystem<br/>MCP Server)]
    Delegate --> Registry[(Agent<br/>Registry)]
    List --> Registry

    Registry -->|HTTP POST| OtherAgent[Other A2A Agent]
```

### Data Flow Summary

| Step | Component | Protocol | Description |
|------|-----------|----------|-------------|
| 1 | Client → Agent | HTTP/JSON-RPC | A2A `message/send` request |
| 2 | Agent → LLM | HTTPS | Gemini API call with tools |
| 3 | Agent → MCP | stdio/JSON-RPC | Tool execution (search/file) |
| 4 | Agent → Agent | HTTP/JSON-RPC | A2A delegation via Registry |
| 5 | Agent → Client | HTTP/JSON-RPC | A2A response with result |
