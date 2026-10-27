"""Run with: python start.py (after copying .env.example to .env)."""
import uvicorn
from localmind.settings import settings


def main():
    host = '127.0.0.1'
    print(f'\nLocalMind 0.1 | http://{host}:{settings.port}')
    print(f"Устройства: {'ДЕМО, никакое железо не переключается' if settings.demo else 'РЕАЛЬНЫЕ через Home Assistant'}")
    print('Ctrl+C — остановить. Не публикуй этот сервер в интернет.\n')
    uvicorn.run('localmind.server:app', host=host, port=settings.port, reload=False)


if __name__ == '__main__':
    main()
