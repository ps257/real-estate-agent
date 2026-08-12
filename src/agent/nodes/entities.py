import re

from agent.nodes.context import NodeContext
from agent.state import AgentState


async def extract_entities(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  : ``normalized_input`` (+ ``intent`` để biết cần entity gì).
    OUTPUT : ``entities`` (dict). Gợi ý key: project, province, property_type,
             min_price_vnd, max_price_vnd, bedrooms, listing_ids...
    """
    raw_text = state.get("normalized_input") or ""
    text = raw_text.lower()
    entities: dict = {}

    # 1. Trích xuất listing_ids (dùng cho US6_COMPARE, US1 detail, v.v.)
    found_ids = re.findall(r"(?:vhm:[a-zA-Z0-9_-]+|oh:[a-zA-Z0-9_-]+|lc_[a-zA-Z0-9_-]+)", raw_text)
    if found_ids:
        # Dedupe keeping order
        entities["listing_ids"] = list(dict.fromkeys(found_ids))
    else:
        # Kiểm tra ngữ cảnh từ lượt trước (tool_results hoặc cards đã có)
        prev_results = state.get("tool_results", [])
        prev_listings = []
        for res in prev_results:
            data = res.get("data")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("id"):
                        prev_listings.append(item["id"])
            elif isinstance(data, dict) and "listings" in data and isinstance(data["listings"], list):
                for item in data["listings"]:
                    if isinstance(item, dict) and item.get("id"):
                        prev_listings.append(item["id"])

        if prev_listings:
            # Nếu người dùng nói "2 căn này", "2 căn vừa tìm", "căn 1 và 2"
            if any(kw in text for kw in ["2 căn", "hai căn", "căn 1 và 2", "căn 1 và căn 2", "2 căn này", "2 căn vừa tìm"]):
                entities["listing_ids"] = prev_listings[:2]
            elif "3 căn" in text or "ba căn" in text:
                entities["listing_ids"] = prev_listings[:3]
            elif "4 căn" in text or "bốn căn" in text:
                entities["listing_ids"] = prev_listings[:4]
            elif any(kw in text for kw in ["so sánh", "so sanh", "compare"]) and len(prev_listings) >= 2:
                entities["listing_ids"] = prev_listings[:min(len(prev_listings), 4)]

    # 2. Trích xuất thực thể US1 (project, province, property_type)
    if "vinhomes" in text:
        entities["project"] = "Vinhomes"
    if "căn hộ" in text or "can ho" in text or "apartment" in text or "chung cư" in text or "chung cu" in text:
        entities["property_type"] = "can_ho"

    cot = list(state.get("cot", []))
    cot.append(f"entities: {entities or '{}'}")
    return {"entities": entities, "cot": cot}
