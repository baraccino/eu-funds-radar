import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from radar.models import Call


def test_replacement_characters_are_scrubbed():
    """SEDIA ships truncated keywords like 'EU Innov�'."""
    c = Call(source="s", source_id="i", title="Clean �title", url="u",
             keywords=["EU Innov�", "fine"], summary="body � here")
    j = c.to_json()
    blob = str(j)
    assert "�" not in blob, blob[:200]
    assert j["keywords"] == ["EU Innov", "fine"]
    assert j["title"] == "Clean title"


def test_scrub_leaves_normal_text_alone():
    c = Call(source="s", source_id="i", title="Potpora mladim poljoprivrednicima",
             url="u", keywords=["agroturizam", "ovčarstvo"])
    j = c.to_json()
    assert j["title"] == "Potpora mladim poljoprivrednicima"
    assert j["keywords"] == ["agroturizam", "ovčarstvo"]
