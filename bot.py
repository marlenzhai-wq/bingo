"""
Bingo Bot — aiogram 3.x
Барлық handler, callback және admin логикасы осы файлда.
"""
import asyncio
import logging
import random

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
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
    FREE,
    LETTERS,
    RANGES,
    check_bingo,
    generate_card,
    generate_marked,
    is_real_bingo,
    render_card_image,
)
from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

# ---------------------------------------------------------------------------
# Утилиталар
# ---------------------------------------------------------------------------

async def get_bot_username(bot: Bot) -> str:
    me = await bot.get_me()
    return me.username


def get_display_name(player: dict) -> str:
    """Ойыншының атын дұрыс тәртіппен қайтарады:
    1. @username
    2. FirstName LastName
    3. FirstName
    4. ID: 123456789
    """
    if player.get("username"):
        return f"@{player['username']}"
    parts = [player.get("first_name") or "", player.get("last_name") or ""]
    full = " ".join(p for p in parts if p).strip()
    if full:
        return full
    return f"ID: {player['user_id']}"


def _players_list_text(players: list[dict]) -> str:
    if not players:
        lines = "  (ешкім жоқ)"
    else:
        lines = "\n".join(
            f"{i + 1}. {get_display_name(p)}"
            for i, p in enumerate(players)
        )
    return f"👥 <b>Ойыншылар тізімі</b>\n\n{lines}\n\nБарлығы: {len(players)}"


def _go_keyboard(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="▶️ GO — ойынды бастау",
                             callback_data=f"go:{game_id}")
    ]])


def build_card_keyboard(game_id: str, card, marked) -> InlineKeyboardMarkup:
    rows = []
    # Тақырып: B I N G O батырмалары (тек безендіру)
    rows.append([
        InlineKeyboardButton(text=letter, callback_data="noop")
        for letter in LETTERS
    ])
    for r in range(5):
        row_btns = []
        for c in range(5):
            val = card[r][c]
            is_marked = marked[r][c]
            if val == FREE:
                text = "⭐"
            elif is_marked:
                text = f"✅{val}"
            else:
                text = str(val)
            row_btns.append(InlineKeyboardButton(
                text=text,
                callback_data=f"pick:{game_id}:{r}:{c}",
            ))
        rows.append(row_btns)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_players_msg(bot: Bot, game_id: str, admin_id: int, players: list[dict]):
    """Ойыншылар тізімі хабарламасын жаңартады (editMessageText).
    game_id берілген кезде DB-ден players_msg_id-ті тікелей оқиды —
    осылай ескі game dict-індегі None мәнін айналып өтеміз."""
    # Ең соңғы players_msg_id-ті DB-ден алу
    fresh_game = await db.get_game(game_id)
    if not fresh_game:
        return
    msg_id = fresh_game.get("players_msg_id")
    if not msg_id:
        logger.warning("_edit_players_msg: players_msg_id жоқ, game_id=%s", game_id)
        return
    try:
        await bot.edit_message_text(
            chat_id=admin_id,
            message_id=msg_id,
            text=_players_list_text(players),
            reply_markup=_go_keyboard(game_id),
            parse_mode="HTML",
        )
        logger.info("Ойыншылар тізімі жаңартылды: game=%s msg=%s", game_id, msg_id)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("edit_message_text TelegramBadRequest: %s", e)
        else:
            logger.info("edit_message_text: хабарлама өзгермеді (not modified), елемейміз")
    except Exception:
        logger.exception("_edit_players_msg күтпеген қате")

# ---------------------------------------------------------------------------
# /newgame
# ---------------------------------------------------------------------------

@router.message(Command("newgame"))
async def cmd_newgame(message: Message, bot: Bot):
    user_id = message.from_user.id
    if not await db.is_admin(user_id):
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    # Ескі белсенді ойын бар болса — жаңасын ашпау
    existing = await db.get_nonfin_game_by_admin(user_id)
    if existing:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        await message.answer(
            f"⚠️ Сізде белсенді ойын бар:\n"
            f"ID: <code>{existing['id']}</code>\n"
            f"Статус: {existing['status']}\n\n"
            f"Алдымен /stop арқылы аяқтаңыз.",
            parse_mode="HTML",
        )
        return

    game_id = await db.create_game(user_id)
    username = await get_bot_username(bot)
    link = f"https://t.me/{username}?start=game_{game_id}"

    await message.answer(
        f"🎲 <b>Жаңа Bingo ойыны ашылды!</b>\n\n"
        f"Ойын ID: <code>{game_id}</code>\n\n"
        f"Ойыншыларды шақыру сілтемесі:\n{link}\n\n"
        f"Командалар:\n"
        f"/next /next2 /next3 /next4 — сан шығару\n"
        f"/go — ойынды бастау (немесе төмендегі батырма)\n"
        f"/stop — ойынды аяқтау",
        parse_mode="HTML",
    )

    # Ойыншылар тізімі хабарламасы (GO батырмасымен)
    list_msg = await message.answer(
        _players_list_text([]),
        reply_markup=_go_keyboard(game_id),
        parse_mode="HTML",
    )
    await db.save_players_msg_id(game_id, list_msg.message_id)

# ---------------------------------------------------------------------------
# /start game_xxxxx (Deep Link) — ойыншы кіреді
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
        await message.answer("❌ Ойын табылмады. Сілтеме қате немесе ойын жойылған.")
        return

    if game["status"] == "started":
        await message.answer(
            "⛔ <b>Бұл ойын басталып кетті.</b>\nҚосылу мүмкін емес.",
            parse_mode="HTML",
        )
        return

    if game["status"] == "finished":
        await message.answer("⚠️ Бұл ойын аяқталған.")
        return

    user_id = message.from_user.id
    existing = await db.get_player(game_id, user_id)

    if existing:
        await message.answer("Сіз бұл ойынға бұрын қосылған болыпсыз. Картаңыз:")
        kb = build_card_keyboard(game_id, existing["card"], existing["marked"])
        await message.answer("Сіздің картаңыз:", reply_markup=kb, parse_mode="HTML")
        return

    card = generate_card()
    marked = generate_marked()
    uname  = message.from_user.username  or ""
    fname  = message.from_user.first_name or ""
    lname  = message.from_user.last_name  or ""

    await db.add_player(game_id, user_id, uname, fname, lname, card, marked)

    # Дерекқорға жазылғанын тексеру
    players = await db.get_players(game_id)
    logger.info("add_player кейін ойыншылар саны: %d (game=%s)", len(players), game_id)

    await message.answer(
        "✅ <b>Сіз ойынға қосылдыңыз!</b>\n\n"
        "Мына картадан санды белгілей аласыз. "
        "Кез келген санды баса аласыз — бір рет басса белгіленеді, "
        "екінші рет басса белгі алынады.\n\n"
        "⚠️ BINGO тек шын шыққан сандар ғана есептеледі!",
        parse_mode="HTML",
    )
    kb = build_card_keyboard(game_id, card, marked)
    await message.answer("Сіздің картаңыз:", reply_markup=kb, parse_mode="HTML")

    # Ойыншылар тізімін жаңарту (editMessageText)
    # players жоғарыда add_player кейін алынды
    await _edit_players_msg(bot, game_id, game["admin_id"], players)


@router.message(CommandStart())
async def cmd_start_plain(message: Message):
    await message.answer(
        "Сәлем! Bingo ботына қош келдіңіз 🎉\n\n"
        "Жаңа ойын ашу үшін: /newgame\n"
        "Ойынға қосылу үшін админнен сілтеме сұраңыз."
    )

# ---------------------------------------------------------------------------
# GO — ойын бастау (/go және батырма)
# ---------------------------------------------------------------------------

async def _do_start_game(bot: Bot, game: dict):
    """Ойынды 'started' күйіне ауыстырады."""
    game_id = game["id"]
    admin_id = game["admin_id"]
    await db.set_game_status(game_id, "started")

    # GO батырмасын алып тастап, "Ойын басталды!" деп жаңартамыз
    fresh = await db.get_game(game_id)
    msg_id = fresh.get("players_msg_id") if fresh else None
    if msg_id:
        players = await db.get_players(game_id)
        try:
            await bot.edit_message_text(
                chat_id=admin_id,
                message_id=msg_id,
                text=_players_list_text(players) + "\n\n✅ <b>Ойын басталды!</b>",
                reply_markup=None,
                parse_mode="HTML",
            )
        except TelegramBadRequest as e:
            if "not modified" not in str(e).lower():
                logger.warning("_do_start_game edit қатесі: %s", e)
        except Exception as e:
            logger.error("_do_start_game edit күтпеген қате: %s", e)


@router.message(Command("go"))
async def cmd_go(message: Message, bot: Bot):
    user_id = message.from_user.id
    if not await db.is_admin(user_id):
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game = await db.get_nonfin_game_by_admin(user_id)
    if not game:
        await message.answer("❌ Белсенді ойын жоқ. /newgame арқылы ашыңыз.")
        return

    if game["status"] == "started":
        await message.answer("⚠️ Ойын қазірдің өзінде басталған.")
        return

    await _do_start_game(bot, game)
    await message.answer(
        "▶️ <b>Ойын басталды!</b>\nЖаңа сілтеме арқылы қосылу мүмкін емес.\n\n"
        "Сандарды шығару: /next /next2 /next3 /next4",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("go:"))
async def cb_go(callback: CallbackQuery, bot: Bot):
    game_id = callback.data.split(":")[1]
    game = await db.get_game(game_id)

    if not game or game["admin_id"] != callback.from_user.id:
        await callback.answer("⛔ Рұқсат жоқ.", show_alert=True)
        return

    if game["status"] == "started":
        await callback.answer("⚠️ Ойын қазірдің өзінде басталған.", show_alert=True)
        return

    if game["status"] == "finished":
        await callback.answer("⚠️ Ойын аяқталған.", show_alert=True)
        return

    await _do_start_game(bot, game)
    await callback.answer("▶️ Ойын басталды!")
    await bot.send_message(
        game["admin_id"],
        "▶️ <b>Ойын басталды!</b>\nСандарды шығару: /next /next2 /next3 /next4",
        parse_mode="HTML",
    )

# ---------------------------------------------------------------------------
# /next, /next2, /next3, /next4 — сандарды шығару (қайталанбайды)
# ---------------------------------------------------------------------------

async def draw_numbers(message: Message, count: int):
    user_id = message.from_user.id
    if not await db.is_admin(user_id):
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game = await db.get_nonfin_game_by_admin(user_id)
    if not game:
        await message.answer("❌ Белсенді ойын жоқ. /newgame арқылы ашыңыз.")
        return

    if game["status"] == "waiting":
        await message.answer(
            "⚠️ Ойын әлі басталмаған. Алдымен /go немесе ▶️ GO батырмасын басыңыз."
        )
        return

    game_id = game["id"]
    called = await db.get_called_numbers(game_id)

    # Әр бағанда (B,I,N,G,O) әлі шықпаған сандары бар бағандар
    available: list[tuple[str, list[int]]] = []
    for letter in LETTERS:
        lo, hi = RANGES[letter]
        remaining = [n for n in range(lo, hi + 1) if n not in called]
        if remaining:
            available.append((letter, remaining))

    if not available:
        await message.answer(
            "🏁 Барлық сандар шығып қойды! Ойынды аяқтау үшін /stop қолданыңыз."
        )
        return

    count = min(count, len(available))
    # Бір шығаруда: ӘРТҮРЛІ бағандардан (letter), ал сандар – қайталанбаған
    selected = random.sample(available, count)

    lines = []
    for letter, remaining in selected:
        number = random.choice(remaining)
        await db.add_called_number(game_id, number, letter)
        lines.append(f"{letter}-{number}")

    total_called = len(called) + len(lines)
    await message.answer(
        "🎯 <b>Шыққан сандар</b>:\n"
        + "\n".join(f"<b>{l}</b>" for l in lines),
        parse_mode="HTML",
    )


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
# noop — B I N G O тақырып батырмалары
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()

# ---------------------------------------------------------------------------
# Ойыншы ұяшықты басады (toggle режимі)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("pick:"))
async def cb_pick_number(callback: CallbackQuery, bot: Bot):
    _, game_id, row_s, col_s = callback.data.split(":")
    row, col = int(row_s), int(col_s)

    game = await db.get_game(game_id)
    if not game or game["status"] == "finished":
        await callback.answer("Бұл ойын аяқталған.", show_alert=True)
        return
    if game["status"] == "waiting":
        await callback.answer("⚠️ Ойын әлі басталмаған.", show_alert=True)
        return

    user_id = callback.from_user.id
    player = await db.get_player(game_id, user_id)
    if not player:
        await callback.answer("Сіз бұл ойынға қосылмағансыз.", show_alert=True)
        return

    card   = player["card"]
    marked = player["marked"]
    val    = card[row][col]

    if val == FREE:
        await callback.answer("⭐ FREE ұяшығы автоматты белгіленген.")
        return

    # Toggle
    marked[row][col] = not marked[row][col]
    await db.update_player_marked(game_id, user_id, marked)

    kb = build_card_keyboard(game_id, card, marked)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass

    if marked[row][col]:
        await callback.answer(f"✅ {val} белгіленді!")
    else:
        await callback.answer(f"↩️ {val} белгісі алынды.")

    # BINGO тексеру (тек белгілегенде)
    if not marked[row][col]:
        return

    win_cells = check_bingo(marked)
    if not win_cells:
        return

    if player["won"]:
        return

    called_set = await db.get_called_numbers(game_id)
    if not is_real_bingo(card, win_cells, called_set):
        await callback.answer(
            "❌ Bingo жоқ.\nҚате белгіленген сандар бар.",
            show_alert=True,
        )
        return

    # Шынайы BINGO!
    await handle_bingo_win(bot, game, player, card, marked, list(win_cells), called_set)


async def handle_bingo_win(
    bot: Bot,
    game: dict,
    player: dict,
    card, marked,
    win_cells: list,
    called_set: set[int],
):
    game_id      = game["id"]
    user_id      = player["user_id"]
    display_name = get_display_name(player)

    await db.set_player_won(game_id, user_id)

    # Ойыншыға
    try:
        await bot.send_message(user_id, "🎉 <b>Сіз BINGO жасадыңыз!</b>",
                               parse_mode="HTML")
    except Exception:
        logger.exception("Ойыншыға хабарлама жіберу мүмкін болмады")

    # Жеңімпаз картасының суреті
    img_bytes = render_card_image(card, marked, win_cells)
    caption   = f"🏆 {display_name} BINGO жасады!"

    # Тек жеңімпазға + ойын админіне
    for target_id in {user_id, game["admin_id"]}:
        photo = BufferedInputFile(
            img_bytes, filename=f"bingo_{game_id}_{user_id}.png"
        )
        try:
            await bot.send_photo(target_id, photo=photo, caption=caption)
        except Exception:
            logger.exception(f"{target_id}-ге сурет жіберу мүмкін болмады")

# ---------------------------------------------------------------------------
# /карта — ойыншы өз картасын қайта алады
# ---------------------------------------------------------------------------

@router.message(Command("card"))
async def cmd_karta(message: Message):
    user_id = message.from_user.id
    result = await db.get_player_active_game(user_id)
    if not result:
        await message.answer(
            "❌ Сіз қазір ешқандай белсенді ойынға қатысып тұрған жоқсыз."
        )
        return
    game_id, player = result
    kb = build_card_keyboard(game_id, player["card"], player["marked"])
    await message.answer("Сіздің картаңыз:", reply_markup=kb)


# ---------------------------------------------------------------------------
# /stop — ойынды аяқтау
# ---------------------------------------------------------------------------

@router.message(Command("stop"))
async def cmd_stop(message: Message, bot: Bot):
    user_id = message.from_user.id
    if not await db.is_admin(user_id):
        await message.answer("⛔ Бұл команда тек админдерге арналған.")
        return

    game = await db.get_nonfin_game_by_admin(user_id)
    if not game:
        await message.answer("❌ Белсенді ойын жоқ.")
        return

    game_id = game["id"]
    await db.set_game_status(game_id, "finished")
    called_set = await db.get_called_numbers(game_id)

    players = await db.get_players(game_id)

    await message.answer(
        f"🏁 <b>Ойын аяқталды!</b>\nБарлық ойыншыларға соңғы карталары жіберілуде...",
        parse_mode="HTML",
    )

    for p in players:
        img_bytes = render_card_image(
            p["card"], p["marked"],
            win_cells=None,
            called_set=called_set,   # ← дұрыс/қате бөлу режимі
        )
        photo = BufferedInputFile(
            img_bytes,
            filename=f"final_{game_id}_{p['user_id']}.png",
        )
        caption = (
            "🏁 <b>Ойын аяқталды!</b>
        )
        try:
            await bot.send_photo(p["user_id"], photo=photo,
                                 caption=caption, parse_mode="HTML")
        except Exception:
            logger.exception(f"{p['user_id']}-ге соңғы карта жіберу мүмкін болмады")

    await message.answer(
        f"✅ Ойын ({game_id}) аяқталды. {len(players)} ойыншыға карта жіберілді."
    )

# ---------------------------------------------------------------------------
# Админ басқару командалары (тек басты админ)
# ---------------------------------------------------------------------------

@router.message(Command("addadmin"))
async def cmd_add_admin(message: Message):
    user_id = message.from_user.id
    if not await db.is_main_admin(user_id):
        await message.answer("⛔ Бұл команда тек <b>басты админге</b> арналған.",
                             parse_mode="HTML")
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Қолданыс: /addadmin <user_id>")
        return

    target = int(parts[1])
    added = await db.add_admin(target)
    if added:
        await message.answer(f"✅ {target} админдерге қосылды.")
    else:
        await message.answer(f"⚠️ {target} бұрыннан админ.")


@router.message(Command("removeadmin"))
async def cmd_remove_admin(message: Message):
    user_id = message.from_user.id
    if not await db.is_main_admin(user_id):
        await message.answer("⛔ Бұл команда тек <b>басты админге</b> арналған.",
                             parse_mode="HTML")
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Қолданыс: /removeadmin <user_id>")
        return

    target = int(parts[1])
    removed = await db.remove_admin(target)
    if removed:
        await message.answer(f"✅ {target} adminдер тізімінен шығарылды.")
    else:
        await message.answer(
            f"⚠️ {target} тізімде жоқ немесе ол басты админ (өшіруге болмайды)."
        )


@router.message(Command("admins"))
async def cmd_admins(message: Message, bot: Bot):
    user_id = message.from_user.id
    if not await db.is_main_admin(user_id):
        await message.answer("⛔ Бұл команда тек <b>басты админге</b> арналған.",
                             parse_mode="HTML")
        return

    admins = await db.get_all_admins()
    if not admins:
        await message.answer("Тізім бос.")
        return

    lines = []
    for i, a in enumerate(admins, 1):
        tag = " 👑 (басты)" if a["is_main"] else ""
        try:
            chat = await bot.get_chat(a["user_id"])
            # get_display_name тәрізді тәртіп
            if chat.username:
                name = f"@{chat.username}"
            else:
                parts = [chat.first_name or "", chat.last_name or ""]
                full  = " ".join(p for p in parts if p).strip()
                name  = full if full else f"ID: {a['user_id']}"
        except Exception:
            name = f"ID: {a['user_id']}"
        lines.append(f"{i}. {name} (<code>{a['user_id']}</code>){tag}")

    await message.answer(
        "<b>Админдер тізімі:</b>\n\n" + "\n".join(lines),
        parse_mode="HTML",
    )

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

async def main():
    await db.init_db()
    bot = Bot(token=BOT_TOKEN,
              default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
