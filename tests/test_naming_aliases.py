from src.utils.naming import standardize_team_name


def test_standardize_team_name_mcneese_alias():
    assert standardize_team_name("McNeese Cowboys") == "McNeese St."
    assert standardize_team_name("McNeese") == "McNeese St."
