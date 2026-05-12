#!/usr/bin/env python3
"""Chrome Dinosaur Game -- terminal clone.

Run:    python3 dino.py
Test:   python3 dino.py --test
"""
import curses
import json
import random
import sys
import time
from pathlib import Path

# ---------- tuning ----------
FRAME = 1 / 30.0
GRAVITY = 0.05
JUMP_V = -0.7
FAST_FALL = 0.20
START_SPEED = 14.0
MAX_SPEED = 22.0
SPEED_RAMP = 0.015  # per frame
DINO_X = 6
MIN_COLS, MIN_ROWS = 60, 15
HI_PATH = Path.home() / ".dinosaur-game-cli" / "highscore.json"

RUN, JUMP, DUCK, DEAD = range(4)


# ---------- sprites ----------
class Sprite:
    __slots__ = ("rows", "w", "h", "cells")

    def __init__(self, s):
        lines = s.strip("\n").splitlines()
        w = max((len(ln) for ln in lines), default=0)
        rows = [ln + " " * (w - len(ln)) for ln in lines]
        cells = frozenset(
            (y, x)
            for y, row in enumerate(rows)
            for x, c in enumerate(row)
            if c != " "
        )
        self.rows, self.w, self.h, self.cells = rows, w, len(rows), cells


DINO_RUN_A = Sprite(r"""
    __
   / _)
  / /
 /_/
   //
""")

DINO_RUN_B = Sprite(r"""
    __
   / _)
  / /
 /_/
   \\
""")

DINO_DUCK = Sprite(r"""
        __
  _____/_)
 /____/
""")

DINO_DEAD = Sprite(r"""
    __
   /x_)
  / /
 /_/
   ||
""")

CACTUS_SMALL = Sprite(r"""
 |
(|)
 |
""")

CACTUS_LARGE = Sprite(r"""
 |
(|)
 |
 |
""")

CACTUS_CLUSTER = Sprite(r"""
 |   |
(|) (|)
 |   |
 |   |
""")

PTERO_A = Sprite(r"""
 \__/
~~~~~~
""")

PTERO_B = Sprite(r"""
 _/\_
 ~~~~
""")

CLOUD = Sprite(r"""
 ___
(___)
""")

MOON = Sprite(r"""
 ()
(  )
 ()
""")

CACTI = [CACTUS_SMALL, CACTUS_LARGE, CACTUS_CLUSTER]


# ---------- persistence ----------
class HighScore:
    @staticmethod
    def load():
        try:
            return int(json.loads(HI_PATH.read_text())["hi"])
        except Exception:
            return 0

    @staticmethod
    def save(v):
        try:
            HI_PATH.parent.mkdir(parents=True, exist_ok=True)
            HI_PATH.write_text(json.dumps({"hi": int(v)}))
        except Exception:
            pass


# ---------- entities ----------
class Dino:
    def __init__(self, ground_y):
        self.ground_y = ground_y
        self.y = float(ground_y - DINO_RUN_A.h + 1)
        self.vy = 0.0
        self.state = RUN
        self.duck_timer = 0
        self.fast_fall = False
        self.cycle = 0

    @property
    def sprite(self):
        if self.state == DEAD:
            return DINO_DEAD
        if self.state == DUCK:
            return DINO_DUCK
        return DINO_RUN_A if (self.cycle // 4) % 2 == 0 else DINO_RUN_B

    def jump(self):
        if self.state == RUN:
            self.vy = JUMP_V
            self.state = JUMP
            self.duck_timer = 0

    def duck_press(self):
        if self.state == JUMP:
            self.fast_fall = True
        elif self.state in (RUN, DUCK):
            self.duck_timer = 8
            self.state = DUCK

    def tick(self):
        self.cycle += 1
        if self.state == DEAD:
            return
        if self.state == JUMP:
            self.vy += GRAVITY
            if self.fast_fall:
                self.vy += FAST_FALL
            self.y += self.vy
            floor = float(self.ground_y - DINO_RUN_A.h + 1)
            if self.y >= floor:
                self.y = floor
                self.vy = 0.0
                self.state = RUN
                self.fast_fall = False
        elif self.state == DUCK:
            if self.duck_timer > 0:
                self.duck_timer -= 1
            else:
                self.state = RUN
            self.y = float(
                self.ground_y - (DINO_DUCK.h if self.state == DUCK else DINO_RUN_A.h) + 1
            )
        else:
            self.y = float(self.ground_y - DINO_RUN_A.h + 1)

    def cells_world(self):
        sp = self.sprite
        oy, ox = int(self.y), DINO_X
        return {(oy + cy, ox + cx) for (cy, cx) in sp.cells}


class Obstacle:
    def __init__(self, sprite, x, ground_y):
        self.sprite = sprite
        self.x = float(x)
        self.y = ground_y - sprite.h + 1

    def update(self, dx):
        self.x -= dx

    def offscreen(self):
        return self.x + self.sprite.w < 0

    def cells_world(self):
        oy, ox = self.y, int(self.x)
        return {(oy + cy, ox + cx) for (cy, cx) in self.sprite.cells}


class Pterodactyl(Obstacle):
    def __init__(self, x, ground_y):
        super().__init__(PTERO_A, x, ground_y)
        # low forces duck, ground-level forces jump
        if random.random() < 0.55:
            self.y = ground_y - 4   # duck under
        else:
            self.y = ground_y - 1   # jump over
        self.flap = 0

    def update(self, dx):
        super().update(dx * 1.15)
        self.flap += 1
        self.sprite = PTERO_A if (self.flap // 5) % 2 == 0 else PTERO_B


class Cloud:
    def __init__(self, x, y):
        self.x = float(x)
        self.y = y

    def update(self, dx):
        self.x -= dx * 0.3

    def offscreen(self):
        return self.x + CLOUD.w < 0


# ---------- world ----------
class World:
    def __init__(self, H, W):
        self.H, self.W = H, W
        self.ground_y = H // 2
        self.dino = Dino(self.ground_y)
        self.obstacles = []
        self.clouds = []
        self.dist = 0.0
        self.speed = START_SPEED
        self.spawn_cd = 8.0
        self.cloud_cd = 3.0
        self.hi = HighScore.load()
        self.quit = False
        self.state = "TITLE"
        self.last_bell = 0

    def score(self):
        return int(self.dist / 4)

    def is_night(self):
        return (self.score() // 700) % 2 == 1

    def start(self):
        self.state = "PLAY"

    def restart(self):
        hi = self.hi
        self.__init__(self.H, self.W)
        self.hi = hi
        self.state = "PLAY"

    def jump(self):
        if self.state == "PLAY":
            self.dino.jump()

    def duck_press(self):
        if self.state == "PLAY":
            self.dino.duck_press()

    def tick(self):
        if self.state != "PLAY":
            return
        dx = self.speed / 30.0
        self.dist += dx
        self.speed = min(MAX_SPEED, self.speed + SPEED_RAMP)

        self.dino.tick()

        self.spawn_cd -= dx
        if self.spawn_cd <= 0 and (
            not self.obstacles or self.obstacles[-1].x < self.W - 25
        ):
            self._spawn_obstacle()
            self.spawn_cd = random.uniform(
                max(20, 60 / self.speed), max(35, 100 / self.speed)
            )

        self.cloud_cd -= dx
        if self.cloud_cd <= 0:
            self.clouds.append(
                Cloud(self.W + 2, random.randint(1, max(2, self.ground_y // 3)))
            )
            self.cloud_cd = random.uniform(20, 50)

        for o in self.obstacles:
            o.update(dx)
        for c in self.clouds:
            c.update(dx)
        self.obstacles = [o for o in self.obstacles if not o.offscreen()]
        self.clouds = [c for c in self.clouds if not c.offscreen()]

        dcells = self.dino.cells_world()
        for o in self.obstacles:
            if dcells & o.cells_world():
                self.dino.state = DEAD
                self.state = "DEAD"
                if self.score() > self.hi:
                    self.hi = self.score()
                    HighScore.save(self.hi)
                break

        s = self.score()
        if s // 100 > self.last_bell:
            self.last_bell = s // 100
            try:
                curses.beep()
            except curses.error:
                pass

    def _spawn_obstacle(self):
        if self.score() > 450 and random.random() < 0.28:
            self.obstacles.append(Pterodactyl(self.W + 1, self.ground_y))
        else:
            self.obstacles.append(
                Obstacle(random.choice(CACTI), self.W + 1, self.ground_y)
            )


# ---------- render ----------
def _safe_addch(stdscr, y, x, ch, attr):
    try:
        stdscr.addch(y, x, ch, attr)
    except curses.error:
        pass


def _safe_addstr(stdscr, y, x, s, attr):
    try:
        stdscr.addstr(y, x, s, attr)
    except curses.error:
        pass


def draw_sprite(stdscr, sprite, y, x, attr=0):
    H, W = stdscr.getmaxyx()
    for dy, row in enumerate(sprite.rows):
        ry = y + dy
        if ry < 0 or ry >= H:
            continue
        for dx, c in enumerate(row):
            if c == " ":
                continue
            rx = x + dx
            if rx < 0 or rx >= W:
                continue
            if ry == H - 1 and rx == W - 1:
                continue  # bottom-right would scroll
            _safe_addch(stdscr, ry, rx, c, attr)


def render(stdscr, world):
    stdscr.erase()
    H, W = stdscr.getmaxyx()
    night = world.is_night()
    attr = curses.A_REVERSE if night else 0

    if night:
        line = " " * max(0, W - 1)
        for y in range(H):
            _safe_addstr(stdscr, y, 0, line, curses.A_REVERSE)

    for c in world.clouds:
        sp = MOON if night else CLOUD
        draw_sprite(stdscr, sp, c.y, int(c.x), attr)

    gy = world.ground_y + 1
    if gy < H:
        _safe_addstr(stdscr, gy, 0, "-" * max(0, W - 1), attr)

    for o in world.obstacles:
        draw_sprite(stdscr, o.sprite, o.y, int(o.x), attr)

    draw_sprite(stdscr, world.dino.sprite, int(world.dino.y), DINO_X, attr)

    hud_left = f"HI {world.hi:05d}"
    hud_right = f"{world.score():05d}"
    hud_y = min(H - 1, world.ground_y + 2)
    _safe_addstr(stdscr, hud_y, 1, hud_left, attr | curses.A_DIM)
    _safe_addstr(
        stdscr, hud_y, max(0, W - len(hud_right) - 2), hud_right, attr | curses.A_BOLD
    )

    if world.state == "TITLE":
        msg = "DINOSAUR  --  SPACE to start, Q to quit"
        _safe_addstr(
            stdscr, H // 2, max(0, (W - len(msg)) // 2), msg, attr | curses.A_BOLD
        )
    elif world.state == "DEAD":
        m1 = "G A M E   O V E R"
        m2 = "press R to restart, Q to quit"
        _safe_addstr(
            stdscr, H // 2 - 1, max(0, (W - len(m1)) // 2), m1, attr | curses.A_BOLD
        )
        _safe_addstr(stdscr, H // 2 + 1, max(0, (W - len(m2)) // 2), m2, attr)

    stdscr.noutrefresh()
    curses.doupdate()


# ---------- main loop ----------
def _too_small(stdscr):
    H, W = stdscr.getmaxyx()
    return H < MIN_ROWS or W < MIN_COLS


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    if _too_small(stdscr):
        stdscr.nodelay(False)
        _safe_addstr(
            stdscr, 0, 0, f"Terminal too small. Need >= {MIN_COLS}x{MIN_ROWS}.", 0
        )
        stdscr.getch()
        return

    H, W = stdscr.getmaxyx()
    world = World(H, W)

    while not world.quit:
        t0 = time.monotonic()

        while True:
            ch = stdscr.getch()
            if ch == -1:
                break
            if ch == curses.KEY_RESIZE:
                H, W = stdscr.getmaxyx()
                if _too_small(stdscr):
                    world.state = "TITLE"
                world = World(H, W)
                continue
            if world.state == "TITLE":
                if ch in (ord(" "), curses.KEY_UP, ord("w"), 10, 13):
                    world.start()
                elif ch in (ord("q"), ord("Q"), 27):
                    world.quit = True
            elif world.state == "PLAY":
                if ch in (ord(" "), curses.KEY_UP, ord("w")):
                    world.jump()
                elif ch in (curses.KEY_DOWN, ord("s")):
                    world.duck_press()
                elif ch in (ord("q"), ord("Q"), 27):
                    world.quit = True
            elif world.state == "DEAD":
                if ch in (ord("r"), ord("R")):
                    world.restart()
                elif ch in (ord("q"), ord("Q"), 27):
                    world.quit = True

        world.tick()
        render(stdscr, world)

        dt = time.monotonic() - t0
        if dt < FRAME:
            time.sleep(FRAME - dt)


def collide_test():
    w = World(24, 80)
    o = Obstacle(CACTUS_SMALL, DINO_X, w.ground_y)
    assert w.dino.cells_world() & o.cells_world(), "expected overlap"
    o2 = Obstacle(CACTUS_SMALL, 70, w.ground_y)
    assert not (w.dino.cells_world() & o2.cells_world()), "expected no overlap"
    # ducking dino should clear a low ptero
    w.dino.duck_press()
    w.dino.tick()
    low = Pterodactyl(DINO_X, w.ground_y)
    low.y = w.ground_y - 4  # force the duck-under variant
    assert not (
        w.dino.cells_world() & low.cells_world()
    ), "ducking dino should clear low-ptero"
    print("collide_test: OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        collide_test()
    else:
        try:
            curses.wrapper(main)
        except KeyboardInterrupt:
            pass
