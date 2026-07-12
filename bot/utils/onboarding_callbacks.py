"""Pure callback contracts for the guided onboarding flow."""
from __future__ import annotations

from typing import Optional


HAPP_DISTRIBUTIONS = {
    'ios': {'ru', 'global'},
    'android': {'google_play'},
    'windows': {'windows'},
    'macos': {'macos'},
}


def parse_happ_callback(data: str) -> Optional[tuple[str, str, int]]:
    """Parse new platform callbacks and legacy iOS region callbacks."""
    parts = data.split(':')
    if len(parts) == 3:
        _, distribution, raw_key_id = parts
        platform = 'ios'
    elif len(parts) == 4:
        _, platform, distribution, raw_key_id = parts
    else:
        return None

    if distribution not in HAPP_DISTRIBUTIONS.get(platform, set()):
        return None
    try:
        key_id = int(raw_key_id)
    except (TypeError, ValueError):
        return None
    return platform, distribution, key_id
