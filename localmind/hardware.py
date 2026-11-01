"""Optional device telemetry. No subprocesses, downloads or CUDA dependency."""
import platform
from threading import Lock

_nvml_lock = Lock()


def hardware_status():
    result = {'cpu': platform.processor() or None, 'cpu_percent': None,
              'ram_total': None, 'ram_available': None, 'gpus': [],
              'gpu_status': 'unavailable'}
    try:
        import psutil
        memory = psutil.virtual_memory()
        result.update(cpu_percent=psutil.cpu_percent(interval=0.05), ram_total=memory.total,
                      ram_available=memory.available)
    except (ImportError, OSError):
        pass
    try:
        import pynvml as nv
        with _nvml_lock:
            nv.nvmlInit()
            try:
                for index in range(nv.nvmlDeviceGetCount()):
                    device = nv.nvmlDeviceGetHandleByIndex(index)
                    item = {'name': None, 'vram_total': None, 'vram_used': None, 'utilization': None}
                    try:
                        name = nv.nvmlDeviceGetName(device)
                        item['name'] = name.decode() if isinstance(name, bytes) else name
                    except nv.NVMLError:
                        pass
                    try:
                        memory = nv.nvmlDeviceGetMemoryInfo(device)
                        item.update(vram_total=memory.total, vram_used=memory.used)
                    except nv.NVMLError:
                        pass
                    try:
                        item['utilization'] = nv.nvmlDeviceGetUtilizationRates(device).gpu
                    except nv.NVMLError:
                        pass
                    result['gpus'].append(item)
                result['gpu_status'] = 'available' if result['gpus'] else 'unavailable'
            finally:
                nv.nvmlShutdown()
    except ImportError:
        pass
    except Exception:
        # Optional vendor bindings can fail independently of the application.
        result['gpu_status'] = 'unavailable'
    return result
