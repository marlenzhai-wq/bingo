"""
Bingo Bot — карта генерациясы және PNG сурет рендері (Pillow).
"""
import io
import random

from PIL import Image, ImageDraw, ImageFont

LETTERS = ["B", "I", "N", "G", "O"]
RANGES = {
    "B": (1, 15),
    "I": (16, 30),
    "N": (31, 45),
    "G": (46, 60),
    "O": (61, 75),
}

FREE = "FREE"

# ---------------------------------------------------------------------------
# Карта генерациясы
# ---------------------------------------------------------------------------

def generate_card() -> list[list]:
    """5×5 карта. card[row][col]. Ортасы (2,2) = FREE."""
    columns = []
    for letter in LETTERS:
        lo, hi = RANGES[letter]
        nums = random.sample(range(lo, hi + 1), 5)
        columns.append(nums)
    card = [[columns[col][row] for col in range(5)] for row in range(5)]
    card[2][2] = FREE
    return card


def generate_marked() -> list[list]:
    marked = [[False] * 5 for _ in range(5)]
    marked[2][2] = True  # FREE автоматты белгіленген
    return marked

# ---------------------------------------------------------------------------
# BINGO тексеру
# ---------------------------------------------------------------------------

def check_bingo(marked: list[list]) -> list[tuple] | None:
    """Визуалды BINGO тексеру.
    Жеңіс болса — ұяшық координаттарының тізімін қайтарады, әйтпесе None."""
    # Горизонталь
    for r in range(5):
        if all(marked[r][c] for c in range(5)):
            return [(r, c) for c in range(5)]
    # Тік
    for c in range(5):
        if all(marked[r][c] for r in range(5)):
            return [(r, c) for r in range(5)]
    # Диагональдар
    if all(marked[i][i] for i in range(5)):
        return [(i, i) for i in range(5)]
    if all(marked[i][4 - i] for i in range(5)):
        return [(i, 4 - i) for i in range(5)]
    return None


def is_real_bingo(card: list[list], win_cells: list[tuple],
                  called_set: set[int]) -> bool:
    """Жеңіс сызығының барлық ұяшықтары шынымен шыққан болуы тиіс.
    FREE ұяшығы әрқашан есептеледі."""
    for r, c in win_cells:
        val = card[r][c]
        if val == FREE:
            continue
        if int(val) not in called_set:
            return False
    return True

# ---------------------------------------------------------------------------
# PNG сурет рендері
# ---------------------------------------------------------------------------

def _load_fonts():
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in paths:
        try:
            return (
                ImageFont.truetype(path, 40),
                ImageFont.truetype(path, 30),
            )
        except Exception:
            pass
    default = ImageFont.load_default()
    return default, default


def render_card_image(
    card: list[list],
    marked: list[list],
    win_cells=None,
    called_set: set[int] | None = None,
) -> bytes:
    """
    Картаны PNG сурет ретінде жасайды.

    Режимдер:
    • called_set=None (ойын барысы):
        - win_cells → сары+қызыл шекара (жеңіс сызығы)
        - marked     → жасыл
        - қалғаны    → ақ
    • called_set берілген (/stop кезінде):
        - marked + called  → жасыл (дұрыс)
        - marked + !called → қызыл (қате)
        - !marked          → ақ
        - FREE             → жасыл
    """
    win_cells = set(win_cells or [])
    font_h, font_c = _load_fonts()

    cell = 100
    header_h = 80
    margin = 10
    width = cell * 5 + margin * 2
    height = cell * 5 + header_h + margin * 2

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # ---- Тақырып әріптері ----
    for col, letter in enumerate(LETTERS):
        x = margin + col * cell + cell // 2
        y = margin + header_h // 2
        draw.text((x, y), letter, fill="#1a1a4d", font=font_h, anchor="mm")

    # ---- Торлар ----
    for r in range(5):
        for c in range(5):
            x0 = margin + c * cell
            y0 = margin + header_h + r * cell
            x1 = x0 + cell
            y1 = y0 + cell

            val = card[r][c]
            is_free = val == FREE
            is_marked = marked[r][c]
            is_win = (r, c) in win_cells

            if called_set is not None:
                # /stop режимі: дұрыс/қате бөлу
                if is_free or (is_marked and (is_free or int(val) in called_set)):
                    fill = "#4caf50"   # жасыл — дұрыс
                    txt_color = "#ffffff"
                elif is_marked:
                    fill = "#f44336"   # қызыл — қате
                    txt_color = "#ffffff"
                else:
                    fill = "#f5f5f5"   # ақ — белгіленбеген
                    txt_color = "#1a1a4d"
                border = "#333333"
                bw = 2
            else:
                # Ойын барысы режимі
                if is_win:
                    fill = "#ffd54f"   # сары — жеңіс сызығы
                    txt_color = "#1a1a4d"
                elif is_marked:
                    fill = "#4caf50"   # жасыл — белгіленген
                    txt_color = "#ffffff"
                else:
                    fill = "#ffffff"
                    txt_color = "#1a1a4d"
                border = "#ff0000" if is_win else "#333333"
                bw = 4 if is_win else 2

            draw.rectangle([x0, y0, x1, y1],
                           fill=fill, outline=border, width=bw)

            text = "★" if is_free else str(val)
            draw.text(((x0 + x1) // 2, (y0 + y1) // 2),
                      text, fill=txt_color, font=font_c, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
