"""LLM Service — Anthropic SDK wrapper for structured judgment calls.

All AI judgment (email categorization, urgency assessment, data interpretation)
flows through this service. Supports prompt caching for repeated system prompts.
"""
import json

import anthropic

from backend.config import ANTHROPIC_API_KEY
from backend.services.logger_service import get_logger

log = get_logger("llm_service")

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def judge_structured(
    system: str,
    user_prompt: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096,
) -> dict:
    """Make a single LLM call expecting JSON output. Returns parsed dict + token usage."""
    client = get_client()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    )

    text = response.content[0].text
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
    }

    # Parse JSON from response — handle markdown code fences
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # skip opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        log.error("llm_json_parse_error", text_preview=text[:200])
        result = {"raw_text": text, "parse_error": True}

    return {"result": result, "usage": usage}


def categorize_emails(emails: list[dict], topics: list[str], scope: str = "") -> dict:
    """Categorize a batch of emails by topic and urgency.

    Args:
        emails: List of dicts with keys: sender, subject, snippet, date
        topics: List of topic names (e.g. ["Business & Finance", "Technology & AI"])
        scope: Focus area filter. "all" or empty = include everything.
               Otherwise, only categorize emails related to the scope description.

    Returns:
        dict with "result" (list of categorized emails) and "usage" (token counts)
    """
    topic_list = "\n".join(f"- {t}" for t in topics)

    scope_instruction = ""
    if scope and scope.lower().strip() not in ("all", ""):
        scope_instruction = f"""
IMPORTANT — SCOPE FILTER: Only categorize emails that are related to: "{scope}"
For emails that are NOT related to this scope, set topic to "Out of Scope" and urgent to false.
Do NOT skip them — include every email in the output, but mark unrelated ones as "Out of Scope".
"""

    system = f"""You are an email categorization assistant. You will receive a batch of emails
and must categorize each one into exactly ONE of the following topics:

{topic_list}
- Other (if none fit well)
{scope_instruction}
For each email, also assess urgency:
- urgent: true if the email requires action, has a deadline, involves financial obligations, or is time-sensitive
- urgent: false for newsletters, notifications, marketing, and informational emails
- If urgent, provide a brief urgency_reason

Return a JSON array where each element has:
{{"index": <0-based index matching input order>, "topic": "<topic name>", "urgent": <true/false>, "urgency_reason": "<reason or empty string>"}}

Return ONLY the JSON array, no other text."""

    email_lines = []
    for i, e in enumerate(emails):
        email_lines.append(
            f"[{i}] From: {e.get('sender', '')} | Subject: {e.get('subject', '')} | "
            f"Date: {e.get('date', '')} | Snippet: {e.get('snippet', '')[:200]}"
        )

    user_prompt = f"Categorize these {len(emails)} emails:\n\n" + "\n".join(email_lines)

    return judge_structured(system, user_prompt)


def generate_email_reply(
    source_from: str,
    source_subject: str,
    source_body: str,
    to_address: str,
    signature: str = "",
    tone: str = "warm and professional",
) -> dict:
    """Generate a short acknowledgment reply for an inbound message.

    `to_address` is the resolved recipient — the actual address the reply will
    be sent to. This is the ground truth for who we are writing to. Names that
    appear in the body refer to other parties (the original recipient of a
    transactional email, for example) and must NOT be used to address the
    reply unless they clearly correspond to to_address.

    Returns a dict with "result" = {"subject": str, "body": str} and "usage" token counts.
    """
    sig_block = ""
    if signature:
        sig_block = (
            "\n\nSignature to append at the end of the reply (use verbatim, "
            "do not modify):\n---\n" + signature + "\n---"
        )

    system = (
        "You write short, genuine acknowledgment replies to inbound emails. "
        "Your goal: confirm receipt, reassure the sender their message was seen, "
        "set a reasonable expectation for follow-up, and stay brief.\n\n"
        "Critical context — the reply will be SENT TO the address provided as "
        "`To (reply destination)`. That address is the ground truth for who you "
        "are writing to. Names appearing in the message body may refer to OTHER "
        "parties (e.g. the original recipient of a transactional notification) "
        "and must NOT be used to address the reply unless you can confirm the "
        "name belongs to the To address.\n\n"
        "Hard rules:\n"
        "- 2–4 sentences, no more.\n"
        "- Never promise a specific time commitment you can't keep; use phrases like 'soon' or 'within a few days'.\n"
        "- Don't invent facts not in the source message (no made-up meetings, dates, or amounts).\n"
        "- Address by first name ONLY if a name in the body clearly belongs to the To address; otherwise use a generic greeting like 'Hello,' or no greeting at all.\n"
        "- Do NOT include a signature, sign-off block, or any name/email at the end. A separate signature block is appended afterward when configured. If no signature is configured, the reply ends with the body text and nothing else.\n"
        "- Tone: " + tone + ".\n\n"
        "Return ONLY a JSON object, no prose before or after:\n"
        "{\"subject\": \"Re: <original subject>\", \"body\": \"<reply text>\"}"
    )

    user_prompt = (
        "Inbound email:\n"
        f"From: {source_from}\n"
        f"Subject: {source_subject}\n"
        f"To (reply destination): {to_address}\n"
        f"Body:\n{source_body[:4000]}"
        f"{sig_block}"
    )

    result = judge_structured(system, user_prompt)

    # If a signature was provided, append it to the body the LLM returned so
    # the model can't accidentally omit it. If NOT provided and the model
    # invented one anyway, we have no safe way to strip it without risking
    # over-deletion — the prompt now strongly tells the model not to.
    if signature and isinstance(result.get("result"), dict):
        body = result["result"].get("body", "")
        if signature.strip() and signature.strip() not in body:
            result["result"]["body"] = f"{body.rstrip()}\n\n{signature.rstrip()}\n"

    return result
