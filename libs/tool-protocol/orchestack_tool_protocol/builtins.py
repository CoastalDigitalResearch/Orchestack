"""Built-in tool descriptors for Orchestack core tools."""

from __future__ import annotations

from orchestack_tool_protocol.descriptor import (
    AuditLevel,
    DataClassification,
    Idempotency,
    RiskClass,
    ToolDescriptor,
)

# ---------------------------------------------------------------------------
# shell_exec
# ---------------------------------------------------------------------------
SHELL_EXEC = ToolDescriptor(
    tool_id="shell-exec",
    name="Shell Execute",
    description="Execute a shell command inside the sandbox and return stdout/stderr.",
    input_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout_seconds": {"type": "integer", "default": 30, "minimum": 1},
            "working_dir": {"type": "string", "description": "Working directory"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "exit_code": {"type": "integer"},
        },
    },
    risk_class=RiskClass.WRITE_LOCAL,
    idempotency=Idempotency.NON_IDEMPOTENT,
    required_capabilities=["process.exec"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.FULL,
)

# ---------------------------------------------------------------------------
# file_read
# ---------------------------------------------------------------------------
FILE_READ = ToolDescriptor(
    tool_id="file-read",
    name="File Read",
    description="Read the contents of a file from the workspace.",
    input_schema={
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string", "description": "Absolute or workspace-relative path"},
            "encoding": {"type": "string", "default": "utf-8"},
            "max_bytes": {"type": "integer", "description": "Read limit in bytes"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "size_bytes": {"type": "integer"},
        },
    },
    risk_class=RiskClass.READ_ONLY,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["fs.read"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.METADATA,
)

# ---------------------------------------------------------------------------
# file_write
# ---------------------------------------------------------------------------
FILE_WRITE = ToolDescriptor(
    tool_id="file-write",
    name="File Write",
    description="Write content to a file in the workspace.",
    input_schema={
        "type": "object",
        "required": ["path", "content"],
        "properties": {
            "path": {"type": "string", "description": "Absolute or workspace-relative path"},
            "content": {"type": "string", "description": "Content to write"},
            "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
            "create_dirs": {"type": "boolean", "default": True},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "bytes_written": {"type": "integer"},
            "path": {"type": "string"},
        },
    },
    risk_class=RiskClass.WRITE_LOCAL,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["fs.write"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.FULL,
)

# ---------------------------------------------------------------------------
# git_clone
# ---------------------------------------------------------------------------
GIT_CLONE = ToolDescriptor(
    tool_id="git-clone",
    name="Git Clone",
    description="Clone a git repository into the workspace.",
    input_schema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "Repository URL"},
            "branch": {"type": "string", "description": "Branch to checkout"},
            "depth": {"type": "integer", "minimum": 1, "description": "Shallow clone depth"},
            "dest": {"type": "string", "description": "Destination directory"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "commit": {"type": "string"},
            "branch": {"type": "string"},
        },
    },
    risk_class=RiskClass.WRITE_LOCAL,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["fs.write", "net.egress"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.METADATA,
)

# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------
GIT_COMMIT = ToolDescriptor(
    tool_id="git-commit",
    name="Git Commit",
    description="Stage files and create a git commit in the workspace repository.",
    input_schema={
        "type": "object",
        "required": ["message"],
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paths to stage (default: all modified)",
            },
            "author": {"type": "string", "description": "Author string (Name <email>)"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "commit_sha": {"type": "string"},
            "message": {"type": "string"},
            "files_changed": {"type": "integer"},
        },
    },
    risk_class=RiskClass.WRITE_LOCAL,
    idempotency=Idempotency.NON_IDEMPOTENT,
    required_capabilities=["fs.write"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.FULL,
)

# ---------------------------------------------------------------------------
# http_fetch
# ---------------------------------------------------------------------------
HTTP_FETCH = ToolDescriptor(
    tool_id="http-fetch",
    name="HTTP Fetch",
    description="Perform an HTTP request and return the response body.",
    input_schema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "Request URL"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "body": {"type": "string"},
        },
    },
    risk_class=RiskClass.WRITE_EXTERNAL,
    idempotency=Idempotency.NON_IDEMPOTENT,
    required_capabilities=["net.egress"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.FULL,
)

# ---------------------------------------------------------------------------
# memory_search
# ---------------------------------------------------------------------------
MEMORY_SEARCH = ToolDescriptor(
    tool_id="memory-search",
    name="Memory Search",
    description="Semantic search over the memory store (vector + keyword).",
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Natural-language query"},
            "top_k": {"type": "integer", "default": 10, "minimum": 1},
            "namespace": {"type": "string", "description": "Memory namespace to search"},
            "filters": {"type": "object", "description": "Metadata filter predicates"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "score": {"type": "number"},
                        "metadata": {"type": "object"},
                    },
                },
            },
        },
    },
    risk_class=RiskClass.READ_ONLY,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["memory.read"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.METADATA,
)

# ---------------------------------------------------------------------------
# memory_write
# ---------------------------------------------------------------------------
MEMORY_WRITE = ToolDescriptor(
    tool_id="memory-write",
    name="Memory Write",
    description="Write or upsert entries into the memory store.",
    input_schema={
        "type": "object",
        "required": ["entries"],
        "properties": {
            "entries": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["content"],
                    "properties": {
                        "id": {"type": "string", "description": "Entry ID (auto-generated if omitted)"},
                        "content": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                },
            },
            "namespace": {"type": "string", "description": "Target namespace"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "written": {"type": "integer"},
            "ids": {"type": "array", "items": {"type": "string"}},
        },
    },
    risk_class=RiskClass.WRITE_LOCAL,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["memory.write"],
    data_classification=DataClassification.INTERNAL,
    audit_level=AuditLevel.FULL,
)

# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------
WEB_SEARCH = ToolDescriptor(
    tool_id="web-search",
    name="Web Search",
    description="Search the web and return a list of result snippets.",
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Search query string"},
            "num_results": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "region": {"type": "string", "description": "Region/locale code (e.g. us-en)"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                },
            },
        },
    },
    risk_class=RiskClass.READ_ONLY,
    idempotency=Idempotency.IDEMPOTENT,
    required_capabilities=["net.egress"],
    data_classification=DataClassification.PUBLIC,
    audit_level=AuditLevel.METADATA,
)


# ---------------------------------------------------------------------------
# Registry of all built-in tools
# ---------------------------------------------------------------------------
BUILTIN_TOOLS: list[ToolDescriptor] = [
    SHELL_EXEC,
    FILE_READ,
    FILE_WRITE,
    GIT_CLONE,
    GIT_COMMIT,
    HTTP_FETCH,
    MEMORY_SEARCH,
    MEMORY_WRITE,
    WEB_SEARCH,
]

BUILTIN_TOOLS_BY_ID: dict[str, ToolDescriptor] = {t.tool_id: t for t in BUILTIN_TOOLS}
