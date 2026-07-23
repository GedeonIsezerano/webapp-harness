from __future__ import annotations
ALLOWED_TRANSITIONS = {
 'ready': {'implementing','blocked'},
 'implementing': {'verifying','blocked'},
 'verifying': {'implementing','reviewing','blocked'},
 'reviewing': {'implementing','completed','blocked'},
 'blocked': {'ready'},
 'completed': set(),
 'proposed': {'ready','blocked'},
}
TERMINAL_STATES={'completed','blocked'}
ACTIVE_STATES={'implementing','verifying','reviewing'}

def can_transition(source: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source,set())
