"""Player commands (input-agnostic)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayerCommand:
    """Command applied to a ship on a single frame."""

    rotate_left: bool = False
    rotate_right: bool = False
    thrust: bool = False
    shoot: bool = False
    hyperspace: bool = False
    shield: bool = False
