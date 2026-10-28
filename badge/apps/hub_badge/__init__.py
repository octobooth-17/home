import random

settings_error = False
try:
    import secrets
except ImportError:
    secrets = None
    print("Hub Badge: no profile settings module; using placeholders.")
except SyntaxError:
    secrets = None
    settings_error = True
    print("Hub Badge: invalid secrets.py syntax; profile settings unavailable.")

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2

ORANGE = color.rgb(255, 163, 26)
BLACK = color.rgb(0, 0, 0)
WHITE = color.rgb(255, 255, 255)
GREY = color.rgb(170, 170, 170)
DIM = color.rgb(105, 105, 105)
HEADER = color.rgb(27, 27, 27)
PILL = color.rgb(45, 45, 45)
SHADES = [
    color.rgb(38, 38, 38),
    color.rgb(92, 56, 10),
    color.rgb(150, 92, 16),
    color.rgb(206, 128, 21),
    ORANGE,
]

mona = font.load("/system/assets/fonts/MonaSans-Medium.af")

HEADER_H = 28
CATEGORIES = ("Repos", "Stars", "Forks", "PRs", "Issues")
TABS = ("Hottest", "Most Starred", "Newest")
REPOS = (
    "hello-world", "dotfiles", "octo-badge", "universe-26", "ship-it",
    "merge-party", "copilot-tricks", "mona-pet", "spoon-knife", "linguist",
    "actions-lab", "pixel-octo", "rubber-duck", "night-build", "yolo-deploy",
)

CARD_W = 148
THUMB_H = 54
CARD_H = 88
GRID_LEFT = 8
GRID_TOP = 58
GRID_GAP_X = 8
GRID_GAP_Y = 6
CELL = 8
CELL_STEP = 10
CELL_COLS = 14
CELL_ROWS = 5


def setting(key):
    return str(getattr(secrets, key, "") or "").strip()


def text_width(text, size):
    return screen.measure_text(text, font_size=size)[0]


def bold(text, x, y, size, weight=None):
    weight = size * 0.035 if weight is None else weight
    screen.text(text, x, y, size)
    screen.text(text, x + weight / 2, y, size)
    screen.text(text, x + weight, y, size)


def fit_size(text, size, max_width):
    width = text_width(text, size)
    if width > max_width:
        size = size * max_width / width
    return size


def center_text(text, y, size, max_width=None, heavy=False):
    max_width = max_width or screen.width - 16
    size = fit_size(text, size, max_width)
    x = (screen.width - text_width(text, size)) / 2
    if heavy:
        bold(text, x, y, size)
    else:
        screen.text(text, x, y, size)


def clip_text(text, size, max_width):
    if text_width(text, size) <= max_width:
        return text
    while text and text_width(text + "...", size) > max_width:
        text = text[:-1]
    return text + "..."


class Logo:
    BOX_TOP = 0.2
    BOX_H = 0.98

    def __init__(self, size):
        screen.font = mona
        self.size = size
        self.git_w = text_width("Git", size)
        self.pad = size * 0.12
        self.gap = size * 0.07
        self.box_w = text_width("hub", size) + self.pad * 2
        self.width = self.git_w + self.gap + self.box_w
        self.box = shape.rounded_rectangle(0, 0, self.box_w, size * self.BOX_H, size * 0.14)

    def draw(self, x, y):
        size = self.size
        screen.font = mona
        screen.pen = WHITE
        bold("Git", x, y, size)
        box_x = x + self.git_w + self.gap
        self.box.transform = mat3().translate(box_x, y + size * self.BOX_TOP)
        screen.pen = ORANGE
        screen.shape(self.box)
        screen.pen = BLACK
        bold("hub", box_x + self.pad, y, size)

    def draw_centered(self, y):
        self.draw((screen.width - self.width) / 2, y)


def make_card(seed, owner):
    random.seed(seed)
    stars = random.randint(120, 98000)
    if stars >= 1000:
        stars_text = "{:.1f}K stars".format(stars / 1000)
    else:
        stars_text = "{} stars".format(stars)
    return {
        "title": owner + "/" + REPOS[random.randint(0, len(REPOS) - 1)],
        "stars": stars_text,
        "score": "{}%".format(random.randint(81, 99)),
        "tag": "v{}.{}.{}".format(random.randint(0, 4), random.randint(0, 19), random.randint(0, 9)),
        "levels": bytes([min(4, max(0, random.randint(-2, 5))) for _ in range(CELL_COLS * 2 * CELL_ROWS)]),
    }


name = setting("CONTACT_NAME")
handle = setting("GITHUB_USERNAME").lstrip("@")
owner = handle or "octocat"

if name and handle:
    title, subtitle = name, "@" + handle
elif handle:
    title, subtitle = handle, "github.com/" + handle
elif name:
    title, subtitle = name, "Add your GitHub username in Settings"
else:
    title = "Your Name"
    subtitle = "Settings file needs fixing" if settings_error else "Add your name in Settings"

big_logo = Logo(58)
small_logo = Logo(17)
cards = [[make_card(tab * 101 + index * 7 + 3, owner) for index in range(4)] for tab in range(len(TABS))]

pill_shapes = []
thumb_shape = shape.rounded_rectangle(0, 0, CARD_W, THUMB_H, 5)
select_shape = shape.rounded_rectangle(0, 0, CARD_W + 6, THUMB_H + 6, 7)
cell_shape = shape.rounded_rectangle(0, 0, CELL, CELL, 2)
search_ring = shape.circle(0, 0, 6).stroke(2)
search_handle = shape.line(0, 0, 5, 5, 2.5)

PILL_SIZE = 13
PILL_H = 22
PILL_PAD = 8
PILL_GAP = 5
screen.font = mona
for label in CATEGORIES:
    width = text_width(label, PILL_SIZE) + PILL_PAD * 2
    pill_shapes.append((width, shape.rounded_rectangle(0, 0, width, PILL_H, PILL_H / 2)))
PILLS_W = sum(width for width, _ in pill_shapes) + PILL_GAP * (len(pill_shapes) - 1)

TAG_SIZE = 11
for tab_cards in cards:
    for card in tab_cards:
        card["tag_w"] = text_width(card["tag"], TAG_SIZE) + 8
        card["tag_shape"] = shape.rounded_rectangle(0, 0, card["tag_w"], 15, 3)

view = 0
tab = 0
selected = 0


def draw_header():
    screen.pen = HEADER
    screen.rectangle(0, 0, screen.width, HEADER_H)

    screen.pen = WHITE
    for i in range(3):
        screen.rectangle(10, 8 + i * 5, 16, 2)

    small_logo.draw_centered(3)

    screen.pen = WHITE
    search_ring.transform = mat3().translate(297, 12)
    screen.shape(search_ring)
    search_handle.transform = mat3().translate(301, 16)
    screen.shape(search_handle)


def draw_pills(y):
    x = (screen.width - PILLS_W) / 2
    active = (badge.ticks // 1400) % len(CATEGORIES)
    for index, label in enumerate(CATEGORIES):
        width, pill = pill_shapes[index]
        pill.transform = mat3().translate(x, y)
        screen.pen = ORANGE if index == active else PILL
        screen.shape(pill)
        screen.pen = BLACK if index == active else WHITE
        screen.text(label, x + PILL_PAD, y + 2, PILL_SIZE)
        x += width + PILL_GAP


def draw_badge():
    draw_header()
    big_logo.draw_centered(44)

    screen.font = mona
    screen.pen = WHITE
    center_text(title, 128, 28, heavy=True)
    screen.pen = ORANGE if (settings_error or name or handle) else GREY
    center_text(subtitle, 166, 17)

    draw_pills(206)


def draw_tabs():
    size = 14
    x = 10
    for index, label in enumerate(TABS):
        width = text_width(label, size)
        screen.pen = ORANGE if index == tab else GREY
        screen.text(label, x, HEADER_H + 4, size)
        if index == tab:
            screen.rectangle(x, HEADER_H + 22, width, 2)
        x += width + 16
    screen.pen = PILL
    screen.rectangle(0, HEADER_H + 24, screen.width, 1)


def draw_card(card, left, top, active):
    if active:
        select_shape.transform = mat3().translate(left - 3, top - 3)
        screen.pen = ORANGE
        screen.shape(select_shape)

    thumb_shape.transform = mat3().translate(left, top)
    screen.pen = BLACK if active else color.rgb(18, 18, 18)
    screen.shape(thumb_shape)

    scroll = (badge.ticks // 220) % CELL_COLS if active else 0
    levels = card["levels"]
    grid_left = left + (CARD_W - CELL_COLS * CELL_STEP + (CELL_STEP - CELL)) / 2
    grid_top = top + (THUMB_H - CELL_ROWS * CELL_STEP + (CELL_STEP - CELL)) / 2
    for row in range(CELL_ROWS):
        for col in range(CELL_COLS):
            screen.pen = SHADES[levels[row * CELL_COLS * 2 + col + scroll]]
            cell_shape.transform = mat3().translate(grid_left + col * CELL_STEP, grid_top + row * CELL_STEP)
            screen.shape(cell_shape)

    tag_w = card["tag_w"]
    tag_shape = card["tag_shape"]
    tag_shape.transform = mat3().translate(left + CARD_W - tag_w - 4, top + THUMB_H - 19)
    screen.pen = color.rgb(0, 0, 0, 210)
    screen.shape(tag_shape)
    screen.pen = WHITE
    screen.text(card["tag"], left + CARD_W - tag_w, top + THUMB_H - 19, TAG_SIZE)

    screen.pen = WHITE
    screen.text(clip_text(card["title"], 13, CARD_W), left, top + THUMB_H + 4, 13)
    screen.pen = GREY
    screen.text(card["stars"], left, top + THUMB_H + 19, 11)
    screen.pen = ORANGE
    score_w = text_width(card["score"], 11)
    screen.text(card["score"], left + CARD_W - score_w, top + THUMB_H + 19, 11)


def draw_browse():
    draw_header()
    screen.font = mona
    draw_tabs()
    for index, card in enumerate(cards[tab]):
        col = index % 2
        row = index // 2
        left = GRID_LEFT + col * (CARD_W + GRID_GAP_X)
        top = GRID_TOP + row * (CARD_H + GRID_GAP_Y)
        draw_card(card, left, top, index == selected)


def handle_input():
    global view, tab, selected
    if badge.pressed(BUTTON_SELECT):
        view = 1 - view
    elif view == 1:
        if badge.pressed(BUTTON_BACK):
            view = 0
        if badge.pressed(BUTTON_RIGHT):
            tab = (tab + 1) % len(TABS)
            selected = 0
        if badge.pressed(BUTTON_LEFT):
            tab = (tab - 1) % len(TABS)
            selected = 0
        if badge.pressed(BUTTON_DOWN):
            selected = (selected + 1) % 4
        if badge.pressed(BUTTON_UP):
            selected = (selected - 1) % 4


def update():
    handle_input()
    screen.fill_rule = image.EVEN_ODD
    screen.font = mona
    screen.pen = BLACK
    screen.clear()
    if view == 0:
        draw_badge()
    else:
        draw_browse()


run(update)
