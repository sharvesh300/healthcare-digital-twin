from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://twin:twin_dev_password@localhost:5432/twin"
    fhir_base: str = "http://localhost:8080/fhir"
    data_dir: Path = Path("data")
    seeds_dir: Path = Path("seeds")
    replay_speed: float = 60.0

    # CGMacros timestamps are naive local time from a Texas study site.
    source_tz: str = "America/Chicago"
    # Matching rule: same sex, |age difference| <= this, then nearest BMI.
    match_max_age_diff: int = 5
    # CGMacros cohort definition (HbA1c %).
    t2d_hba1c: float = 6.5

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.source_tz)

    @property
    def cgmacros_dir(self) -> Path:
        return self.data_dir / "raw" / "cgmacros"

    @property
    def synthea_fhir_dir(self) -> Path:
        return self.data_dir / "synthea" / "fhir"

    @property
    def synthea_general_fhir_dir(self) -> Path:
        """General-population cohort (ages 35-65) used for the BIG IDEAs composite twins."""
        return self.data_dir / "synthea_general" / "fhir"

    @property
    def synthea_fhir_dirs(self) -> list[Path]:
        return [d for d in (self.synthea_fhir_dir, self.synthea_general_fhir_dir) if d.exists()]

    @property
    def reports_dir(self) -> Path:
        path = self.data_dir / "reports"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def settings() -> Settings:
    return Settings()
