"""Modulo de registro do pipeline "Boletim IA" (persistencia em SQLite).

Grava os metadados de cada boletim gerado (data, quantidade de noticias, texto,
caminho do audio e duracao em segundos) num banco SQLite local. Usa apenas a
biblioteca padrao (`sqlite3`), sem dependencias externas.

Uso:
    from src.registro import inicializar_banco, registrar_boletim

    inicializar_banco("boletim.db")
    id_boletim = registrar_boletim(
        "boletim.db",
        data_geracao="2026-09-17 10:30:00",
        qtd_noticias=12,
        texto_boletim="...",
        caminho_audio="audio/boletim_2026-09-17.wav",
        duracao_audio_segundos=72.8,
    )

Teste rapido (a partir da raiz do projeto):
    python src/registro.py
"""

from __future__ import annotations

import io
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

DB_PADRAO = "boletim.db"

SQL_CRIAR_TABELA = """
CREATE TABLE IF NOT EXISTS boletins (
    id INTEGER PRIMARY KEY,
    data_geracao TEXT,
    qtd_noticias INTEGER,
    texto_boletim TEXT,
    caminho_audio TEXT,
    duracao_audio_segundos REAL
)
"""

SQL_INSERIR = (
    "INSERT INTO boletins "
    "(data_geracao, qtd_noticias, texto_boletim, caminho_audio, duracao_audio_segundos) "
    "VALUES (?, ?, ?, ?, ?)"
)


def _conectar(caminho_db: str) -> sqlite3.Connection:
    """Abre (criando se necessario) o banco no caminho indicado."""
    caminho = Path(caminho_db)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(caminho))


def inicializar_banco(caminho_db: str = DB_PADRAO) -> None:
    """Cria a tabela `boletins` se ela ainda nao existir.

    Args:
        caminho_db: caminho do arquivo SQLite (padrao: boletim.db na raiz).
    """
    with closing(_conectar(caminho_db)) as conexao, conexao:
        conexao.execute(SQL_CRIAR_TABELA)


def registrar_boletim(
    caminho_db: str,
    data_geracao: str,
    qtd_noticias: int,
    texto_boletim: str,
    caminho_audio: str,
    duracao_audio_segundos: float,
) -> int:
    """Insere um boletim na tabela `boletins` e retorna o id gerado.

    Args:
        caminho_db: caminho do arquivo SQLite.
        data_geracao: data/hora da geracao (texto ISO ou "YYYY-MM-DD HH:MM:SS").
        qtd_noticias: quantidade de noticias usadas no roteiro.
        texto_boletim: roteiro completo gerado pelo LLM.
        caminho_audio: caminho do WAV gerado.
        duracao_audio_segundos: duracao do audio em segundos.

    Returns:
        O id (INTEGER PRIMARY KEY) do registro inserido.
    """
    with closing(_conectar(caminho_db)) as conexao, conexao:
        cursor = conexao.execute(
            SQL_INSERIR,
            (
                data_geracao,
                int(qtd_noticias),
                texto_boletim,
                caminho_audio,
                float(duracao_audio_segundos),
            ),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):  # evita UnicodeEncodeError em console cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    inicializar_banco(DB_PADRAO)

    with closing(sqlite3.connect(DB_PADRAO)) as conexao:
        total = conexao.execute("SELECT COUNT(*) FROM boletins").fetchone()[0]

    print(f"[ok] banco '{DB_PADRAO}' inicializado (tabela 'boletins').")
    print(f"[ok] registros gravados ate agora: {total}.")
