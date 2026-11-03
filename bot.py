import os
import random
import sqlite3
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

ADMIN = "soyle0"
CHANNEL = "@LeocronBlog"
CHANNEL_URL = "https://t.me/LeocronBlog"
MEDALS = ("🥇", "🥈", "🥉")

# Con DATABASE_URL usa Postgres (Render free ha disco effimero), altrimenti SQLite locale.
DB_URL = os.environ.get("DATABASE_URL")
SQLITE_PATH = os.path.join(os.path.dirname(__file__), "contest.db")


def run(sql, args=()):
    """Esegue una query in una connessione nuova (evita connessioni scadute) -> (righe, rowcount)."""
    if DB_URL:
        import psycopg2
        conn, sql = psycopg2.connect(DB_URL), sql.replace("?", "%s")
    else:
        conn = sqlite3.connect(SQLITE_PATH)
    try:
        with conn:
            cur = conn.cursor()
            cur.execute(sql, args)
            return (cur.fetchall() if cur.description else []), cur.rowcount
    finally:
        conn.close()


run("CREATE TABLE IF NOT EXISTS iscritti (user_id BIGINT PRIMARY KEY, username TEXT, nick TEXT NOT NULL)")


def tag(username, user_id):
    return f"@{escape(username)}" if username else f'<a href="tg://user?id={user_id}">utente</a>'


def is_admin(update: Update) -> bool:
    return (update.effective_user.username or "").lower() == ADMIN


async def reply(update: Update, text: str):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def partecipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    parts = update.message.text.split(maxsplit=1)
    nick = parts[1].strip().strip('"“”«»\'').strip() if len(parts) > 1 else ""
    if not nick or len(nick) > 32:
        return await reply(update, "<b>Uso corretto</b>\n<code>/partecipo \"nick in game\"</code>\n<i>Il nick deve essere lungo massimo 32 caratteri.</i>")

    try:
        member = await context.bot.get_chat_member(CHANNEL, user.id)
        joined = member.status in ("member", "administrator", "creator") or (member.status == "restricted" and member.is_member)
    except TelegramError:
        return await reply(update, "<b>Errore</b>\nNon riesco a verificare l'iscrizione al canale. Riprova tra poco.")
    if not joined:
        return await reply(update, f"<b>Iscrizione negata</b>\nPer partecipare devi prima entrare nel canale:\n{CHANNEL_URL}\n\n<i>Dopo esserti iscritto, riscrivi il comando.</i>")

    _, n = run("INSERT INTO iscritti VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (user.id, user.username, nick))
    if n == 0:
        return await reply(update, "<b>Sei già iscritto.</b>\nPuoi usare <code>/partecipo</code> una sola volta.")
    await reply(update, f"<b>Iscrizione confermata</b>\nNick registrato: <code>{escape(nick)}</code>\n<i>In bocca al lupo per il contest.</i>")


async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await reply(update, "<b>Comando riservato all'admin.</b>")
    rows, _ = run("SELECT user_id, username, nick FROM iscritti")
    if not rows:
        return await reply(update, "<b>Nessun iscritto</b> al momento.")
    lines = [f"{i}. <code>{escape(n)}</code> — {tag(u, uid)}" for i, (uid, u, n) in enumerate(rows, 1)]
    chunk = f"<b>Lista iscritti</b> · <i>{len(rows)} totali</i>\n"
    for line in lines:
        if len(chunk) + len(line) > 3800:  # limite Telegram 4096
            await reply(update, chunk)
            chunk = ""
        chunk += "\n" + line
    await reply(update, chunk)


async def sorteggia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await reply(update, "<b>Comando riservato all'admin.</b>")
    rows, _ = run("SELECT user_id, username, nick FROM iscritti")
    if len(rows) < 3:
        return await reply(update, f"<b>Iscritti insufficienti</b>\nServono almeno 3 partecipanti, al momento sono <b>{len(rows)}</b>.")
    winners = random.SystemRandom().sample(rows, 3)
    places = ("Primo posto", "Secondo posto", "Terzo posto")
    out = "<b>Vincitori del contest</b>\n"
    for m, p, (uid, u, n) in zip(MEDALS, places, winners):
        out += f"\n{m} <b>{p}</b>\n<code>{escape(n)}</code> — {tag(u, uid)}\n"
    await reply(update, out)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await reply(update, "<b>Comando riservato all'admin.</b>")
    _, n = run("DELETE FROM iscritti")
    await reply(update, f"<b>Lista azzerata</b>\nRimossi <b>{n}</b> iscritti.")


class Health(BaseHTTPRequestHandler):
    """Risponde 200 a GET/HEAD: serve a Render (porta aperta) e a UptimeRobot (ping)."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


def main():
    if "PORT" in os.environ:  # presente solo su Render
        threading.Thread(target=HTTPServer(("", int(os.environ["PORT"])), Health).serve_forever, daemon=True).start()
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
    for name, fn in (("partecipo", partecipo), ("lista", lista), ("sorteggia", sorteggia), ("clear", clear)):
        app.add_handler(CommandHandler(name, fn))
    app.run_polling()


if __name__ == "__main__":
    main()
