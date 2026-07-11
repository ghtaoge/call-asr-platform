class LocalTranslationProvider:
    def translate(self, text: str, source_language: str = "zh", target_language: str = "en") -> str:
        if not text:
            return ""
        if source_language == target_language:
            return text
        return f"[{target_language}] {text}"
