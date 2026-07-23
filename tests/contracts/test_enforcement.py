from gp_assistant.contracts import check_retired, manifest


def test_contract_manifest_and_retirement_checker():
    assert manifest.main(["--check"]) == 0
    assert check_retired.main() == 0
