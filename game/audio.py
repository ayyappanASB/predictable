"""Sound effects and music. Audio is optional: if the mixer or a file is
unavailable the game simply stays silent instead of crashing."""

import os

import pygame

SOUND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "sounds")
NAMES = ("orb", "powerup", "close", "death", "level", "clear", "shield", "click",
         "surprise", "heartbeat", "confused", "taunt", "killcam", "music_a", "music_b")
VOLUMES = {"music_a": 0.22, "music_b": 0.22, "heartbeat": 0.6, "taunt": 0.35}


class Audio:
    def __init__(self):
        """Start the mixer and load every sound; missing audio just leaves the game silent."""
        self.sounds = {}
        self.muted = False
        self.track = None          # music the game wants playing (even while muted)
        self.channel = None
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.set_num_channels(16)
        except Exception:
            return
        for name in NAMES:
            try:
                snd = pygame.mixer.Sound(os.path.join(SOUND_DIR, name + ".ogg"))
                snd.set_volume(VOLUMES.get(name, 0.45))
                self.sounds[name] = snd
            except Exception:
                pass

    def play(self, name, volume=None):
        """Play a sound effect once (does nothing while muted).

        Args:
            name: one of NAMES, e.g. "orb" or "death".
            volume: optional volume 0..1 for this sound; None keeps the current one.
        """
        if self.muted:
            return
        snd = self.sounds.get(name)
        if snd is None:
            return
        try:
            if volume is not None:
                snd.set_volume(max(0.0, min(1.0, volume)))
            snd.play()
        except Exception:
            pass

    # ------------------------------------------------------------------ music
    def music(self, name):
        """Loop a music track; re-requesting the same track does nothing.

        Args:
            name: "music_a", "music_b" or None to stop the music.
        """
        if name == self.track and (self.channel is not None or self.muted):
            return
        self._stop_channel()
        self.track = name
        if name and not self.muted:
            self._start_channel()

    def _start_channel(self):
        """Start looping the current track on its own channel."""
        snd = self.sounds.get(self.track)
        if snd is None:
            return
        try:
            self.channel = snd.play(loops=-1)
        except Exception:
            self.channel = None

    def _stop_channel(self):
        """Stop the music channel if it is playing."""
        if self.channel is not None:
            try:
                self.channel.stop()
            except Exception:
                pass
        self.channel = None

    def toggle(self):
        """Mute or unmute all sound.

        Returns:
            True if the game is now muted.
        """
        self.muted = not self.muted
        if self.muted:
            self._stop_channel()
        elif self.track:
            self._start_channel()
        return self.muted
