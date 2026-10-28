"""
base.py — Tüm analizörlerin uyduğu temel şablon (Strategy Pattern)
ve tek seferlik disk I/O yöneten context manager (TempCodeManager).
"""

import os
import tempfile
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAnalyzer(ABC):
    """
    Tüm analiz motorlarının uyduğu soyut temel sınıf.

    Her alt sınıf yalnızca bir analiz aracından sorumludur
    ve sonuçlarını standart bir Dict[str, Any] olarak döner.
    """

    @abstractmethod
    def analyze(self, code: str, temp_file: str = None) -> Dict[str, Any]:
        """
        Kodu analiz eder ve sonuç sözlüğü döner.

        Args:
            code:      Ham Python kodu (string).
            temp_file: Önceden diske yazılmış geçici dosya yolu.
                       Verilmezse analizör kendi geçici dosyasını yönetir.

        Returns:
            Analiz sonuçlarını içeren Dict.
        """


class TempCodeManager:
    """
    Context Manager — Kodu diske TEK SEFER yazar, çıkışta siler.

    Kullanım:
        with TempCodeManager(code) as tmp_path:
            run_pylint(tmp_path)
            run_flake8(tmp_path)
        # Dosya burada silinmiş olur

    Böylece aynı kod için 5 ayrı subprocess yerine tek bir I/O işlemi yapılır.
    """

    def __init__(self, code: str):
        self._code = code
        self._path: str = None

    def __enter__(self) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(self._code)
            self._path = f.name
        return self._path

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._path and os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except OSError:
                pass
        return False  # İstisnaları yukarıya ilet
