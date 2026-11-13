"""
Revisa backend/afiliaciones.json: valida el formato, resume el estado y lista las páginas con más inversión que aún
no están en el archivo.

Uso (desde la carpeta backend/):
    .\\.venv\\Scripts\\python.exe tools\\validar_afiliaciones.py                 # valida y resume
    .\\.venv\\Scripts\\python.exe tools\\validar_afiliaciones.py --faltantes 30   # además, las 30 páginas con más inversión sin registro
    .\\.venv\\Scripts\\python.exe tools\\validar_afiliaciones.py --faltantes 30 --agregar   # y las agrega como pendientes

Reglas del archivo:
- "verificado": true exige "afiliacion" y una "fuente" que sea una URL http(s).
- Una persona con varias páginas de Meta es UNA entrada: "page_id" (el principal) y "page_ids" (todos los ID, incluido el principal).
  Un ID no puede estar en dos entradas. Los nombres se comparan sin tildes (Muñoz = Munoz) y sin mayúsculas.
- Si la misma persona aparece con otro nombre (el pagador con su segundo nombre, otra grafía), ese nombre va en "otros_nombres" de la
  misma entrada; ningún nombre puede estar en dos entradas. En la web se hace marcando las entradas en Entidades y pulsando «Unificar».
- "partido": "Neutral" es un valor reservado para los medios (tipo «medio») que informan sin alinearse con un partido; otros medios
  sí lo están (p. ej. con el oficialismo). No es una organización: se pinta en gris y no se une a ningún partido. Se escribe así,
  con la inicial en mayúscula, y solo en entradas de tipo «medio». En la web: Entidades → Partido → «Neutral».
- Una entrada con afiliación pero sin verificar se muestra en la web como «sin verificar» (no como dato).
- Meta no publica afiliación: no la deduzcas del nombre ni del contenido de la página.
Sale con código 1 si encuentra errores de formato.
"""
import argparse
import json
import os
import re
import sys
import unicodedata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "afiliaciones.json")
SNAPSHOT = os.path.join(RAIZ, "data", "ads_snapshot.json")
TIPOS = {"partido", "candidato", "persona", "institucion", "medio", "agencia", "gobierno", "empresa", "otro"}


def norm(texto):
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def medio(rango):
    if not rango:
        return 0.0
    lo, hi = rango.get("min"), rango.get("max")
    return float(lo or 0) if hi is None else (float(hi or 0) if lo is None else (lo + hi) / 2.0)


def ids_de(e):
    """Todos los ID de página de una entrada: el principal («page_id») y los de «page_ids» (una persona puede tener varias páginas)."""
    extra = e.get("page_ids") if isinstance(e.get("page_ids"), list) else []
    ids = []
    for v in [e.get("page_id")] + extra:
        v = str(v).strip() if v not in (None, "") else ""
        if v and v not in ids:
            ids.append(v)
    return ids


def nombres_de(e):
    """Nombres normalizados de una entrada: el principal y los de «otros_nombres» (el pagador declarado, otra grafía, otra página…)."""
    extra = e.get("otros_nombres") if isinstance(e.get("otros_nombres"), list) else []
    nombres = []
    for v in [e.get("nombre")] + extra:
        n = norm(v)
        if n and n not in nombres:
            nombres.append(n)
    return nombres


def validar(entidades):
    errores, avisos, vistos, ids_vistos = [], [], {}, {}
    for i, e in enumerate(entidades, 1):
        nombre = e.get("nombre") or ""
        et = f"#{i} «{nombre or '(sin nombre)'}»"
        if not nombre:
            errores.append(f"{et}: falta «nombre».")
        if norm(nombre) in vistos:
            errores.append(f"{et}: nombre repetido (ya está en #{vistos[norm(nombre)]}; «Muñoz» y «Munoz» cuentan como el mismo nombre).")
        vistos[norm(nombre)] = i
        otros = e.get("otros_nombres")
        if otros is not None and (not isinstance(otros, list) or any(not isinstance(x, str) or not x.strip() for x in otros)):
            errores.append(f"{et}: «otros_nombres» debe ser una lista de nombres.")
        for n in nombres_de(e)[1:]:
            if vistos.get(n, i) != i:
                errores.append(f"{et}: el otro nombre «{n}» ya es de #{vistos[n]}.")
            else:
                vistos[n] = i
        ids_e = e.get("page_ids")
        if ids_e is not None and (not isinstance(ids_e, list) or any(not re.fullmatch(r"\d{1,40}", str(x).strip()) for x in ids_e)):
            errores.append(f"{et}: «page_ids» debe ser una lista de ID de página (solo dígitos).")
        for pid in ids_de(e):
            if pid in ids_vistos:
                errores.append(f"{et}: el ID de página {pid} ya está en #{ids_vistos[pid]}.")
            else:
                ids_vistos[pid] = i
        if e.get("tipo") is not None and e["tipo"] not in TIPOS:
            errores.append(f"{et}: «tipo» debe ser uno de {sorted(TIPOS)} (o null).")
        if e.get("partido") and norm(e["partido"]) == "neutral":
            if e["partido"] != "Neutral":
                errores.append(f"{et}: escribe el partido como «Neutral».")
            if e.get("tipo") != "medio":
                errores.append(f"{et}: «Neutral» solo se usa en medios (tipo «medio»).")
        fuente = e.get("fuente")
        if fuente and not re.match(r"^https?://\S+$", fuente):
            errores.append(f"{et}: «fuente» debe ser una URL http(s).")
        if e.get("verificado"):
            if not e.get("afiliacion"):
                errores.append(f"{et}: «verificado» es true pero falta «afiliacion».")
            if not fuente:
                errores.append(f"{et}: «verificado» es true pero falta «fuente».")
            if not e.get("actualizado"):
                avisos.append(f"{et}: agrega la fecha en «actualizado» (AAAA-MM-DD).")
        elif e.get("afiliacion") and not fuente:
            avisos.append(f"{et}: tiene afiliación sin fuente; se mostrará como «sin verificar».")
    return errores, avisos


def paginas_del_snapshot():
    try:
        with open(SNAPSHOT, encoding="utf-8") as f:
            ads = json.load(f).get("ads", [])
    except (OSError, ValueError):
        return []
    por_pagina = {}
    for a in ads:
        p = por_pagina.setdefault(a["page_name"], {"nombre": a["page_name"], "page_id": a.get("page_id"), "gasto": 0.0})
        p["gasto"] += medio(a.get("gasto"))
    return sorted(por_pagina.values(), key=lambda p: p["gasto"], reverse=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faltantes", type=int, default=0, metavar="N", help="lista las N páginas con más inversión sin registro")
    ap.add_argument("--agregar", action="store_true", help="agrega las páginas faltantes como entradas pendientes")
    args = ap.parse_args()

    with open(RUTA, encoding="utf-8") as f:
        datos = json.load(f)
    entidades = datos.get("entidades", [])
    errores, avisos = validar(entidades)

    verificadas = sum(1 for e in entidades if e.get("verificado") and e.get("afiliacion") and e.get("fuente"))
    pendientes = sum(1 for e in entidades if e.get("afiliacion") and not (e.get("verificado") and e.get("fuente")))
    vacias = len(entidades) - verificadas - pendientes
    print(f"{len(entidades)} entradas: {verificadas} verificadas, {pendientes} con afiliación sin verificar, {vacias} por completar.")
    for m in avisos:
        print("  aviso:", m)
    for m in errores:
        print("  ERROR:", m)

    if args.faltantes:
        conocidas = {n for e in entidades for n in nombres_de(e)} | {pid for e in entidades for pid in ids_de(e)}
        faltan = [p for p in paginas_del_snapshot() if norm(p["nombre"]) not in conocidas and str(p["page_id"]) not in conocidas]
        faltan = faltan[:args.faltantes]
        print(f"\nPáginas con más inversión sin registro ({len(faltan)}):")
        for p in faltan:
            print(f"  USD {p['gasto']:>7,.0f}  {p['nombre']}  (id {p['page_id']})")
        if args.agregar and faltan:
            for p in faltan:
                entidades.append({"nombre": p["nombre"], "page_id": p["page_id"], "tipo": None, "afiliacion": None,
                                  "fuente": None, "verificado": False, "actualizado": None})
            datos["entidades"] = entidades
            with open(RUTA, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            print(f"Agregadas {len(faltan)} entradas pendientes a afiliaciones.json.")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
