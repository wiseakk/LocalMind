"""Safe device gateway: allowlisted entity IDs and actions only.

No code supplied by a language model is ever executed here.
"""
import httpx
import time
import copy
from .results import ActionResult
from .settings import settings, DEVICES
from .home_assistant import home_assistant, HomeAssistant, HAError, local_origin

# Fake hardware in demo mode. State resets on server restart.
_demo_states = {key: False for key in DEVICES}
_demo_devices = copy.deepcopy(DEVICES)

class DeviceError(Exception):
    pass

def is_demo():
    return home_assistant.demo_requested or settings.demo and not home_assistant.configured


def sync_devices():
    if home_assistant.configured:
        DEVICES.clear()
        DEVICES.update({key: dict(item) for key, item in home_assistant.approved.items()})
    elif is_demo():
        DEVICES.clear()
        DEVICES.update(copy.deepcopy(_demo_devices))


def device_catalog():
    sync_devices()
    if is_demo():
        return [{'id': key, 'name': item['name'], 'state': _demo_states.get(key, False),
                 'status': 'on' if _demo_states.get(key, False) else 'off', 'available': True, 'mode': 'DEMO'}
                for key, item in DEVICES.items()]
    if home_assistant.configured:
        try:
            observed = {item['id']: item for item in home_assistant.discover()}
        except HAError:
            observed = {}
        return [{'id': key, 'name': item['name'], 'mode': 'REAL',
                 'state': observed.get(key, {}).get('state') == 'on' if observed.get(key, {}).get('state') in ('on', 'off') else None,
                 'status': observed.get(key, {}).get('state', 'unavailable'),
                 'available': observed.get(key, {}).get('available', False)} for key, item in DEVICES.items()]
    return [{'id': key, 'name': item['name'], 'mode': 'REAL', 'state': None, 'status': 'unavailable', 'available': False}
            for key, item in DEVICES.items()]

def find_device(text: str):
    text = text.lower()
    for key, config in DEVICES.items():
        if key in text or any(alias in text for alias in config['aliases']):
            return key
    return None

def set_light(device_id: str, state: str):
    started = time.monotonic()
    if device_id not in DEVICES:
        raise DeviceError('Устройство не разрешено в конфигурации')
    if DEVICES[device_id]['domain'] not in ('light', 'switch') or state not in ('on', 'off'):
        raise DeviceError('Недопустимая операция')

    if is_demo():
        _demo_states[device_id] = state == 'on'
        return ActionResult(True, 'set_light', device_id, 'observed', state, mode='DEMO',
                            duration_ms=round((time.monotonic() - started) * 1000),
                            status_text=f"ДЕМО: {DEVICES[device_id]['name']} — {'включена' if state == 'on' else 'выключена'}.")

    if home_assistant.configured:
        return home_assistant.command(device_id, state)

    if not settings.ha_url or not settings.ha_token:
        raise DeviceError('Нужны HOME_ASSISTANT_URL и HOME_ASSISTANT_TOKEN')

    # Legacy environment configuration retains its allowlist, with the same
    # local-origin validation and state verification as the GUI connection.
    gateway = HomeAssistant(client_factory=httpx.Client)
    try:
        gateway.origin, gateway.token = local_origin(settings.ha_url), settings.ha_token
        gateway.approved = {device_id: DEVICES[device_id]}
        return gateway.command(device_id, state)
    except HAError as exc:
        raise DeviceError(str(exc)) from None


def list_enabled():
    rows = device_catalog()
    active = [item['name'] for item in rows if item['state'] is True]
    unavailable = [item['name'] for item in rows if not item.get('available')]
    mode = 'DEMO' if is_demo() else 'REAL'
    text = ('ДЕМО · симуляция. ' if mode == 'DEMO' else 'Home Assistant. ')
    text += 'Включены: ' + (', '.join(active) if active else 'нет подтверждённых включённых устройств') + '.'
    if unavailable:
        text += ' Не отвечают: ' + ', '.join(unavailable) + '.'
    return ActionResult(not unavailable, 'devices.list_enabled', None, 'observed' if not unavailable else 'partial',
                        'device_states' if not unavailable else None, mode=mode, status_text=text, data={'devices': rows})


sync_devices()
