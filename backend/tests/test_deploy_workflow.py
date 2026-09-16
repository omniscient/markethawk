from pathlib import Path


def test_deploy_migration_step_bypasses_backend_entrypoint():
    workflow = Path(__file__).parents[2] / ".github" / "workflows" / "deploy.yml"
    deploy_yml = workflow.read_text(encoding="utf-8")

    assert (
        "docker compose run --rm --entrypoint python backend -m alembic upgrade head"
        in deploy_yml
    )
    assert "docker compose run --rm backend python -m alembic upgrade head" not in deploy_yml
