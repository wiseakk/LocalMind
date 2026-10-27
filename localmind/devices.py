"""Safe device gateway: allowlisted entity IDs and actions only.

No code supplied by a language model is ever executed here.
"""
import httpx
from .settings import settings, DEVICES

# Fake hardware in demo mode. State resets on server restart.
_demo_states = {key: False for key in DEVICES}

class DeviceError(Exception):
    pass

def device_catalog():
    return [{'id': device_id, 'name': device['name'], 'state': _demo_states[device_id] if settings.demo else None}
            for device_id, device in DEVICES.items()]

def find_device(text: str):
    text = text.lower()
    for key, config in DEVICES.items():
        if key in text or any(alias in text for alias in config['aliases']):
            return key
    return None

def set_light(device_id: str, state: str):
    if device_id not in DEVICES:
        raise DeviceError('Устройство не разрешено в конфигурации')
    if DEVICES[device_id]['domain'] != 'light' or state not in ('on', 'off'):
        raise DeviceError('Недопустимая операция')

    if settings.demo:
        _demo_states[device_id] = state == 'on'
        return f"ДЕМО: {DEVICES[device_id]['name']} — {'включена' if state == 'on' else 'выключена'}."

    if not settings.ha_url or not settings.ha_token:
        raise DeviceError('Нужны HOME_ASSISTANT_URL и HOME_ASSISTANT_TOKEN')

    # Action and entity are NOT supplied as arbitrary LLM-generated URLs.
    action = 'turn_on' if state == 'on' else 'turn_off'
    try:
        with httpx.Client(timeout=8) as client:
            response = client.post(
                f'{settings.ha_url}/api/services/light/{action}',
                headers={'Authorization': f'Bearer {settings.ha_token}'},
                json={'entity_id': DEVICES[device_id]['entity_id']}
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DeviceError('Home Assistant недоступен или отклонил команду') from exc
    return f"Отправлена команда: {DEVICES[device_id]['name']} — {state}."
