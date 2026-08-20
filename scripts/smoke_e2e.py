#!/usr/bin/env python3
"""Smoke-test TOÀN LUỒNG qua HTTP thật.

Cần server đang chạy ở terminal khác:
    uvicorn agent.server.app:app --reload

Rồi:
    python scripts/smoke_e2e.py

Khác các smoke script trước (chỉ test một node): script này đi qua nguyên
stack — HTTP -> runner -> graph 6 node -> MCP -> compose -> JSON. Nó bắt được
loại lỗi mà unit test không thấy: sai wiring, sai shape giữa các node, MCP trả
khác giả định.

Tốn API thật (mỗi lượt ~3 LLM call: guardrail, intent, entities).
"""

from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8000"
TIMEOUT = 60.0

# Dự án dùng cho case cần DỮ LIỆU THẬT. Phải là dự án có nhiều căn hộ, nếu không
# search_listings trả rỗng và test báo sai trong khi code vẫn đúng.
# (Vinhomes Global Gate chỉ có 1 căn liền kề -> lọc can_ho ra 0.)
PROJECT = "Vinhomes Grand Park"


def chat(client: httpx.Client, message: str, thread_id: str) -> dict:
    r = client.post(f"{BASE}/chat", json={"message": message, "thread_id": thread_id})
    r.raise_for_status()
    return r.json()


def show(label: str, payload: dict, *, want_intent: str | None = None,
         want_actions: list[str] | None = None, want_tools: list[str] | None = None) -> bool:
    tools = [c["name"] for c in payload.get("tool_calls", [])]
    actions = [a["type"] for a in payload.get("actions", [])]
    intent = payload.get("intent")

    problems = []
    if want_intent and intent != want_intent:
        problems.append(f"intent: cần {want_intent}, được {intent}")
    if want_actions is not None and actions != want_actions:
        problems.append(f"actions: cần {want_actions}, được {actions}")
    if want_tools is not None and tools != want_tools:
        problems.append(f"tools: cần {want_tools}, được {tools}")

    print(f"\n{'ok  ' if not problems else 'SAI '} {label}")
    print(f"       intent={intent}  tools={tools}  actions={actions}")
    print(f"       text: {payload.get('text', '')[:88]}")
    for p in problems:
        print(f"       └─ {p}")
    return not problems


def main() -> int:
    try:
        with httpx.Client(timeout=5.0) as c:
            c.get(f"{BASE}/health").raise_for_status()
    except Exception as exc:
        print(f"❌ Server không chạy ở {BASE} ({type(exc).__name__}).")
        print("   Mở terminal khác: uvicorn agent.server.app:app --reload")
        return 1

    ok = []
    with httpx.Client(timeout=TIMEOUT) as c:
        print("=" * 96)
        print("GUARDRAIL — không chạm MCP, không qua intent")
        ok.append(show(
            "câu ngoài phạm vi bị chặn",
            chat(c, "Theo em thì bỏ tiền vào đây có ổn không?", "e2e-guard"),
            want_intent=None, want_actions=["clarify"], want_tools=[],
        ))

        print("\n" + "=" * 96)
        print("US1 — tra cứu")
        ok.append(show(
            "tên đầy đủ -> cards + cta",
            chat(c, f"Tìm căn hộ {PROJECT}", "e2e-us1a"),
            want_intent="US1_SEARCH",
            want_tools=["resolve_project", "search_listings", "listing_cta_actions"],
        ))
        ok.append(show(
            "tên mơ hồ -> hỏi lại, KHÔNG tìm theo tỉnh",
            chat(c, "Tìm căn hộ Vinhomes", "e2e-us1b"),
            want_intent="US1_SEARCH", want_actions=["clarify"],
            want_tools=["resolve_project"],
        ))
        filtered = chat(c, f"Căn hộ 2 phòng ngủ dưới 5 tỷ ở {PROJECT}", "e2e-us1c")
        ok.append(show("có điều kiện lọc", filtered, want_intent="US1_SEARCH"))
        args = next((c_["args"] for c_ in filtered["tool_calls"]
                     if c_["name"] == "search_listings"), {})
        has_filter = "bedrooms" in args or "max_price_vnd" in args
        print(f"       → search_listings args: { {k: v for k, v in args.items() if k != 'limit'} }")
        print(f"       {'ok  ' if has_filter else 'SAI '} điều kiện lọc tới được MCP")
        ok.append(has_filter)

        print("\n" + "=" * 96)
        print("ĐA LƯỢT — cùng thread_id, lượt 2 chọn từ gợi ý")
        show("lượt 1: mơ hồ", chat(c, "Đặt lịch tham quan Vinhomes", "e2e-multi"))
        ok.append(show(
            "lượt 2: chọn dự án -> đủ slot, ra form",
            chat(c, PROJECT, "e2e-multi"),
            want_intent="US2_1_VISIT", want_actions=["form"],
        ))

        print("\n" + "=" * 96)
        print("US2–US5")
        for label, msg, intent, actions in [
            ("US2.2 tư vấn", f"Cho anh gặp tư vấn viên dự án {PROJECT}",
             "US2_2_CONSULT", ["form"]),
            ("US3 chính sách (RAG chưa bật -> từ chối)",
             f"Dự án {PROJECT} có cho nuôi chó mèo không?",
             "US3_POLICY", ["clarify"]),
            ("US4 tổng quan", f"Xem tổng quan dự án {PROJECT}",
             "US4_ANALYTICS", ["overview"]),
            ("US5 bản đồ", f"Cho em xem bản đồ dự án {PROJECT}",
             "US5_MAP", ["map"]),
        ]:
            ok.append(show(label, chat(c, msg, f"e2e-{intent}"),
                           want_intent=intent, want_actions=actions))

        print("\n" + "=" * 96)
        print("US6 — so sánh (lấy listing_id thật từ lần search ở trên)")
        cards = next((a["items"] for a in
                      chat(c, f"Tìm căn hộ {PROJECT}", "e2e-us6")["actions"]
                      if a["type"] == "cards"), [])
        ids = [x["id"] for x in cards[:2] if x.get("id")]
        if len(ids) < 2:
            print(f"\n(bỏ qua) dự án chỉ có {len(ids)} căn, không đủ 2 để so sánh")
        else:
            ok.append(show(
                f"so sánh {len(ids)} căn",
                chat(c, f"So sánh căn {ids[0]} với căn {ids[1]}", "e2e-us6"),
                want_intent="US6_COMPARE", want_actions=["compare"],
            ))

    print("\n" + "=" * 96)
    print(f"KẾT QUẢ: {sum(ok)}/{len(ok)} đúng")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
