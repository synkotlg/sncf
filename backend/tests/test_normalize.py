from railfine.reference.normalize import bilingual_variant, clean_display_name, match_key, normalize_name, strip_accents
from railfine.reference.store import normalize_uic


def test_strip_accents_and_ligatures():
    assert strip_accents("Liège-Guillemins") == "Liege-Guillemins"
    assert strip_accents("Cœur") == "Coeur"


def test_normalize_abbreviations():
    assert normalize_name("St-Étienne Châteaucreux") == "saint etienne chateaucreux"
    assert normalize_name("Marseille St-Charles") == normalize_name("MARSEILLE SAINT CHARLES")
    assert normalize_name("Bxl-Central") == "bruxelles central"


def test_match_key_drops_stopwords():
    assert match_key("Gare de Lille-Flandres") == "lille flandres"
    assert match_key("LILLE FLANDRES") == "lille flandres"
    # "Paris Gare de Lyon" ne doit pas devenir "lyon"
    assert match_key("Paris Gare de Lyon") == "paris lyon"


def test_bilingual_variant():
    assert bilingual_variant("Brussel-Zuid") == "bruxelles midi"
    assert bilingual_variant("Namur") is None


def test_clean_display_name():
    assert clean_display_name("  LYON PART-DIEU ") == "Lyon Part-Dieu"
    assert clean_display_name("Lyon Part-Dieu") == "Lyon Part-Dieu"


def test_normalize_uic():
    assert normalize_uic("87751230") == "8775123"
    assert normalize_uic("008814001") == "8814001"
    assert normalize_uic("8814001") == "8814001"
    assert normalize_uic("123") is None
    assert normalize_uic(None) is None
