#!/usr/bin/env python3
"""Gera feeds CNVH a partir da API MediaWiki e das tabelas públicas do BeachUp."""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "generated-rankings"
WIKIPEDIA_PAGE = "https://pt.wikipedia.org/wiki/Ranking_da_Federa%C3%A7%C3%A3o_Internacional_de_Voleibol"
WIKIPEDIA_API = "https://pt.wikipedia.org/w/api.php?action=parse&page=Ranking_da_Federa%C3%A7%C3%A3o_Internacional_de_Voleibol&prop=text&format=json&formatversion=2"
BEACH_URLS = {
    "male": "https://www.beachup.app/pt/volei-praia-classificacao-mundial-homens/",
    "female": "https://www.beachup.app/pt/volei-praia-classificacao-mundial-mulheres/",
}
USER_AGENT = "CartolaNews-Volei-Hub/1.5 (+https://cartolanews.com.br/)"
PT_MONTHS = {"janeiro":1,"fevereiro":2,"março":3,"abril":4,"maio":5,"junho":6,"julho":7,"agosto":8,"setembro":9,"outubro":10,"novembro":11,"dezembro":12}

COUNTRY_CODES = {
    "alemanha":"GER", "argentina":"ARG", "belgica":"BEL", "brasil":"BRA", "bulgaria":"BUL",
    "canada":"CAN", "catar":"QAT", "chequia":"CZE", "china":"CHN", "colombia":"COL", "coreia do sul":"KOR",
    "cuba":"CUB", "dinamarca":"DEN", "egito":"EGY", "eslovenia":"SLO", "estados unidos":"USA",
    "estonia":"EST", "finlandia":"FIN", "franca":"FRA", "grecia":"GRE", "hungria":"HUN", "ira":"IRI",
    "israel":"ISR", "italia":"ITA", "japao":"JPN", "mexico":"MEX", "paises baixos":"NED", "polonia":"POL",
    "porto rico":"PUR", "portugal":"POR", "quenia":"KEN", "republica dominicana":"DOM", "romenia":"ROU",
    "russia":"RUS", "servia":"SRB", "suecia":"SWE", "suica":"SUI", "tailandia":"THA", "turquia":"TUR",
    "ucrania":"UKR", "vietna":"VIE",
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table": self.table = []
        elif self.table is not None and tag == "tr": self.row = []
        elif self.row is not None and tag in ("th", "td"): self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split())); self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if self.row: self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table); self.table = None


def fetch(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html;q=0.9"})
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:  # pragma: no cover - rede externa
            last_error = error
            if attempt < 2: time.sleep(1 + attempt)
    raise RuntimeError(f"Falha ao acessar {url}: {last_error}")


def key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower().strip()


def parse_number(value: str) -> float:
    return float(value.replace(".", "").replace(",", ".").strip())


def wikipedia_rankings() -> dict[str, dict]:
    payload = json.loads(fetch(WIKIPEDIA_API))
    html = payload.get("parse", {}).get("text", "")
    parser = TableParser(); parser.feed(html)
    adult = [table for table in parser.tables if len(table) >= 3 and table[1][:4] == ["Pos.", "Equipe", "Pontos", "Confederação"]][:2]
    if len(adult) != 2: raise RuntimeError("As duas tabelas adultas da Wikipédia não foram encontradas.")
    result = {}
    for gender, table in zip(("male", "female"), adult):
        teams = []
        for row in table[2:]:
            if len(row) < 4 or not row[0].isdigit(): continue
            teams.append({"rank": int(row[0]), "name": row[1], "country_code": COUNTRY_CODES.get(key(row[1]), ""), "points": parse_number(row[2]), "confederation": row[3]})
        if len(teams) < 20: raise RuntimeError(f"Ranking Wikipedia {gender} incompleto: {len(teams)} equipes.")
        caption = table[0][0] if table and table[0] else ""
        date_match = re.search(r"em\s+(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", caption, re.I)
        if date_match and date_match.group(2).lower() in PT_MONTHS:
            updated_at = datetime(int(date_match.group(3)), PT_MONTHS[date_match.group(2).lower()], int(date_match.group(1)), tzinfo=timezone.utc).isoformat()
        else:
            updated_at = datetime.now(timezone.utc).isoformat()
        result[gender] = {
            "version":"1.0", "type":"official_ranking", "gender":gender,
            "source":"Wikipédia em português (dados atribuídos à página indicada)", "source_url":WIKIPEDIA_PAGE,
            "license":"CC BY-SA 4.0; consulte o histórico da página para autores", "updated_at":updated_at,
            "teams":teams,
        }
    return result


def beach_ranking(gender: str, url: str) -> dict:
    html = fetch(url); parser = TableParser(); parser.feed(html)
    tables = [table for table in parser.tables if table and table[0][:5] == ["Rank", "Nation", "Team", "Played", "Points"]]
    if not tables: raise RuntimeError(f"Tabela BeachUp {gender} não encontrada.")
    teams = []
    for row in tables[0][1:]:
        if len(row) < 5 or not row[0].isdigit(): continue
        teams.append({"rank":int(row[0]), "country_code":row[1][:3].upper(), "name":row[2], "played":int(row[3] or 0), "points":float(row[4])})
    if len(teams) < 50: raise RuntimeError(f"Ranking BeachUp {gender} incompleto: {len(teams)} duplas.")
    match = re.search(r"Last updated:.{0,80}?(\d{4}-\d{2}-\d{2})", html, re.I | re.S)
    updated = (match.group(1) + "T00:00:00+00:00") if match else datetime.now(timezone.utc).isoformat()
    return {"version":"1.0", "type":"beach_ranking", "gender":gender, "source":"BeachUp", "source_url":url, "updated_at":updated, "teams":teams}


def write_valid(name: str, data: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / name; temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(f"{name}: {len(data['teams'])} registros")


def main() -> int:
    try:
        indoor = wikipedia_rankings()
        beach = {gender: beach_ranking(gender, url) for gender, url in BEACH_URLS.items()}
        write_valid("male.json", indoor["male"]); write_valid("female.json", indoor["female"])
        write_valid("beach-male.json", beach["male"]); write_valid("beach-female.json", beach["female"])
        return 0
    except Exception as error:
        print(f"::error::{error}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
