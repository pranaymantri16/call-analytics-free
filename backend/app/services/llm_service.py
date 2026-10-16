import json
from ollama import AsyncClient
from app.config import settings

SYSTEM_PROMPT = '''You are a professional call-intelligence analyst. The source transcript may be in Hindi, Hinglish, English, or a mixture of languages.

ROLE ATTRIBUTION:
- Caller means the company agent/representative, not necessarily the person who dialled or spoke first.
- Customer means the client/prospect. Keep the agent's claims/actions separate from the customer's needs, answers and commitments.
- Role labels are evidence-based model inferences, not verified identities. Use conversational evidence; do not invent attribution.
- Unassigned speech has uncertain roles. Describe it without assigning it to either party.
- Put only agent-attributed behavior into caller_summary, and only customer-attributed needs/responses into customer_summary.
- If a role is not identifiable, say so in its summary. Put relevant ambiguous information into unassigned_summary (empty if none).
- Score agent behavior only from speech attributed to the agent; do not score the customer's behavior as agent performance.

LANGUAGE REQUIREMENT — MANDATORY:
- Write EVERY generated text value in English only: caller_summary, customer_summary, unassigned_summary, every key_topics item, and every action_items item.
- If the transcript is in Hindi or Hinglish, understand it and translate its meaning into natural, concise English before summarizing it.
- Do not return Hindi script, Hinglish, or transliterated Hindi in any generated text field.
- Preserve product names, people names, brands, amounts, dates, and other factual details accurately.
- Do not translate or alter the fixed enum values for customer_interest_level: use exactly High, Medium, or Low.
- Do not translate the fixed JSON field names or add extra fields.
- Return ONLY valid JSON matching the supplied schema. No markdown, preamble, or commentary.

Analyze only information supported by the transcript. Do not invent facts or action items. Score agent performance from 1 to 10 based only on observable call behavior. Customer interest means expressed interest in the product/service, not sentiment alone. If evidence is insufficient, use Medium interest and a conservative score.'''


async def summarize_call(transcript: str) -> dict:
    client = AsyncClient(host=settings.ollama_base_url)
    response = await client.chat(
        model=settings.ollama_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Analyze this call transcript. All generated text must be in English, regardless of the transcript language.\n\nTRANSCRIPT:\n" + transcript},
        ],
        format={
            "type": "object",
            "properties": {
                "caller_summary": {"type": "string", "description": "English account of the company agent's statements/actions; say unidentifiable if not supported."},
                "customer_summary": {"type": "string", "description": "English account of the customer's needs/responses; say unidentifiable if not supported."},
                "unassigned_summary": {"type": "string", "description": "Relevant speech whose role is uncertain, without assigning it to either party; empty if none."},
                "customer_interest_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "key_topics": {"type": "array", "items": {"type": "string", "description": "Topic written in English."}},
                "action_items": {"type": "array", "items": {"type": "string", "description": "Action item written in English."}},
                "agent_performance_score": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["caller_summary", "customer_summary", "unassigned_summary", "customer_interest_level", "key_topics", "action_items", "agent_performance_score"],
        },
        options={"temperature": 0.1},
    )
    data = json.loads(response.message.content)
    score = max(1, min(10, int(data.get("agent_performance_score", 5))))
    interest = data.get("customer_interest_level", "Medium")
    if interest not in {"High", "Medium", "Low"}:
        interest = "Medium"
    caller_summary = str(data.get("caller_summary", "Caller role could not be identified."))
    customer_summary = str(data.get("customer_summary", "Customer role could not be identified."))
    parts = ["Caller (agent): " + caller_summary, "Customer: " + customer_summary]
    if data.get("unassigned_summary"):
        parts.append("Unassigned speech: " + str(data["unassigned_summary"]))
    return {
        "call_summary": "\n\n".join(parts),
        "customer_interest_level": interest,
        "key_topics": [str(item) for item in data.get("key_topics", [])],
        "action_items": [str(item) for item in data.get("action_items", [])],
        "agent_performance_score": score,
    }
