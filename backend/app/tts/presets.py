from dataclasses import dataclass


@dataclass(frozen=True)
class PresetVoice:
    id: str
    label: str
    language: str
    gender: str
    model_speaker: str

    @property
    def voice_id(self) -> str:
        return f"preset:{self.id}"


# CosyVoice-300M-SFT speaker IDs are kept on the server so clients cannot pass
# arbitrary model identifiers to the isolated worker.
PRESET_VOICES = (
    PresetVoice("zh_female", "普通话女声", "普通话", "female", "中文女"),
    PresetVoice("zh_male", "普通话男声", "普通话", "male", "中文男"),
    PresetVoice("yue_female", "粤语女声", "粤语", "female", "粤语女"),
    PresetVoice("en_female", "英语女声", "英语", "female", "英文女"),
    PresetVoice("en_male", "英语男声", "英语", "male", "英文男"),
    PresetVoice("ja_male", "日语男声", "日语", "male", "日语男"),
    PresetVoice("ko_female", "韩语女声", "韩语", "female", "韩语女"),
)
PRESET_BY_ID = {voice.id: voice for voice in PRESET_VOICES}


def preset_from_voice_id(voice_id: str) -> PresetVoice | None:
    if not voice_id.startswith("preset:"):
        return None
    return PRESET_BY_ID.get(voice_id.removeprefix("preset:"))
