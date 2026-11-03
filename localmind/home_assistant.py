"""Optional local HA gateway: explicit controller + entity grants + observation."""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from threading import RLock
import time
from urllib.parse import urlsplit
import httpx
from .paths import PRIVATE, atomic_json, ordinary_tree
from .secret_store import protect, unprotect
from .results import ActionResult, refused

ENTITY = re.compile(r'(light|switch)\.[a-z0-9_]{1,100}')
LOCAL_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))


class HAError(ValueError):
    def __init__(self, message, status='unavailable'):
        super().__init__(message)
        self.status = status


def local_origin(value):
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or '')
        if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or not (address.is_loopback or any(address in net for net in LOCAL_NETWORKS))
                or parsed.port is not None and not 1 <= parsed.port <= 65535):
            raise ValueError()
    except ValueError:
        raise HAError('Введите локальный IP-адрес контроллера, например http://192.168.1.20:8123.')
    return value.rstrip('/')


def entity_id(value):
    if type(value) is not str or not ENTITY.fullmatch(value):
        raise HAError('Поддерживаются только устройства light и switch.', 'action_rejected')
    return value


def device_aliases(name, entity):
    words = {'настольная': 'настольную', 'настенная': 'настенную', 'умная': 'умную',
             'лампа': 'лампу', 'розетка': 'розетку'}
    nominative = name.casefold()
    accusative = ' '.join(words.get(word, word) for word in nominative.split())
    return list(dict.fromkeys((nominative, accusative, entity)))


class HomeAssistant:
    def __init__(self, path=None, *, client_factory=httpx.Client, protect_token=protect, unprotect_token=unprotect,
                 clock=time.monotonic, sleep=time.sleep):
        self.path = Path(path) if path else None
        self.client_factory, self.protect_token, self.unprotect_token = client_factory, protect_token, unprotect_token
        self.clock, self.sleep = clock, sleep
        self.lock = RLock()
        self.origin, self.token, self.approved = '', '', {}
        self.demo_requested = False
        self.discovery = {}
        self.problem = None
        if self.path and self.path.exists():
            try:
                if ordinary_tree(self.path).stat().st_size > 65536:
                    raise ValueError()
                config = json.loads(self.path.read_text(encoding='utf-8'))
                if config.get('mode') == 'DEMO':
                    self.demo_requested = True
                    return
                self.origin = local_origin(config['origin'])
                self.token = self.unprotect_token(config['token'])
                for item in config.get('approved', [])[:100]:
                    entity = entity_id(item['entity_id'])
                    key = 'ha-' + hashlib.sha256(entity.encode()).hexdigest()[:24]
                    if key != item['id'] or not isinstance(item.get('name'), str) or not 1 <= len(item['name']) <= 80:
                        raise ValueError('Invalid saved entity grant')
                    self.approved[key] = {'id': key, 'entity_id': entity, 'domain': entity.split('.')[0],
                                          'name': item['name'], 'aliases': device_aliases(item['name'], entity)}
            except (OSError, ValueError, KeyError, TypeError):
                self.token = ''
                self.approved = {}
                self.problem = 'Токен или конфигурация недоступны. Подключите контроллер повторно.'

    @property
    def configured(self):
        return bool(self.origin)

    def _request(self, method, path, body=None, *, origin=None, token=None):
        base, credential = origin or self.origin, token or self.token
        if not base or not credential:
            raise HAError('Home Assistant не подключён. Откройте «Умный дом».')
        local_origin(base)  # Revalidate stored config on every request.
        try:
            with self.client_factory(timeout=httpx.Timeout(3, connect=2), trust_env=False, follow_redirects=False) as client:
                with client.stream(method, base + '/api/' + path,
                    headers={'Authorization': 'Bearer ' + credential}, json=body) as response:
                    if response.status_code in (401, 403):
                        raise HAError('Контроллер отклонил доступ. Проверьте токен и разрешения.', 'action_rejected')
                    if not 200 <= response.status_code < 300:
                        raise HAError('Контроллер не принял запрос.', 'action_rejected')
                    content, deadline = bytearray(), self.clock() + 8
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 2097152 or self.clock() > deadline:
                            raise HAError('Ответ контроллера слишком большой или медленный.')
                    return json.loads(content)
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, HAError):
                raise
            raise HAError('Контроллер не отвечает. Проверьте адрес и локальную сеть.') from None

    def connect(self, origin, token):
        origin = local_origin(origin)
        if not isinstance(token, str) or not 10 <= len(token) <= 4096 or any(c.isspace() for c in token):
            raise HAError('Введите токен Home Assistant без пробелов.')
        with self.lock:
            config = self._request('GET', 'config', origin=origin, token=token)
            if not isinstance(config, dict) or not isinstance(config.get('components'), list):
                raise HAError('По этому адресу не подтверждён Home Assistant.')
            # Encryption and disk write must succeed before changing live state.
            approved = self.approved if self.origin == origin and self.token == token else {}
            if self.path:
                atomic_json(self.path, {'origin': origin, 'token': self.protect_token(token), 'approved': list(approved.values())})
            self.origin, self.token, self.approved = origin, token, approved
            self.demo_requested = False
            self.discovery, self.problem = {}, None
        return self.public()

    def disconnect(self):
        with self.lock:
            if self.path:
                atomic_json(self.path, {'mode': 'DEMO'})
            self.origin, self.token, self.approved, self.discovery, self.problem = '', '', {}, {}, None
            self.demo_requested = True
        return self.public()

    def public(self):
        with self.lock:
            return {'configured': self.configured, 'mode': 'REAL' if self.configured else 'DEMO',
                    'origin': self.origin, 'problem': self.problem,
                    'approved': list(self.approved.values()), 'token_stored': bool(self.token)}

    def discover(self):
        with self.lock:
            states = self._request('GET', 'states')
            if not isinstance(states, list):
                raise HAError('Некорректный список устройств контроллера.')
            discovered = {}
            for state in states[:2000]:
                if not isinstance(state, dict) or not ENTITY.fullmatch(str(state.get('entity_id', ''))):
                    continue
                entity = state['entity_id']
                attributes = state.get('attributes')
                name = attributes.get('friendly_name', entity) if isinstance(attributes, dict) else entity
                if not isinstance(name, str):
                    name = entity
                key = 'ha-' + hashlib.sha256(entity.encode()).hexdigest()[:24]
                discovered[key] = {'id': key, 'name': name[:80], 'entity_id': entity, 'domain': entity.split('.')[0],
                                   'state': state.get('state') if state.get('state') in ('on', 'off', 'unavailable', 'unknown') else 'unknown',
                                   'available': state.get('state') in ('on', 'off'), 'allowed': key in self.approved}
                if len(discovered) >= 100:
                    break
            self.discovery = discovered
            return list(discovered.values())

    def approve(self, key, allowed, name=None):
        with self.lock:
            if type(allowed) is not bool or key not in self.discovery:
                raise HAError('Сначала обновите обнаруженные устройства.')
            item = self.discovery[key]
            entity_id(item['entity_id'])
            if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 80):
                raise HAError('Название устройства должно содержать от 1 до 80 символов.')
            changed = dict(self.approved)
            if allowed:
                display = (name or item['name']).strip()
                aliases = device_aliases(display, item['entity_id'])
                # Single-domain generic names are resolved separately, without
                # pretending morphological guessing is a reliable entity ID.
                changed[key] = {k: item[k] for k in ('id', 'entity_id', 'domain')}
                changed[key].update(name=display, aliases=aliases)
            else:
                changed.pop(key, None)
            if self.path:
                atomic_json(self.path, {'origin': self.origin, 'token': self.protect_token(self.token), 'approved': list(changed.values())})
            self.approved = changed
            return self.public()

    def read(self, key):
        with self.lock:
            item = self.approved.get(key)
            if not item:
                raise HAError('Устройство не разрешено владельцем.', 'action_rejected')
            data = self._request('GET', 'states/' + entity_id(item['entity_id']))
            if not isinstance(data, dict) or data.get('entity_id') != item['entity_id']:
                raise HAError('Контроллер вернул состояние другого устройства.')
            return data.get('state') if data.get('state') in ('on', 'off', 'unavailable', 'unknown') else 'unknown'

    def command(self, key, state):
        started = self.clock()
        accepted = False
        with self.lock:
            item = self.approved.get(key)
            if not item or state not in ('on', 'off'):
                return refused('set_light', key, 'Устройство или действие не разрешено.', status='action_rejected')
            try:
                current = self.read(key)
                if current in ('unavailable', 'unknown'):
                    return refused('set_light', key, 'Устройство не отвечает. Команда не отправлена.', status='unavailable')
                entity = entity_id(item['entity_id'])
                self._request('POST', 'services/' + entity.split('.')[0] + '/turn_' + state, {'entity_id': entity})
                accepted = True
                deadline = self.clock() + 4
                for attempt in range(12):
                    observed = self.read(key)
                    if observed == state:
                        return ActionResult(True, 'set_light', key, 'observed', state,
                            duration_ms=round((self.clock() - started) * 1000),
                            status_text=f'Home Assistant: {item["name"]} — ' + ('включено.' if state == 'on' else 'выключено.'))
                    if self.clock() >= deadline or observed in ('unavailable', 'unknown'):
                        break
                    self.sleep(.25)
                return ActionResult(False, 'set_light', key, 'request_accepted', observed,
                    status_text='Контроллер принял запрос, но нужное состояние устройства не подтверждено.')
            except HAError as exc:
                if accepted:
                    return ActionResult(False, 'set_light', key, 'request_accepted', error=str(exc),
                        status_text='Контроллер принял команду, но проверка состояния недоступна. ' + str(exc))
                return refused('set_light', key, str(exc), status=exc.status)


home_assistant = HomeAssistant(PRIVATE / 'home-assistant.json')
