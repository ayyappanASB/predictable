"""Record a backup demo video of PREDICTABLE straight from the game engine.

Every frame is rendered by the real game (headless, at 1080p) and piped into ffmpeg, so the
video is perfectly smooth with no cursor or screen-capture artefacts. Sound effects and music
are the game's own sounds, mixed at the exact frames the game asked for them.

    python tools/record_demo.py [output.mp4]

The run is the real AI against an evasive bot (seed 69): it reaches level 5 and is caught by
a prediction made 5 moves earlier. Nothing in the gameplay is scripted except the player's input.
"""

import array
import os
import random
import subprocess
import sys
import tempfile
import wave

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import pygame  # noqa: E402

from game import config as C, storage  # noqa: E402
from game.app import App  # noqa: E402
from game.audio import SOUND_DIR, VOLUMES  # noqa: E402
from game.world import World  # noqa: E402
from experiment import evasive_direction  # noqa: E402

W, H, FPS = 1920, 1080, 60
BAND = 88                          # caption band under the game, so captions never cover play
GAME_H = H - BAND
SEED = 69
RATE = 44100
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Documents/Balasubramanian_Ayyappan_PREDICTABLE_Demo.mp4")
storage.DESKTOP_FILE = os.path.join(tempfile.gettempdir(), "predictable_demo_save.json")
if os.path.exists(storage.DESKTOP_FILE):
    os.remove(storage.DESKTOP_FILE)

CYAN, PINK, TEXT, MUTED, BG = C.PLAYER, C.HUNTER, C.TEXT, C.MUTED, C.BG


class FakeClock:
    def tick(self, fps=0):
        """Exactly one 60 fps frame in milliseconds; `fps` is ignored."""
        return 1000.0 / FPS


class Recorder:
    """Collects frames (piped to ffmpeg), captions, fades and the sound timeline."""

    def __init__(self):
        """Start ffmpeg reading raw RGB frames from a pipe."""
        self.video_tmp = os.path.join(tempfile.gettempdir(), "predictable_demo_video.mp4")
        self.ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
             "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", self.video_tmp],
            stdin=subprocess.PIPE)
        self.frame_no = 0
        self.sounds = []            # (frame, name, volume)
        self.music = []             # (frame, track or None)
        self.caption = None         # (title, text, start_frame)
        self.fonts = {}
        self.canvas = pygame.Surface((W, H))

    def font(self, size, bold=False):
        """Cached pygame default font at `size` pixels (`bold` for headings)."""
        key = (size, bold)
        if key not in self.fonts:
            f = pygame.font.Font(None, size)
            f.set_bold(bold)
            self.fonts[key] = f
        return self.fonts[key]

    def say(self, title, text):
        """Show a caption (in the band under the game) with a short `title` and an explanation `text`."""
        self.caption = (title, text, self.frame_no)

    def hush(self):
        """Hide the caption (it fades out)."""
        if self.caption:
            self.caption = (*self.caption[:2], -self.frame_no)

    def hook_audio(self, app):
        """Record every sound and music change the game requests (with the frame it happens on).

        Args:
            app: the App whose Audio object is wrapped.
        """
        rec = self

        def play(name, volume=None):
            """Log a sound effect at the current frame; `name` and `volume` as in Audio.play."""
            rec.sounds.append((rec.frame_no, name, VOLUMES.get(name, 0.45) if volume is None else volume))

        def music(name):
            """Log a music change at the current frame; `name` is a track or None."""
            if not rec.music or rec.music[-1][1] != name:
                rec.music.append((rec.frame_no, name))
        app.audio.play = play
        app.audio.music = music

    def _caption_alpha(self):
        """Opacity 0..1 of the caption for the current frame (fade in / fade out)."""
        title, text, start = self.caption
        if start >= 0:
            return min(1.0, (self.frame_no - start) / 12)
        return max(0.0, 1 - (self.frame_no + start) / 12)

    def draw_caption(self, surf):
        """Draw the current caption in the band under the game on `surf` (a 1920x1080 frame)."""
        if not self.caption:
            return
        a = self._caption_alpha()
        if a <= 0:
            if self.caption[2] < 0:            # finished fading out (a new caption starts at 0)
                self.caption = None
            return
        title, text = self.caption[:2]
        ts = self.font(44, True).render(title, True, CYAN)
        dot = self.font(40).render("   ·   ", True, MUTED)
        bs = self.font(40).render(text, True, TEXT)
        w = ts.get_width() + dot.get_width() + bs.get_width()
        line = pygame.Surface((w, max(ts.get_height(), bs.get_height())), pygame.SRCALPHA)
        line.blit(ts, (0, 0))
        line.blit(dot, (ts.get_width(), 3))
        line.blit(bs, (ts.get_width() + dot.get_width(), 3))
        line.set_alpha(int(255 * a))
        surf.blit(line, ((W - w) // 2, GAME_H + (BAND - line.get_height()) // 2 + 2))

    def push(self, surf, fade=1.0):
        """Add one frame: `surf` (already 1920x1080) with caption, dimmed by `fade` (0..1)."""
        self.draw_caption(surf)
        if fade < 1.0:
            dark = pygame.Surface((W, H))
            dark.set_alpha(int(255 * (1 - fade)))
            surf.blit(dark, (0, 0))
        self.ff.stdin.write(pygame.image.tobytes(surf, "RGB"))
        self.frame_no += 1

    def push_app(self, app, fade=1.0):
        """Add the app's current screen as a frame, centred above the caption band.

        Args:
            app: the App that just drew a frame.
            fade: brightness 0..1 for fades.
        """
        scr = app.screen
        self.canvas.fill(BG)
        sw, sh = scr.get_size()
        k = min(1.0, W / sw, GAME_H / sh)
        img = scr if k == 1 else pygame.transform.smoothscale(scr, (round(sw * k), round(sh * k)))
        self.canvas.blit(img, ((W - img.get_width()) // 2, (GAME_H - img.get_height()) // 2))
        frame = self.canvas.copy()
        self.push(frame, fade)

    def finish_video(self):
        """Close the ffmpeg pipe and wait for the encoder."""
        self.ff.stdin.close()
        self.ff.wait()


def load_pcm(name):
    """Decode assets/sounds/<name>.ogg to a mono float array at RATE Hz."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", os.path.join(SOUND_DIR, name + ".ogg"),
                          "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"],
                         capture_output=True, check=True).stdout
    a = array.array("f")
    a.frombytes(raw)
    return a


def build_audio(rec, path):
    """Mix the recorded sound and music timeline into a WAV file.

    Args:
        rec: the Recorder holding the timeline.
        path: where to write the 16-bit stereo WAV.
    """
    n = int(rec.frame_no / FPS * RATE) + RATE
    mix = array.array("f", bytes(4 * n))
    cache = {}
    def pcm(name):
        """Decoded samples of sound `name` (cached)."""
        if name not in cache:
            cache[name] = load_pcm(name)
        return cache[name]
    for frame, name, vol in rec.sounds:
        s, start = pcm(name), int(frame / FPS * RATE)
        for i in range(min(len(s), n - start)):
            mix[start + i] += s[i] * vol
    changes = rec.music + [(rec.frame_no, None)]
    for (f0, track), (f1, _) in zip(changes, changes[1:]):
        if not track:
            continue
        s, a0, a1 = pcm(track), int(f0 / FPS * RATE), min(n, int(f1 / FPS * RATE))
        vol, L = VOLUMES.get(track, 0.22), len(s)
        for i in range(a1 - a0):
            mix[a0 + i] += s[i % L] * vol
    peak = max(1.0, max(abs(v) for v in mix) / 0.9)
    out = array.array("h", (int(max(-1.0, min(1.0, v / peak)) * 32000) for v in mix for _ in (0, 1)))
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(out.tobytes())


def frames(rec, app, n, before=None, fade_in=0, fade_out=0):
    """Run the game for `n` frames, recording each one.

    Args:
        rec: the Recorder.
        app: the App to run.
        n: number of frames.
        before: optional function called before every frame (player input).
        fade_in: frames of fade-in at the start.
        fade_out: frames of fade-out at the end.
    """
    for i in range(n):
        if before:
            before()
        app.frame()
        fade = 1.0
        if fade_in and i < fade_in:
            fade = i / fade_in
        if fade_out and i >= n - fade_out:
            fade = (n - 1 - i) / fade_out
        rec.push_app(app, fade)


def make_app(layout, scale):
    """A headless App with a fixed clock, no performance step-down and seeded visuals.

    Args:
        layout: "desktop" or "portrait".
        scale: drawing scale (the desktop uses 1080 / 620 so the video is 1080p).
    """
    random.seed(SEED)
    app = App(layout=layout, scale=scale)
    app.clock = FakeClock()
    app.watch_performance = lambda work: None      # keep a fixed resolution while recording
    pygame.event.set_blocked(getattr(pygame, "WINDOWFOCUSLOST", pygame.NOEVENT))
    return app


def end_card(rec, n):
    """Closing card with the link and the author (fades in and out).

    Args:
        rec: the Recorder to add the frames to.
        n: length of the card in frames.
    """
    big, mid, small = rec.font(150, True), rec.font(60), rec.font(42)
    for i in range(n):
        s = pygame.Surface((W, H))
        s.fill(BG)
        t = big.render("PREDICTABLE", True, TEXT)
        s.blit(t, ((W - t.get_width()) // 2, 300))
        tag = mid.render("It learns how you move.", True, MUTED)
        s.blit(tag, ((W - tag.get_width()) // 2, 450))
        link = mid.render("Play it:  predictable-pi.vercel.app", True, CYAN)
        s.blit(link, ((W - link.get_width()) // 2, 590))
        who = small.render("Balasubramanian Ayyappan  ·  3073JDDJ  ·  5FTC2067 AI Principles", True, MUTED)
        s.blit(who, ((W - who.get_width()) // 2, 700))
        fade = min(1.0, i / 20, (n - 1 - i) / 30)
        rec.push(s, fade)


def main():
    """Record the whole demo: desktop run, pause menu, phone layout and end card."""
    pygame.init()
    rec = Recorder()
    app = make_app("desktop", GAME_H / 620)        # 1600 x 992, drawn natively (sharp)
    rec.hook_audio(app)
    print("desktop frame", app.screen.get_size())

    # 1. title screen (the game is silent here; the video gets the game's own music as a bed)
    rec.music.append((rec.frame_no, "music_a"))
    rec.say("PREDICTABLE", "A chase game where the AI learns how you move")
    frames(rec, app, 300, fade_in=30)
    rec.hush()

    # 2. how-to-play guide
    app.do_action("guide", "demo")
    rec.say("HOW TO PLAY", "Built-in illustrated guide  ·  the info button or H")
    for page in range(7):
        app.guide_page = page
        frames(rec, app, 84)
    app.close_guide()
    rec.hush()
    frames(rec, app, 30)

    # 3. the real run: the AI against an evasive player bot (seed 69)
    app.start_run()
    app.world = World(seed=SEED, predictor=app.predictor)
    app.on_world_events(app.world.pop_events())       # level-1 sound + music, as in a normal start
    shown = set()
    captions = {
        1: ("LEVEL 1  ·  WANDERER", "A random walk  ·  the player collects orbs and must not be touched"),
        2: ("LEVEL 2  ·  CHASER", "Greedy hill-climbing: always steps closer, gets stuck behind walls"),
        3: ("LEVEL 3  ·  TRACKER  ·  AI VISION ON", "A* search: the line is the hunter's planned shortest path"),
        4: ("LEVEL 4  ·  MIND READER", "A Markov model predicts the next moves; the dots are its forecast"),
        5: ("LEVEL 5  ·  THE PACK", "Two hunters: one chases with A*, one ambushes with predictions"),
    }
    state = {"confused_said": False, "kill_said": False, "hush_at": None}

    def player_input():
        """Steer the evasive bot and trigger captions as the run unfolds."""
        w = app.world
        if w.phase == "intro" and w.level_no not in shown:
            shown.add(w.level_no)
            rec.say(*captions.get(w.level_no, ("THE GAUNTLET", "Mind Reader + Mirror")))
            state["hush_at"] = rec.frame_no + 330
            if w.level_no == 3:
                app.renderer.vision = True
        if w.confused and not state["confused_said"] and w.level_no >= 4:
            state["confused_said"] = True
            rec.say("SURPRISE THE AI", "Fooling confident predictions fills the CHAOS meter: hunters get confused")
            state["hush_at"] = rec.frame_no + 300
        if w.phase == "killcam" and not state["kill_said"]:
            state["kill_said"] = True
            rec.say("KILL-CAM", w.killcam["caption"].capitalize() + "  ·  the habit that gave it away")
            state["hush_at"] = None
        if state["hush_at"] and rec.frame_no >= state["hush_at"]:
            rec.hush()
            state["hush_at"] = None
        if w.phase == "play" and w.orb:
            w.steer(evasive_direction(w))

    while app.state == "play":
        frames(rec, app, 1, before=player_input)
    rec.hush()

    # 4. results card (music bed again after the death sting)
    rec.music.append((rec.frame_no + 45, "music_a"))
    rec.say("RESULTS", "How much of the player the AI read, the habit it found, and a player type")
    frames(rec, app, 420)
    rec.hush()

    # 5. play again + pause menu (How to play / Support)
    app.over_timer = 0
    app.on_key(pygame.K_SPACE)
    app.world = World(seed=SEED + 1, predictor=app.predictor)
    frames(rec, app, 200, before=lambda: app.world.phase == "play" and app.world.orb
           and app.world.steer(evasive_direction(app.world)))
    app.pause()
    rec.say("PAUSE MENU", "How to play and Support: players can send bug reports straight to the developer")
    frames(rec, app, 300, fade_out=24)
    rec.hush()

    # 6. the same game on a phone (portrait layout, D-pad)
    pygame.quit()
    pygame.init()
    rec.fonts.clear()
    rec.canvas = pygame.Surface((W, H))
    phone = make_app("portrait", 1.0)
    rec.hook_audio(phone)
    phone.audio.muted = False
    phone.start_run()
    phone.world = World(seed=SEED + 2, predictor=phone.predictor)
    phone.on_world_events(phone.world.pop_events())
    phone.renderer.vision = True
    rec.say("ON A PHONE", "Same Python game in the browser: D-pad, swipes and touch buttons")

    def thumb():
        """Steer with the on-screen D-pad (shown pressed) like a player's thumb."""
        w = phone.world
        if w.phase == "play" and w.orb:
            d = evasive_direction(w)
            phone.pad = {1: d}
            w.steer(d)
    frames(rec, phone, 540, before=thumb, fade_in=24, fade_out=24)
    rec.hush()

    # 7. end card
    end_card(rec, 240)
    rec.finish_video()
    print("frames", rec.frame_no, "=", round(rec.frame_no / FPS, 1), "s; sounds", len(rec.sounds))

    wav = os.path.join(tempfile.gettempdir(), "predictable_demo_audio.wav")
    build_audio(rec, wav)
    dur = rec.frame_no / FPS
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", rec.video_tmp, "-i", wav,
                    "-af", f"afade=t=in:d=0.6,afade=t=out:st={dur - 3:.2f}:d=3",   # match the picture fades
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT],
                   check=True)
    print("saved", OUT)


if __name__ == "__main__":
    main()
