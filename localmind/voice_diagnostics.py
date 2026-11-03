"""Non-sensitive domain failures shared by isolated stdlib worker transports."""
MESSAGES = {
    'dependency_missing': 'Компоненты голоса отсутствуют. Восстановите LocalMind установщиком.',
    'model_missing': 'Модель отсутствует. Нажмите «Подготовить голос» в настройках.',
    'path_invalid': 'Ресурсы голоса недоступны по сохранённому пути. Подготовьте голос повторно.',
    'resource_corrupt': 'Ресурсы повреждены. Нажмите «Подготовить голос» для восстановления.',
    'library_incompatible': 'Библиотеки голоса несовместимы. Восстановите LocalMind установщиком.',
    'gpu_error': 'GPU недоступен или не хватает памяти. Выберите профиль CPU.',
}


def classify_voice_error(exc):
    text = str(exc).lower()
    if any(x in text for x in ('cuda', 'cudnn', 'cublas', 'out of memory')):
        return 'gpu_error'
    if any(x in text for x in ('dll load', 'undefined symbol', 'metadata_errors', 'incompatible')):
        return 'library_incompatible'
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return 'dependency_missing'
    if isinstance(exc, FileNotFoundError):
        return 'path_invalid'
    return 'resource_corrupt'
