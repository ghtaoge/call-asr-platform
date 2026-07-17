import re
from pathlib import Path


def test_cosyvoice_setup_is_pinned_and_contains_no_secret():
    script = (Path(__file__).parents[1] / "scripts" / "setup_cosyvoice.ps1").read_text(
        encoding="utf-8"
    )

    assert "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc" in script
    assert "submodule update --init --recursive" in script
    assert "python=3.10" in script
    assert "FunAudioLLM/Fun-CosyVoice3-0.5B-2512" in script
    assert "iic/CosyVoice-300M-SFT" in script
    assert re.search(r"sk-[A-Za-z0-9]{16,}", script) is None
