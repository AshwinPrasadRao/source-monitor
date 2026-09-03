from pathlib import Path

from orrery_monitor.config import REQUIRED_FEED_OUTPUTS, load_config


def test_repository_config_declares_exact_v1_outputs() -> None:
    config = load_config(Path(__file__).parents[1] / "sources.yml")

    assert config.feed_outputs == REQUIRED_FEED_OUTPUTS
    assert len(config.feed_outputs) == 12
    assert {source.id for source in config.sources if source.enabled} == {
        "dot_wpc",
        "drdo",
        "fcc_icfs",
        "idex",
        "inspace",
        "isro",
        "nsil",
        "parliament_space",
        "pib_space",
    }
    assert config.default_retention == 300
