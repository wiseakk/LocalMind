import sys
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

import start
from localmind import agent, devices, server
from localmind.settings import settings
from localmind.windows_state import LaunchCoordinator, ApplicationState


class LocalMindTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000))

    def setUp(self):
        devices._demo_states['desk_light'] = False
        # This legacy suite exercises the deterministic fallback. The separate
        # response suite verifies real composer inputs and accepted output.
        composer = mock.patch.object(agent, '_compose_action', side_effect=ValueError('fallback fixture'))
        composer.start()
        self.addCleanup(composer.stop)

    def test_light_direct_rule_preserved(self):
        self.assertTrue(settings.demo)
        result = agent.reply('Включи настольную лампу', actions_authorized=True)
        self.assertEqual(result['engine'], 'rules')
        self.assertTrue(devices._demo_states['desk_light'])
        result = agent.reply('Выключи лампу на столе', actions_authorized=True)
        self.assertIn('ДЕМО', result['answer'])
        self.assertFalse(devices._demo_states['desk_light'])

        result = agent.reply('Включи лампу пожалуйста', actions_authorized=True)
        self.assertIn('ДЕМО', result['answer'])
        self.assertTrue(devices._demo_states['desk_light'])

    def test_supported_app_command_forms_are_unambiguous(self):
        phrases = (
            'Открой калькулятор',
            'Пожалуйста, открой калькулятор',
            'Запусти на компьютере блокнот',
            'Я хочу чтобы ты открыл блокнот',
        )
        for text in phrases:
            with self.subTest(text=text):
                assessment = agent.assess_action(text)
                self.assertIsNotNone(assessment.grant)
                self.assertEqual(assessment.grant.name, 'open_app')

    def test_no_false_device_or_unauthorized_tool(self):
        self.assertIsNone(devices.find_device('Включи рандомную розетку'))
        with self.assertRaises(devices.DeviceError):
            devices.set_light('unlisted_power_socket', 'on')
        self.assertIn('не разрешены', agent.dispatch('execute_shell', {'command': 'rm -rf /'}))
        self.assertIn('не разрешено', agent.open_app('cmd.exe'))

    def test_api_smoke_and_explicit_action_authorization(self):
        info = self.client.get('/api/info')
        self.assertEqual(info.status_code, 200)
        self.assertTrue(info.json()['demo'])

        review = self.client.post('/api/chat', json={
            'text': 'Включи настольную лампу',
            'actions_authorized': False,
        })
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()['engine'], 'action-review')
        self.assertTrue(review.json()['confirmation_required'])
        self.assertEqual(review.json()['actions'], [])
        self.assertFalse(devices._demo_states['desk_light'])

        execute = self.client.post('/api/chat', json={'text': 'Включи настольную лампу'})
        self.assertEqual(execute.status_code, 200)
        self.assertEqual(execute.json()['engine'], 'rules')
        self.assertTrue(devices._demo_states['desk_light'])

    def test_ollama_chat_preserved_without_executable_tools(self):
        observed = []

        def fake(messages, tools, **_options):
            observed.append((messages, tools))
            return {'role': 'assistant', 'content': json.dumps({'answer': 'RSA — асимметричный криптоалгоритм.'})}

        with mock.patch.object(agent, 'ollama_chat', side_effect=fake):
            answer = agent.reply('Что такое RSA-шифрование?')
        self.assertEqual(answer['engine'], 'ollama')
        self.assertIn('RSA', answer['answer'])
        self.assertEqual(observed[0][1], [])

    def test_negated_phrases_never_execute(self):
        phrases = (
            'Не включай настольную лампу',
            'Не запускай калькулятор',
            'Не открывай блокнот',
            'Не закрывай калькулятор',
            'Никогда не включай настольную лампу',
        )
        with (
            mock.patch.object(agent, 'open_app', side_effect=AssertionError('must not open')),
            mock.patch.object(agent, 'close_app', side_effect=AssertionError('must not close')),
            mock.patch.object(agent, 'set_light', side_effect=AssertionError('must not actuate')),
        ):
            for text in phrases:
                with self.subTest(text=text):
                    result = agent.reply(text, actions_authorized=True)
                    self.assertEqual(result['actions'], [])
                    self.assertIn('не выполняю', result['answer'])

    def test_quoted_ambiguous_and_mixed_phrases_never_execute(self):
        phrases = (
            'Он сказал: "открой калькулятор"',
            'Фраза «включи настольную лампу» — пример команды',
            'Открой калькулятор или блокнот',
            'Открой что-нибудь',
            'Открой калькулятор и расскажи про RSA',
            'Мне нужно узнать, как открыть калькулятор',
            'Мне сказали открыть калькулятор',
            "Он сказал: 'открой калькулятор'",
            'Он сказал: ‘открой калькулятор’',
            'Он сказал: "открой калькулятор',
            'Он сказал: открой калькулятор',
            '`открой калькулятор`',
            'Пример команды: открой калькулятор',
            'Повтори за мной: открой калькулятор',
            'Команда открой калькулятор означает запуск приложения',
            'Я запрещаю: открой калькулятор',
            'Я хочу узнать, открой калькулятор или нет',
            "Переведи 'открой калькулятор' на английский",
            'Напиши фразу `открой калькулятор`',
            'Я изучаю команду открой калькулятор',
            'Правильно ли я сказал: открой калькулятор',
            'Открой калькулятор и удали документы',
            'Включи настольную лампу, а потом открой блокнот',
        )
        with (
            mock.patch.object(agent, 'open_app', side_effect=AssertionError('must not open')),
            mock.patch.object(agent, 'close_app', side_effect=AssertionError('must not close')),
            mock.patch.object(agent, 'set_light', side_effect=AssertionError('must not actuate')),
        ):
            for text in phrases:
                with self.subTest(text=text):
                    result = agent.reply(text, actions_authorized=True)
                    self.assertEqual(result['actions'], [])
                    self.assertEqual(result['engine'], 'rules')

    def test_informational_phrases_receive_no_tools_or_actions(self):
        phrases = (
            'Как открыть калькулятор?',
            'Расскажи, как включить настольную лампу',
            'Можно ли закрыть блокнот?',
        )
        observed = []

        def fake(_messages, tools, **_options):
            observed.append(tools)
            return {
                'role': 'assistant',
                'content': json.dumps({'answer': 'Это только объяснение.'}),
                'tool_calls': [{
                    'function': {'name': 'open_app', 'arguments': {'app': 'notepad'}},
                }],
            }

        with (
            mock.patch.object(agent, 'open_app', side_effect=AssertionError('must not open')),
            mock.patch.object(agent, 'close_app', side_effect=AssertionError('must not close')),
            mock.patch.object(agent, 'set_light', side_effect=AssertionError('must not actuate')),
            mock.patch.object(agent, 'ollama_chat', side_effect=fake),
        ):
            for text in phrases:
                with self.subTest(text=text):
                    result = agent.reply(text, actions_authorized=True)
                    self.assertEqual(result['actions'], [])
                    self.assertEqual(result['engine'], 'ollama')
        self.assertEqual(observed, [[], [], []])

    def test_dispatch_revalidates_exact_action_target_and_arguments(self):
        grant = agent.ActionGrant('set_light', {'device_id': 'desk_light', 'state': 'on'})
        mismatch = agent.dispatch(
            'set_light',
            {'device_id': 'desk_light', 'state': 'off'},
            authorization=grant,
        )
        self.assertIn('не авторизовано', mismatch)
        self.assertFalse(devices._demo_states['desk_light'])

        extra = agent.dispatch(
            'set_light',
            {'device_id': 'desk_light', 'state': 'on', 'extra': 'ignored'},
            authorization=grant,
        )
        self.assertIn('параметры не разрешены', extra)
        self.assertFalse(devices._demo_states['desk_light'])

        allowed = agent.dispatch('set_light', grant.arguments, authorization=grant)
        self.assertIn('ДЕМО', allowed)
        self.assertTrue(devices._demo_states['desk_light'])

    @unittest.skipUnless(agent.platform.system() == 'Windows', 'Windows-only integration')
    def test_builtin_apps_use_verified_absolute_targets(self):
        system_directory = agent._windows_system_directory()
        self.assertIsNotNone(system_directory)
        observed = []
        with mock.patch.object(agent, 'launch_coordinator', LaunchCoordinator(inspector=lambda _: ApplicationState('absent'))), mock.patch.object(
            agent.subprocess,
            'Popen',
            side_effect=lambda argv, **options: observed.append((argv, options)) or object(),
        ):
            self.assertEqual(agent.open_app('calculator').execution_status, 'process_created')
            self.assertEqual(agent.open_app('notepad').execution_status, 'process_created')
        self.assertEqual(len(observed), 2)
        for argv, options in observed:
            self.assertEqual(len(argv), 1)
            self.assertTrue(Path(argv[0]).is_absolute())
            self.assertEqual(Path(argv[0]).parent, system_directory.resolve())
            self.assertEqual(options, {'shell': False, 'close_fds': True})

    def test_missing_or_unapproved_app_target_never_launches(self):
        with (
            mock.patch.object(agent.platform, 'system', return_value='Windows'),
            mock.patch.object(
                agent,
                '_windows_system_directory',
                return_value=Path.cwd() / '__missing_windows_system_directory__',
            ),
            mock.patch.object(agent.subprocess, 'Popen') as popen,
        ):
            self.assertIn('проверить безопасный путь', agent.open_app('calculator'))
            self.assertIn('не разрешено', agent.open_app('powershell.exe'))
            popen.assert_not_called()

    def test_close_app_never_invokes_process_termination(self):
        with mock.patch.object(agent.subprocess, 'run') as run:
            result = agent.close_app('calculator')
        run.assert_not_called()
        self.assertIn('Безопасное автоматическое закрытие недоступно', result)

    def test_transcribe_only_returns_text_and_never_executes(self):
        class Segment:
            text = 'Включи настольную лампу'

        class Whisper:
            def transcribe(self, _path, **options):
                if options != {'language': 'ru', 'vad_filter': True}:
                    raise AssertionError(options)
                return [Segment()], {}

        fake_module = SimpleNamespace(WhisperModel=Whisper)
        with (
            mock.patch.object(server, 'transcribe_audio', return_value={'text':'Включи настольную лампу'}),
            mock.patch.object(server, 'reply', side_effect=AssertionError('must not execute')),
        ):
            response = self.client.post(
                '/api/transcribe',
                files={'audio': ('voice.wav', b'x' * 2048, 'audio/wav')},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'text': 'Включи настольную лампу'})

    def test_voice_transcript_is_staged_for_review_not_auto_sent(self):
        html = Path('static/index.html').read_text(encoding='utf-8')
        script = Path('static/assets/app.js').read_text(encoding='utf-8')
        self.assertNotIn('sendText(r.text)', script)
        self.assertIn("$('message').value=r.text", script)
        self.assertIn('Текст НЕ отправлен', html)

    def test_remote_clients_are_rejected_and_loopback_clients_work(self):
        remote = TestClient(server.app, base_url='http://127.0.0.1', client=('192.168.1.50', 50000))
        self.assertEqual(remote.get('/api/info').status_code, 403)
        self.assertEqual(self.client.get('/api/info').status_code, 200)
        ipv6 = TestClient(server.app, base_url='http://[::1]', client=('::1', 50000))
        self.assertEqual(ipv6.get('/api/info').status_code, 200)

    def test_startup_is_fixed_to_ipv4_loopback(self):
        with (
            mock.patch.object(start.uvicorn, 'run') as run,
            mock.patch('builtins.print'),
        ):
            start.main()
        self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')
        self.assertEqual(settings.host, '127.0.0.1')

    def test_runtime_has_no_global_forced_termination_or_bare_app_launches(self):
        runtime = '\n'.join(
            path.read_text(encoding='utf-8')
            for path in [*Path('localmind').glob('*.py'), Path('start.py')]
        ).lower()
        self.assertNotIn('taskkill', runtime)
        self.assertNotIn("['calc.exe']", runtime)
        self.assertNotIn("['notepad.exe']", runtime)

    def test_shipped_configuration_does_not_offer_lan_binding(self):
        env_example = Path('.env.example').read_text(encoding='utf-8')
        readme = Path('README.md').read_text(encoding='utf-8')
        self.assertNotIn('LOCALMIND_HOST', env_example)
        self.assertNotIn('LOCALMIND_HOST=0.0.0.0', readme)


if __name__ == '__main__':
    unittest.main()
