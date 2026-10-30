"""Fixed, isolated parser entry point. Never interprets input as code or paths."""
import json
import sys

from .attachments import MAX_FILE_BYTES, _worker


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('pdf', 'docx', 'png', 'jpg', 'jpeg', 'webp'):
        raise SystemExit(2)
    content = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise SystemExit(2)
    result = _worker(content, sys.argv[1])
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    main()
