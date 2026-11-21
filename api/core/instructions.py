from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InstructionVerdict:
    kind: str
    priority: str
    reason: str = ""


_INTERRUPT_EXACT = re.compile(
    r"^\s*(?:(?:请|麻烦|先)\s*)*(?:please\s+)?(?:停止|停下|停下来|停一下|取消|中断|终止|暂停|别做了|不做了|不用了|算了|"
    r"stop|halt|abort|cancel|quit)\s*(?:当前|这个|上面|正在执行|正在做的)?\s*(?:任务|工作|需求|计划)?\s*[。.!！]?\s*$",
    re.IGNORECASE,
)

_STOP_CONTINUE_EXACT = re.compile(
    r"^\s*(?:不要|别|不用|先别|先不要)(?:再)?继续(?:了|啦|吧)?\s*[。.!！]?\s*$"
)

_INTERRUPT_PATTERNS = [
    re.compile(
        r"(?:停止|停下|停下来|停一下|取消|中断|终止|暂停|放弃|别做|不要做|不用做|不必做|先别|别继续|不要继续|不用继续)"
        r".{0,12}?(?:当前|这个|上面|之前|原来|正在|现在的?)?"
        r".{0,8}?(?:任务|工作|需求|执行|计划|事情)"
    ),
    re.compile(r"(?:不要|别|不用|先别|先不要)(?:再)?(?:管|做|继续|执行|处理)(?:上面|之前|原来|当前|这个)"),
    re.compile(r"(?:换个|换一个|换做|改做|改为做|改成做|切到|切换到)(?:任务|需求|方向|别的|其他)"),
    re.compile(r"(?:重新开始|从头开始|推倒重来)"),
    re.compile(
        r"\b(?:stop|cancel|abort|halt|terminate|quit|drop)\s+(?:the\s+)?"
        r"(?:current|this|ongoing|previous|above|running)\s+(?:task|work|job|run|request)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:stop|quit|cancel|abort)\s+(?:working|running)\b", re.IGNORECASE),
]

_NEGATED_INTERRUPT = re.compile(
    r"(?:不要|别|不用|无需|不必|勿|不)\s*(?:中断|停止|停下|取消|终止|暂停)"
    r"|\b(?:do not|don't|never)\s+(?:stop|interrupt|cancel|abort)\b",
    re.IGNORECASE,
)

_HIGH_PRIORITY = re.compile(
    r"(?:优先|优先级|先处理|先做|先帮我|先看|先跑|首先|马上|立刻|立即|紧急|急用|尽快|赶紧|现在(?:就|先)|"
    r"最高优先|第一优先)"
    r"|\b(?:urgent|asap|immediately|right away|priority|first|before (?:anything|continuing)|high priority)\b",
    re.IGNORECASE,
)

_CHATTER = re.compile(
    r"^\s*(?:好的?|好|嗯+|收到|明白了?|知道了?|谢谢|多谢|ok|okay|thanks|thank you|got it|cool|nice)\s*[。.!！]*\s*$",
    re.IGNORECASE,
)


def classify_instruction(text: str) -> InstructionVerdict:
    content = (text or "").strip()
    if not content or _CHATTER.match(content):
        return InstructionVerdict("chatter", "low", "acknowledgement")
    if _NEGATED_INTERRUPT.search(content):
        priority = "urgent" if _HIGH_PRIORITY.search(content) else "high"
        return InstructionVerdict("addition", priority, "negated stop")
    if _INTERRUPT_EXACT.match(content) or _STOP_CONTINUE_EXACT.match(content):
        return InstructionVerdict("interrupt", "urgent", "explicit stop")
    for pattern in _INTERRUPT_PATTERNS:
        if pattern.search(content):
            return InstructionVerdict("interrupt", "urgent", "explicit stop")
    priority = "urgent" if _HIGH_PRIORITY.search(content) else "high"
    return InstructionVerdict("addition", priority, "mid-task requirement")


def addition_message(content: str, priority: str = "high") -> str:
    level = "urgent" if priority == "urgent" else "high"
    return (
        f"[system: mid-task addition | priority: {level}]\n"
        "The user added a requirement while the current task is still running. Treat it as a parallel workstream: "
        "briefly acknowledge it, judge priority yourself, and handle it before lower-priority remaining work. "
        "Keep the original task and its progress; do not discard or restart it. If the addition conflicts with the "
        "original task, follow this addition for the conflicting part only. Only stop the original task if the user "
        "explicitly asks to interrupt or cancel it. If a plan is active, add or update a step for this addition "
        "without erasing completed steps. If you are blocked on a command or approval, state the next step for the "
        "addition first.\n\n"
        "Added requirement:\n" + content
    )


def interrupt_notice() -> str:
    return (
        "[system: the user explicitly interrupted the previous task]\n"
        "The previous task was cancelled at the user's request. Do not resume or continue the interrupted work "
        "unless the newest request depends on it. The previous plan has been cleared. Focus on the newest user "
        "message."
    )


def interrupt_message(content: str) -> str:
    return interrupt_notice() + "\n\nNewest user request:\n" + content
