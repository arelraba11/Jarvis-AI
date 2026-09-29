"""The stub orchestrator: the one tool every candidate gets, with canned Hebrew answers.

The real orchestrator doesn't exist yet (Phase 2). Here ask_orchestrator logs the request text,
which is what comprehension is scored on, and returns a fixed answer for the current example.
"""

TOOL = {
    "name": "ask_orchestrator",
    "description": (
        "Jarvis's orchestrator knows the user (calendar, meetings, email, contacts, notes, "
        "personal details) and can act for them. Call it for every question or request about "
        "the user or their data. It does not hear the conversation: it sees only `request`, "
        "so the request must be complete and self-contained."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": (
                    "The complete request in Hebrew, understandable on its own: every name, "
                    "day, date and time the user said, kept as said. No references to earlier "
                    "turns: write out what they refer to."
                ),
            }
        },
        "required": ["request"],
    },
}

_TOMORROW = "מחר יש לך פגישת צוות בעשר, ארוחת צהריים עם נועה באחת, ושיחה עם רואה החשבון בארבע."
# Example 7 needs an answer long enough to interrupt in the middle of it.
_TOMORROW_LONG = (
    "מחר יש לך יום עמוס. בשמונה וחצי סטנדאפ של הצוות, בעשר פגישת תכנון רבעוני עם יעל ואבי, "
    "באחת ארוחת צהריים עם נועה בתל אביב, בשלוש שיחת זום עם הלקוח מלונדון, "
    "בארבע וחצי שיחה עם רואה החשבון על הדוחות, ובשבע בערב אימון בחדר הכושר."
)
_THURSDAY = "ביום חמישי יש לך רק פגישה אחת: סקירת פרויקט עם דני באחת עשרה."
_ZOOM = "כן, יש לך שיחת זום עם הלקוח מלונדון היום בשלוש."
_SCHEDULE = "יצרתי טיוטה לפגישה ב־14 באוקטובר בתשע ורבע. היא מחכה לאישור שלך על המסך."

# One list of answers per example (see the conversation script in README.md).
# The n-th tool call in a session gets the n-th answer; the last one repeats.
CANNED: dict[int, list[str]] = {
    1: [_TOMORROW],
    2: ["הצעתי להזיז את הפגישה עם דני ליום חמישי בשלוש וחצי. היא מחכה לאישור שלך על המסך."],
    3: ["הכנתי טיוטת תשובה שאתה מאשר ליום ראשון. היא מחכה לאישור שלך על המסך."],
    4: ["בעל הדירה כתב שהחוזה מוארך בשנה, והשכירות עולה בשלוש מאות שקל מינואר."],
    5: [_ZOOM],
    6: [_SCHEDULE],
    7: [_TOMORROW_LONG, _THURSDAY],
    8: [_TOMORROW, _ZOOM, _SCHEDULE],
}


class StubOrchestrator:
    def __init__(self, example: int) -> None:
        self.answers = CANNED[example]
        self.calls = 0

    def ask(self, request: str) -> str:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer
