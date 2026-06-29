import asyncio
import logging
import random

from aiohttp import ClientTimeout
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import db
from cardgen import (
    LETTERS,
    RANGES,
    check_bingo,
    generate_card,
    generate_marked,
    render_card_image,
)
from config import ADMIN_IDS, BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()


# ---------------------------------------------------------------------------
# Көмекші функциялар
# ---------------------------------------------------------------------------

def build_card_keyboard(game_id: str, card, marked) -> InlineKeyboardMarkup:
    rows = []

    # Жоғарғы "B I N G O" қатары — батырма түрінде көрсетіледі, бірақ
    # басқанда ешқандай әрекет болмайды (тек безендіру/тақырып ретінде).
    header_row = [
        InlineKeyboardButton(text=letter, callback_data="noop")
        for letter in LETTERS
    ]
    rows.append(header_row)

    for r in range(5):
        buttons = []
        for c in range(5):
            value = card[r][c]
            is_marked = marked[r][c]
            if value == "FREE":
                text = "⭐FREE"
            elif is_marked:
                text = f"✅{value}"
            else:
                text = str(value)
            buttons.append(
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"pick:{game_id}:{r}:{c}",
                )
            )
        rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_header_text() -> str:
    return "Сіздің картаңыз:"


async def get_bot_username(bot: Bot) -> str:
    me = await bot.get_me()
    return me.username


# ---------------------------------------------------------------------------
# /newgame — админ ойын ашады
# ---------------------------------------------------------------------------

@router.message(Command("newgame"))
async def cmd_newgame(message: Message, bot: Bot):
    admin_id = message.from_user.id

    if admin_id not in ADMIN_IDS:
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game_id = await db.create_game(admin_id)
    username = await get_bot_username(bot)
    link = f"https://t.me/{username}?start=game_{game_id}"

    await message.answer(
        "🎲 Жаңа Bingo ойыны ашылды!\n\n"
        f"Ойын ID: <code>{game_id}</code>\n\n"
        "Ойыншыларды шақыру үшін мына сілтемені жіберіңіз:\n"
        f"{link}\n\n"
        "Сандарды шығару командалары (тек сізге көрінеді):\n"
        "/next, /next2, /next3, /next4\n\n"
        "Ойынды аяқтау: /stop"
    )


# ---------------------------------------------------------------------------
# /start game_xxxxx — ойыншы кіреді (Deep Linking)
# ---------------------------------------------------------------------------

@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject, bot: Bot):
    payload = command.args or ""
    if not payload.startswith("game_"):
        await message.answer("Сәлем! Ойынға қосылу үшін админнен сілтеме алыңыз.")
        return

    game_id = payload[len("game_"):]
    game = await db.get_game(game_id)

    if not game:
        await message.answer("❌ Бұл ойын табылмады. Сілтеме қате немесе ойын жойылған.")
        return

    if game["status"] != "active":
        await message.answer("⚠️ Бұл ойын аяқталған.")
        return

    user_id = message.from_user.id
    existing = await db.get_player(game_id, user_id)

    if existing:
        kb = build_card_keyboard(
            game_id,
            existing["card"],
            existing["marked"]
        )

        await message.answer(
            "Сіз бұл ойынға бұрын қосылған болыпсыз.",
            reply_markup=kb
        )
        return

    card = generate_card()
    marked = generate_marked()
    username = message.from_user.username or message.from_user.full_name

    await db.add_player(game_id, user_id, username, card, marked)

    kb = build_card_keyboard(game_id, card, marked)

    try:
        await message.answer(
            "✅ Сіз ойынға қосылдыңыз!\n\n"
            "Міне сіздің жеке картаңыз.\n"
            "Админ жариялаған сан шыққанда, оны басыңыз.",
            reply_markup=kb
        )
    except Exception:
        logger.exception("Ойыншыға карта жіберілмеді")

    try:
        await bot.send_message(
            game["admin_id"],
            f"👤 Жаңа ойыншы қосылды: @{username} (ойын {game_id})"
        )
    except Exception:
        logger.exception("Админге хабар жіберілмеді")
@router.message(CommandStart())
async def cmd_start_plain(message: Message):
    await message.answer(
        "Сәлем! Bingo ботына қош келдіңіз 🎉\n\n"
        "Жаңа ойын ашу үшін: /newgame\n"
        "Ойынға қосылу үшін админнен сілтеме сұраңыз."
    )


# ---------------------------------------------------------------------------
# /next, /next2, /next3, /next4 — админ сандарды шығарады
# ---------------------------------------------------------------------------

async def draw_numbers(message: Message, count: int):
    admin_id = message.from_user.id

    if admin_id not in ADMIN_IDS:
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game = await db.get_active_game_by_admin(admin_id)

    if not game:
        await message.answer(
            "❌ Сізде белсенді ойын жоқ. Алдымен /newgame командасын қолданыңыз."
        )
        return

    game_id = game["id"]

    # Бір шығаруда бірдей әріп екі рет шықпауы керек (мыс. екі B қатар шықпайды),
    # сондықтан count санына сай ӘРТҮРЛІ әріптер таңдаймыз (барлығы 5: B,I,N,G,O).
    count = min(count, len(LETTERS))
    selected_letters = random.sample(LETTERS, count)

    lines = []
    for letter in selected_letters:
        lo, hi = RANGES[letter]
        # Сан келесі шығаруларда қайталана алады, сондықтан мұнда тек кездейсоқ
        # таңдаймыз — бұрын шыққан сандарды алып тастамаймыз.
        number = random.randint(lo, hi)
        await db.add_called_number(game_id, number, letter)
        lines.append(f"{letter}-{number}")

    try:
        await message.answer("\n".join(lines))
    except Exception:
        logger.exception("Сандарды жіберу мүмкін болмады")


@router.message(Command("next"))
async def cmd_next(message: Message):
    await draw_numbers(message, 1)


@router.message(Command("next2"))
async def cmd_next2(message: Message):
    await draw_numbers(message, 2)


@router.message(Command("next3"))
async def cmd_next3(message: Message):
    await draw_numbers(message, 3)


@router.message(Command("next4"))
async def cmd_next4(message: Message):
    await draw_numbers(message, 4)


# ---------------------------------------------------------------------------
# Ойыншы батырманы басады
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    # B I N G O тақырып батырмалары — тек безендіру үшін, ешқандай әрекет жасамайды.
    await callback.answer()


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_number(callback: CallbackQuery, bot: Bot):
    _, game_id, row_s, col_s = callback.data.split(":")
    row, col = int(row_s), int(col_s)

    game = await db.get_game(game_id)
    if not game or game["status"] != "active":
        await callback.answer("Бұл ойын аяқталған.", show_alert=True)
        return

    user_id = callback.from_user.id
    player = await db.get_player(game_id, user_id)
    if not player:
        await callback.answer("Сіз бұл ойынға қосылмағансыз.", show_alert=True)
        return

    card = player["card"]
    marked = player["marked"]
    value = card[row][col]

    if value == "FREE":
        await callback.answer("Бұл ұяшық автоматты түрде белгіленген ⭐")
        return

    if marked[row][col]:
        await callback.answer("Бұл сан қазір де белгіленген ✅")
        return

    is_called = await db.is_number_called(game_id, int(value))
    if not is_called:
        await callback.answer("❌ Бұл сан әлі шықпаған.")
        return

    marked[row][col] = True
    await db.update_player_marked(game_id, user_id, marked)

    kb = build_card_keyboard(game_id, card, marked)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass

    await callback.answer(f"✅ {value} белгіленді!")

    win_cells = check_bingo(marked)
    if win_cells and not player["won"]:
        await handle_bingo_win(bot, game, player, card, marked, win_cells)


async def handle_bingo_win(bot: Bot, game: dict, player: dict, card, marked, win_cells):
    game_id = game["id"]
    user_id = player["user_id"]
    username = player["username"] or str(user_id)

    await db.set_player_won(game_id, user_id)

    # Ойыншыға хабарлама
    try:
        await bot.send_message(user_id, "🎉 Сіз BINGO жасадыңыз!")
    except Exception:
        logger.exception("Ойыншыға хабарлама жіберу мүмкін болмады")

    # Дәлел ретінде картаны сурет түрінде жасау
    image_bytes = render_card_image(card, marked, win_cells)
    photo = BufferedInputFile(image_bytes, filename=f"bingo_{game_id}_{user_id}.png")

    caption = f"🏆 @{username} BINGO жасады!"

    # Админге сурет пен хабарлама
    try:
        await bot.send_photo(game["admin_id"], photo=photo, caption=caption)
    except Exception:
        logger.exception("Админге сурет жіберу мүмкін болмады")

    # Барлық ойыншыларға хабарлау
    players = await db.get_players(game_id)
    for p in players:
        if p["user_id"] == game["admin_id"]:
            continue
        photo2 = BufferedInputFile(image_bytes, filename=f"bingo_{game_id}_{user_id}.png")
        try:
            await bot.send_photo(p["user_id"], photo=photo2, caption=caption)
        except Exception:
            logger.exception("Ойыншыға сурет жіберу мүмкін болмады")


# ---------------------------------------------------------------------------
# /stop — ойынды аяқтау
# ---------------------------------------------------------------------------

@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot):
    admin_id = message.from_user.id

    if admin_id not in ADMIN_IDS:
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game = await db.get_active_game_by_admin(admin_id)

    if not game:
        await message.answer("❌ Сізде белсенді ойын жоқ.")
        return

    game_id = game["id"]
    await db.set_game_status(game_id, "finished")

    players = await db.get_players(game_id)
    for p in players:
        try:
            await bot.send_message(p["user_id"], "Ойын аяқталды.")
        except Exception:
            logger.exception("Хабарлама жіберу мүмкін болмады")

    await message.answer(f"✅ Ойын ({game_id}) аяқталды. Барлық ойыншыларға хабарланды.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await db.init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML")
    )

    dp = Dispatcher()
    dp.include_router(router)

    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)
        except Exception:
            logger.exception("Polling қатесі")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
