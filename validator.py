from __future__ import annotations

import re


_INSTRUCTION_HINTS = (
    "create ",
    "write ",
    "fix ",
    "refactor ",
    "update ",
    "ensure ",
    "use aider",
    "script ",
    "reads from",
    "prints ",
    "should ",
)


def _parse_file_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _looks_like_instruction(text: str) -> bool:
    lower = text.strip().lower()
    if not lower:
        return False
    words = re.findall(r"[a-z0-9_]+", lower)
    if "\n" in lower and len(words) >= 6:
        return True
    if len(lower) > 140 and len(words) >= 8:
        return True
    if any(hint in lower for hint in _INSTRUCTION_HINTS) and len(words) >= 4:
        return True
    if lower.endswith(".") and len(words) >= 6:
        return True
    return False


def _looks_like_file_token(token: str) -> bool:
    text = token.strip()
    if not text or "\n" in text or len(text) > 160:
        return False
    if _looks_like_instruction(text):
        return False
    if any(ch in text for ch in ("/", "\\")):
        return True
    if "." in text:
        return True
    if re.fullmatch(r"[\w -]{1,80}", text) and len(text.split()) <= 4:
        return True
    return False


def validate_args(args: dict, context: dict) -> list[str]:
    errors: list[str] = []

    message = args.get("message")
    if not isinstance(message, str) or not message.strip():
        errors.append("`message` is required and must contain the aider instruction.")

    for field in ("files", "read_only_files"):
        value = args.get(field)
        if not isinstance(value, str):
            continue
        raw = value.strip()
        if not raw:
            continue
        if _looks_like_instruction(raw):
            errors.append(
                f"`{field}` must contain comma-separated file paths only; "
                "move the instruction text into `message`."
            )
            continue
        invalid = [item for item in _parse_file_list(raw) if not _looks_like_file_token(item)]
        if invalid:
            shown = ", ".join(repr(item) for item in invalid[:3])
            errors.append(
                f"`{field}` must contain comma-separated file paths only; "
                f"invalid entries: {shown}."
            )

    return errors


def repair_args(args: dict, context: dict) -> dict:
    repaired = dict(args)
    if isinstance(repaired.get("message"), str):
        repaired["message"] = repaired["message"].strip()
    for field in ("files", "read_only_files"):
        value = repaired.get(field)
        if isinstance(value, str):
            repaired[field] = ", ".join(_parse_file_list(value))
    return repaired
