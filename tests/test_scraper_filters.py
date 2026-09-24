import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from radar.sources.html_listing import CALL_WORDS, NOISE, NOT_A_CALL


def keeps(title: str) -> bool:
    return bool(CALL_WORDS.search(title)) and not NOISE.search(title) and not NOT_A_CALL.search(title)


def test_keeps_real_calls():
    for t in [
        "JAVNI POZIV za podnošenje prijava za Potporu mladim poljoprivrednicima",
        "JAVNI POZIV za podnošenje prijava za potporu u oblasti agroturizma",
        "Javni natječaj za sufinanciranje projekata iz oblasti vodoprivrede",
        "Open call for proposals: cascade funding for SMEs",
    ]:
        assert keeps(t), t


def test_drops_job_adverts():
    for t in [
        "Javni natječaj za prijem pripravnika u Županijskom tužiteljstvu",
        "JAVNI OGLAS za prijem vježbenika srednje stručne spreme",
        "Javni oglas za popunu upražnjenog radnog mjesta namještenika",
    ]:
        assert not keeps(t), t


def test_drops_non_call_documents():
    for t in [
        "https://ec.europa.eu/info/funding-tenders/opportunities/docs/2021-2027",
        "Factsheet on the FTSP mechanism and the first sub-call",
        "Obrazac za prijavu na javni oglas",
    ]:
        assert not keeps(t), t
