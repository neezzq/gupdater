import pytest

from gupdater.core import vdf


def test_nested_objects_and_lowercase_keys():
    data = vdf.loads('"AppState"\n{\n\t"appid"\t"730"\n\t"StateFlags"\t"4"\n\t"UserConfig"\n\t{\n\t\t"language"\t"russian"\n\t}\n}\n')
    assert data == {"appstate": {"appid": "730", "stateflags": "4", "userconfig": {"language": "russian"}}}


def test_escapes_comments_and_conditionals():
    text = '// comment\n"root"\n{\n\t"path"\t"C:\\\\Games\\\\Steam"\n\t"quote"\t"say \\"hi\\""\n\t"x"\t"1"\t[$WIN32]\n}\n'
    assert vdf.loads(text) == {"root": {"path": "C:\\Games\\Steam", "quote": 'say "hi"', "x": "1"}}


def test_bom_and_unquoted_tokens():
    assert vdf.loads('\ufeffroot { key value }') == {"root": {"key": "value"}}


def test_old_libraryfolders_format():
    data = vdf.loads('"LibraryFolders"\n{\n\t"TimeNextStatsReport"\t"1"\n\t"1"\t"D:\\\\SteamLibrary"\n}\n')
    assert data["libraryfolders"]["1"] == "D:\\SteamLibrary"


@pytest.mark.parametrize("text", ['"a" {', '"a" }', '"a"', '{ }'])
def test_broken_files_raise(text):
    with pytest.raises(vdf.VdfError):
        vdf.loads(text)
