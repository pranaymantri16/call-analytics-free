import json
from ollama import AsyncClient
from app.config import settings

SYSTEM_PROMPT = '''You are a professional call-intelligence analyst. The source transcript may be in Hindi, Hinglish, English, or a mixture of languages.

LANGUAGE REQUIREMENT — MANDATORY:
- Write EVERY generated text value in English only: call_summary, every key_topics item, and every action_items item.
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
                "call_summary": {"type": "string", "description": "Concise English summary, translating source meaning when needed."},
                "customer_interest_level": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "key_topics": {"type": "array", "items": {"type": "string", "description": "Topic written in English."}},
                "action_items": {"type": "array", "items": {"type": "string", "description": "Action item written in English."}},
                "agent_performance_score": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["call_summary", "customer_interest_level", "key_topics", "action_items", "agent_performance_score"],
        },
        options={"temperature": 0.1},
    )
    data = json.loads(response.message.content)
    score = max(1, min(10, int(data.get("agent_performance_score", 5))))
    interest = data.get("customer_interest_level", "Medium")
    if interest not in {"High", "Medium", "Low"}:
        interest = "Medium"
    return {
        "call_summary": str(data.get("call_summary", "")),
        "customer_interest_level": interest,
        "key_topics": [str(item) for item in data.get("key_topics", [])],
        "action_items": [str(item) for item in data.get("action_items", [])],
        "agent_performance_score": score,
    }
