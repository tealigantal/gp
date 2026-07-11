from pathlib import Path

import yaml


def test_all_python_services_share_one_backend_image_and_only_api_builds():
    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    names = [
        "gp",
        "gp-worker",
        "gp-serenity-worker",
        "gp-serenity-bootstrap",
        "gp-rebuild-daybook",
        "gp-postclose-archive",
    ]
    assert {services[name]["image"] for name in names} == {"${GP_BACKEND_IMAGE:-gp-backend}:${GP_BACKEND_TAG:-local}"}
    assert [name for name in names if "build" in services[name]] == ["gp"]
    assert services["gp-rebuild-daybook"]["command"][-2:] == ["ops-run", "rebuild-daybook"]
    assert services["gp-postclose-archive"]["command"][-2:] == ["ops-run", "postclose-archive"]
