"""Almacén local en JSON: nichos + 'seleccionados' (shortlist) por nicho.

Guarda en data/store.json para que sobreviva reinicios.
"""
from __future__ import annotations

import json
import pathlib
import threading

_LOCK = threading.Lock()
_DEFAULT = {"niches": ["Inteligencia Artificial"], "shortlist": {}}


class Store:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(_DEFAULT)

    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            d.setdefault("niches", ["Inteligencia Artificial"])
            d.setdefault("shortlist", {})
            return d
        except Exception:
            return dict(_DEFAULT)

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def niches(self) -> list:
        return self._read().get("niches", [])

    def add_niche(self, name: str) -> list:
        name = (name or "").strip()
        with _LOCK:
            d = self._read()
            if name and name not in d["niches"]:
                d["niches"].append(name)
                self._write(d)
        return self.niches()

    def shortlist(self, niche: str) -> list:
        return self._read().get("shortlist", {}).get(niche, [])

    def add_item(self, niche: str, ad: dict) -> list:
        with _LOCK:
            d = self._read()
            sl = d.setdefault("shortlist", {}).setdefault(niche, [])
            lid = str(ad.get("library_id"))
            if not any(str(x.get("library_id")) == lid for x in sl):
                sl.insert(0, ad)
                self._write(d)
        return self.shortlist(niche)

    def remove_item(self, niche: str, library_id: str) -> list:
        with _LOCK:
            d = self._read()
            sl = d.setdefault("shortlist", {}).get(niche, [])
            d["shortlist"][niche] = [x for x in sl if str(x.get("library_id")) != str(library_id)]
            self._write(d)
        return self.shortlist(niche)

    # ----- resultados scrapeados (caché por nicho, para que no se pierdan) -----
    def results(self, niche: str) -> list:
        return self._read().get("results", {}).get(niche, {}).get("ads", [])

    def results_query(self, niche: str) -> str:
        return self._read().get("results", {}).get(niche, {}).get("query", "")

    def merge_results(self, niche: str, ads: list, query: str = "") -> list:
        """Mezcla anuncios nuevos con el pool del nicho (nuevos primero, sin duplicar)."""
        with _LOCK:
            d = self._read()
            r = d.setdefault("results", {}).setdefault(niche, {"ads": [], "query": ""})
            by_id = {}
            for a in list(ads) + r.get("ads", []):  # nuevos primero
                lid = str(a.get("library_id"))
                if lid and lid not in by_id:
                    by_id[lid] = a
            r["ads"] = list(by_id.values())[:500]
            if query:
                r["query"] = query
            self._write(d)
        return self.results(niche)

    def clear_results(self, niche: str) -> list:
        with _LOCK:
            d = self._read()
            if niche in d.get("results", {}):
                d["results"][niche] = {"ads": [], "query": ""}
                self._write(d)
        return []

    # ----- cuándo se scrapeó cada término (para el aviso de cooldown) -----
    def scraped_at(self, niche: str) -> dict:
        return self._read().get("scraped_at", {}).get(niche, {})

    def set_scraped(self, niche: str, term: str, iso: str) -> None:
        with _LOCK:
            d = self._read()
            d.setdefault("scraped_at", {}).setdefault(niche, {})[term] = iso
            self._write(d)
