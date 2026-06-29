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


def letter_for_number(number: int) -> str:
    for letter, (lo, hi) in RANGES.items():
        if lo <= number <= hi:
            return letter
    return "?"


def generate_card():
    """5x5 карта жасайды. card[row][col]. Орталығы (2,2) = FREE."""
    columns = []
    for letter in LETTERS:
        lo, hi = RANGES[letter]
        nums = random.sample(range(lo, hi + 1), 5)
        columns.append(nums)

    card = [[columns[col][row] for col in range(5)] for row in range(5)]
    card[2][2] = FREE
    return card


def generate_marked():
    marked = [[False] * 5 for _ in range(5)]
    marked[2][2] = True  # FREE автоматты белгіленген
    return marked


def check_bingo(marked):
    """Жеңіс сызықтарын тексереді. Жеңіс болса, белгіленген ұяшықтардың
    координаттар тізімін қайтарады, әйтпесе None."""
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


def render_card_image(card, marked, win_cells=None) -> bytes:
    """Картаны PNG сурет ретінде жасап шығарады."""
    win_cells = set(win_cells or [])

    cell_size = 100
    header_h = 80
    margin = 10
    grid_size = cell_size * 5
    width = grid_size + margin * 2
    height = grid_size + header_h + margin * 2

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_header = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40
        )
        font_cell = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30
        )
    except Exception:
        font_header = ImageFont.load_default()
        font_cell = ImageFont.load_default()

    # Header letters
    for col, letter in enumerate(LETTERS):
        x = margin + col * cell_size + cell_size // 2
        y = margin + header_h // 2
        draw.text((x, y), letter, fill="#1a1a4d", font=font_header, anchor="mm")

    # Grid
    for row in range(5):
        for col in range(5):
            x0 = margin + col * cell_size
            y0 = margin + header_h + row * cell_size
            x1 = x0 + cell_size
            y1 = y0 + cell_size

            is_marked = marked[row][col]
            is_win = (row, col) in win_cells

            if is_win:
                fill_color = "#ffd54f"  # жеңіс сызығы - сары/алтын
            elif is_marked:
                fill_color = "#4caf50"  # белгіленген - жасыл
            else:
                fill_color = "#ffffff"  # белгіленбеген - ақ

            border_color = "#ff0000" if is_win else "#333333"
            border_width = 4 if is_win else 2

            draw.rectangle([x0, y0, x1, y1], fill=fill_color, outline=border_color, width=border_width)

            value = card[row][col]
            text = "★" if value == FREE else str(value)
            text_color = "#ffffff" if (is_marked and not is_win) else "#1a1a4d"
            draw.text(
                ((x0 + x1) // 2, (y0 + y1) // 2),
                text,
                fill=text_color,
                font=font_cell,
                anchor="mm",
            )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()
