"""Small, deliberately closed Russian rule grammar. No model or execution here."""
from pathlib import Path
import re
import secrets


def parse_rules(text, *, scope=None, apps=(), folders=None):
    def unclear(message):
        return {'rules': [], 'interpretation': '', 'clarification': message}

    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
        return unclear('Введите одно правило длиной до 2000 символов.')
    normalized = text.strip().rstrip('.').casefold().replace('ё', 'е')
    folders = folders or {}
    rules = []

    def rule(kind, effect, operations, description, **target):
        rules.append({'id': secrets.token_hex(12), 'kind': kind, 'effect': effect,
                      'operations': operations, 'description': description, **target})

    match = re.fullmatch(r'не трогай папку [«"“]?(.+?)[»"”]?', normalized)
    if match:
        name = match[1].strip('«»"“” ')
        matches = {str(path) for label, path in folders.items() if label.casefold().replace('ё', 'е') == name}
        # Exact existing approved path is also supported; never guess relative paths.
        if Path(name).is_absolute():
            matches.update(str(path) for path in folders.values() if str(path).casefold() == name)
        if len(matches) != 1:
            return unclear('Уточните папку: выберите её в разрешённых областях или используйте её точное имя.')
        target = matches.pop()
        description = f'Запрещены поиск, чтение, открытие и все изменения папки {target} и её содержимого.'
        rule('path', 'deny', ['search', 'read', 'open', 'create', 'overwrite', 'move', 'delete'], description, target=target)
    elif normalized == 'разрешаю редактировать документы, но запрещаю удалять их':
        if not scope:
            return unclear('В какой папке разрешено редактирование документов? Выберите область и повторите просмотр.')
        if str(scope) not in {str(x) for x in folders.values()}:
            return unclear('Выберите существующую разрешённую область документов.')
        rule('path', 'allow', ['overwrite'], f'Разрешена перезапись документов в {scope}; каждое изменение требует подтверждения.', target=str(scope))
        rule('path', 'deny', ['delete'], f'Запрещено удаление документов в {scope} и вложенных папках.', target=str(scope))
    else:
        match = re.fullmatch(r'можно открывать (.+), но не закрывать (?:его|ее|их)', normalized)
        if not match:
            return unclear('Фраза пока не поддерживается. Используйте «Не трогай папку …», «Можно открывать …, но не закрывать его» или правило редактирования документов.')
        name = match[1].strip('«»" ')
        matches = []
        for app in apps:
            labels = [app.get('id', ''), app.get('name', ''), *app.get('aliases', [])]
            if name in {str(x).casefold().replace('ё', 'е') for x in labels}:
                matches.append(app)
        # Duplicates of a single executable are one app, other matches ambiguous.
        groups = {str(a.get('target') or a.get('id')).casefold() for a in matches}
        if len(groups) != 1:
            return unclear('Приложение неизвестно или имя неоднозначно. Обновите каталог и уточните название.')
        identifiers = set()
        for app in matches:
            identifiers.update(str(x).casefold() for x in [app['id'], app.get('name', ''), app.get('target', ''), *app.get('aliases', []), *app.get('policy_identifiers', [])] if x)
            if app.get('target') and app.get('fingerprint'):
                identifiers.add('image:' + app['target'].casefold() + '|' + app['fingerprint'])
        label = matches[0].get('name', name)
        rule('app', 'allow', ['launch'], f'Разрешён запуск {label}.', identifiers=sorted(identifiers))
        rule('app', 'deny', ['close'], f'Закрытие {label} запрещено, включая все его псевдонимы.', identifiers=sorted(identifiers))
    return {'rules': rules, 'interpretation': '\n'.join(r['description'] for r in rules), 'clarification': None}
