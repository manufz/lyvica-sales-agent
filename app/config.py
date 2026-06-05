from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lyvica"
    LYVICA_SCORING_URL: str = "http://localhost:8000"
    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = "Manuel <manuel@yourdomain.com>"
    STRIPE_SECRET_KEY: str = ""
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""
    STRIPE_STARTER_LINK: str = ""
    STRIPE_PRO_LINK: str = ""
    HERMES_SHARED_SECRET: str = "change-this"
    APP_BASE_URL: str = "http://localhost:9000"

    class Config:
        env_file = ".env"


settings = Settings()
