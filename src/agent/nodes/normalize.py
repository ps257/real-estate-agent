"""Node: Input Normalization & Guardrail.  [DONE]

PRD bước 1, hai việc:
  1. **Chuẩn hoá** input tiếng Việt: Unicode NFC, khoảng trắng, dấu câu lặp,
     ký tự kéo dài, viết tắt/teencode phổ biến.
  2. **Guardrail** hai tầng, chặn sớm các chủ đề "Out of scope" của PRD (định giá,
     tư vấn đầu tư, mô phỏng tài chính/trả góp, giao dịch online):
       - tầng 1 = regex trong file này (rẻ, deterministic, chạy mọi request);
       - tầng 2 = LLM classifier (agent/guardrail_llm.py), chỉ chạy khi tầng 1
         không bắt được, để phủ cách diễn đạt vòng vo.

Khi guardrail bắt được, node đặt ``state["guardrail"]`` và graph rẽ **thẳng** sang
``compose`` — bỏ qua intent/entities/tools (xem graph.py::_route_after_normalize).
Không dùng ``needs_clarification`` cho việc này vì node ``conversation`` sẽ ghi đè.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from agent.nodes.context import NodeContext
from agent.state import AgentState

# ============================================================== 1. Chuẩn hoá

_CONTROL_CHARS = re.compile(r"[\u0000-\u001f\u007f-\u009f]")
_MULTI_SPACE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:])")
_REPEAT_PUNCT = re.compile(r"([!?.,;:])\1+")
# Ký tự kéo dài ("đẹppppp" -> "đẹpp"). Loại trừ chữ số để KHÔNG phá giá tiền
# ("5000000" phải giữ nguyên) — đó là lý do dùng [^\W\d_] thay vì \w.
_REPEAT_CHAR = re.compile(r"([^\W\d_])\1{2,}")

# Tín hiệu nghiệp vụ đủ rõ để không cần gọi Guardrail LLM. Bao gồm cả câu hỏi
# tiện ích quanh dự án, nhờ vậy "quán ăn gần Vinhomes Ocean Park" không bị chặn
# bởi rule đồ ăn độc lập ở dưới.
_CLEAR_IN_SCOPE = re.compile(
    r"(?:bất động sản|bđs|\bbds\b|\bcăn\b|căn hộ|chung cư|nhà đất|dự án|vinhomes?|"
    r"ocean\s*park|smart\s*city|grand\s*park|times\s*city|royal\s*city|masteri|imperia|ecopark|"
    r"\blisting\b|\b[a-z]{1,10}(?::|_)[a-z0-9_-]+\b|so sánh|đối chiếu|"
    r"phòng ngủ|mua nhà|thuê (?:nhà|căn)|giá (?:rao|bán)|"
    r"đặt lịch tham quan|tư vấn mua nhà|xem bản đồ|tiện ích|chính sách|pháp lý|"
    r"phân tích tổng quan|thống kê (?:giá|diện tích)|giá trung bình|"
    r"diện tích trung bình|bao nhiêu căn|khoảng giá|cơ cấu loại hình|"
    r"nguồn giá|giá chào bán|giá ước tính|"
    r"bat dong san|\bcan\b|can ho|chung cu|nha dat|du an|so sanh|doi chieu|phong ngu|mua nha|"
    r"thue (?:nha|can)|gia (?:rao|ban)|dat lich tham quan|tu van mua nha|"
    r"xem ban do|tien ich|chinh sach|phap ly)",
    re.IGNORECASE,
)

# Viết tắt dính số: xử lý trước vì "2pn" không tách được bằng ranh giới từ.
_STICKY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\w)(\d+)\s*pn(?!\w)", re.IGNORECASE), r"\1 phòng ngủ"),
    (re.compile(r"(?<!\w)(\d+)\s*(?:wc|vs)(?!\w)", re.IGNORECASE), r"\1 vệ sinh"),
    (re.compile(r"(?<!\w)(\d+)\s*m2(?!\w)", re.IGNORECASE), r"\1 m2"),
)

# Viết tắt/teencode -> dạng đầy đủ, chỉ thay khi đứng riêng thành một từ.
# Danh sách cố tình BẢO THỦ: thà bỏ sót còn hơn đổi sai nghĩa. Ví dụ đã loại bỏ:
#   "k"  (có thể là "nghìn"), "ch" (quá mơ hồ), "đn" ("Đà Nẵng" hay "Đồng Nai"?).
_ABBREVIATIONS: dict[str, str] = {
    "ko": "không",
    "hok": "không",
    "khong": "không",
    "dc": "được",
    "đc": "được",
    "j": "gì",
    "z": "vậy",
    "vs": "với",
    "bds": "bất động sản",
    "bđs": "bất động sản",
    "cc": "chung cư",
    "tphcm": "hồ chí minh",
    "hcm": "hồ chí minh",
    "sg": "hồ chí minh",
    "hn": "hà nội",
    "tr": "triệu",
    "ty": "tỷ",
    "tỉ": "tỷ",
}

# Ghép thành 1 regex (từ dài trước để "tphcm" không bị "hcm" ăn mất).
_ABBREV_RE = re.compile(
    r"(?<!\w)(" + "|".join(sorted(map(re.escape, _ABBREVIATIONS), key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)


def normalize_text(raw: str) -> str:
    """Chuẩn hoá một message tiếng Việt. Hàm thuần — dễ unit-test riêng.

    Cố ý **giữ nguyên chữ hoa/thường và dấu**: tên dự án ("Vinhomes Ocean Park")
    là tín hiệu quan trọng cho NER ở node ``entities``.

    Chưa xử lý: khác biệt vị trí dấu thanh kiểu cũ/mới ("hoà" vs "hòa") — NFC
    không gộp được vì đó là hai chuỗi ký tự khác nhau thật sự. Cần bảng map riêng
    nếu muốn khớp tên dự án chặt hơn.
    """
    text = unicodedata.normalize("NFC", raw or "")
    text = _CONTROL_CHARS.sub(" ", text)

    for pattern, repl in _STICKY_PATTERNS:
        text = pattern.sub(repl, text)

    text = _REPEAT_CHAR.sub(r"\1\1", text)
    text = _REPEAT_PUNCT.sub(r"\1", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _MULTI_SPACE.sub(" ", text).strip()

    return _ABBREV_RE.sub(lambda m: _ABBREVIATIONS[m.group(1).lower()], text)


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt + đ->d. Dùng để so khớp guardrail không phụ thuộc dấu."""
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


# ============================================================== 2. Guardrail


@dataclass(frozen=True)
class GuardrailRule:
    """Một nhóm chủ đề nằm ngoài phạm vi PRD.

    ``exemptible=True`` -> bỏ qua nếu user đang **hỏi về chính sách** chứ không
    yêu cầu thực hiện (vd "chính sách trả góp của dự án X" là US3_POLICY, hợp lệ).
    """

    code: str
    message: str
    patterns: tuple[re.Pattern[str], ...]
    suggestions: tuple[dict[str, str], ...] = field(default_factory=tuple)
    exemptible: bool = False


# Gợi ý dùng lại cho nhiều rule: luôn mở lối cho user đi tiếp thay vì chỉ từ chối.
_FALLBACK_SUGGESTIONS: tuple[dict[str, str], ...] = (
    {"label": "Tra cứu BĐS theo dự án", "intent": "US1_SEARCH"},
    {"label": "Xem tổng quan dự án", "intent": "US4_ANALYTICS"},
    {"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"},
)

_OUT_OF_DOMAIN_MESSAGE = (
    "Dạ em là trợ lý chuyên về bất động sản Vinhomes nên chưa hỗ trợ yêu cầu "
    "ngoài lĩnh vực này ạ. Em có thể giúp anh/chị tìm dự án, căn hộ, giá rao bán "
    "hoặc tiện ích xung quanh một dự án cụ thể."
)

_UNKNOWN_SCOPE_MESSAGE = (
    "Dạ em chưa xác định được yêu cầu này có liên quan đến bất động sản. "
    "Anh/chị muốn tìm căn hộ, xem thông tin dự án, phân tích giá hay đặt lịch tham quan ạ?"
)

# Câu hỏi *về* chính sách/thủ tục là US3 (RAG) — không phải yêu cầu giao dịch hay
# mô phỏng tài chính. Miễn trừ cho các rule có exemptible=True.
_INFORMATIONAL_RE = re.compile(
    r"chinh sach|quy dinh|quy che|dieu kien|thu tuc|quy trinh|ho so|giay to|phap ly"
)

# Pattern viết ở dạng KHÔNG DẤU vì được so khớp với strip_diacritics(text).lower().
_RULES: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        code="valuation",
        message=(
            "Dạ em xin phép chưa hỗ trợ định giá bất động sản ạ. "
            "Em có thể giúp anh/chị tra cứu giá rao bán hiện có của các căn trong dự án, "
            "hoặc nối máy với tư vấn viên để được hỗ trợ kỹ hơn ạ."
        ),
        patterns=(
            re.compile(r"dinh\s*gia"),
            re.compile(r"tham\s*dinh"),
            re.compile(r"(ban|sang nhuong)\s*(duoc|dc)\s*(bao nhieu|gia nao)"),
            re.compile(r"gia\s*tri\s*(thuc|that|thi truong)"),
        ),
        suggestions=_FALLBACK_SUGGESTIONS,
    ),
    GuardrailRule(
        code="investment",
        message=(
            "Dạ em chỉ cung cấp thông tin bất động sản, chưa tư vấn đầu tư hay đánh giá "
            'căn nào "đáng mua hơn" ạ. Em có thể trình bày dữ liệu từng căn để anh/chị '
            "tự đối chiếu, hoặc kết nối tư vấn viên ạ."
        ),
        patterns=(
            re.compile(r"(co\s*)?nen\s*(mua|dau tu|xuong tien|chot)"),
            re.compile(r"(can|can ho|du an|cho)\s*nao\s*(dang|tot hon|ngon|loi|sinh loi|hoi)"),
            re.compile(r"tu van\s*dau tu"),
            # "chủ đầu tư" là thực thể hợp lệ -> loại trừ bằng lookbehind cố định.
            re.compile(r"(?<!chu )dau tu\s*(co|nen|sinh loi|luot song|kiem loi)"),
            re.compile(r"luot song|sinh loi|ty suat|loi nhuan"),
            re.compile(r"(se|du bao|du doan|tuong lai).{0,15}(tang gia|giam gia|len gia)"),
        ),
        suggestions=(
            {"label": "So sánh thông số các căn", "intent": "US6_COMPARE"},
            {"label": "Xem tổng quan dự án", "intent": "US4_ANALYTICS"},
            {"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"},
        ),
    ),
    GuardrailRule(
        code="financial",
        message=(
            "Dạ phần tính toán vay/trả góp nằm ngoài phạm vi hỗ trợ của em ạ. "
            "Anh/chị có thể hỏi em về chính sách thanh toán được công bố của dự án, "
            "hoặc để em nối máy với tư vấn viên ạ."
        ),
        patterns=(
            re.compile(r"tra gop"),
            re.compile(r"vay\s*(ngan hang|von|mua nha|the chap)"),
            re.compile(r"lai suat"),
            re.compile(r"an han\s*(goc|no)"),
            re.compile(r"(tinh|mo phong|du tinh).{0,12}(khoan vay|goc lai|ky han)"),
        ),
        suggestions=(
            {"label": "Chính sách thanh toán dự án", "intent": "US3_POLICY"},
            {"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"},
        ),
        exemptible=True,
    ),
    GuardrailRule(
        code="transaction",
        message=(
            "Dạ em chưa hỗ trợ đặt cọc, thanh toán hay ký hợp đồng trực tuyến ạ. "
            "Em có thể đặt lịch tham quan hoặc nối máy tư vấn viên để anh/chị làm việc "
            "trực tiếp với dự án ạ."
        ),
        patterns=(
            re.compile(r"dat coc"),
            re.compile(r"thanh toan\s*(online|truc tuyen|qua (app|the|vi))"),
            re.compile(r"ky\s*(hop dong|hd)\s*(dien tu|online)"),
            re.compile(r"chuyen khoan"),
        ),
        suggestions=(
            {"label": "Đặt lịch tham quan", "intent": "US2_1_VISIT"},
            {"label": "Nối tư vấn viên", "intent": "US2_2_CONSULT"},
        ),
        exemptible=True,
    ),
    GuardrailRule(
        code="smalltalk",
        message=(
            "Xin chào anh/chị! Em là trợ lý bất động sản Vinhomes. "
            "Em có thể giúp tìm căn hộ, xem thông tin dự án, phân tích số liệu "
            "hoặc đặt lịch tham quan ạ."
        ),
        patterns=(
            re.compile(r"^\s*(?:(?:xin\s+)?chao|hello|hi|alo)(?:\s+(?:ban|em|anh|chi))?[.!?]*\s*$"),
            re.compile(r"^\s*(?:cam\s+on|thanks|thank\s+you)(?:\s+(?:ban|em|anh|chi))?[.!?]*\s*$"),
            re.compile(r"^\s*(?:tam\s+biet|bye|goodbye)[.!?]*\s*$"),
        ),
        suggestions=_FALLBACK_SUGGESTIONS,
    ),
    GuardrailRule(
        code="out_of_domain",
        message=_OUT_OF_DOMAIN_MESSAGE,
        patterns=(
            re.compile(r"(?:tim|kiem|goi y|muon).{0,24}(?:do an|mon an|quan an|nha hang)"),
            re.compile(r"(?:thoi tiet|du bao thoi tiet|nhiet do hom nay)"),
            re.compile(r"(?:viet|tao|sua).{0,20}(?:code|ma nguon|python|javascript|java\b)"),
            re.compile(r"(?:ve may bay|chuyen bay|dat phong khach san|du lich)"),
            re.compile(r"(?:chua benh|bac si|ke don|thuoc gi)"),
        ),
        suggestions=_FALLBACK_SUGGESTIONS,
    ),
)

_UNKNOWN_SCOPE_RULE = GuardrailRule(
    code="unknown_scope",
    message=_UNKNOWN_SCOPE_MESSAGE,
    patterns=(),
    suggestions=_FALLBACK_SUGGESTIONS,
)


# Tra rule theo code — dùng khi tầng 2 (LLM) trả về code thay vì rule object.
_RULES_BY_CODE: dict[str, GuardrailRule] = {r.code: r for r in _RULES}


def check_guardrail(text: str) -> GuardrailRule | None:
    """Tầng 1 — regex. Trả về rule bị vi phạm, hoặc None nếu không bắt được.

    Rẻ (~micro giây) và deterministic, nhưng chỉ bắt được cách diễn đạt gần với
    pattern. Phần vòng vo do tầng 2 (agent/guardrail_llm.py) xử lý.
    """
    probe = strip_diacritics(text).lower()
    informational = bool(_INFORMATIONAL_RE.search(probe))
    clear_in_scope = bool(_CLEAR_IN_SCOPE.search(text))

    for rule in _RULES:
        if rule.exemptible and informational:
            continue
        if rule.code == "out_of_domain" and clear_in_scope:
            continue
        if any(p.search(probe) for p in rule.patterns):
            return rule
    return None


# ============================================================== 3. Node


async def normalize(state: AgentState, ctx: NodeContext) -> dict:
    """
    INPUT  (đọc state): ``user_input``.
    OUTPUT (merge vào state):
        - ``normalized_input``: str đã chuẩn hoá.
        - ``guardrail``: None nếu hợp lệ; dict ``{code, message, suggestions}``
          nếu out-of-scope (graph sẽ rẽ thẳng sang ``compose``).
        - ``cot``: thêm 2 bước reasoning.
    """
    raw = state.get("user_input", "")
    text = normalize_text(raw)

    cot = list(state.get("cot", []))
    suffix = "" if text == raw.strip() else " (đã chuẩn hoá)"
    cot.append(f"normalize: {text!r}{suffix}")

    clear_in_scope = bool(_CLEAR_IN_SCOPE.search(text))

    # Tầng 1: regex — rẻ, chạy trước, bắt cách diễn đạt trực diện.
    rule = check_guardrail(text)
    source = "regex"

    # Tầng 2 chỉ xử lý câu chưa có tín hiệu nghiệp vụ rõ. LLM trả cả in_scope để
    # phân biệt kết luận hợp lệ với lỗi/timeout. Lỗi thì hỏi lại an toàn.
    if rule is None and ctx.guardrail_llm is not None and not clear_in_scope:
        verdict = await ctx.guardrail_llm.classify(text)
        if verdict is None:
            rule = _UNKNOWN_SCOPE_RULE
            source = "llm unavailable/uncertain"
        elif verdict.code != "in_scope":
            rule = _RULES_BY_CODE.get(verdict.code)
            source = f"llm {verdict.confidence:.2f} — {verdict.reason}"
    elif rule is None and ctx.guardrail_llm is None and not clear_in_scope:
        rule = _UNKNOWN_SCOPE_RULE
        source = "classifier unavailable"

    if rule is not None:
        cot.append(f"guardrail: dừng sớm theo nhóm '{rule.code}' [{source}]")
        return {
            "normalized_input": text,
            "guardrail": {
                "code": rule.code,
                "message": rule.message,
                "suggestions": [dict(s) for s in rule.suggestions],
            },
            "cot": cot,
        }

    tiers = "regex (fast-path domain)" if clear_in_scope else (
        "regex" if ctx.guardrail_llm is None else "regex+llm"
    )
    cot.append(f"guardrail: pass (trong phạm vi hỗ trợ) [{tiers}]")
    # Trả None tường minh để xoá guardrail còn sót từ lượt trước (checkpointer
    # giữ state theo thread_id, không tự reset field này).
    return {"normalized_input": text, "guardrail": None, "cot": cot}
