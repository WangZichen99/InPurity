import locale
from typing import Any
from messages import _translations

class I18n:
    current_lang = None
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if cls.current_lang is None:
                try:
                    cls.current_lang = locale.getdefaultlocale()[0]
                    if cls.current_lang not in _translations:
                        cls.current_lang = 'en'
                except:
                    cls.current_lang = 'en'
        return cls._instance

    @classmethod
    def set_language(cls, lang: str) -> None:
        """设置语言"""
        if lang in _translations:
            cls.current_lang = lang

    @classmethod
    def get(cls, key: str, *args: Any) -> str:
        """获取翻译文本"""
        if cls.current_lang is None:
            cls()
        
        translation = _translations.get(cls.current_lang, {}).get(key)
        if translation is None:
            # 如果找不到翻译，尝试使用英语
            translation = _translations['en'].get(key, key)
        
        return translation.format(*args) if args else translation 