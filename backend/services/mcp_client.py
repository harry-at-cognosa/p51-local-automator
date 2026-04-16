"""MCP Client — calls local MCP servers (Apple Mail, Apple Calendar, etc.) from Python.

Each MCP server runs as a subprocess via stdio transport. This module manages
connections and provides typed helpers for common operations.
"""
import asyncio
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from backend.services.logger_service import get_logger

log = get_logger("mcp_client")

# Server definitions — maps server name to how to start it
MCP_SERVERS = {
    "apple-mail": StdioServerParameters(
        command="npx",
        args=["@griches/apple-mail-mcp"],
    ),
    "apple-calendar": StdioServerParameters(
        command="npx",
        args=["@griches/apple-calendar-mcp"],
    ),
}


@asynccontextmanager
async def mcp_session(server_name: str):
    """Open a session to a local MCP server. Use as async context manager.

    Usage:
        async with mcp_session("apple-mail") as session:
            result = await session.call_tool("list_mailboxes", {})
    """
    if server_name not in MCP_SERVERS:
        raise ValueError(f"Unknown MCP server: {server_name}. Available: {list(MCP_SERVERS.keys())}")

    params = MCP_SERVERS[server_name]
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def call_tool(server_name: str, tool_name: str, arguments: dict) -> list:
    """Call a single MCP tool and return the content blocks."""
    async with mcp_session(server_name) as session:
        result = await session.call_tool(tool_name, arguments)
        return result.content


async def list_tools(server_name: str) -> list[dict]:
    """List all available tools on a server."""
    async with mcp_session(server_name) as session:
        result = await session.list_tools()
        return [{"name": t.name, "description": t.description} for t in result.tools]


# ── Apple Mail helpers ───────────────────────────────────────


async def mail_list_mailboxes() -> list[dict]:
    """List all mailboxes across all accounts."""
    import json
    content = await call_tool("apple-mail", "list_mailboxes", {})
    return json.loads(content[0].text) if content else []


async def mail_list_messages(account: str, mailbox: str = "INBOX", limit: int = 50) -> list[dict]:
    """List recent messages in a mailbox."""
    import json
    content = await call_tool("apple-mail", "list_messages", {
        "account": account,
        "mailbox": mailbox,
        "limit": limit,
    })
    return json.loads(content[0].text) if content else []


async def mail_get_message(account: str, mailbox: str, message_id: int) -> dict:
    """Get full content of a message."""
    import json
    content = await call_tool("apple-mail", "get_message", {
        "account": account,
        "mailbox": mailbox,
        "message_id": message_id,
    })
    return json.loads(content[0].text) if content else {}


async def mail_search_messages(query: str, account: str = None, mailbox: str = None, limit: int = 25) -> list[dict]:
    """Search messages by subject or sender."""
    import json
    args = {"query": query, "limit": limit}
    if account:
        args["account"] = account
    if mailbox:
        args["mailbox"] = mailbox
    content = await call_tool("apple-mail", "search_messages", args)
    return json.loads(content[0].text) if content else []


# ── Apple Calendar helpers ───────────────────────────────────


async def calendar_list_events(calendar: str, from_date: str, to_date: str) -> list[dict]:
    """List events in a calendar within a date range."""
    import json
    content = await call_tool("apple-calendar", "list_events", {
        "calendar": calendar,
        "from_date": from_date,
        "to_date": to_date,
    })
    return json.loads(content[0].text) if content else []


async def calendar_list_calendars() -> list[dict]:
    """List all calendars."""
    import json
    content = await call_tool("apple-calendar", "list_calendars", {})
    return json.loads(content[0].text) if content else []
