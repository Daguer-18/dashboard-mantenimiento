"""
limpieza.py — Depuración de datos de OT, cálculo de KPIs y confiabilidad con censura
=====================================================================================
Uso:
    python limpieza.py ruta_al_archivo.csv|.xlsx  [--capacidad 288] [--tolerancia 3]

Genera en ./salida/:
    OT_depuradas.csv         base limpia con la categoría de cada registro
    bitacora_limpieza.csv    trazabilidad: qué regla se aplicó a cada OT y por qué
    kpis_por_equipo.csv      MTBF, MTTR, Ao, nº fallas por equipo
    weibull_por_tipo.csv     beta, eta (MLE con censura a la derecha)
    resumen.md               cifras listas para la memoria y el informe ejecutivo

IMPORTANTE: si el archivo del docente usa otros nombres de columna, edita
COLUMNAS (abajo). La clave es el nombre interno; el valor, el nombre en tu archivo.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gamma

# ------------------------------------------------------------------ CONFIG
COLUMNAS = {
    "ot": "OT_ID",
    "equipo": "Equipo_ID",
    "tipo_equipo": "Tipo_Equipo",
    "subsistema": "Subsistema",
    "criticidad": "Criticidad",
    "especialidad": "Especialidad",
    "tipo_ot": "Tipo_OT",
    "f_reporte": "Fecha_Reporte",
    "t_inicio": "Fecha_Inicio_Paro",
    "t_fin": "Fecha_Fin_Paro",
    "f_programada": "Fecha_Programada",
    "descripcion": "Descripcion_Operador",
    "modo": "Modo_Falla",
    "causa": "Causa_Raiz",
    "hh": "HH_Reportadas",
    "paro_prod": "Horas_Paro_Produccion",   # tiempo de paro según bitácora de producción/SCADA
    "espera_rep": "Horas_Espera_Repuesto",
    "hh_estimadas": "Horas_Estimadas",
    "costo_rep": "Costo_Repuestos_PEN",
    "costo_hh": "Costo_HH_PEN",
    "estado": "Estado",
}

LIMITE_MENSUAL_H = 720          # una parada no puede superar las horas de un mes
TOL_DISCREPANCIA_REL = 0.5      # |OT − producción| > 50 % ...
TOL_DISCREPANCIA_ABS = 2.0      # ... y > 2 h  -> se concilia con producción
ESTADOS_ABIERTOS = {"ABIERTA", "EN ESPERA DE REPUESTO", "EN PROCESO", "PENDIENTE"}

# Taxonomía ISO 14224 (modos de falla usados en el estudio)
MODOS_ISO = {
    "ELP": "Fuga externa de fluido de proceso",
    "VIB": "Vibración",
    "LOO": "Bajo caudal / presión",
    "OHE": "Sobrecalentamiento",
    "FTS": "Falla al arrancar",
    "UST": "Parada espuria",
    "BRD": "Ruptura / rotura (breakdown)",
    "ERO": "Lectura errónea",
    "NOO": "Sin señal de salida",
    # modos adicionales (equipos de manejo de sólidos: planta cementera)
    "STD": "Deficiencia estructural / desgaste",
    "PLU": "Atoro / obstrucción",
    "ELU": "Fuga externa de fluido de servicio (aceite)",
    "AIR": "Lectura anormal de instrumento",
    "NOI": "Ruido anormal",
    "UNK": "No determinado",
}
# Reglas de reclasificación: palabra clave en la CAUSA RAÍZ (prioridad) -> modo
CAUSA_A_MODO = [
    (r"sello", "ELP"),
    # --- manejo de sólidos (cementera); van antes que las reglas genéricas
    (r"atoro|obstrucci", "PLU"), (r"hidr[aá]ulic|aceite", "ELU"),
    (r"celda de carga|descalibra|encoder", "AIR"),
    (r"rotura de banda|empalme|rotura de cadena|rotura de resorte|fisura", "BRD"),
    (r"blindaje|martillo|barras|malla|revestimiento|cangil|rastra", "STD"),
    (r"pull.?cord|fin de carrera|sensor de desalineamiento", "UST"),
    (r"aislamiento del motor|arrancador|portacable|contactor", "FTS"),
    (r"lubricaci|reductor", "OHE"), (r"rodamiento|grasa|desalineamiento|acople", "VIB"),
    (r"impulsor|cavitaci", "LOO"), (r"rodete|s[oó]lidos|ventilador|polvo|disipador", "OHE"),
    (r"devanado|igbt", "FTS"), (r"bus dc|transitorio", "UST"),
    (r"descargas parciales|aislamiento", "BRD"),
    (r"calibraci|deriva", "ERO"), (r"humedad|conexi", "NOO"),
]
# ... y si no hay causa, en el TEXTO del operador, solo si NO es ambiguo
TEXTO_A_MODO = [
    (r"atorad|atoro|atascad|tapad", "PLU"), (r"aceite|hidr[aá]ulic", "ELU"),
    (r"banda rota|se rompi[oó] la (faja|banda)|cadena rota", "BRD"),
    (r"b[aá]scula marca mal|pesaje", "AIR"), (r"ruido|golpeteo", "NOI"),
    (r"fuga|gotea", "ELP"), (r"vibra|ruido en rodamiento", "VIB"),
    (r"no levanta|bajo caudal|no bombea", "LOO"), (r"temperatura|calentamiento", "OHE"),
    (r"se apag[oó] solo|alarma en variador", "UST"), (r"marca mal|lectura", "ERO"),
    (r"no marca|sin se[ñn]al", "NOO"),
]
MODO_A_ESPECIALIDAD = {"ELP": "Mecánica", "VIB": "Mecánica", "LOO": "Mecánica", "OHE": None,
                       "FTS": "Eléctrica", "UST": "Eléctrica", "BRD": None,
                       "ERO": "Instrumentación", "NOO": "Instrumentación",
                       "STD": "Mecánica", "PLU": "Mecánica", "ELU": "Mecánica", "AIR": "Instrumentación", "NOI": None}


# ------------------------------------------------------------------ CARGA
def cargar(ruta: str | Path) -> pd.DataFrame:
    ruta = Path(ruta)
    if ruta.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(ruta)
    else:
        df = pd.read_csv(ruta, encoding="utf-8-sig", sep=None, engine="python")
    inv = {v: k for k, v in COLUMNAS.items()}
    faltan = [v for k, v in COLUMNAS.items() if v not in df.columns and k in ("ot", "equipo", "tipo_ot", "t_inicio", "t_fin")]
    if faltan:
        raise ValueError(f"Columnas obligatorias no encontradas: {faltan}. Edita COLUMNAS en limpieza.py")
    return df.rename(columns=inv)


def _norm_id(s):
    if pd.isna(s):
        return s
    s = str(s).strip().upper().replace("_", "-").replace(" ", "")
    m = re.fullmatch(r"(\d{3})-?([A-Z]{2,4})-?(\d{1,2})", s)   # TAG tipo 110-TOL-01
    if m:
        return f"{m.group(1)}-{m.group(2)}-{int(m.group(3)):02d}"
    m = re.fullmatch(r"([A-Z]+)-?(\d+)", s)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else s


# --------------------------------------------------------------- LIMPIEZA
def depurar(df_raw: pd.DataFrame):
    """Devuelve (df_depurado, bitacora). No elimina filas: las marca."""
    df = df_raw.copy()
    log = []

    def anotar(i, regla, accion, antes="", despues=""):
        log.append(dict(OT_ID=df.at[i, "ot"], Regla=regla, Accion=accion,
                        Valor_antes=antes, Valor_despues=despues))

    for c in ("f_reporte", "t_inicio", "t_fin", "f_programada"):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce", dayfirst=False)
    for c in ("hh", "paro_prod", "espera_rep", "hh_estimadas", "costo_rep", "costo_hh"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        else:
            df[c] = np.nan

    df["Categoria"] = "Cerrado limpio"
    df["Usar_TTR"] = True        # entra al cálculo de MTTR / indisponibilidad
    df["Usar_Evento"] = True     # el evento de falla cuenta para MTBF / Weibull
    df["Motivo"] = ""

    # R0 — Normalización de texto e IDs
    ids0 = df["equipo"].copy()
    df["equipo"] = df["equipo"].map(_norm_id)
    for i in df.index[ids0.astype(str) != df["equipo"].astype(str)]:
        anotar(i, "R0", "ID de equipo normalizado", ids0[i], df.at[i, "equipo"])
    df["tipo_ot"] = df["tipo_ot"].astype(str).str.strip().str.capitalize()
    df["estado_n"] = df.get("estado", pd.Series("CERRADA", index=df.index)).astype(str).str.strip().str.upper()
    df["modo_original"] = df.get("modo", pd.Series(np.nan, index=df.index))
    df["modo"] = df["modo_original"].astype("string").str.strip().str.upper()
    # completar atributos maestros del equipo (si alguna fila los trae vacíos)
    for c in ("tipo_equipo", "subsistema", "criticidad"):
        if c in df:
            df[c] = df.groupby("equipo")[c].transform(lambda s: s.fillna(s.mode().iat[0] if not s.mode().empty else np.nan))

    # R1 — Duplicados
    dup = df.duplicated(subset=[c for c in df.columns if c not in ("Categoria", "Usar_TTR", "Usar_Evento", "Motivo")], keep="first")
    for i in df.index[dup]:
        df.loc[i, ["Categoria", "Usar_TTR", "Usar_Evento", "Motivo"]] = ["Descartado", False, False, "Registro duplicado"]
        anotar(i, "R1", "Descartado: OT duplicada")

    # R2 — OTs abiertas: incompletas (censuradas en su tiempo de reparación)
    abiertas = df["estado_n"].isin(ESTADOS_ABIERTOS) | (df["t_fin"].isna() & df["t_inicio"].notna())
    for i in df.index[abiertas & ~dup]:
        df.loc[i, ["Categoria", "Usar_TTR", "Motivo"]] = ["Incompleto (OT abierta)", False, "Sin cierre al corte"]
        anotar(i, "R2", "Marcada como incompleta / backlog", df.at[i, "estado_n"])
    sin_inicio = df["t_inicio"].isna() & ~dup
    for i in df.index[sin_inicio]:
        df.loc[i, ["Categoria", "Usar_TTR", "Usar_Evento", "Motivo"]] = ["Descartado", False, False, "Sin fecha de inicio"]
        anotar(i, "R2", "Descartado: sin fecha de inicio")

    df["Dur_OT_h"] = (df["t_fin"] - df["t_inicio"]).dt.total_seconds() / 3600
    df["TTR_validado_h"] = df["Dur_OT_h"]
    activos = (df["Categoria"] == "Cerrado limpio")

    def corregir(i, valor, regla, accion):
        anotar(i, regla, accion, round(df.at[i, "Dur_OT_h"], 2), round(valor, 2))
        df.at[i, "TTR_validado_h"] = valor
        df.at[i, "Categoria"] = "Cerrado corregido"
        df.at[i, "Motivo"] = accion

    def descartar_tiempo(i, regla, accion):
        anotar(i, regla, accion, round(df.at[i, "Dur_OT_h"], 2))
        df.loc[i, ["Categoria", "Usar_TTR", "Motivo"]] = ["Descartado", False, accion]
        df.at[i, "TTR_validado_h"] = np.nan
        # la falla SÍ ocurrió (hay fecha de inicio): se conserva el evento para MTBF

    prod = df["paro_prod"]
    hay_prod = prod.notna()

    # R3 — Duraciones negativas o nulas
    neg = activos & (df["Dur_OT_h"] <= 0)
    for i in df.index[neg]:
        d = abs(df.at[i, "Dur_OT_h"])
        p = prod[i]
        if df["tipo_ot"][i] == "Predictivo" and d == 0:
            continue  # inspección en marcha: paro cero es válido
        if pd.notna(p) and p > 0 and abs(d - p) <= max(TOL_DISCREPANCIA_ABS, TOL_DISCREPANCIA_REL * p):
            df.at[i, "t_inicio"], df.at[i, "t_fin"] = df.at[i, "t_fin"], df.at[i, "t_inicio"]
            corregir(i, d, "R3", "Fechas inicio/fin invertidas: se intercambian (validado con producción)")
        elif pd.notna(p) and p > 0:
            corregir(i, p, "R3", "Duración negativa: imputada con bitácora de producción")
        else:
            descartar_tiempo(i, "R3", "Duración negativa sin respaldo: se aísla del cálculo de MTTR")

    # R4 — Duraciones absurdas (> 720 h) por olvido de cierre
    activos = df["Categoria"].isin(["Cerrado limpio"])
    absurda = activos & (df["Dur_OT_h"] > LIMITE_MENSUAL_H)
    for i in df.index[absurda]:
        if hay_prod[i] and prod[i] > 0:
            corregir(i, prod[i], "R4", f"Duración > {LIMITE_MENSUAL_H} h (olvido de cierre): imputada con producción")
        else:
            descartar_tiempo(i, "R4", f"Duración > {LIMITE_MENSUAL_H} h sin respaldo: se aísla del cálculo de MTTR")

    # R5 — Discrepancia OT vs paro real del proceso
    activos = df["Categoria"].isin(["Cerrado limpio"])
    diff = (df["Dur_OT_h"] - prod).abs()
    discrep = activos & hay_prod & (diff > np.maximum(TOL_DISCREPANCIA_ABS, TOL_DISCREPANCIA_REL * prod))
    for i in df.index[discrep]:
        corregir(i, prod[i], "R5", "Discrepancia OT vs. producción: se adopta el paro registrado por producción")

    # R6 — Outliers por IQR (por tipo de equipo, solo correctivas) -> investigar, no borrar a ciegas
    df["Outlier_IQR"] = False
    corr_ok = (df["tipo_ot"] == "Correctivo") & df["Usar_TTR"]
    for tipo, g in df[corr_ok].groupby("tipo_equipo"):
        q1, q3 = g["TTR_validado_h"].quantile([.25, .75])
        lim = q3 + 1.5 * (q3 - q1)
        for i in g.index[g["TTR_validado_h"] > lim]:
            df.at[i, "Outlier_IQR"] = True
            esp = df.at[i, "espera_rep"]
            if pd.notna(esp) and esp > 0:
                anotar(i, "R6", f"Outlier IQR (> {lim:.1f} h) JUSTIFICADO: {esp:.0f} h de espera de repuesto — se conserva",
                       round(df.at[i, "TTR_validado_h"], 2))
            elif hay_prod[i]:
                anotar(i, "R6", f"Outlier IQR (> {lim:.1f} h) confirmado por producción — se conserva",
                       round(df.at[i, "TTR_validado_h"], 2))
            else:
                descartar_tiempo(i, "R6", f"Outlier IQR (> {lim:.1f} h) sin justificación: se aísla")

    # R7 — Reclasificación del modo de falla (taxonomía ISO 14224)
    df["Modo_ISO"] = np.where(df["tipo_ot"] == "Correctivo", df["modo"], pd.NA)
    df["Modo_reclasificado"] = False
    for i in df.index[(df["tipo_ot"] == "Correctivo") & df["Usar_Evento"]]:
        actual = df.at[i, "modo"]
        actual = None if pd.isna(actual) else actual
        causa = str(df.at[i, "causa"]) if pd.notna(df.at[i, "causa"]) else ""
        texto = str(df.at[i, "descripcion"]) if pd.notna(df.at[i, "descripcion"]) else ""
        por_causa = next((m for pat, m in CAUSA_A_MODO if re.search(pat, causa, re.I)), None)
        nuevo = None
        if actual in MODOS_ISO and actual != "UNK":
            # código válido, pero ¿contradice a la causa raíz? (p.ej. 'eléctrico' con causa mecánica)
            if por_causa and por_causa != actual and MODO_A_ESPECIALIDAD.get(actual) not in (None, MODO_A_ESPECIALIDAD.get(por_causa)):
                nuevo = por_causa
        else:
            nuevo = por_causa or next((m for pat, m in TEXTO_A_MODO if re.search(pat, texto, re.I)), None) or "UNK"
        if nuevo and nuevo != actual:
            df.at[i, "Modo_ISO"] = nuevo
            df.at[i, "Modo_reclasificado"] = True
            fuente = "causa raíz" if por_causa == nuevo else ("texto del operador" if nuevo != "UNK" else "sin información suficiente")
            anotar(i, "R7", f"Modo de falla reclasificado según {fuente}",
                   f"{df.at[i, 'modo_original']} | '{texto}'", f"{nuevo} - {MODOS_ISO[nuevo]}")
            if df.at[i, "Categoria"] == "Cerrado limpio":
                df.at[i, "Categoria"] = "Cerrado corregido"
                df.at[i, "Motivo"] = "Modo de falla reclasificado"
    df["Modo_ISO_desc"] = df["Modo_ISO"].map(lambda m: f"{m} - {MODOS_ISO[m]}" if m in MODOS_ISO else pd.NA)

    bit = pd.DataFrame(log, columns=["OT_ID", "Regla", "Accion", "Valor_antes", "Valor_despues"])
    bit[["Valor_antes", "Valor_despues"]] = bit[["Valor_antes", "Valor_despues"]].astype(str)
    return df, bit


# ------------------------------------------------------------------ KPIs
def periodo(df):
    ini = df["t_inicio"].min().normalize().replace(day=1)
    fin = df["t_inicio"].max().ceil("D")  # corte del estudio = último evento registrado
    return ini, fin


def kpis_por_equipo(df, ini=None, fin=None, frac_operacion=1.0):
    """frac_operacion = horas planificadas de operación / horas calendario
    (1.0 = operación continua 24/7; p.ej. 8200/8760 si la planta planifica 8,200 h/año)."""
    if ini is None:
        ini, fin = periodo(df)
    horas_cal = (fin - ini).total_seconds() / 3600 * frac_operacion
    base = df[df["Categoria"] != "Descartado"].copy()
    ttr_ok = df[df["Usar_TTR"]]
    filas = []
    for eq, g in df[df["Usar_Evento"] | df["Usar_TTR"]].groupby("equipo"):
        corr_ev = g[(g["tipo_ot"] == "Correctivo") & g["Usar_Evento"]]
        gt = ttr_ok[ttr_ok["equipo"] == eq]
        ttr_corr = gt.loc[gt["tipo_ot"] == "Correctivo", "TTR_validado_h"]
        paro_prev = gt.loc[gt["tipo_ot"] == "Preventivo", "TTR_validado_h"].sum()
        # paro correctivo: TTR medido + (n_eventos sin TTR válido)×MTTR del equipo (no se pierde indisponibilidad)
        mttr = ttr_corr.mean() if len(ttr_corr) else np.nan
        faltantes = len(corr_ev) - len(ttr_corr)
        paro_corr = ttr_corr.sum() + (faltantes * mttr if pd.notna(mttr) else 0)
        down = paro_corr + paro_prev
        up = horas_cal - down
        n_f = len(corr_ev)
        n_int = n_f + (gt["tipo_ot"] == "Preventivo").sum()
        mtbm = up / n_int if n_int else np.nan
        mdt = down / n_int if n_int else np.nan
        meta = g.iloc[0]
        filas.append(dict(
            Equipo=eq, Tipo=meta["tipo_equipo"], Subsistema=meta["subsistema"], Criticidad=meta["criticidad"],
            N_fallas=n_f, Horas_operativas=round(up, 1), Horas_paro_correctivo=round(paro_corr, 1),
            Horas_paro_preventivo=round(paro_prev, 1),
            MTBF_h=round(up / n_f, 1) if n_f else np.nan,
            MTBF_censurado=n_f == 0,
            MTTR_h=round(mttr, 2) if pd.notna(mttr) else np.nan,
            Espera_repuesto_media_h=round(gt.loc[gt["tipo_ot"] == "Correctivo", "espera_rep"].mean(), 2) if len(ttr_corr) else np.nan,
            Ao_pct=round(100 * mtbm / (mtbm + mdt), 2) if n_int else 100.0,
        ))
    return pd.DataFrame(filas).sort_values(["Criticidad", "Equipo"])


def adherencia(df, tolerancia_dias=3, corte=None):
    p = df[(df["tipo_ot"] == "Preventivo") & df["f_programada"].notna() & (df["Categoria"] != "Descartado")]
    if corte is not None:
        p = p[p["f_programada"] <= corte]
    if p.empty:
        return np.nan, 0, 0
    a_tiempo = p["t_inicio"].notna() & (p["t_inicio"] <= p["f_programada"] + pd.Timedelta(days=tolerancia_dias + 1))
    return 100 * a_tiempo.mean(), int(a_tiempo.sum()), len(p)


def backlog(df, capacidad_semanal_hh):
    ab = df[df["Categoria"] == "Incompleto (OT abierta)"]
    hh = ab["hh_estimadas"].fillna(ab["hh"]).sum()
    return hh / capacidad_semanal_hh, hh, len(ab)


def costos(df):
    d = df[df["Categoria"] != "Descartado"].copy()
    d["costo_total"] = d["costo_rep"].fillna(0) + d["costo_hh"].fillna(0)
    c = d.groupby("tipo_ot")["costo_total"].sum()
    return c.get("Correctivo", 0.0), c.get("Preventivo", 0.0) + c.get("Predictivo", 0.0)


# ------------------------------------------------------ CONFIABILIDAD
def tiempos_vida(df, ini, fin, agrupar="tipo_equipo"):
    """Tiempos entre fallas (TBF) por equipo + suspensión final (censura a la derecha).
    Supuesto: reparación 'tan buena como nueva' y equipo en t=0 al inicio del estudio."""
    filas = []
    ev = df[(df["tipo_ot"] == "Correctivo") & df["Usar_Evento"]]
    equipos = df.drop_duplicates("equipo")[["equipo", agrupar]]
    for _, row in equipos.iterrows():
        eq = row["equipo"]
        g = ev[ev["equipo"] == eq].sort_values("t_inicio")
        t_prev = ini
        for _, r in g.iterrows():
            filas.append(dict(equipo=eq, grupo=row[agrupar], t=(r["t_inicio"] - t_prev).total_seconds() / 3600, falla=1))
            ttr = r["TTR_validado_h"] if pd.notna(r["TTR_validado_h"]) else 0
            t_prev = r["t_inicio"] + pd.Timedelta(hours=float(ttr))
        filas.append(dict(equipo=eq, grupo=row[agrupar], t=(fin - t_prev).total_seconds() / 3600, falla=0))
    out = pd.DataFrame(filas)
    return out[out["t"] > 0]


def weibull_mle(t, falla):
    """MLE Weibull 2P con censura a la derecha: L = Π f(t_i) · Π R(t_j)."""
    t, d = np.asarray(t, float), np.asarray(falla, int)
    if d.sum() < 2:
        return np.nan, np.nan

    def nll(p):
        b, e = np.exp(p)
        z = (t / e) ** b
        return -(np.sum(d * (np.log(b) - np.log(e) + (b - 1) * np.log(t / e))) - np.sum(z))
    x0 = [0.0, np.log(t.sum() / d.sum())]
    r = minimize(nll, x0, method="Nelder-Mead", options=dict(xatol=1e-6, fatol=1e-8, maxiter=4000))
    return tuple(np.exp(r.x))


def kaplan_meier(t, falla):
    d = pd.DataFrame({"t": t, "e": falla}).sort_values("t")
    tiempos = np.sort(d.loc[d.e == 1, "t"].unique())
    S, out = 1.0, [(0.0, 1.0)]
    for ti in tiempos:
        n_riesgo = (d.t >= ti).sum()
        n_fallas = ((d.t == ti) & (d.e == 1)).sum()
        S *= 1 - n_fallas / n_riesgo
        out.append((ti, S))
    return pd.DataFrame(out, columns=["t", "S"])


def tabla_weibull(vida):
    filas = []
    for gname, g in vida.groupby("grupo"):
        b, e = weibull_mle(g["t"], g["falla"])
        filas.append(dict(Grupo=gname, N_fallas=int(g["falla"].sum()), N_suspensiones=int((g["falla"] == 0).sum()),
                          beta=round(b, 3) if pd.notna(b) else np.nan, eta_h=round(e, 1) if pd.notna(e) else np.nan,
                          MTTF_h=round(e * gamma(1 + 1 / b), 1) if pd.notna(b) else np.nan,
                          Interpretacion=("Fallas por desgaste (β>1): mantenimiento preventivo por tiempo eficaz" if b > 1.2 else
                                          "Fallas aleatorias (β≈1): priorizar predictivo/condición" if b >= 0.8 else
                                          "Mortalidad infantil (β<1): revisar montaje/calidad de repuestos") if pd.notna(b)
                          else "Sin fallas suficientes: equipo censurado (solo cota inferior de vida)"))
    return pd.DataFrame(filas)


# ------------------------------------------------------------ RESUMEN
def resumen_calidad(df):
    n = len(df)
    c = df["Categoria"].value_counts()
    return pd.DataFrame({"Registros": c, "Porcentaje": (100 * c / n).round(1)})


def diagnostico(k):
    sub = k.groupby("Subsistema").agg(Horas_paro=("Horas_paro_correctivo", "sum"), Fallas=("N_fallas", "sum"),
                                      Horas_op=("Horas_operativas", "sum")).sort_values("Horas_paro", ascending=False)
    sub["MTBF_h"] = (sub["Horas_op"] / sub["Fallas"].replace(0, np.nan)).round(0)
    sub["MTTR_h"] = (sub["Horas_paro"] / sub["Fallas"].replace(0, np.nan)).round(1)
    sub["Pct_paro_total"] = (100 * sub["Horas_paro"] / sub["Horas_paro"].sum()).round(1)
    return sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archivo")
    ap.add_argument("--capacidad", type=float, default=288, help="HH disponibles por semana (p.ej. 6 técnicos × 48 h)")
    ap.add_argument("--tolerancia", type=int, default=3, help="días de tolerancia para considerar una preventiva 'a tiempo'")
    a = ap.parse_args()

    raw = cargar(a.archivo)
    df, bit = depurar(raw)
    ini, fin = periodo(df)
    k = kpis_por_equipo(df, ini, fin)
    vida = tiempos_vida(df, ini, fin, agrupar="subsistema")
    wb = tabla_weibull(vida)
    adh, ok, tot = adherencia(df, a.tolerancia, fin)
    bl_sem, bl_hh, bl_n = backlog(df, a.capacidad)
    cc, cp = costos(df)
    calidad = resumen_calidad(df)
    diag = diagnostico(k)

    out = Path("salida"); out.mkdir(exist_ok=True)
    df.rename(columns=COLUMNAS).to_csv(out / "OT_depuradas.csv", index=False, encoding="utf-8-sig")
    bit.to_csv(out / "bitacora_limpieza.csv", index=False, encoding="utf-8-sig")
    k.to_csv(out / "kpis_por_equipo.csv", index=False, encoding="utf-8-sig")
    wb.to_csv(out / "weibull_por_tipo.csv", index=False, encoding="utf-8-sig")

    reglas = bit.groupby("Regla").size().rename("OT afectadas")
    pareto = (df[(df["tipo_ot"] == "Correctivo") & df["Usar_Evento"] & (df["criticidad"] == "A")]
              .groupby("Modo_ISO_desc").agg(Fallas=("ot", "size"), Horas_paro=("TTR_validado_h", "sum"))
              .sort_values("Horas_paro", ascending=False))
    pareto["Pct_acum_horas"] = (100 * pareto["Horas_paro"].cumsum() / pareto["Horas_paro"].sum()).round(1)
    sin_fallas = k.loc[k["MTBF_censurado"], "Equipo"].tolist()

    md = [f"# Resumen automático — {Path(a.archivo).name}",
          f"Periodo analizado: {ini:%d/%m/%Y} – {fin:%d/%m/%Y} ({(fin-ini).total_seconds()/3600:,.0f} h calendario)\n",
          "## 1. Calidad de datos (para la memoria de limpieza)", calidad.to_markdown(), "",
          "Reglas aplicadas (nº de OT afectadas):", reglas.to_markdown(), "",
          f"Equipos sin ninguna falla al corte (censura a la derecha, NO se descartan): {', '.join(sin_fallas) or 'ninguno'}",
          f"Suspensiones totales usadas en Weibull/Kaplan-Meier: {(vida['falla']==0).sum()}  |  Fallas: {int(vida['falla'].sum())}",
          f"Modos de falla reclasificados: {int(df['Modo_reclasificado'].sum())}  |  quedaron 'No determinado' (UNK): {int((df['Modo_ISO']=='UNK').sum())}\n",
          "## 2. KPIs globales",
          f"- Adherencia al preventivo: {adh:.1f} % ({ok}/{tot}, tolerancia {a.tolerancia} días)",
          f"- Backlog: {bl_hh:.0f} HH en {bl_n} OT abiertas = {bl_sem:.2f} semanas (capacidad {a.capacidad:.0f} HH/sem)",
          f"- Relación costo correctivo / preventivo: {cc/cp:.2f}  (correctivo S/ {cc:,.0f}; preventivo+predictivo S/ {cp:,.0f})",
          "", "## 3. KPIs por equipo", k.to_markdown(index=False), "",
          "## 4. Diagnóstico por subsistema (cuello de botella = mayor horas de paro correctivo)", diag.to_markdown(), "",
          "## 5. Pareto de modos de falla — equipos clase A", pareto.to_markdown(), "",
          "## 6. Weibull con censura (MLE) por subsistema", wb.to_markdown(index=False)]
    (out / "resumen.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:12]))
    print(f"\nArchivos escritos en {out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
