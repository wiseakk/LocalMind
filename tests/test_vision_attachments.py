"""Real bounded image decoding plus production attachment-to-message contracts."""
import base64
import io
import json
import struct
import zlib
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from localmind import agent, attachments, server
from localmind.conversations import ConversationStore
from localmind.requests import RequestStore


def picture(fmt='PNG', size=(80, 60), **kwargs):
    output = io.BytesIO()
    Image.new('RGB', size, 'red').save(output, format=fmt, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize('suffix,fmt', [('png', 'PNG'), ('jpg', 'JPEG'), ('jpeg', 'JPEG'), ('webp', 'WEBP')])
def test_real_image_worker_decodes_and_strips_metadata(suffix, fmt):
    image = attachments.extract_document(picture(fmt), 'fixture.' + suffix)
    assert isinstance(image, attachments.ImageAttachment)
    assert (image.width, image.height) == (80, 60)
    decoded = Image.open(io.BytesIO(base64.b64decode(image.encoded)))
    assert decoded.format == 'JPEG' and decoded.mode == 'RGB'
    assert not decoded.getexif()
    public = image.public(preview=True)
    assert public['kind'] == 'image' and public['characters'] == 0
    assert 'encoded' not in public and 'images' not in public


def test_mismatched_corrupt_and_animated_images_fail():
    for data, filename in ((picture('JPEG'), 'wrong.png'), (b'\x89PNG\r\n\x1a\ncorrupt', 'bad.png')):
        with pytest.raises(attachments.AttachmentError):
            attachments.extract_document(data, filename)
    output = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(output, format='WEBP', save_all=True,
        append_images=[Image.new('RGB', (10, 10), 'blue')], duration=100)
    with pytest.raises(attachments.AttachmentError, match='Анимированные'):
        attachments.extract_document(output.getvalue(), 'animated.webp')


def test_pixel_bomb_rejected_from_header_before_decode():
    header = struct.pack('>IIBBBBB', 5000, 5000, 8, 2, 0, 0, 0)
    chunk = b'IHDR' + header
    data = b'\x89PNG\r\n\x1a\n' + struct.pack('>I', len(header)) + chunk + struct.pack('>I', zlib.crc32(chunk))
    with pytest.raises(attachments.AttachmentError):
        attachments.extract_document(data, 'bomb.png')


def test_resize_is_bounded_and_orientation_metadata_removed():
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees.
    image = attachments.extract_document(picture('JPEG', (3000, 1000), exif=exif), 'rotated.jpg')
    assert image.height == 2560 and image.width < 1000
    decoded = Image.open(io.BytesIO(base64.b64decode(image.encoded)))
    assert not decoded.getexif()


def test_image_references_are_owned_removed_and_separated_from_public_sources():
    memory = ConversationStore()
    owner, other = memory.acquire(memory.create()), memory.acquire(memory.create())
    try:
        image = attachments.extract_document(picture(), 'object.png')
        attachments.add_document(owner, image)
        facts = attachments.document_context(owner, [image.id])
        documents, images = attachments.inference_attachments(facts)
        assert documents == [] and images == [image.encoded]
        assert 'images' not in json.dumps(attachments.attachment_sources(facts))
        with pytest.raises(attachments.AttachmentError, match='другому'):
            attachments.document_context(other, [image.id])
        owner.attachments.pop(image.id)
        with pytest.raises(attachments.AttachmentError):
            attachments.document_context(owner, [image.id])
    finally:
        memory.release(owner)
        memory.release(other)


def test_later_page_retrieval_keeps_actual_passage_and_page_label():
    text = '[Страница 1]\n' + 'Введение. ' * 5000 + '\n[Страница 22]\nСекретный номер проекта: ZXQ-8142. Финансирование 900 рублей.'
    document = attachments.extract_document(text.encode(), 'long.txt')
    assert 'ZXQ-8142' in document.text
    selected = attachments.choose_document_text(document.text, 'Какой номер проекта и финансирование на странице 22?', 1800)
    assert len(selected) <= 1800
    assert '[Страница 22]' in selected and 'ZXQ-8142' in selected


def test_image_only_turn_reaches_production_message_builder(monkeypatch):
    requests, memory = RequestStore(), ConversationStore()
    monkeypatch.setattr(server, 'store', requests)
    monkeypatch.setattr(server, 'conversations', memory)
    seen = []
    def infer(messages, *args, **kwargs):
        seen.append(messages)
        return {'content': '{"answer":"Красный объект."}'}
    monkeypatch.setattr(agent, 'ollama_chat', infer)
    try:
        client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12))
        key = memory.create()
        upload = client.post('/api/attachments', data={'conversation_id': key,
            'server_instance': server.SERVER_INSTANCE}, files={'file': ('object.png', picture())})
        assert upload.status_code == 200, upload.text
        image_id = upload.json()['id']
        response = client.post('/api/chat', json={'text': '', 'conversation_id': key, 'attachment_ids': [image_id]})
        assert response.status_code == 200, response.text
        assert seen, response.text
        assert any(message.get('images') for message in seen[-1])
        actual = next(message['images'][0] for message in seen[-1] if message.get('images'))
        assert Image.open(io.BytesIO(base64.b64decode(actual))).getpixel((1, 1))[0] > 200
        assert actual not in response.text
        assert response.json()['context_sources'][0]['id'] == image_id
    finally:
        requests.close()


@pytest.mark.parametrize('llm_first', [False, True])
@pytest.mark.parametrize('state', ['exists', 'missing', 'forbidden'])
@pytest.mark.parametrize('prefix', ['Что изображено на картинке', 'Опиши изображение', 'Прочитай файл'])
def test_disk_image_returns_honest_limit_without_io_or_generation(tmp_path, monkeypatch, llm_first, state, prefix):
    from localmind.conversations import Conversation
    target = tmp_path / '1234.png'
    if state != 'missing':
        target.write_bytes(picture())
    inference = Mock(side_effect=AssertionError('no fabricated image analysis'))
    reader = Mock(side_effect=AssertionError('disk image bytes must not be read'))
    policy = Mock(side_effect=AssertionError('must not claim to check this file'))
    monkeypatch.setattr(agent, 'ollama_chat', inference)
    monkeypatch.setattr(Path, 'read_bytes', reader)
    monkeypatch.setattr('localmind.file_access.file_access.read_file', reader)
    monkeypatch.setattr('localmind.file_access.file_access.personal_mode.roots', policy)
    if state == 'forbidden':
        target = Path(r'C:\Windows\1234.png')
    prepared = agent.prepare_reply(f'{prefix} {target}?', actions_authorized=True,
                                   conversation=Conversation('owner', 0), llm_first=llm_first)
    result = agent.complete_reply(prepared)
    assert result['answer'] == ('Анализ изображения по пути на диске пока не поддерживается. '
                                'Прикрепи изображение к сообщению.')
    assert result['actions'] == result['action_results'] == []
    assert not prepared.dialogue and not prepared.document_facts
    inference.assert_not_called()
    reader.assert_not_called()
    policy.assert_not_called()


def test_http_disk_image_does_not_generate_description(tmp_path, monkeypatch):
    requests, memory = RequestStore(), ConversationStore()
    monkeypatch.setattr(server, 'store', requests)
    monkeypatch.setattr(server, 'conversations', memory)
    inference = Mock(side_effect=AssertionError('no image inference without attachment'))
    monkeypatch.setattr(agent, 'ollama_chat', inference)
    target = tmp_path / '1234.png'
    target.write_bytes(picture())
    try:
        client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12))
        response = client.post('/api/chat', json={'text': f'Что изображено на картинке {target}.',
            'actions_authorized': True, 'server_instance': server.SERVER_INSTANCE})
        assert response.status_code == 200, response.text
        assert 'Прикрепи изображение' in response.json()['answer']
        assert response.json()['action_results'] == []
        inference.assert_not_called()
    finally:
        requests.close()


# Exercise existing behavior when the local planner is unavailable.
import pytest
pytestmark = pytest.mark.usefixtures("offline_desktop_planner")
