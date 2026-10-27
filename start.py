"""Run with: python start.py (after copying .env.example to .env)."""
import sys
import uvicorn
from localmind.settings import settings

if __name__ == '__main__':
    if settings.host not in ('127.0.0.1', 'localhost', '::1') and len(settings.key) < 24:
        sys.exit('ОШИБКА: для доступа по LAN нужен LOCALMIND_KEY не короче 24 символов.')
    print(f'\nLocalMind 0.1 | http://{settings.host}:{settings.port}')
    print(f"Устройства: {'ДЕМО, никакое железо не переключается' if settings.demo else 'РЕАЛЬНЫЕ через Home Assistant'}")
    print('Ctrl+C — остановить. Не публикуй этот сервер в интернет.\n')
    uvicorn.run('localmind.server:app', host=settings.host, port=settings.port, reload=False)
