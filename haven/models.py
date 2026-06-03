from datetime import date

from pydantic import BaseModel, Field


class Nabo(BaseModel):
    plante_id: str
    note:      str | None = None


class Naboer(BaseModel):
    gode:     list[Nabo] = []
    dårlige:  list[Nabo] = []


class Skadedyr(BaseModel):
    id:          str
    navn:        str
    beskrivelse: str | None = None
    forebyggelse: str | None = None
    familier:    list[str] = []


class FotoModel(BaseModel):
    fil:       str
    kilde:     str | None = None
    url:       str | None = None
    licens:    str | None = None
    forfatter: str | None = None


class Plante(BaseModel):
    id:          str
    navn:        str
    sort:        str | None = None
    latin:       str | None = Field(None, json_schema_extra={"kilde": "wikidata", "prop": "P225"})
    familie:     str | None = Field(None, json_schema_extra={"kilde": "wikidata", "prop": "P171"})
    wikidata:    str | None = Field(None, json_schema_extra={"kilde": "wizard"})
    farve:       str | None = None
    placering:   str | None = None
    afstand:     int | str | None = None
    rækkeafstand: int | str | None = None
    sådybde:     float | None = None
    indendørs:   int | None = Field(None, ge=1, le=12)
    udplantning: int | None = Field(None, ge=1, le=12)
    direkte:     int | None = Field(None, ge=1, le=12)
    høst_fra:    int | None = Field(None, ge=1, le=12)
    høst_til:    int | None = Field(None, ge=1, le=12)
    noter:       str | None = None
    pasning:     str | None = None
    foto:        FotoModel | None = None
    naboer:      Naboer | None = None
    skadedyr_ids: list[str] = []


class Høne(BaseModel):
    id:          str
    navn:        str | None = None
    race:        str | None = None
    farve:       str | None = None
    fødselsdato: str | date | None = None
    aktiv:       bool = True
    noter:       str | None = None
    foto:        FotoModel | None = None
