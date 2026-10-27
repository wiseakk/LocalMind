import pytest
from fastapi.testclient import TestClient
from localmind import agent, devices, server
from localmind.settings import settings

client = TestClient(server.app)

def test_light_direct_rule(monkeypatch):
    assert settings.demo is True  # default demonstration mode
    result = agent.reply('Включи настольную лампу')
    assert result['engine'] == 'rules'
    assert devices._demo_states['desk_light'] is True
    result = agent.reply('Выключи лампу на столе')
    assert 'ДЕМО' in result['answer']
    assert devices._demo_states['desk_light'] is False

def test_no_false_device_or_unauthorized_tool():
    assert devices.find_device('Включи рандомную розетку') is None
    with pytest.raises(devices.DeviceError):
        devices.set_light('unlisted_power_socket', 'on')
    assert 'не разрешён' in agent.dispatch('execute_shell', {'command':'rm -rf /'})
    assert 'не разрешено' in agent.open_app('cmd.exe')

def test_api_smoke():
    info=client.get('/api/info')
    assert info.status_code==200 and info.json()['demo'] is True
    chat=client.post('/api/chat',json={'text':'Включи настольную лампу'})
    assert chat.status_code==200 and chat.json()['engine']=='rules'

def test_agent_ollama_tool_call(monkeypatch):
    calls=[]
    def fake(messages, tools):
        calls.append((messages,tools))
        if len(calls)==1:
            return {'role':'assistant','content':'', 'tool_calls':[{'function':{
                'name':'set_light','arguments':{'device_id':'desk_light','state':'on'}}}]}
        return {'role':'assistant','content':'Готово!'}
    monkeypatch.setattr(agent, 'ollama_chat', fake)
    r=agent.reply('Сделай освещение рабочего места поярче')
    assert r['engine']=='ollama'
    assert 'ДЕМО:' in r['answer'] and 'Готово' in r['answer']
    assert len(calls)==2

def test_negation_does_not_turn_on_light():
    devices._demo_states['desk_light'] = False
    result=agent.reply('Не включи настольную лампу')
    assert 'не выполняю' in result['answer']
    assert devices._demo_states['desk_light'] is False


def test_questions_do_not_receive_tools(monkeypatch):
    observed = []
    def fake(messages, tools):
        observed.append(tools)
        return {'role': 'assistant', 'content': 'RSA — асимметричный криптоалгоритм.'}
    monkeypatch.setattr(agent, 'ollama_chat', fake)
    answer = agent.reply('Что такое RSA-шифрование?')
    assert 'RSA' in answer['answer']
    assert observed == [[]]
    answer = agent.reply('Подробную инструкцию как сварить пельмени')
    assert observed == [[], []]


def test_questions_about_light_do_not_toggle_device(monkeypatch):
    devices._demo_states['desk_light'] = False
    observed = []
    monkeypatch.setattr(agent, 'ollama_chat', lambda messages, tools: (observed.append(tools) or {'role':'assistant','content':'Попроси меня включить лампу.'}))
    ans = agent.reply('Расскажи, как включить настольную лампу')
    assert ans['engine'] == 'ollama'
    assert observed == [[]]
    assert devices._demo_states['desk_light'] is False


def test_open_and_close_calculator_windows_mock(monkeypatch):
    import subprocess
    class Proc:
        returncode = 0
    observed = []
    monkeypatch.setattr(agent.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(agent.subprocess, 'Popen', lambda argv, shell: observed.append(('start',argv,shell)))
    monkeypatch.setattr(agent.subprocess, 'run', lambda argv, **opts: observed.append(('stop',argv,opts)) or Proc())
    agent._launched_apps.clear()
    assert 'не запускал' in agent.reply('Закрой калькулятор')['answer']
    assert 'Запущено' in agent.reply('Запусти калькулятор')['answer']
    assert 'закрыт' in agent.reply('Закрой калькулятор')['answer']
    assert observed[0] == ('start', ['calc.exe'], False)
    assert observed[1][1] == ['taskkill', '/IM', 'CalculatorApp.exe', '/F']
    assert observed[1][2]['shell'] is False
    assert 'недоступно' in agent.close_app('notepad')


def test_open_app_negated_or_unsupported(monkeypatch):
    monkeypatch.setattr(agent.platform, 'system', lambda: 'Windows')
    def prohibit(*args, **kwargs):
        raise AssertionError('не должно запускаться')
    monkeypatch.setattr(agent.subprocess, 'Popen', prohibit)
    assert 'не выполняю' in agent.reply('Не открой калькулятор')['answer']
    assert 'не разрешено' in agent.open_app('cmd.exe')
