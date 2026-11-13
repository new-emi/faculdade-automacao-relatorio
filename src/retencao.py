"""Politica de retencao de dados do Boletim IA (principio da necessidade, LGPD art. 6, III).

Cada tipo de dado e guardado so enquanto tem finalidade:

  - Audios (audio/boletim_AAAA-MM-DD.wav): 30 dias. Sao pesados e ouvidos uma vez so.
  - Roteiros em texto (coluna texto_boletim da tabela boletins): 12 meses. Sao leves e
    servem para recapitulacoes. Vencido o prazo, so o TEXTO e apagado; a linha continua
    (data, quantidade de noticias, duracao), para nao quebrar as metricas que apontam
    para ela.
  - Metricas (tabelas requisicoes e execucoes): sem prazo. Nao tem dado pessoal.

O que fica de fora de proposito:
  - arquivos em subpastas de audio/ (ex.: audio/evidencias/, as provas da documentacao);
  - qualquer arquivo cujo nome nao siga o padrao boletim_AAAA-MM-DD.wav (ex.: smoke.wav).

A idade do audio vem da DATA NO NOME do arquivo, e nao da data de modificacao: o OneDrive
e copias de backup podem mudar a data de modificacao, mas o nome nao muda.

Uso:
  python src/retencao.py            -> SIMULA: so lista o que seria apagado (nao apaga nada)
  python src/retencao.py --aplicar  -> apaga de verdade
O main.py chama aplicar_retencao(...) no fim de cada boletim gerado com sucesso.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

DIAS_AUDIO = 30
DIAS_TEXTO = 365
PADRAO_AUDIO = re.compile(r"^boletim_(\d{4}-\d{2}-\d{2})\.wav$")


def aplicar_retencao(
    caminho_db: str = "boletim.db",
    pasta_audio: str = "audio",
    dias_audio: int = DIAS_AUDIO,
    dias_texto: int = DIAS_TEXTO,
    simular: bool = False,
    agora: datetime | None = None,
) -> dict:
    """Apaga (ou, com simular=True, so lista) o que passou do prazo de retencao.

    Returns:
        {"audios": [nomes dos arquivos], "roteiros": [ids dos boletins]}
    """
    agora = agora or datetime.now()
    limite_audio = (agora - timedelta(days=dias_audio)).date()
    limite_texto = (agora - timedelta(days=dias_texto)).strftime("%Y-%m-%d %H:%M:%S")

    # 1) audios vencidos: so arquivos soltos em audio/ com o nome no padrao
    audios = []
    pasta = Path(pasta_audio)
    if pasta.is_dir():
        for arquivo in sorted(pasta.iterdir()):
            achou = PADRAO_AUDIO.match(arquivo.name)
            if not (arquivo.is_file() and achou):
                continue
            data_arquivo = datetime.strptime(achou.group(1), "%Y-%m-%d").date()
            if data_arquivo < limite_audio:
                audios.append(arquivo.name)
                if not simular:
                    arquivo.unlink()

    # 2) roteiros vencidos: apaga so o texto, mantem a linha
    roteiros = []
    if Path(caminho_db).is_file():
        with closing(sqlite3.connect(caminho_db)) as conexao, conexao:
            roteiros = [
                linha[0]
                for linha in conexao.execute(
                    "SELECT id FROM boletins WHERE data_geracao < ? AND texto_boletim IS NOT NULL",
                    (limite_texto,),
                )
            ]
            if roteiros and not simular:
                conexao.execute(
                    "UPDATE boletins SET texto_boletim = NULL "
                    "WHERE data_geracao < ? AND texto_boletim IS NOT NULL",
                    (limite_texto,),
                )

    return {"audios": audios, "roteiros": roteiros}


if __name__ == "__main__":
    aplicar = "--aplicar" in sys.argv
    resultado = aplicar_retencao(simular=not aplicar)
    verbo = "apagados" if aplicar else "SERIAM apagados (simulacao, nada foi apagado)"
    print(f"Audios com mais de {DIAS_AUDIO} dias {verbo}: {resultado['audios'] or 'nenhum'}")
    print(f"Roteiros com mais de {DIAS_TEXTO} dias {verbo}: {resultado['roteiros'] or 'nenhum'}")
