from __future__ import annotations

ALLOWED_TRANSITIONS = {
    "proposed": {"ready", "blocked", "cancelled", "superseded"},
    "ready": {"implementing", "blocked", "cancelled", "superseded"},
    "implementing": {"verifying", "blocked"},
    "verifying": {"implementing", "reviewing", "blocked"},
    "reviewing": {"implementing", "browser_validating", "completed", "blocked"},
    "browser_validating": {"implementing", "completed", "blocked"},
    "blocked": {"ready", "cancelled", "superseded"},
    "completed": set(),
    "cancelled": set(),
    "superseded": set(),
}
TERMINAL_STATES = {"completed", "cancelled", "superseded"}
ACTIVE_STATES = {
    "implementing",
    "verifying",
    "reviewing",
    "browser_validating",
}
RETIRED_STATES = {"cancelled", "superseded"}

def can_transition(source: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, set())
