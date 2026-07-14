from pathlib import Path

import yaml


def test_all_python_services_share_one_backend_image_and_only_api_builds():
    compose = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    names = [
        "api",
        "worker",
        "serenity",
    ]
    assert {services[name]["image"] for name in names} == {"${GP_BACKEND_IMAGE:-gp-backend}:${GP_BACKEND_TAG:-local}"}
    assert [name for name in names if "build" in services[name]] == ["api"]
    assert services["serenity"]["command"] == ["python", "-m", "gp_assistant.cli", "serenity-loop"]
    assert "profiles" not in services["serenity"]


def test_backend_build_proxy_is_explicit_and_has_no_machine_specific_default():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    build_args = compose["x-backend-build"]["args"]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert build_args["HTTP_PROXY"] == "${HTTP_PROXY:-}"
    assert build_args["HTTPS_PROXY"] == "${HTTPS_PROXY:-}"
    assert build_args["ALL_PROXY"] == "${ALL_PROXY:-}"
    assert "host.docker.internal:7890" not in dockerfile


def test_backend_image_declares_the_native_serenity_selection_policy():
    dockerfile = (
        Path(__file__).resolve().parents[1] / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert 'io.gp.selection-policy="adaptive_v2_native_serenity_single_score"' in dockerfile
    assert 'io.gp.selection-policy="adaptive_policy_single_path"' not in dockerfile


def test_frontend_proxy_inputs_are_explicit_and_not_persisted_in_runtime_image():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    build_args = compose["services"]["web"]["build"]["args"]
    dockerfile = (root / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert {build_args[name] for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")} == {"${HTTP_PROXY:-}", "${HTTPS_PROXY:-}", "${ALL_PROXY:-}"}
    assert "FROM ${BASE_NGINX_IMAGE} AS runtime\nARG HTTP_PROXY" not in dockerfile
    assert "ENV HTTP_PROXY" not in dockerfile
