"""Local input reading and conversion to PlayerCommand."""

import pygame as pg

from core.commands import PlayerCommand


class InputMapper:
    """Converts keyboard input and events into PlayerCommand."""

    def __init__(self) -> None:
        self._shoot_pressed = False
        self._hyper_pressed = False
        self._shield_pressed = False

    def handle_event(self, event: pg.event.Event) -> None:
        if event.type != pg.KEYDOWN:
            return

        if event.key == pg.K_SPACE:
            self._shoot_pressed = True
        elif event.key == pg.K_LSHIFT:
            self._hyper_pressed = True
        elif event.key == pg.K_DOWN:
            self._shield_pressed = True

    def build_command(self, keys: pg.key.ScancodeWrapper) -> PlayerCommand:
        rotate_left = keys[pg.K_LEFT] or keys[pg.K_a]
        rotate_right = keys[pg.K_RIGHT] or keys[pg.K_d]
        thrust = keys[pg.K_UP] or keys[pg.K_w]

        cmd = PlayerCommand(
            rotate_left=rotate_left,
            rotate_right=rotate_right,
            thrust=thrust,
            shoot=self._shoot_pressed,
            hyperspace=self._hyper_pressed,
            shield=self._shield_pressed,
        )

        self._shoot_pressed = False
        self._hyper_pressed = False
        self._shield_pressed = False
        return cmd
