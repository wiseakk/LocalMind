"""Run with: python start.py (after copying .env.example to .env)."""
import uvicorn
import sys


def main():
    from localmind.paths import migrate_legacy, legacy_preferences_plan
    # Redirected Windows consoles may default to cp1252, which cannot print Russian.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    plan = legacy_preferences_plan()
    if plan:
        print('Найдены старые настройки. План копирования (источники сохраняются):')
        for row in plan:
            print(row['source'] + '\n→ ' + row['target'])
        if sys.stdin.isatty() and input('Скопировать эти настройки? [y/N]: ').strip().lower() == 'y':
            migrate_legacy(consent=True, reviewed_plan=plan)
        else:
            print('Перенос не выполнен. Старые файлы сохранены; desktop предложит план при запуске.')
    from localmind.settings import settings
    host = '127.0.0.1'
    print(f'\nLocalMind 1.0 | http://{host}:{settings.port}')
    print(f"Устройства: {'ДЕМО, никакое железо не переключается' if settings.demo else 'РЕАЛЬНЫЕ через Home Assistant'}")
    print('Ctrl+C — остановить. Не публикуй этот сервер в интернет.\n')
    uvicorn.run('localmind.server:app', host=host, port=settings.port, reload=False,
                proxy_headers=False)


if __name__ == '__main__':
    main()
