from app import config


def test_supabase_pooler_uses_psycopg_and_requires_ssl(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.ref:secret@aws-1-eu-west-1.pooler.supabase.com:5432/postgres",
    )

    url = config.database_url()

    assert url.startswith("postgresql+psycopg://postgres.ref:secret@aws-1-eu-west-1.pooler.supabase.com")
    assert "sslmode=require" in url


def test_local_database_url_does_not_require_ssl(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/gigahack")

    url = config.database_url()

    assert url == "postgresql+psycopg://localhost:5432/gigahack"
