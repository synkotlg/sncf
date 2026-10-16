"""Extraction des champs : documents de test FICTIFS (backend/tests/fixtures/texts)."""

from railfine.ingest.parser import fold, parse_date_value, parse_document, parse_fine, parse_time_value, split_segments


def vals(fields):
    return {k: v.value for k, v in fields.items()}


def test_fold_keeps_length():
    s = "Montant à payer : 62,40 € — Œuvre"
    assert len(fold(s)) == len(s)
    assert fold("ÉTÉ") == "ete"


def test_sncf_ter_pv(texts):
    f = parse_fine(texts["sncf_ter_pv"])
    v = vals(f)
    assert v["amount_initial"] == 62.4  # total à payer, pas l'indemnité seule ni le capital social
    assert v["amount_paid"] is None
    assert v["fine_date"] == "2025-03-14"  # pas la date limite de paiement
    assert v["fine_time"] == "07:52"  # pas les horaires du service client
    assert v["origin_name"] == "Lille Flandres"
    assert v["dest_name"] == "Arras"
    assert v["train_number"] == "847123"
    assert v["train_type"] == "TER"
    assert v["reason"] == "absence_titre"
    assert v["case_number"] == "452188901234"
    assert v["status"] == "a_payer"
    assert not f["amount_initial"].uncertain
    assert "2025-05-13" in f["fine_date"].alternatives


def test_recouvrement_payee(texts):
    f = parse_fine(texts["sncf_recouvrement_payee"])
    v = vals(f)
    assert v["amount_initial"] == 90.0
    assert v["amount_paid"] == 140.0
    assert v["fine_date"] == "2024-06-21"
    assert v["fine_time"] == "18:35"
    assert v["origin_name"] == "Paris Gare de Lyon"
    assert v["dest_name"] == "Marseille St-Charles"
    assert v["train_type"] == "TGV"
    assert v["reason"] == "surclassement"
    assert v["status"] == "payee"
    assert "375" in (v["notes"] or "")


def test_sncb(texts):
    v = vals(parse_fine(texts["sncb_constat"]))
    assert v["amount_initial"] == 75.0
    assert v["fine_date"] == "2025-02-03"
    assert v["fine_time"] == "08:12"
    assert v["origin_name"] == "Bruxelles-Midi"
    assert v["dest_name"] == "Liège-Guillemins"
    assert v["train_number"] == "2117"
    assert v["train_type"] == "SNCB"
    assert v["country"] == "BE"
    assert v["reason"] == "non_validation"


def test_multiple_fines_split(texts):
    segs = split_segments(texts["multi_amendes"])
    assert len(segs) == 2
    drafts = parse_document(texts["multi_amendes"])
    assert [d["case_number"]["value"] for d in drafts] == ["700120023003", "700120029999"]
    assert drafts[0]["train_type"]["value"] == "TRANSILIEN"
    assert drafts[0]["line_label"]["value"] == "Ligne P"
    # "TGV" dans le nom de la gare ne doit pas faire passer un RER pour un TGV
    assert drafts[1]["train_type"]["value"] == "RER"
    assert drafts[1]["line_label"]["value"] == "RER B"


def test_nothing_is_invented_on_empty_or_unrelated_text():
    for text in ("", "Bonjour, ceci est un courrier sans rapport.\nCordialement."):
        v = vals(parse_fine(text))
        for key in ("amount_initial", "amount_paid", "fine_date", "fine_time", "origin_name", "dest_name", "train_number",
                    "case_number", "reason"):
            assert v[key] is None, key


def test_ambiguous_amounts_are_flagged():
    f = parse_fine("Montant total : 50,00 €\nTotal : 80,00 €")
    assert f["amount_initial"].uncertain
    assert 80.0 in f["amount_initial"].alternatives


def test_unlabelled_date_is_uncertain():
    f = parse_fine("Courrier\n12/01/2024\n15/02/2024")
    assert f["fine_date"].uncertain


def test_value_parsers():
    assert parse_date_value("14/03/2025") == "2025-03-14"
    assert parse_date_value("2025-03-14") == "2025-03-14"
    assert parse_date_value("31/02/2025") is None
    assert parse_time_value("7h52") == "07:52"
    assert parse_time_value("25:00") is None


def test_dutch_document():
    text = ("NMBS - Vaststelling\nDatum van vaststelling: 12 maart 2025 om 08:40\nTrein IC 1817\n"
            "Traject: Antwerpen-Centraal naar Gent-Sint-Pieters\nReden: Reiziger zonder geldig vervoerbewijs\nTe betalen: 75,00 EUR")
    v = vals(parse_fine(text))
    assert v["fine_date"] == "2025-03-12"
    assert v["fine_time"] == "08:40"
    assert v["train_number"] == "1817"
    assert v["reason"] == "absence_titre"
    assert v["amount_initial"] == 75.0
