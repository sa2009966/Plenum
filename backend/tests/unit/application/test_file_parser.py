"""Cobertura del parser multi-formato."""
from pathlib import Path

import pytest

from src.application.file_parser import (
    UnsupportedFormatError,
    extension_of,
    is_supported,
    parse_file,
)

#: PDF de una página con el texto "Hola Plenum, texto de prueba", cifrados con pikepdf
_PDFS = Path(__file__).resolve().parents[2] / "fixtures" / "pdf"


class TestParseFile:

    def test_txt_utf8(self):
        text = parse_file("notas.txt", "Hola mundo".encode("utf-8"))
        assert text == "Hola mundo"

    def test_txt_latin_detected(self):
        raw = "caf\xe9"  # latin-1 "café"
        text = parse_file("datos.txt", raw.encode("latin-1"))
        assert "caf" in text

    def test_markdown(self):
        text = parse_file("apuntes.md", "# Titulo\n\nCuerpo".encode("utf-8"))
        assert "Titulo" in text
        assert "Cuerpo" in text

    def test_code_python(self):
        text = parse_file("main.py", b"def hello():\n    return 1")
        assert "hello" in text

    def test_code_json(self):
        text = parse_file("data.json", b'{"a": 1}')
        assert '"a"' in text

    def test_pdf_binary_raises_when_not_readable(self):
        # Bytes inválidos como PDF deberían lanzar UnsupportedFormatError
        with pytest.raises(UnsupportedFormatError):
            parse_file("doc.pdf", b"not a real pdf content")

    @pytest.mark.parametrize("nombre", ["protegido-aes128.pdf", "protegido-aes256.pdf"])
    def test_pdf_protegido_sin_contrasena_de_apertura_se_lee(self, nombre):
        """Los PDF "protegidos" (se abren sin contraseña pero no dejan editar ni copiar)
        van cifrados con AES. Sin pycryptodome, PyPDF2 fallaba ("PyCryptodome is
        required") o decía que el PDF estaba escaneado."""
        text = parse_file(nombre, (_PDFS / nombre).read_bytes())
        assert "Hola Plenum" in text

    def test_pdf_con_contrasena_de_apertura_lo_dice(self):
        with pytest.raises(UnsupportedFormatError, match="contraseña"):
            parse_file("con-contrasena.pdf", (_PDFS / "con-contrasena.pdf").read_bytes())

    def test_binary_raises_when_not_readable(self):
        with pytest.raises(UnsupportedFormatError):
            parse_file("doc.docx", b"\x00\x01\x02 not a docx")

    def test_empty_text(self):
        text = parse_file("vacio.txt", b"")
        assert text == ""


class TestIsSupported:

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.txt", True),
            ("a.md", True),
            ("a.pdf", True),
            ("a.docx", True),
            ("a.xlsx", True),
            ("a.pptx", True),
            ("a.py", True),
            ("a.json", True),
            ("a.csv", True),
            ("a.log", True),
            ("a.exe", False),
            ("a.zip", False),
            ("a.png", False),
            (".env", True),  # sin extensión reconocible → se trata como texto
        ],
    )
    def test_support(self, name, expected):
        assert is_supported(name) == expected


class TestExtensionOf:

    def test_extension_lowercased(self):
        assert extension_of("ARCHIVO.PDF") == "pdf"

    def test_no_extension(self):
        assert extension_of("README") == ""

    def test_dotted_hidden(self):
        assert extension_of(".env") == ""
