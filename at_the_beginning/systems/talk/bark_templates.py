from __future__ import annotations

"""Fallback bark templates for nearby audible NPC chatter."""


DEFAULT_BARK_TEMPLATES: dict[str, list[str]] = {
    "greet": [
        "Morning.",
        "You all right?",
        "Good to see you.",
    ],
    "warn": [
        "Stay close.",
        "Keep your eyes open.",
        "Something's wrong.",
    ],
    "fear": [
        "Run!",
        "Back away!",
        "Keep back!",
    ],
    "comfort": [
        "I'm here.",
        "Breathe slowly.",
        "You'll be all right.",
    ],
    "conflict": [
        "Watch yourself.",
        "Back off.",
        "I'm not asking twice.",
    ],
    "gossip": [
        "Did you hear that?",
        "Something strange is happening.",
        "People keep talking.",
    ],
    "trade": [
        "Need anything?",
        "I can trade.",
        "What's your offer?",
    ],
    "work": [
        "Keep moving.",
        "Let's finish this.",
        "One more load.",
    ],
    "alarm": [
        "Get down!",
        "Trouble!",
        "Move now!",
    ],
}


def bark_templates_for(speech_act: str) -> list[str]:
    return list(DEFAULT_BARK_TEMPLATES.get(str(speech_act or "").strip().lower(), []))


def choose_fallback_bark(speech_act: str, *, seed_hint: int = 0) -> str:
    templates = bark_templates_for(speech_act)
    if not templates:
        return "..."
    index = abs(int(seed_hint)) % len(templates)
    return str(templates[index])
