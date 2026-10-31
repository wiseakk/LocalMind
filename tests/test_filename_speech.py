"""Speech-channel checks; these do not establish audible TTS quality."""
import pytest

from localmind.results import ActionResult, file_output, output_channels
from localmind.speech_text import filename_description, normalize_speech, pronounce_filename


def test_reported_filename_has_natural_speech_and_exact_display_and_data():
    original = 'Spisok_rabot pobeditelej_i_prizjorov_IB2026.pdf'
    result = ActionResult(True, 'files.search', 'selected', 'observed', data={'filename': original})
    display, speech = file_output(result)
    assert speech == 'Найден PDF-файл: «Список работ победителей и призёров, ИБ, за две тысячи двадцать шестой год».'
    channels = output_channels(display, [result.to_dict()], speech)
    assert original in channels['display_text']
    assert channels['structured_result']['actions'][0]['data']['filename'] == original
    assert normalize_speech(normalize_speech(speech)) == normalize_speech(speech)


@pytest.mark.parametrize('filename,expected', [
    ('Otchet_2027.pdf', 'Отчёт, за две тысячи двадцать седьмой год'),
    ('Plan_rabot_2030.docx', 'План работ, за две тысячи тридцатый год'),
    ('Spisok_uchastnikov_1999.txt', 'Список участников, за тысяча девятьсот девяносто девятый год'),
    ('Itogi_2000.pdf', 'Итоги, за двухтысячный год'),
    ('Otchet_za_2026_god.pdf', 'Отчёт, за две тысячи двадцать шестой год'),
    ('LocalMind_Obsidian_Python.pdf', 'Локалмайнд Обсидиан Пайтон'),
    ('LocalMind2027.pdf', 'Локалмайнд, за две тысячи двадцать седьмой год'),
    ('UnknownEnglish_XYZ.pdf', 'Unknown English икс уай зет'),
    ('Доклад_Ёж.pdf', 'Доклад Ёж'),
])
def test_unseen_titles_use_composable_vocabulary(filename, expected):
    assert pronounce_filename(filename) == expected


@pytest.mark.parametrize('filename', [
    'a' * 64 + '.pdf',
    '12345678-1234-1234-abcd-1234567890ab.pdf',
    'z7Hk9Gmn1Qwx5Abd6Yui8Opf2Rf4Vb3T.pdf',
    'q' * 300 + '.pdf',
    '+++.pdf',
])
def test_opaque_names_are_short_type_descriptions(filename):
    assert filename_description(filename) == 'PDF-файл с техническим именем'


def test_paths_hashes_and_metadata_are_not_spoken():
    title = filename_description('C:\\private\\Otchet_' + 'a' * 64 + '_2028.pdf')
    assert title == 'PDF-файл: «Отчёт, за две тысячи двадцать восьмой год»'
    assert not any(part in title for part in ('private', 'C:', 'aaaa', '.pdf'))


def test_versions_decimals_and_misleading_extensions_do_not_become_years_or_pdf_labels():
    assert pronounce_filename('Python_v2026.1.pdf') == 'Пайтон v два ноль два шесть запятая один'
    assert pronounce_filename('Python_v3.14.pdf') == 'Пайтон v три запятая один четыре'
    assert not filename_description('report.pdf.exe').startswith('PDF-файл')
    assert not filename_description('report.pdf.backup').startswith('PDF-файл')


@pytest.mark.parametrize('name', ['Spisok_IB2026.pdf', 'Python_v3.14.pdf', 'Отчёт_2027.pdf', 'XYZ_notes.txt'])
def test_prepared_filename_speech_is_stable_under_repeated_tts_normalization(name):
    once = normalize_speech(filename_description(name))
    assert normalize_speech(once) == once
