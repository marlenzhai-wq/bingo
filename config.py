import os

# Токенді осында жазыңыз немесе BOT_TOKEN env переменнойы арқылы беріңіз
BOT_TOKEN = os.getenv("BOT_TOKEN", "8864955547:AAGZ48_baItmVVVuy-mspVLI_rs_hmcVW3E")

DB_PATH = os.getenv("BINGO_DB_PATH", "bingo.db")

ADMIN_IDS = [8031146911, 8384667300, 8109812467, 5829736145, 7481511729]
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "8109812467"))
