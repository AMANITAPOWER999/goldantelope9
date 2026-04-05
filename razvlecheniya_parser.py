"""
Одноразовый парсер: берёт последние 30 сообщений из каждого канала афиши
и отправляет в @razvlecheniyavietnam через Bot API (бот-админ).
Запуск: python3 razvlecheniya_parser.py
"""
import asyncio, logging, os, time, io, requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telethon.errors import FloodWaitError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('razvlecheniya')

API_ID   = int(os.environ.get('TG_API_ID',   '36461704'))
API_HASH = os.environ.get('TG_API_HASH', '57fd0ec8dc0e2786420c4e78a8d1c5d4')
SESSION  = os.environ.get('TELETHON_SESSION2', '').strip()
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()

DEST_CHANNEL = '@razvlecheniyavietnam'

SOURCES = [
    'nyachang_ru',
    'T2TNhaTrangEvents',
    'nhatrang_tusa_afisha',
    'afisha_nhatrang',
    'danang_afisha',
    'danangpals',
    'nhatrang_affiche',
    'introconcertvn',
    'familyday_nt_events',
    'hoshimin_afisha',
    'nyachangafisha',
    'svoidanang',
    'afishaVietnam',
    'afisha_vietnama',
    'vietnam_afisha',
    'afisha_phuquoc',
    'nha_trang_tusa',
    'nhatrang_afisha',
    'party_danang',
]

LIMIT_PER_CHANNEL = 30
DELAY_BETWEEN_MSGS = 2.0
DELAY_BETWEEN_CHANNELS = 5


def bot_send_photo(photo_bytes: bytes, caption: str) -> bool:
    """Отправляет фото через Bot API."""
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto',
            data={'chat_id': DEST_CHANNEL, 'caption': caption[:1024], 'parse_mode': ''},
            files={'photo': ('photo.jpg', photo_bytes, 'image/jpeg')},
            timeout=30
        )
        return r.json().get('ok', False)
    except Exception as ex:
        log.warning(f'bot_send_photo error: {ex}')
        return False


def bot_send_text(text: str) -> bool:
    """Отправляет текст через Bot API."""
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': DEST_CHANNEL, 'text': text[:4096]},
            timeout=15
        )
        return r.json().get('ok', False)
    except Exception as ex:
        log.warning(f'bot_send_text error: {ex}')
        return False


async def main():
    if not SESSION:
        log.error('❌ TELETHON_SESSION2 не задана!')
        return
    if not BOT_TOKEN:
        log.error('❌ TELEGRAM_BOT_TOKEN не задан!')
        return

    log.info('=' * 60)
    log.info(f'API_ID  : {API_ID}')
    log.info(f'DEST    : {DEST_CHANNEL}')
    log.info(f'Каналов : {len(SOURCES)}, сообщений из каждого: {LIMIT_PER_CHANNEL}')
    log.info('=' * 60)

    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH,
                            connection_retries=10, retry_delay=5)
    await client.connect()

    if not await client.is_user_authorized():
        log.error('❌ Сессия недействительна!')
        return

    me = await client.get_me()
    log.info(f'✅ Авторизован: {me.first_name} (id={me.id})')
    log.info(f'📤 Отправка через Bot API → {DEST_CHANNEL}')
    log.info('-' * 60)

    total_sent = 0
    total_skip = 0
    total_err  = 0

    for src in SOURCES:
        log.info(f'\n📡 @{src}...')
        try:
            entity = await client.get_entity(src)
            cname = getattr(entity, 'title', src)
            log.info(f'   ✅ {cname}')
        except Exception as ex:
            log.warning(f'   ❌ Не удалось: {ex}')
            continue

        msgs_collected = []
        try:
            async for msg in client.iter_messages(entity, limit=LIMIT_PER_CHANNEL):
                has_photo = msg.media and isinstance(msg.media, MessageMediaPhoto)
                has_text  = bool(msg.raw_text and len(msg.raw_text.strip()) >= 10)
                if has_photo or has_text:
                    msgs_collected.append(msg)
            log.info(f'   📥 Получено: {len(msgs_collected)} сообщений')
        except Exception as ex:
            log.warning(f'   ❌ iter_messages: {ex}')
            continue

        for msg in reversed(msgs_collected):
            try:
                txt = (msg.raw_text or '').strip()
                src_link = f'https://t.me/{src}/{msg.id}'
                caption = f'{txt}\n\n📌 {src_link}' if txt else f'📌 {src_link}'

                if msg.media and isinstance(msg.media, MessageMediaPhoto):
                    # Скачиваем фото через Telethon и шлём через Bot API
                    buf = io.BytesIO()
                    await client.download_media(msg.media, file=buf)
                    buf.seek(0)
                    photo_bytes = buf.read()
                    if photo_bytes and bot_send_photo(photo_bytes, caption):
                        log.info(f'   📸 → {DEST_CHANNEL} | {src}/#{msg.id}')
                        total_sent += 1
                    else:
                        # Откат: текст
                        if txt and bot_send_text(caption):
                            log.info(f'   📝 (текст без фото) | {src}/#{msg.id}')
                            total_sent += 1
                        else:
                            log.warning(f'   ⚠️  Не отправлено | {src}/#{msg.id}')
                            total_err += 1
                elif txt:
                    if bot_send_text(caption):
                        log.info(f'   📝 → {DEST_CHANNEL} | {src}/#{msg.id}')
                        total_sent += 1
                    else:
                        log.warning(f'   ⚠️  Не отправлено | {src}/#{msg.id}')
                        total_err += 1
                else:
                    total_skip += 1
                    continue

                await asyncio.sleep(DELAY_BETWEEN_MSGS)

            except Exception as ex:
                log.error(f'   ❌ msg#{msg.id}: {ex}')
                total_err += 1
                await asyncio.sleep(1)

        log.info(f'   ✅ @{src} готово. Пауза {DELAY_BETWEEN_CHANNELS}s...')
        await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

    log.info('\n' + '=' * 60)
    log.info(f'✅ ГОТОВО! Отправлено: {total_sent} | Пропущено: {total_skip} | Ошибок: {total_err}')
    log.info('=' * 60)
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
