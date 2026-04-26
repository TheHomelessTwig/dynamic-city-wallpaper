#!/usr/bin/env python3
"""
dynamic-city — animated pixel art wallpaper for Wayland desktops.

Usage:
  python3 dynamic-city.py --init                                        # interactive setup
  python3 dynamic-city.py --preview [period]                            # instant preview
  python3 dynamic-city.py --preview night --rain 3 --lightning 1        # override for testing
  python3 dynamic-city.py --fetch-weather                               # print shell vars and exit
  python3 dynamic-city.py --period night --rain 2 --clouds 1 \
    --snow 0 --vx 1 --vy 4 --lightning 0 --out /tmp/foo.gif            # daemon mode
"""

from PIL import Image, ImageDraw
import os, random, math
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    'display':  {'resolution': '2560x1440'},
    'location': {'lat': None, 'lon': None},
    'city':     {'layout_seed': 42, 'tree_density': 6, 'building_density': 6},
    'wallpaper':{'setter': 'awww', 'transition': 'wipe'},
}

def load_config():
    import tomllib
    path = Path.home() / '.config' / 'dynamic-city' / 'config.toml'
    if not path.exists():
        return DEFAULT_CONFIG
    with open(path, 'rb') as f:
        user = tomllib.load(f)
    cfg = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    for section, values in user.items():
        if section in cfg:
            cfg[section].update(values)
    return cfg

# ── Canvas ────────────────────────────────────────────────────────────────────
RENDER_W   = 320
RENDER_H   = 180
GROUND_Y   = 162
TREE_TOP_Y = 112
FRAMES     = 320
FRAME_MS   = 80

RAIN_DROPS  = {0: 0,  1: 150, 2: 420, 3: 800}
SNOW_FLAKES = {0: 0,  1: 70,  2: 150, 3: 240}
CLOUD_COUNT = {0: 2,  1: 5,   2: 9}

# ── Density ───────────────────────────────────────────────────────────────────
def density_scale(density: int, sparse: float, dense: float) -> float:
    """
    Map a density value (1–10) to a number between sparse (at 1) and dense (at 10).
    Used to interpolate gap sizes, building widths, etc.
    """
    # TODO(human): implement this function.
    # density is an int from 1 (least dense) to 10 (most dense).
    # Return a float between sparse and dense that reflects that scale.
    # Consider whether a linear or curved interpolation feels better visually.
    pass

# ── Palettes ──────────────────────────────────────────────────────────────────
PALETTES = {
    'night': {
        'sky_top':  (8,  12, 35),  'sky_bot':  (18, 20, 55),
        'cloud':    (20, 25, 52),
        'far_bld':  (15, 18, 45),  'near_bld': (22, 26, 58),
        'win_lit':  (255,218,95),  'win_dim':  (28, 32, 62),
        'ground':   (12, 14, 34),  'puddle':   (20, 24, 52),
        'rain':     (95, 120,185),
        'stars': True,  'moon': True,  'lit_prob': 0.65,
    },
    'dawn': {
        'sky_top':  (58, 32, 95),  'sky_bot':  (218,112,52),
        'cloud':    (175,98, 80),
        'far_bld':  (55, 38, 78),  'near_bld': (42, 30, 65),
        'win_lit':  (255,195,85),  'win_dim':  (55, 40, 72),
        'ground':   (38, 28, 50),  'puddle':   (60, 50, 78),
        'rain':     (175,135,165),
        'stars': False, 'moon': False, 'lit_prob': 0.40,
    },
    'day': {
        'sky_top':  (88, 102,128), 'sky_bot':  (142,158,178),
        'cloud':    (108,120,140),
        'far_bld':  (92, 98, 115), 'near_bld': (75, 80, 98),
        'win_lit':  (205,220,255), 'win_dim':  (82, 88, 105),
        'ground':   (62, 68, 78),  'puddle':   (78, 88, 105),
        'rain':     (185,200,220),
        'stars': False, 'moon': False, 'lit_prob': 0.15,
    },
    'dusk': {
        'sky_top':  (62, 38, 88),  'sky_bot':  (222,98, 42),
        'cloud':    (155,88, 72),
        'far_bld':  (62, 42, 78),  'near_bld': (48, 34, 62),
        'win_lit':  (255,182,68),  'win_dim':  (58, 40, 68),
        'ground':   (40, 28, 48),  'puddle':   (58, 44, 68),
        'rain':     (168,108,132),
        'stars': False, 'moon': False, 'lit_prob': 0.38,
    },
    'evening': {
        'sky_top':  (12, 16, 48),  'sky_bot':  (25, 30, 70),
        'cloud':    (22, 28, 60),
        'far_bld':  (18, 22, 55),  'near_bld': (28, 32, 68),
        'win_lit':  (255,205,88),  'win_dim':  (35, 40, 72),
        'ground':   (18, 20, 44),  'puddle':   (25, 30, 62),
        'rain':     (78, 100,162),
        'stars': True,  'moon': False, 'lit_prob': 0.58,
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

# ── Season ────────────────────────────────────────────────────────────────────
def get_season():
    from datetime import datetime
    month = datetime.now().month
    if   month in (12, 1, 2): return 'summer'
    elif month in (3, 4, 5):  return 'autumn'
    elif month in (6, 7, 8):  return 'winter'
    else:                     return 'spring'

_HOLIDAY_OVERRIDE = None

def _is_christmas_week():
    if _HOLIDAY_OVERRIDE: return _HOLIDAY_OVERRIDE == 'christmas'
    from datetime import datetime
    d = datetime.now()
    return d.month == 12 and 18 <= d.day <= 25

def _easter_date(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19*a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2*e + 2*i - h - k) % 7
    m = (a + 11*h + 22*l) // 451
    month = (h + l - 7*m + 114) // 31
    day   = ((h + l - 7*m + 114) % 31) + 1
    return month, day

def _is_easter_week():
    if _HOLIDAY_OVERRIDE: return _HOLIDAY_OVERRIDE == 'easter'
    from datetime import datetime, date
    today = datetime.now().date()
    em, ed = _easter_date(today.year)
    return abs((today - date(today.year, em, ed)).days) <= 3

def _is_new_year():
    if _HOLIDAY_OVERRIDE: return _HOLIDAY_OVERRIDE == 'newyear'
    from datetime import datetime
    d = datetime.now()
    return (d.month == 12 and d.day == 31) or (d.month == 1 and d.day == 1)

TREE_TRUNK = (45, 32, 20)
TREE_COLORS = {
    'summer': [(32, 98, 48),   (48, 128, 58),  (65, 150, 70)],
    'autumn': [(185, 88, 28),  (165, 55, 32),  (205, 165, 38), (148, 65, 25)],
    'spring': [(88, 165, 72),  (118, 188, 88), (215, 158, 178)],
    'winter': [],
}

# ── Moon phase ────────────────────────────────────────────────────────────────
def moon_phase_age():
    from datetime import datetime
    known_new = datetime(2000, 1, 6, 18, 14)
    delta = (datetime.now() - known_new).total_seconds() / 86400
    return delta % 29.53058867

# ── Drawing ───────────────────────────────────────────────────────────────────
def draw_sky(draw, p):
    STEPS = 20
    for i in range(STEPS):
        t  = i / (STEPS - 1)
        y0 = i * GROUND_Y // STEPS
        y1 = (i + 1) * GROUND_Y // STEPS
        draw.rectangle([0, y0, RENDER_W, y1], fill=lerp_color(p['sky_top'], p['sky_bot'], t))

def draw_stars(draw, rng):
    for _ in range(80):
        x = rng.randint(0, RENDER_W - 1)
        y = rng.randint(0, GROUND_Y // 2)
        v = rng.randint(140, 255)
        draw.point((x, y), fill=(v, v, max(0, v - 30)))

def draw_moon(draw, p, age, sky_pos=0.5):
    cycle = 29.53058867
    frac  = age / cycle
    if frac < 0.04 or frac > 0.96:
        return
    arc = 4 * sky_pos * (1 - sky_pos)
    cx  = int(sky_pos * RENDER_W)
    cy  = int((GROUND_Y - 6) - (GROUND_Y - 16) * arc)
    r   = 7
    sky        = lerp_color(p['sky_top'], p['sky_bot'], max(0, cy) / GROUND_Y)
    lit_color  = (238, 232, 195)
    dark_color = tuple(max(0, c - 12) for c in sky)
    waxing     = frac < 0.5
    lit_t      = frac * 2 if waxing else (1 - frac) * 2
    terminator = 1 - lit_t * 2
    for py in range(cy - r, cy + r + 1):
        for px in range(cx - r, cx + r + 1):
            dx, dy = px - cx, py - cy
            if dx * dx + dy * dy > r * r:
                continue
            nx  = dx / r
            lit = (nx >= terminator) if waxing else (nx <= -terminator)
            draw.point((px, py), fill=lit_color if lit else dark_color)

def draw_sun(draw, sky_pos):
    arc = 4 * sky_pos * (1 - sky_pos)
    sx  = int(sky_pos * RENDER_W)
    sy  = int((GROUND_Y - 6) - (GROUND_Y - 16) * arc)
    if sy >= GROUND_Y - 3:
        return
    t    = arc
    core = lerp_color((255, 160,  60), (255, 245, 140), t)
    glow = lerp_color((255, 120,  30), (255, 210,  80), t)
    r = 4
    draw.ellipse([sx - r - 1, sy - r - 1, sx + r + 1, sy + r + 1], fill=glow)
    draw.ellipse([sx - r,     sy - r,     sx + r,     sy + r    ], fill=core)

def draw_clouds(draw, p, clouds):
    for (cx, cy, cw, ch) in clouds:
        c = p['cloud']
        draw.rectangle([cx,          cy + ch//3,  cx + cw,       cy + ch   ], fill=c)
        draw.rectangle([cx + 4,      cy,           cx + cw - 4,  cy + ch   ], fill=c)
        draw.rectangle([cx + cw//4,  cy - ch//4,   cx + 3*cw//4, cy + ch//2], fill=c)

def draw_buildings(draw, buildings, bld_color, win_lit, win_dim, lit_prob, rng):
    WW, WH, WG = 2, 2, 2
    for (x, top, w) in buildings:
        draw.rectangle([x, top, x + w - 1, GROUND_Y - 1], fill=bld_color)
        wy = top + WG + 1
        while wy + WH <= GROUND_Y - WG:
            wx = x + WG
            while wx + WW <= x + w - WG:
                color = win_lit if rng.random() < lit_prob else win_dim
                draw.rectangle([wx, wy, wx + WW - 1, wy + WH - 1], fill=color)
                wx += WW + WG
            wy += WH + WG

def draw_ground(draw, p, rng):
    draw.rectangle([0, GROUND_Y, RENDER_W, RENDER_H - 1], fill=p['ground'])
    for _ in range(6):
        px = rng.randint(0, RENDER_W - 30)
        pw = rng.randint(12, 45)
        py = GROUND_Y + rng.randint(2, 10)
        if py < RENDER_H:
            draw.rectangle([px, py, px + pw, py + 1], fill=p['puddle'])

_DROPS = None
def _get_drops():
    global _DROPS
    if _DROPS is None:
        r = random.Random(99)
        _DROPS = [(r.randint(0, RENDER_W - 1), r.randint(0, RENDER_W - 1), r.randint(4, 8))
                  for _ in range(800)]
    return _DROPS

def draw_rain(draw, p, frame, n_drops, vx, vy):
    if n_drops == 0:
        return
    for (bx, by, length) in _get_drops()[:n_drops]:
        x = (bx + frame * vx) % RENDER_W
        y = (by + frame * vy) % RENDER_W
        for i in range(length):
            py = y + i
            if py >= GROUND_Y: break
            if py < 0:         continue
            px = (x + (i * vx) // max(vy, 1)) % RENDER_W
            draw.point((px, py), fill=p['rain'])

_SNOW = None
def _get_snow():
    global _SNOW
    if _SNOW is None:
        r     = random.Random(77)
        _SNOW = [(r.randint(0, RENDER_W - 1), r.randint(0, RENDER_W - 1), r.randint(-2, 2))
                 for _ in range(240)]
    return _SNOW

def draw_snow(draw, frame, n_flakes, vx):
    SVX, SVY = max(0, vx - 1), 2
    for (bx, by, drift) in _get_snow()[:n_flakes]:
        x = (bx + frame * SVX + drift * (frame % 2)) % RENDER_W
        y = (by + frame * SVY) % RENDER_W
        if 0 <= x < RENDER_W - 1 and 0 <= y < GROUND_Y - 1:
            draw.rectangle([x, y, x + 1, y + 1], fill=(220, 235, 255))

def draw_lightning(draw, cloud, frame):
    cx, cy, cw, ch = cloud
    rng = random.Random(frame * 37 + 11)
    bx = cx + cw // 2 + rng.randint(-cw // 4, cw // 4)
    by = cy + ch
    bolt  = (255, 255, 190)
    spark = (200, 200, 100)
    x, y  = bx, by
    path  = [(x, y)]
    while y < GROUND_Y - 2:
        x = max(1, min(RENDER_W - 2, x + rng.randint(-3, 3)))
        y = min(y + rng.randint(5, 9), GROUND_Y - 2)
        path.append((x, y))
    for i in range(len(path) - 1):
        draw.line([path[i], path[i + 1]], fill=bolt, width=1)
    mid = path[len(path) // 2]
    bx2, by2 = mid
    for _ in range(rng.randint(2, 4)):
        bx2 = max(1, min(RENDER_W - 2, bx2 + rng.randint(-3, 3)))
        by2 = min(by2 + rng.randint(3, 6), GROUND_Y - 1)
        draw.line([mid, (bx2, by2)], fill=spark, width=1)
        mid = (bx2, by2)
    ix, _ = path[-1]
    for _ in range(rng.randint(8, 12)):
        sx = max(0, min(RENDER_W - 1, ix + rng.randint(-7, 7)))
        sy = max(0, min(RENDER_H - 1, GROUND_Y - 1 + rng.randint(-2, 2)))
        draw.point((sx, sy), fill=bolt)

# ── Scene layout ──────────────────────────────────────────────────────────────
def generate_clouds(n_clouds, rng):
    return [(rng.randint(-10, RENDER_W - 30), rng.randint(4, GROUND_Y // 3),
             rng.randint(28, 68),              rng.randint(6, 12))
            for _ in range(n_clouds)]

def generate_buildings(rng, density=6):
    """Generate three-layer building layout. density 1-10 controls skyline packing."""
    far, mid, near = [], [], []

    gap_far  = int(density_scale(density, sparse=8,  dense=0))
    gap_mid  = int(density_scale(density, sparse=10, dense=0))
    gap_near = int(density_scale(density, sparse=12, dense=1))

    x = 0
    while x < RENDER_W:
        w   = rng.randint(14, 24)
        top = rng.randint(62, 108)
        far.append((x, top, w))
        x += w + rng.randint(0, gap_far)
    x = -rng.randint(5, 20)
    while x < RENDER_W:
        w   = rng.randint(18, 34)
        top = rng.randint(82, 118)
        mid.append((x, top, w))
        x += w + rng.randint(0, gap_mid)
    x = -rng.randint(5, 20)
    while x < RENDER_W:
        w   = rng.randint(26, 46)
        top = rng.randint(98, 130)
        near.append((x, top, w))
        x += w + rng.randint(0, gap_near)
    return far, mid, near

def generate_people(rng):
    people = []
    for _ in range(MAX_PEOPLE):
        is_child = rng.random() < 0.22
        height   = rng.randint(3, 4) if is_child else rng.randint(5, 8)
        colors   = CHILD_COLORS if is_child else PERSON_COLORS
        people.append((rng.randint(5, RENDER_W - 5),
                       colors[rng.randint(0, len(colors) - 1)],
                       SKIN_TONES[rng.randint(0, len(SKIN_TONES) - 1)],
                       rng.choice([-1, -1, -1, 0, 1, 1, 1]),
                       height, is_child))
    return people

def generate_birds(rng):
    return [(rng.randint(0, RENDER_W), rng.randint(5, GROUND_Y//2), rng.randint(2, 4))
            for _ in range(MAX_BIRDS)]

def generate_trees(rng, density=6):
    """Generate street trees. density 1-10 controls how many fit along the street."""
    trees    = []
    gap_min  = int(density_scale(density, sparse=35, dense=5))
    gap_max  = int(density_scale(density, sparse=65, dense=12))
    gap_min  = max(5, gap_min)
    gap_max  = max(gap_min + 1, gap_max)

    x = rng.randint(5, 20)
    while x < RENDER_W - 8:
        kind = 'pine' if rng.random() < 0.4 else 'round'
        if kind == 'pine':
            trees.append((x, rng.randint(9, 15), 2, rng.randint(9, 15), 0, 'pine'))
        else:
            trees.append((x, rng.randint(11, 19), rng.randint(2, 3),
                          rng.randint(8, 13),     rng.randint(0, 3), 'round'))
        x += rng.randint(gap_min, gap_max)
    return trees

def generate_lightning_events(rng, clouds):
    if not clouds:
        return {}
    events = {}
    for _ in range(rng.randint(2, 3)):
        events[rng.randint(0, FRAMES - 1)] = rng.choice(clouds)
    return events

def generate_street_furniture(rng):
    streetlights = []
    x = rng.randint(15, 40)
    while x < RENDER_W - 10:
        streetlights.append(x)
        x += rng.randint(45, 70)
    benches = []
    x = rng.randint(30, 55)
    while x < RENDER_W - 10:
        if not any(abs(x - sl) < 12 for sl in streetlights):
            benches.append(x)
        x += rng.randint(55, 85)
    return streetlights, benches

CAT_COLORS = [(180,152,118),(42,40,38),(148,145,140),(225,200,165),(200,155,100)]
DOG_COLORS = [(200,175,140),(45,40,36),(168,128,92),(222,218,208),(148,112,82)]

def generate_cats(rng, period):
    if period == 'day': return []
    n = rng.randint(1, 3) if period in ('night', 'evening') else rng.randint(0, 2)
    cats = []
    for _ in range(n):
        walking = rng.random() < 0.35
        cats.append((rng.randint(8, RENDER_W - 8),
                     CAT_COLORS[rng.randint(0, len(CAT_COLORS) - 1)],
                     walking,
                     rng.choice([-1, 1]),
                     rng.randint(1, 2) if walking else 0))
    return cats

def generate_dogs(rng, period):
    n = rng.randint(0, 2) if period in ('day', 'dawn', 'dusk', 'evening') else rng.randint(0, 1)
    return [(rng.randint(8, RENDER_W - 8),
             DOG_COLORS[rng.randint(0, len(DOG_COLORS) - 1)],
             rng.choice([-1, 1]),
             rng.randint(1, 2))
            for _ in range(n)]

def generate_pigeons(rng):
    return [(rng.randint(20, RENDER_W - 20),
             rng.randint(0, FRAMES - 1),
             rng.randint(10, 25))
            for _ in range(rng.randint(2, 5))]

def generate_plane(rng, period):
    if rng.random() < 0.72: return None
    return (rng.randint(-60, RENDER_W // 2), rng.randint(12, 50))

def generate_shooting_stars(rng, period):
    if period != 'night': return []
    return [(rng.randint(20, RENDER_W - 20), rng.randint(4, GROUND_Y // 4),
             rng.randint(0, FRAMES - 18))
            for _ in range(rng.randint(0, 2))]

def generate_bats(rng, period):
    if period not in ('night', 'evening') or rng.random() < 0.55: return []
    return [(rng.randint(0, RENDER_W), rng.randint(8, GROUND_Y // 2 - 5),
             rng.randint(3, 5))
            for _ in range(rng.randint(1, 3))]

PINE_COLORS    = [(28, 72, 38), (38, 95, 48), (22, 58, 32)]
PERSON_COLORS  = [(180,70,70),(70,90,180),(70,150,90),(180,140,60),(130,70,150),(60,140,160),(190,110,50)]
SKIN_TONES     = [(220,180,140),(190,145,110),(160,110,80),(105,72,52)]
UMBRELLA_COLORS= [(200,60,60),(60,110,200),(55,140,85),(175,140,50)]
CHILD_COLORS   = [(220,75,75),(75,130,220),(80,195,100),(220,185,55),(190,80,190),(60,195,195)]
MAX_PEOPLE, MAX_BIRDS = 12, 10

def activity_levels(period, rain_level):
    base_p = {'night': 1, 'dawn': 3, 'day': 9,  'dusk': 6, 'evening': 4}[period]
    base_b = {'night': 0, 'dawn': 5, 'day': 8,  'dusk': 3, 'evening': 1}[period]
    factor = [1.0, 0.6, 0.3, 0.1][rain_level]
    return max(0, int(base_p * factor)), max(0, int(base_b * factor))

def draw_trees(draw, trees, season, snow):
    colors = TREE_COLORS[season]
    for (x, trunk_h, trunk_w, canopy_r, variety, kind) in trees:
        tx = x - trunk_w // 2
        ty = GROUND_Y - trunk_h
        draw.rectangle([tx, ty, tx + trunk_w - 1, GROUND_Y - 1], fill=TREE_TRUNK)
        rng = random.Random(x * 13 + variety)
        if kind == 'pine':
            canopy_h = canopy_r * 2
            tip_y    = ty - canopy_h
            for row in range(canopy_h):
                y      = tip_y + row
                half_w = (row * canopy_r) // canopy_h
                if y < 0 or y >= RENDER_H: continue
                c = PINE_COLORS[row % len(PINE_COLORS)]
                draw.line([x - half_w, y, x + half_w, y], fill=c)
                if snow and half_w > 0:
                    draw.point((x - half_w, y), fill=(220, 235, 255))
                    draw.point((x + half_w, y), fill=(220, 235, 255))
        elif season == 'winter':
            draw.line([x, ty,     x - rng.randint(5,8), ty - rng.randint(5,8)], fill=TREE_TRUNK)
            draw.line([x, ty,     x + rng.randint(5,8), ty - rng.randint(5,8)], fill=TREE_TRUNK)
            draw.line([x, ty + 3, x - rng.randint(3,6), ty - rng.randint(2,5)], fill=TREE_TRUNK)
            if snow:
                for sx in range(x - 7, x + 8, 2):
                    if 0 <= sx < RENDER_W:
                        draw.point((sx, ty - 2), fill=(220, 235, 255))
        else:
            cy = ty - canopy_r
            for i in range(3):
                c  = colors[(variety + i) % len(colors)]
                ox = rng.randint(-canopy_r // 3, canopy_r // 3)
                oy = rng.randint(-canopy_r // 4, canopy_r // 4)
                r  = canopy_r + rng.randint(-1, 2)
                draw.ellipse([x+ox-r, cy+oy-r, x+ox+r, cy+oy+r], fill=c)
            if snow:
                draw.ellipse([x - canopy_r//2, cy - canopy_r,
                              x + canopy_r//2, cy - canopy_r//2], fill=(220, 235, 255))

def draw_people(draw, people, rain, frame, lit_lamps=None):
    LEGS = (50, 45, 55)
    for i, (bx, color, skin, direction, height, is_child) in enumerate(people):
        x  = (bx + frame * direction) % RENDER_W
        gy = GROUND_Y - 1
        if lit_lamps and any(abs(x - lx) <= 5 for lx in lit_lamps):
            skin  = lerp_color(skin,  (255, 232, 175), 0.28)
            color = lerp_color(color, (255, 238, 195), 0.22)
        head_y     = gy - height + 1
        leg_rows   = 3 if height >= 7 else 2
        stride_spd = 5 if is_child else 8
        draw.point((x, head_y), fill=skin)
        for body_y in range(head_y + 1, gy - leg_rows + 1):
            draw.point((x, body_y), fill=color)
        if direction != 0 and (frame // stride_spd) % 2 == 0:
            draw.point((x - 1, gy - 1), fill=LEGS)
            draw.point((x + 1, gy),     fill=LEGS)
            for ly in range(gy - leg_rows + 1, gy - 1):
                draw.point((x, ly), fill=LEGS)
        else:
            for ly in range(gy - leg_rows + 1, gy + 1):
                draw.point((x, ly), fill=LEGS)
        if rain > 0:
            uc = UMBRELLA_COLORS[i % len(UMBRELLA_COLORS)]
            uy = head_y - 2
            draw.line([x - 1, uy, x + 1, uy], fill=uc)
            draw.point((x - 1, uy + 1), fill=uc)
            draw.point((x + 1, uy + 1), fill=uc)

def draw_birds(draw, birds, frame):
    BIRD = (35, 38, 48)
    for (bx, by, speed) in birds:
        x = (bx + frame * speed) % RENDER_W
        if x >= RENDER_W: continue
        if frame % 2 == 0:
            if x > 0:             draw.point((x-1, by-1), fill=BIRD)
            draw.point((x, by),   fill=BIRD)
            if x < RENDER_W - 1: draw.point((x+1, by-1), fill=BIRD)
        else:
            if x > 0:             draw.point((x-1, by), fill=BIRD)
            draw.point((x, by),   fill=BIRD)
            if x < RENDER_W - 1: draw.point((x+1, by), fill=BIRD)

def draw_cat(draw, bx, color, is_walking, direction, speed, frame):
    x    = (bx + frame * speed * direction) % RENDER_W if speed else bx
    y    = GROUND_Y - 1
    dark = tuple(max(0, c - 50) for c in color)
    if not is_walking:
        draw.point((x - 1, y - 5), fill=color)
        draw.point((x + 1, y - 5), fill=color)
        for dx in [-1, 0, 1]:
            draw.point((x + dx, y - 4), fill=color)
        draw.point((x + direction, y - 4), fill=dark)
        for dy in range(-3, 0):
            for dx in [-1, 0, 1]:
                draw.point((x + dx, y + dy), fill=color)
        tx = x - direction * 2
        draw.point((tx, y - 1), fill=color)
        draw.point((tx, y - 2), fill=color)
        draw.point((tx + direction, y - 3), fill=color)
    else:
        stride = (frame // 8) % 2
        hx = x + direction * 2
        draw.point((hx + direction, y - 3), fill=color)
        draw.point((hx, y - 3), fill=color)
        draw.point((hx, y - 2), fill=color)
        draw.point((x,  y - 2), fill=color)
        draw.point((x - direction, y - 2), fill=color)
        draw.point((x - direction, y - 1), fill=color)
        if stride == 0:
            draw.point((hx,             y), fill=dark)
            draw.point((x - direction * 2, y), fill=dark)
        else:
            draw.point((hx - direction, y), fill=dark)
            draw.point((x - direction,  y), fill=dark)
        for i in range(1, 3):
            draw.point((x - direction * (i + 1), y - i), fill=color)

def draw_dog(draw, bx, color, direction, speed, frame):
    y      = GROUND_Y - 1
    x      = (bx + frame * speed * direction) % RENDER_W
    dark   = tuple(max(0, c - 50) for c in color)
    stride = (frame // 6) % 2
    hx     = x + direction * 2
    draw.point((hx - direction, y - 4), fill=dark)
    draw.point((hx - direction, y - 3), fill=dark)
    draw.rectangle([hx - 1, y - 3, hx, y - 2], fill=color)
    draw.point((hx + direction, y - 2), fill=color)
    for i in range(4):
        draw.point((x - direction * i, y - 2), fill=color)
    if stride == 0:
        draw.point((hx - 1, y - 1), fill=dark); draw.point((hx - 1, y), fill=dark)
        draw.point((x - direction * 2, y - 1), fill=dark)
        draw.point((x - direction * 2, y),     fill=dark)
    else:
        draw.point((hx,     y - 1), fill=dark); draw.point((hx,     y), fill=dark)
        draw.point((x - direction * 3, y - 1), fill=dark)
        draw.point((x - direction * 3, y),     fill=dark)
    tail_x   = x - direction * 3
    tail_wag = (frame // 5) % 2
    draw.point((tail_x, y - 2),            fill=color)
    draw.point((tail_x, y - 3 - tail_wag), fill=color)

_BAT_WOBBLE = [0, 1, 2, 1, 0, -1, -2, -1]

def draw_bats(draw, bats, frame):
    BAT = (42, 36, 52)
    for (bx, by, speed) in bats:
        x  = (bx + frame * speed) % RENDER_W
        y  = by + _BAT_WOBBLE[(frame // 5) % 8]
        wy = y + (-1 if (frame // 4) % 2 == 0 else 1)
        if not (0 <= y < RENDER_H and 0 <= wy < RENDER_H): continue
        for dx in [-2, 2]:
            if 0 <= x + dx < RENDER_W: draw.point((x + dx, wy), fill=BAT)
        for dx in [-1, 0, 1]:
            if 0 <= x + dx < RENDER_W: draw.point((x + dx, y), fill=BAT)

def draw_pigeons(draw, pigeons, frame):
    body_c = (112, 108, 120)
    head_c = (150, 148, 160)
    half   = FRAMES // 2
    for (bx, offset, rng_px) in pigeons:
        t           = (frame + offset) % FRAMES
        wave        = t / half if t < half else 2.0 - t / half
        x           = int(bx + (wave * 2 - 1) * rng_px)
        going_right = t < half
        y           = GROUND_Y - 1
        bob         = 1 if (t // 7) % 2 == 0 else 0
        hx          = x + (1 if going_right else -1)
        draw.point((x - (1 if going_right else -1), y), fill=body_c)
        draw.point((x,  y),            fill=body_c)
        draw.point((hx, y - 1 - bob),  fill=head_c)

def draw_plane(draw, plane, p, period, frame):
    if plane is None: return
    sx, alt_y = plane
    x = sx + frame * 2
    if not (-8 <= x <= RENDER_W + 8): return
    body_c = lerp_color(p['sky_top'], (192, 190, 196), 0.55)
    for dx in range(-4, 5):
        if 0 <= x + dx < RENDER_W: draw.point((x + dx, alt_y), fill=body_c)
    for dx in [-2, -1, 0, 1, 2]:
        if 0 <= x + dx < RENDER_W and alt_y + 1 < RENDER_H:
            draw.point((x + dx, alt_y + 1), fill=body_c)
    for dx_fin, dy_fin in [(-4, -1), (4, -1)]:
        if 0 <= x + dx_fin < RENDER_W and alt_y + dy_fin >= 0:
            draw.point((x + dx_fin, alt_y + dy_fin), fill=body_c)
    if period in ('night', 'evening') and (frame // 15) % 2 == 0:
        if 0 <= x - 2 < RENDER_W and alt_y + 1 < RENDER_H:
            draw.point((x - 2, alt_y + 1), fill=(255, 55, 55))
        if 0 <= x + 2 < RENDER_W and alt_y + 1 < RENDER_H:
            draw.point((x + 2, alt_y + 1), fill=(75, 200, 75))

def draw_shooting_stars(draw, stars, p, frame):
    for (sx, sy, f0) in stars:
        t = frame - f0
        if not (0 <= t < 14): continue
        fade  = 1.0 - t / 14
        sky_c = lerp_color(p['sky_top'], p['sky_bot'], sy / GROUND_Y)
        col   = lerp_color((245, 245, 215), sky_c, 1.0 - fade)
        for i in range(min(t + 1, 7)):
            px, py = sx - i * 2, sy + i
            if 0 <= px < RENDER_W and 0 <= py < RENDER_H:
                draw.point((px, py), fill=col)

_AURORA_COLS = [(35,185,120),(40,200,140),(30,160,110),(70,215,165),(55,175,205),(120,80,200)]

def draw_aurora(draw, p, season, weather, period, frame):
    if season != 'winter' or period not in ('night', 'evening') or weather['clouds'] > 0:
        return
    for band, by in enumerate([28, 36, 43, 50]):
        for bx in range(0, RENDER_W, 2):
            wave = int(4 * math.sin(bx / 18.0 + frame / 22.0 + band * 1.1))
            py   = by + wave
            if 0 <= py < RENDER_H:
                ci  = (band + bx // 35 + frame // 40) % len(_AURORA_COLS)
                sky = lerp_color(p['sky_top'], p['sky_bot'], py / RENDER_H)
                draw.point((bx, py), fill=lerp_color(sky, _AURORA_COLS[ci], 0.32))

_FW_RAYS = [(round(r * math.cos(math.radians(a))),
             round(r * math.sin(math.radians(a)) * 0.5), i)
            for a in range(0, 360, 24)
            for i, r in enumerate([3, 6, 10])]

def draw_fireworks(draw, frame):
    if not _is_new_year():
        return
    r = random.Random(88)
    for _ in range(5):
        cx    = r.randint(40, RENDER_W - 40)
        cy    = r.randint(15, 55)
        t_off = r.randint(0, FRAMES - 1)
        color = _XMAS_COLORS[r.randint(0, len(_XMAS_COLORS) - 1)]
        t = (frame - t_off) % (FRAMES // 4)
        if 0 < t <= 30:
            stage = min(2, (t - 1) // 10)
            for (dx, dy, ri) in _FW_RAYS:
                if ri <= stage:
                    px, py = cx + dx, cy + dy
                    if 0 <= px < RENDER_W and 0 <= py < RENDER_H:
                        draw.point((px, py), fill=color)

def _lights_on(period, sky_pos):
    return (period in ('night', 'evening') or
            (period == 'dawn' and sky_pos < 0.10) or
            (period == 'dusk' and sky_pos > 0.90))

def draw_light_cones(draw, img, p, streetlights, period, sky_pos):
    if not _lights_on(period, sky_pos):
        return
    lamp_col = p['win_lit']
    lamp_y   = GROUND_Y - 12
    cone_h   = GROUND_Y - lamp_y
    cone_hw  = 8
    for x in streetlights:
        lamp_x = x + 4
        for cy in range(lamp_y, GROUND_Y):
            frac  = (cy - lamp_y) / cone_h
            hw    = max(1, int(frac * cone_hw))
            blend = 0.20 * (1.0 - frac * 0.55)
            for cx in range(lamp_x - hw, lamp_x + hw + 1):
                if 0 <= cx < RENDER_W:
                    draw.point((cx, cy),
                               fill=lerp_color(img.getpixel((cx, cy)), lamp_col, blend))

def draw_streetlight(draw, p, x, period, sky_pos):
    pole_col = lerp_color(p['ground'], p['near_bld'], 0.7)
    pole_top = GROUND_Y - 16
    draw.line([(x, GROUND_Y - 1), (x, pole_top + 2)], fill=pole_col)
    draw.line([(x, pole_top + 2), (x + 4, pole_top + 2)], fill=pole_col)
    draw.point((x + 4, pole_top + 3), fill=pole_col)
    lit     = _lights_on(period, sky_pos)
    lamp_c  = p['win_lit'] if lit else lerp_color(p['win_dim'], (200, 200, 180), 0.5)
    draw.rectangle([x + 3, pole_top + 3, x + 5, pole_top + 4], fill=lamp_c)
    if lit:
        sky_c = lerp_color(p['sky_top'], p['sky_bot'], pole_top / GROUND_Y)
        glow  = lerp_color(lamp_c, sky_c, 0.55)
        for gx, gy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1),(0,2),(2,0)]:
            px, py = x + 4 + gx, pole_top + 3 + gy
            if 0 <= px < RENDER_W and 0 <= py < RENDER_H:
                draw.point((px, py), fill=glow)

def draw_bench(draw, p, x):
    wood  = (162, 104, 50)
    frame = (72,  52,  35)
    draw.line([(x,     GROUND_Y - 6), (x + 8, GROUND_Y - 6)], fill=wood)
    draw.line([(x,     GROUND_Y - 6), (x,     GROUND_Y - 4)], fill=frame)
    draw.line([(x,     GROUND_Y - 4), (x + 8, GROUND_Y - 4)], fill=wood)
    draw.line([(x + 1, GROUND_Y - 4), (x + 1, GROUND_Y - 1)], fill=frame)
    draw.line([(x + 7, GROUND_Y - 4), (x + 7, GROUND_Y - 1)], fill=frame)

VEHICLE_COLORS = [(188,38,38),(38,78,188),(38,155,65),(188,172,38),
                  (88,88,92),(212,212,218),(38,38,38),(188,95,38)]
BIKE_RIDER_COLORS = [(210,170,120),(240,200,160),(180,130,90),(160,100,70),(100,70,50)]

def generate_vehicles(rng, period):
    n = {'day':rng.randint(4,7),'dusk':rng.randint(2,5),'dawn':rng.randint(2,4),
         'evening':rng.randint(1,3),'night':rng.randint(0,2)}[period]
    vehicles = []
    for _ in range(n):
        r = rng.random()
        if r < 0.12:   vtype = 'bus'
        elif r < 0.27: vtype = 'bike'
        elif r < 0.42: vtype = 'motorbike'
        else:          vtype = 'car'
        spd = (rng.randint(1,2) if vtype in ('bus','bike') else rng.randint(2,4))
        rider = BIKE_RIDER_COLORS[rng.randint(0, len(BIKE_RIDER_COLORS)-1)]
        vehicles.append((rng.randint(0, RENDER_W),
                         vtype,
                         VEHICLE_COLORS[rng.randint(0, len(VEHICLE_COLORS)-1)],
                         rng.choice([-1, 1]),
                         spd,
                         rider))
    return vehicles

def draw_vehicles(draw, vehicles, frame, period, sky_pos):
    lit   = _lights_on(period, sky_pos)
    whl_c = (22, 22, 25)
    for (bx, vtype, color, d, speed, rider) in vehicles:
        x   = (bx + frame * speed * d) % RENDER_W
        y   = GROUND_Y - 1
        drk = tuple(max(0, c - 55) for c in color)
        win = lerp_color(color, (190, 218, 245), 0.38)
        if vtype == 'bike':
            draw.point(((x-2)%RENDER_W, y),   fill=whl_c)
            draw.point(((x+2)%RENDER_W, y),   fill=whl_c)
            for dx in range(-2, 3):
                draw.point(((x+dx)%RENDER_W, y-1), fill=color)
            draw.point((x%RENDER_W, y-2), fill=rider)
            draw.point((x%RENDER_W, y-3), fill=rider)
        elif vtype == 'car':
            for dx in range(-3, 4):
                draw.point(((x+dx)%RENDER_W, y-1), fill=color)
            for dx in range(-2, 3):
                draw.point(((x+dx)%RENDER_W, y-2), fill=color)
                draw.point(((x+dx)%RENDER_W, y-3), fill=win if abs(dx)<=1 else color)
            for dx in [-3, -2, 2, 3]:
                draw.point(((x+dx)%RENDER_W, y), fill=whl_c)
            if lit:
                draw.point(((x+d*3)%RENDER_W, y-1), fill=(255,252,200))
                draw.point(((x-d*3)%RENDER_W, y-1), fill=(210,40,40))
        elif vtype == 'bus':
            for dy in [y-1, y-2, y-3]:
                for dx in range(-6, 7):
                    draw.point(((x+dx)%RENDER_W, dy), fill=color)
            for dx in range(-5, 6):
                draw.point(((x+dx)%RENDER_W, y-4), fill=color)
            for wx in [-4, 0, 4]:
                draw.point(((x+wx)%RENDER_W, y-3), fill=win)
                draw.point(((x+wx)%RENDER_W, y-4), fill=win)
            for dx in [-5, -4, 3, 4]:
                draw.point(((x+dx)%RENDER_W, y), fill=whl_c)
            if lit:
                draw.point(((x+d*6)%RENDER_W, y-2), fill=(255,252,200))
                draw.point(((x-d*6)%RENDER_W, y-2), fill=(210,40,40))
        else:
            for dx in range(-2, 3):
                draw.point(((x+dx)%RENDER_W, y-1), fill=color)
            draw.point((x%RENDER_W, y-2), fill=drk)
            draw.point(((x-2)%RENDER_W, y), fill=whl_c)
            draw.point(((x+1)%RENDER_W, y), fill=whl_c)
            if lit:
                draw.point(((x+d*2)%RENDER_W, y-1), fill=(255,252,200))

_PUDDLE_SHIMMER = None
def _get_puddle_shimmer():
    global _PUDDLE_SHIMMER
    if _PUDDLE_SHIMMER is None:
        r = random.Random(75)
        _PUDDLE_SHIMMER = [(r.randint(0, RENDER_W-1), r.randint(0, 5)) for _ in range(300)]
    return _PUDDLE_SHIMMER

def draw_reflections(draw, p, weather, frame):
    if weather['rain'] == 0:
        return
    intensity = weather['rain'] / 3.0
    ripple    = (frame // 6) % 3
    n         = int(130 * intensity)
    for (px, py_off) in _get_puddle_shimmer()[:n]:
        py = GROUND_Y + 1 + (py_off + ripple) % 6
        if py < RENDER_H:
            col = p['win_lit'] if (px + py_off) % 6 == 0 else p['sky_bot']
            draw.point((px, py), fill=lerp_color(col, p['ground'], 0.68))

_XMAS_COLORS = [(220,40,40),(40,185,40),(40,100,220),(225,200,40),(220,80,185),(255,165,0)]
_LEAF_COLORS = [(185,88,28),(165,55,32),(205,165,38),(148,65,25),(210,120,30)]
_BLOSSOM_C   = [(245,182,193),(252,215,225),(250,235,245),(255,200,210)]
_EGG_COLORS  = [(220,60,60),(60,180,80),(60,100,220),(220,200,60),(180,60,200),(60,200,200),(240,130,60)]

_BLOSSOM_DROPS = None
def _get_blossom_drops():
    global _BLOSSOM_DROPS
    if _BLOSSOM_DROPS is None:
        r = random.Random(73)
        _BLOSSOM_DROPS = [(r.randint(0,RENDER_W-1), r.randint(0,RENDER_H-1),
                           r.randint(1,2), r.choice([-1,0,1])) for _ in range(60)]
    return _BLOSSOM_DROPS

def draw_building_decorations(draw, p, season, near, streetlights, frame):
    if _is_christmas_week():
        blink = (frame // 12) % len(_XMAS_COLORS)
        for (bx, top, w) in near:
            for dx in range(0, w, 3):
                cx = (bx + dx) % RENDER_W
                if 0 <= cx < RENDER_W and 0 <= top < RENDER_H:
                    draw.point((cx, top), fill=_XMAS_COLORS[(dx//3 + blink) % len(_XMAS_COLORS)])
        for sx in streetlights:
            for i in range(len(_XMAS_COLORS)):
                cx = (sx + i * 3) % RENDER_W
                if 0 <= cx < RENDER_W:
                    draw.point((cx, GROUND_Y - 7), fill=_XMAS_COLORS[(i + blink) % len(_XMAS_COLORS)])
    elif _is_easter_week():
        r = random.Random(79)
        for _ in range(9):
            ex = r.randint(8, RENDER_W - 10)
            c1 = _EGG_COLORS[r.randint(0, len(_EGG_COLORS)-1)]
            c2 = _EGG_COLORS[r.randint(0, len(_EGG_COLORS)-1)]
            ey = GROUND_Y - 2
            draw.point((ex,   ey),   fill=c1)
            draw.point((ex+1, ey),   fill=c1)
            draw.point((ex,   ey-1), fill=c2)
            draw.point((ex+1, ey-1), fill=c2)
            draw.point((ex,   ey-2), fill=c1)
            draw.point((ex+1, ey-2), fill=c1)
    if season == 'winter':
        frost   = (218, 232, 255)
        flicker = (frame // 25) % 2
        for (bx, top, w) in near:
            for dx in range(3, w - 3, 5):
                cx = (bx + dx + flicker) % RENDER_W
                if 0 <= cx < RENDER_W and 0 <= top + 2 < RENDER_H:
                    draw.point((cx, top + 2), fill=frost)
                    draw.point((cx, top + 1), fill=lerp_color(frost, p['win_dim'], 0.5))

def draw_weather_decorations(draw, season, frame, trees=None):
    band = GROUND_Y - TREE_TOP_Y - 4
    if season == 'autumn':
        tree_xs = [x for (x, *_, kind) in (trees or []) if kind == 'round'] or [80, 160, 240]
        r = random.Random(71)
        for i in range(35):
            tx    = tree_xs[i % len(tree_xs)]
            off   = r.randint(-9, 9)
            by    = r.randint(0, band - 1)
            drift = r.choice([-1, 0, 1])
            bx    = (tx + off) % RENDER_W
            x     = (bx + drift * (frame // 5)) % RENDER_W
            y     = TREE_TOP_Y + (by + frame // 2) % band
            draw.point((x, y), fill=_LEAF_COLORS[(bx + by) % len(_LEAF_COLORS)])
    elif season == 'spring':
        for (bx, by, speed, drift) in _get_blossom_drops()[:45]:
            x = (bx + drift * (frame // 6)) % RENDER_W
            y = TREE_TOP_Y + (by + frame // 3) % band
            draw.point((x, y), fill=_BLOSSOM_C[(bx + by) % len(_BLOSSOM_C)])

# ── Composition ───────────────────────────────────────────────────────────────
def render_frame(period, frame, far, mid, near, clouds, trees, season,
                 lightning_events, moon_age, weather, sky_pos,
                 streetlights, benches, cats, dogs, pigeons, plane,
                 shooting_stars, bats, people, n_people, birds, n_birds,
                 vehicles):
    p  = dict(PALETTES[period])
    sf = 1.0
    sf += 0.12 if period == 'day' and weather['rain'] == 0 and weather['clouds'] == 0 else 0
    sf -= weather['rain']   * 0.07
    sf -= weather['clouds'] * 0.04
    sf  = max(0.6, min(1.15, sf))
    p['sky_top'] = tuple(max(0, min(255, int(c * sf))) for c in p['sky_top'])
    p['sky_bot'] = tuple(max(0, min(255, int(c * sf))) for c in p['sky_bot'])

    mid_bld = lerp_color(p['far_bld'], p['near_bld'], 0.5)
    img  = Image.new('RGB', (RENDER_W, RENDER_H))
    draw = ImageDraw.Draw(img)

    draw_sky(draw, p)
    if p['stars']: draw_stars(draw, random.Random(41))
    if p['moon']:  draw_moon(draw, p, moon_age, sky_pos)
    if period in ('dawn', 'day', 'dusk'): draw_sun(draw, sky_pos)
    draw_aurora(draw, p, season, weather, period, frame)
    draw_shooting_stars(draw, shooting_stars, p, frame)
    draw_fireworks(draw, frame)
    draw_clouds(draw, p, clouds)
    draw_plane(draw, plane, p, period, frame)
    draw_bats(draw, bats, frame)
    draw_buildings(draw, far,  p['far_bld'],  p['win_lit'], p['win_dim'], p['lit_prob'] * 0.5,  random.Random(43))
    draw_buildings(draw, mid,  mid_bld,        p['win_lit'], p['win_dim'], p['lit_prob'] * 0.75, random.Random(46))
    draw_buildings(draw, near, p['near_bld'], p['win_lit'], p['win_dim'], p['lit_prob'],         random.Random(44))
    draw_building_decorations(draw, p, season, near, streetlights, frame)
    draw_ground(draw, p, random.Random(45))
    draw_reflections(draw, p, weather, frame)
    draw_vehicles(draw, vehicles, frame, period, sky_pos)
    draw_trees(draw, trees, season, weather['snow'])
    draw_light_cones(draw, img, p, streetlights, period, sky_pos)
    for sx in streetlights: draw_streetlight(draw, p, sx, period, sky_pos)
    for bx in benches:      draw_bench(draw, p, bx)
    draw_pigeons(draw, pigeons, frame)
    for (bx, color, is_walking, direction, speed) in cats:
        draw_cat(draw, bx, color, is_walking, direction, speed, frame)
    for (bx, color, direction, speed) in dogs:
        draw_dog(draw, bx, color, direction, speed, frame)
    lit_lamps = [sx + 4 for sx in streetlights] if _lights_on(period, sky_pos) else []
    draw_people(draw, people[:n_people], weather['rain'], frame, lit_lamps)
    draw_birds(draw, birds[:n_birds], frame)
    if weather['snow']:
        draw_snow(draw, frame, SNOW_FLAKES[weather['rain']], weather['vx'])
    else:
        draw_rain(draw, p, frame, RAIN_DROPS[weather['rain']], weather['vx'], weather['vy'])
    draw_weather_decorations(draw, season, frame, trees)
    if weather['lightning'] and frame in lightning_events:
        draw_lightning(draw, lightning_events[frame], frame)
    return img

def build_gif(period, weather, out_path, season=None, moon_age=None, sky_pos=None,
              life_seed=0, layout_seed=42, tree_density=6, building_density=6):
    if sky_pos is None:
        from datetime import datetime
        now_min = datetime.now().hour * 60 + datetime.now().minute
        sr      = weather.get('sunrise_min', 360)
        ss      = weather.get('sunset_min',  1080)
        dawn_s, dawn_e = sr - 45, sr + 60
        dusk_s, dusk_e = ss - 60, ss + 60
        if period == 'dawn':
            sky_pos = max(0.0, min(1.0, (now_min - dawn_s) / max(1, dawn_e - dawn_s))) * 0.2
        elif period == 'day':
            sky_pos = 0.2 + max(0.0, min(1.0, (now_min - dawn_e) / max(1, dusk_s - dawn_e))) * 0.6
        elif period == 'dusk':
            sky_pos = 0.8 + max(0.0, min(1.0, (now_min - dusk_s) / max(1, dusk_e - dusk_s))) * 0.2
        else:
            night_len = (dawn_s + 1440 - dusk_e) % 1440
            nm        = now_min if now_min >= dusk_e else now_min + 1440
            sky_pos   = max(0.0, min(1.0, (nm - dusk_e) / max(1, night_len)))

    clouds         = generate_clouds(CLOUD_COUNT[weather['clouds']], random.Random(42))
    far, mid, near = generate_buildings(random.Random(layout_seed),     building_density)
    trees          = generate_trees(random.Random(layout_seed + 1),     tree_density)
    streetlights, benches = generate_street_furniture(random.Random(layout_seed + 2))

    L  = life_seed * 1000
    people         = generate_people(random.Random(20 + L))
    birds          = generate_birds(random.Random(21 + L))
    cats           = generate_cats(random.Random(61 + L), period)
    dogs           = generate_dogs(random.Random(66 + L), period)
    pigeons        = generate_pigeons(random.Random(62 + L))
    plane          = generate_plane(random.Random(63 + L), period)
    shooting_stars = generate_shooting_stars(random.Random(64 + L), period)
    bats           = generate_bats(random.Random(65 + L), period)
    vehicles       = generate_vehicles(random.Random(67 + L), period)

    season         = season or get_season()
    moon_age       = moon_age if moon_age is not None else moon_phase_age()
    n_people, n_birds = activity_levels(period, weather['rain'])
    lightning_events  = (generate_lightning_events(random.Random(55), clouds)
                         if weather['lightning'] else {})
    frames = [render_frame(period, f, far, mid, near, clouds, trees, season,
                           lightning_events, moon_age, weather, sky_pos,
                           streetlights, benches, cats, dogs, pigeons, plane,
                           shooting_stars, bats, people, n_people, birds, n_birds,
                           vehicles)
              for f in range(FRAMES)]
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=FRAME_MS, loop=0, optimize=False, disposal=2)

# ── Wallpaper setter ──────────────────────────────────────────────────────────
def _detect_setter():
    import shutil
    for s in ('awww', 'swww'):
        if shutil.which(s):
            return s
    return None

def apply_wallpaper(setter, gif_path, transition='wipe'):
    import subprocess
    if setter == 'awww':
        subprocess.run(['awww', 'clear-cache'], check=False, capture_output=True)
        subprocess.run(['awww', 'img', gif_path,
                        '--filter', 'Nearest',
                        '--transition-type', transition], check=False)
    elif setter == 'swww':
        subprocess.run(['swww', 'img', gif_path,
                        '--transition-type', transition,
                        '--transition-fps', '25'], check=False)
    else:
        raise ValueError(f"Unknown setter '{setter}'. Supported: awww, swww")

# ── Weather ───────────────────────────────────────────────────────────────────
def fetch_weather(lat=None, lon=None):
    import urllib.request, json as _json

    DEFAULTS = dict(rain=2, clouds=1, snow=False, vx=1, vy=4,
                    lightning=False, sunrise_min=360, sunset_min=1080)
    try:
        if lat is None or lon is None:
            with urllib.request.urlopen('https://ipapi.co/json/', timeout=5) as r:
                loc = _json.loads(r.read())
            lat, lon = loc['latitude'], loc['longitude']

        url = (f'https://api.open-meteo.com/v1/forecast'
               f'?latitude={lat}&longitude={lon}'
               f'&current=weather_code,cloud_cover,temperature_2m,wind_speed_10m'
               f'&daily=sunrise,sunset'
               f'&timezone=auto')
        with urllib.request.urlopen(url, timeout=8) as r:
            data = _json.loads(r.read())
        cur   = data['current']
        daily = data['daily']
        code  = cur['weather_code']
        cover = cur['cloud_cover']
        temp  = cur['temperature_2m']
        wind  = cur['wind_speed_10m']

        def parse_hhmm(s):
            t = s.split('T')[1]
            h, m = map(int, t.split(':'))
            return h * 60 + m

        sunrise_min = parse_hhmm(daily['sunrise'][0])
        sunset_min  = parse_hhmm(daily['sunset'][0])
    except Exception:
        return DEFAULTS

    if   code <= 3:  rain = 0
    elif code <= 48: rain = 0
    elif code <= 55: rain = 1
    elif code == 61: rain = 1
    elif code == 63: rain = 2
    elif code == 65: rain = 3
    elif code <= 75: rain = 1
    elif code == 80: rain = 1
    elif code == 81: rain = 2
    else:            rain = 3

    snow      = temp <= 2.0 and 51 <= code <= 77
    clouds    = 0 if cover < 25 else (1 if cover < 65 else 2)
    lightning = code >= 95

    if   wind < 5:  vx, vy = 0, 5
    elif wind < 15: vx, vy = 1, 4
    elif wind < 30: vx, vy = 2, 3
    else:           vx, vy = 3, 2

    return dict(rain=rain, clouds=clouds, snow=snow, vx=vx, vy=vy,
                lightning=lightning, sunrise_min=sunrise_min, sunset_min=sunset_min)

def _current_period(sunrise_min, sunset_min):
    from datetime import datetime
    now_min = datetime.now().hour * 60 + datetime.now().minute
    dawn_s, dawn_e = sunrise_min - 45, sunrise_min + 60
    dusk_s, dusk_e = sunset_min  - 60, sunset_min  + 60
    if   dawn_s <= now_min < dawn_e:   return 'dawn'
    elif dawn_e <= now_min < dusk_s:   return 'day'
    elif dusk_s <= now_min < dusk_e:   return 'dusk'
    elif now_min >= dusk_e:            return 'evening'
    else:                              return 'night'

def _next_wake(sunrise_min, sunset_min):
    from datetime import datetime
    now   = datetime.now()
    now_s = now.hour * 3600 + now.minute * 60 + now.second
    for b in sorted([(sunrise_min - 45) * 60, (sunrise_min + 60) * 60,
                     (sunset_min  - 60) * 60, (sunset_min  + 60) * 60]):
        diff = b - now_s
        if diff > 60:
            return min(diff, 1800)
    return 1800

# ── Init wizard ───────────────────────────────────────────────────────────────
def _prompt_int(prompt, lo, hi, default):
    while True:
        raw = input(f"{prompt} [{lo}-{hi}] (default {default}): ").strip()
        if raw == '':
            return default
        try:
            v = int(raw)
            if lo <= v <= hi:
                return v
            print(f"  Please enter a number between {lo} and {hi}.")
        except ValueError:
            print("  Invalid input — enter a number.")

def run_init():
    cfg_path = Path.home() / '.config' / 'dynamic-city' / 'config.toml'
    print("\n=== dynamic-city setup ===\n")
    print("Press Enter to keep the default value shown in brackets.\n")

    tree_d = _prompt_int("Tree density   (1=sparse, 10=dense forest)", 1, 10, 6)
    bld_d  = _prompt_int("Building density (1=scattered, 10=packed skyline)", 1, 10, 6)
    print()

    setter = _detect_setter()
    if setter:
        print(f"Detected wallpaper setter: {setter}")
    else:
        print("Could not detect awww or swww. Install one before running the daemon.")
        setter = 'awww'

    QUICK_WEATHER = dict(rain=1, clouds=1, snow=False, vx=1, vy=4,
                         lightning=False, sunrise_min=360, sunset_min=1080)

    chosen_seed = None
    while True:
        seed = random.randint(1, 99999)
        print(f"\nLayout seed: {seed} — rendering preview (this takes ~10s)...")
        out  = f'/tmp/dynamic_city_init_{seed}.gif'
        build_gif('night', QUICK_WEATHER, out,
                  layout_seed=seed, tree_density=tree_d, building_density=bld_d)
        if setter:
            apply_wallpaper(setter, out, transition='none')
            print("Preview applied as wallpaper.")
        else:
            print(f"Preview saved to {out} — open it manually to inspect.")

        choice = input("Keep this layout? [y=yes / n=new seed / q=quit]: ").strip().lower()
        if choice == 'y':
            chosen_seed = seed
            break
        elif choice == 'q':
            print("Setup cancelled.")
            return

    res = input(f"\nMonitor resolution [default 2560x1440]: ").strip() or '2560x1440'

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(f"""\
# dynamic-city configuration — generated by --init
# Re-run `python3 dynamic-city.py --init` to pick a new layout.

[display]
resolution = "{res}"

[location]
# lat =
# lon =

[city]
layout_seed      = {chosen_seed}
tree_density     = {tree_d}
building_density = {bld_d}

[wallpaper]
setter     = "{setter}"
transition = "wipe"
""")
    print(f"\nConfig written to {cfg_path}")
    print("Run daemon.sh to start the live wallpaper, or add it to your compositor startup.\n")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys, subprocess
    args = sys.argv[1:]

    cfg = load_config()
    layout_seed      = cfg['city']['layout_seed']
    tree_density     = cfg['city']['tree_density']
    building_density = cfg['city']['building_density']
    setter           = cfg['wallpaper']['setter']
    transition       = cfg['wallpaper']['transition']
    loc_lat          = cfg['location'].get('lat') or None
    loc_lon          = cfg['location'].get('lon') or None

    def arg(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    def bool_arg(flag):
        v = arg(flag)
        return v not in (None, '0', 'false', 'False', 'no')

    def weather_from_args():
        return dict(rain=int(arg('--rain', '2')), clouds=int(arg('--clouds', '1')),
                    snow=bool_arg('--snow'), vx=int(arg('--vx', '1')),
                    vy=int(arg('--vy', '4')), lightning=bool_arg('--lightning'))

    if '--init' in args:
        run_init()

    elif '--export-lock-frames' in args:
        idx      = args.index('--export-lock-frames')
        out_dir  = args[idx + 1]
        gif_path = os.environ.get('DYNAMIC_CITY_GIF') or arg('--gif', '')
        if not gif_path:
            print('Set DYNAMIC_CITY_GIF env var or pass --gif PATH'); sys.exit(1)
        os.makedirs(out_dir, exist_ok=True)
        img = Image.open(gif_path)
        for f in range(FRAMES):
            img.seek(f)
            img.convert('RGB').save(os.path.join(out_dir, f'frame_{f:04d}.png'),
                                    compress_level=1)
        print(f'Exported {FRAMES} frames to {out_dir}')

    elif '--fetch-weather' in args:
        w      = fetch_weather(lat=loc_lat, lon=loc_lon)
        period = _current_period(w['sunrise_min'], w['sunset_min'])
        wake   = _next_wake(w['sunrise_min'], w['sunset_min'])
        print(f"period={period} rain={w['rain']} clouds={w['clouds']} "
              f"snow={int(w['snow'])} vx={w['vx']} vy={w['vy']} "
              f"lightning={int(w['lightning'])} wake={wake}")

    elif '--preview' in args:
        idx    = args.index('--preview')
        period = (args[idx + 1] if idx + 1 < len(args) and args[idx + 1] in PALETTES else 'night')
        if arg('--rain') and arg('--clouds'):
            weather = weather_from_args()
        else:
            print('Fetching weather...')
            raw     = fetch_weather(lat=loc_lat, lon=loc_lon)
            weather = {k: raw[k] for k in ('rain','clouds','snow','vx','vy','lightning')}
            for k, flag in [('rain','--rain'),('clouds','--clouds'),('vx','--vx'),('vy','--vy')]:
                if arg(flag): weather[k] = int(arg(flag))
            if '--snow'      in args: weather['snow']      = bool_arg('--snow')
            if '--lightning' in args: weather['lightning'] = bool_arg('--lightning')
        print(f"  period={period}  rain={weather['rain']}  clouds={weather['clouds']}  "
              f"snow={weather['snow']}  lightning={weather['lightning']}")
        path = (f"/tmp/dynamic_city_preview_{period}"
                f"_r{weather['rain']}_c{weather['clouds']}"
                f"_s{int(weather['snow'])}_l{int(weather['lightning'])}.gif")
        build_gif(period, weather, path,
                  layout_seed=layout_seed, tree_density=tree_density,
                  building_density=building_density)
        apply_wallpaper(setter, path, transition='none')
        print('Preview set. Re-run to update.')

    elif arg('--period'):
        _HOLIDAY_OVERRIDE = arg('--holiday')
        period  = arg('--period')
        weather = weather_from_args()
        out     = arg('--out', f'/tmp/dynamic_city_{period}.gif')
        ma = arg('--moon-age')
        sp = arg('--sky-pos')
        ls = arg('--life-seed')
        build_gif(period, weather, out,
                  season=arg('--season'),
                  moon_age=float(ma) if ma else None,
                  sky_pos=float(sp) if sp else None,
                  life_seed=int(ls) if ls else 0,
                  layout_seed=int(arg('--layout-seed', layout_seed)),
                  tree_density=int(arg('--tree-density', tree_density)),
                  building_density=int(arg('--building-density', building_density)))
        print(f'  {out}')

    else:
        out_dir = os.path.dirname(os.path.abspath(__file__))
        print('Fetching weather...')
        raw = fetch_weather(lat=loc_lat, lon=loc_lon)
        w   = {k: raw[k] for k in ('rain','clouds','snow','vx','vy','lightning')}
        print(f"  rain={w['rain']}  clouds={w['clouds']}  snow={w['snow']}  lightning={w['lightning']}")
        print('Generating wallpapers...')
        for period in PALETTES:
            out = os.path.join(out_dir, f'{period}.gif')
            build_gif(period, w, out,
                      layout_seed=layout_seed, tree_density=tree_density,
                      building_density=building_density)
            print(f'  {period}.gif  ({os.path.getsize(out)//1024} KB)')
        print('Done.')
