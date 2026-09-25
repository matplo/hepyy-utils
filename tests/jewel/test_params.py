from hepyy_utils.jewel.params import set_param_text


def test_set_param_replaces_first_active_occurrence_and_drops_duplicates():
    text = "# NEVENT 1\nNEVENT 10\nPDFSET 13100\nNEVENT 20\n"

    updated = set_param_text(text, "NEVENT", 3)

    assert "# NEVENT 1" in updated
    assert "NEVENT 3\n" in updated
    assert "NEVENT 10" not in updated
    assert "NEVENT 20" not in updated
    assert "PDFSET 13100" in updated


def test_set_param_appends_missing_key():
    updated = set_param_text("PDFSET 13100\n", "HEPMCFILE", "events/out.hepmc")

    assert updated.endswith("HEPMCFILE events/out.hepmc\n")
