"""
generar_datos_prueba.py
-----------------------
Genera un dataset SINTÉTICO de 800 órdenes de trabajo (OT) para PROBAR el
pipeline de limpieza y el dashboard mientras el docente habilita el archivo real.

>>> NO es el dataset de la tarea. No entregar resultados basados en este archivo. <<<

Simula 2 años de operación (24/7) de una estación de bombeo con:
motobombas, variadores de frecuencia (VFD), transformadores secos e instrumentación,
e inyecta deliberadamente los 4 vicios descritos en el enunciado:
  1. Tiempos de reparación negativos o absurdos (olvido de cierre de OT)
  2. Equipos sin fallas al corte del estudio (censura a la derecha)
  3. Modos de falla mal etiquetados o ambiguos ("se quemó", "no arranca")
  4. Discrepancias entre las horas de la OT y el paro real del proceso
Además: IDs mal digitados ("mb-01", "MB01") y algunos duplicados.
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(14224)
INICIO = pd.Timestamp("2024-10-01 00:00")
CORTE = pd.Timestamp("2026-09-30 23:59")
HORAS_PERIODO = (CORTE - INICIO).total_seconds() / 3600

# ---------------------------------------------------------------- equipos
# (id, tipo, subsistema, criticidad, beta, eta_h, mediana_TTR_h, prob_espera_repuesto)
EQUIPOS = [
    ("MB-01", "Motobomba", "Bombeo principal", "A", 1.6, 1500, 5.0, 0.45),
    ("MB-02", "Motobomba", "Bombeo principal", "A", 1.6, 1400, 5.0, 0.45),
    ("MB-03", "Motobomba", "Bombeo principal", "A", 1.5, 1700, 5.0, 0.45),
    ("MB-04", "Motobomba", "Bombeo auxiliar", "B", 1.3, 3500, 4.0, 0.25),
    ("MB-05", "Motobomba", "Bombeo auxiliar", "B", 1.3, 3800, 4.0, 0.25),
    ("MB-06", "Motobomba", "Drenaje", "C", 1.2, 5000, 3.0, 0.10),
    ("VFD-01", "Variador de frecuencia", "Accionamiento", "A", 1.1, 3000, 3.0, 0.30),
    ("VFD-02", "Variador de frecuencia", "Accionamiento", "A", 1.1, 3200, 3.0, 0.30),
    ("VFD-03", "Variador de frecuencia", "Accionamiento", "B", 1.0, 6000, 2.5, 0.20),
    ("VFD-04", "Variador de frecuencia", "Accionamiento", "B", 1.0, 6500, 2.5, 0.20),
    ("TR-01", "Transformador seco", "Distribución eléctrica", "A", 2.5, 40000, 8.0, 0.30),
    ("TR-02", "Transformador seco", "Distribución eléctrica", "B", 2.5, 60000, 8.0, 0.30),
    ("TR-03", "Transformador seco", "Distribución eléctrica", "B", 2.5, 60000, 8.0, 0.30),
    ("PT-01", "Instrumentación", "Instrumentación de campo", "A", 0.9, 4500, 1.5, 0.10),
    ("FT-01", "Instrumentación", "Instrumentación de campo", "A", 0.9, 4000, 2.0, 0.15),
    ("LT-01", "Instrumentación", "Instrumentación de campo", "B", 0.9, 7000, 1.5, 0.10),
    ("PT-02", "Instrumentación", "Instrumentación de campo", "B", 0.9, 9000, 1.5, 0.10),
    ("TT-01", "Instrumentación", "Instrumentación de campo", "C", 0.9, 30000, 1.0, 0.05),
    ("FT-02", "Instrumentación", "Instrumentación de campo", "C", 0.9, 12000, 2.0, 0.10),
    ("AV-01", "Instrumentación", "Instrumentación de campo", "C", 0.9, 40000, 1.0, 0.05),
]

# Modos de falla reales (ISO 14224) por tipo: (codigo, descripcion, causa raíz, especialidad, peso)
MODOS = {
    "Motobomba": [
        ("ELP", "Fuga externa de fluido de proceso", "Desgaste de caras del sello mecánico", "Mecánica", 0.38),
        ("VIB", "Vibración", "Degradación de grasa en rodamientos", "Mecánica", 0.22),
        ("VIB", "Vibración", "Desalineamiento acople bomba-motor", "Mecánica", 0.10),
        ("LOO", "Bajo caudal / presión", "Desgaste de impulsor por cavitación", "Mecánica", 0.12),
        ("OHE", "Sobrecalentamiento", "Bloqueo de rodete por sólidos", "Mecánica", 0.08),
        ("FTS", "Falla al arrancar", "Falla de aislamiento del devanado", "Eléctrica", 0.10),
    ],
    "Variador de frecuencia": [
        ("UST", "Parada espuria", "Sobretensión en bus DC por transitorios de red", "Eléctrica", 0.40),
        ("OHE", "Sobrecalentamiento", "Ventilador de disipador obstruido", "Eléctrica", 0.35),
        ("FTS", "Falla al arrancar", "Módulo IGBT dañado", "Eléctrica", 0.25),
    ],
    "Transformador seco": [
        ("OHE", "Sobrecalentamiento", "Acumulación de polvo en ductos de ventilación", "Eléctrica", 0.6),
        ("BRD", "Ruptura / falla de aislamiento", "Descargas parciales en devanado", "Eléctrica", 0.4),
    ],
    "Instrumentación": [
        ("ERO", "Lectura errónea", "Deriva de calibración del transmisor", "Instrumentación", 0.55),
        ("NOO", "Sin señal de salida", "Humedad en caja de conexiones", "Instrumentación", 0.45),
    ],
}

# Textos libres que escribe el operador (algunos ambiguos o engañosos)
TEXTO_OPERADOR = {
    "ELP": ["Fuga por el sello", "gotea agua por la bomba", "se quemó", "no arranca, motor caliente"],
    "VIB": ["vibra mucho", "ruido en rodamiento", "falla eléctrica, disparó térmico", "suena raro"],
    "LOO": ["no levanta presión", "bajo caudal", "bomba no bombea"],
    "OHE": ["calentamiento", "se quemó", "disparó por temperatura", "falla eléctrica"],
    "FTS": ["no arranca", "se quemó", "no prende el motor"],
    "UST": ["se apagó solo", "falla eléctrica", "alarma en variador"],
    "BRD": ["olor a quemado", "se quemó", "disparo de protección"],
    "NOO": ["no marca", "sin señal", "instrumento malogrado"],
    "ERO": ["marca mal", "lectura rara", "instrumento malogrado"],
}
AMBIGUOS = {"se quemó", "no arranca", "falla eléctrica", "falla eléctrica, disparó térmico",
            "no arranca, motor caliente", "suena raro", "instrumento malogrado", "no prende el motor"}

COSTO_HH = 45.0  # PEN por hora-hombre (supuesto)
ESCALA = {"Motobomba": 0.45, "Variador de frecuencia": 0.5, "Instrumentación": 0.5}  # ajusta la tasa de fallas


def fecha(ts):
    return ts.round("min")


registros = []

# ------------------------------------------------------- OTs correctivas
for eid, tipo, sub, crit, beta, eta, ttr_med, p_rep in EQUIPOS:
    t = 0.0
    while True:
        t += eta * ESCALA.get(tipo, 1.0) * rng.weibull(beta)
        if t >= HORAS_PERIODO:
            break
        modos = MODOS[tipo]
        pesos = np.array([m[4] for m in modos]); pesos /= pesos.sum()
        cod, desc, causa, esp, _ = modos[rng.choice(len(modos), p=pesos)]
        t_ini = INICIO + pd.Timedelta(hours=t)
        reparacion = rng.lognormal(np.log(ttr_med), 0.5)
        espera = rng.uniform(8, 72) if rng.random() < p_rep else 0.0  # espera de repuesto
        respuesta = rng.uniform(0.25, 1.5)
        paro_real = respuesta + espera + reparacion
        t_fin = t_ini + pd.Timedelta(hours=paro_real)
        tecnicos = int(rng.choice([1, 2, 2, 3]))
        registros.append(dict(
            Equipo_ID=eid, Tipo_Equipo=tipo, Subsistema=sub, Criticidad=crit,
            Especialidad=esp, Tipo_OT="Correctivo",
            Fecha_Reporte=fecha(t_ini), Fecha_Inicio_Paro=fecha(t_ini), Fecha_Fin_Paro=fecha(t_fin),
            Fecha_Programada=pd.NaT,
            Descripcion_Operador=rng.choice(TEXTO_OPERADOR[cod]),
            Modo_Falla=cod, Causa_Raiz=causa,
            HH_Reportadas=round(reparacion * tecnicos, 1),
            Horas_Paro_Produccion=round(paro_real, 2),
            Horas_Espera_Repuesto=round(espera, 1),
            Horas_Estimadas=round(reparacion * tecnicos, 1),
            Costo_Repuestos_PEN=round(rng.uniform(300, 4500) if cod in ("ELP", "VIB", "LOO", "FTS", "BRD") else rng.uniform(50, 800), 0),
            Estado="Cerrada",
        ))
        t += paro_real

# ------------------------------------------- OTs preventivas / predictivas
FREC_PREV = {"A": 15, "B": 30, "C": 60}  # días (A: quincenal)
for eid, tipo, sub, crit, *_ in EQUIPOS:
    esp = {"Motobomba": "Mecánica", "Instrumentación": "Instrumentación"}.get(tipo, "Eléctrica")
    d = FREC_PREV[crit]
    prog = INICIO + pd.Timedelta(days=int(rng.integers(3, d)))
    while prog < CORTE:
        es_pred = rng.random() < 0.2 and tipo != "Instrumentación"
        retraso_dias = 0 if rng.random() < 0.72 else rng.integers(4, 25)  # ~28% fuera de plazo
        t_ini = prog + pd.Timedelta(days=int(retraso_dias), hours=8)
        if t_ini >= CORTE:  # ejecutada después del corte: queda fuera del estudio
            prog += pd.Timedelta(days=d); continue
        dur = rng.lognormal(np.log(2.0 if not es_pred else 0.75), 0.3)
        tecnicos = int(rng.choice([1, 2]))
        registros.append(dict(
            Equipo_ID=eid, Tipo_Equipo=tipo, Subsistema=sub, Criticidad=crit,
            Especialidad=esp if not es_pred else "Predictivo",
            Tipo_OT="Predictivo" if es_pred else "Preventivo",
            Fecha_Reporte=fecha(prog - pd.Timedelta(days=7)),
            Fecha_Inicio_Paro=fecha(t_ini), Fecha_Fin_Paro=fecha(t_ini + pd.Timedelta(hours=dur)),
            Fecha_Programada=fecha(prog),
            Descripcion_Operador="Rutina programada" if not es_pred else "Ruta de vibraciones / termografía",
            Modo_Falla=np.nan, Causa_Raiz=np.nan,
            HH_Reportadas=round(dur * tecnicos, 1),
            Horas_Paro_Produccion=round(dur, 2) if not es_pred else 0.0,
            Horas_Espera_Repuesto=0.0, Horas_Estimadas=round(dur * tecnicos, 1),
            Costo_Repuestos_PEN=round(rng.uniform(40, 350), 0), Estado="Cerrada",
        ))
        prog += pd.Timedelta(days=d)

df = pd.DataFrame(registros)
# Para el predictivo el paro de proceso es 0 (equipo en marcha) -> la OT no genera indisponibilidad
df.loc[df.Tipo_OT == "Predictivo", ["Fecha_Fin_Paro"]] = df.loc[df.Tipo_OT == "Predictivo", "Fecha_Inicio_Paro"]

# Recortar a 800 registros conservando todas las correctivas
corr = df[df.Tipo_OT == "Correctivo"]
resto = df[df.Tipo_OT != "Correctivo"]
n_resto = 800 - len(corr) - 6
resto = resto.sample(n=n_resto, random_state=1)
df = pd.concat([corr, resto]).sort_values("Fecha_Inicio_Paro").reset_index(drop=True)

# ---------------------------------------------------------------- VICIOS
n = len(df)
idx_corr = df.index[df.Tipo_OT == "Correctivo"].to_numpy()

# OTs abiertas al corte (últimas semanas): sin fecha de fin -> backlog
recientes = df.index[df.Fecha_Inicio_Paro > CORTE - pd.Timedelta(days=21)]
abiertas = rng.choice(recientes, size=min(18, len(recientes)), replace=False)
df.loc[abiertas, "Estado"] = rng.choice(["Abierta", "En espera de repuesto"], size=len(abiertas))
df.loc[abiertas, ["Fecha_Fin_Paro"]] = pd.NaT
df.loc[abiertas, ["HH_Reportadas", "Horas_Paro_Produccion"]] = np.nan

cand = np.setdiff1d(idx_corr, abiertas)

# Vicio 1a: duraciones negativas (fechas invertidas o año mal digitado)
neg = rng.choice(cand, 14, replace=False)
for i in neg[:9]:  # inversión inicio/fin
    a, b = df.at[i, "Fecha_Inicio_Paro"], df.at[i, "Fecha_Fin_Paro"]
    df.at[i, "Fecha_Inicio_Paro"], df.at[i, "Fecha_Fin_Paro"] = b, a
for i in neg[9:]:  # fin con un día anterior (error de digitación), sin registro de producción
    df.at[i, "Fecha_Fin_Paro"] = df.at[i, "Fecha_Inicio_Paro"] - pd.Timedelta(hours=float(rng.uniform(2, 30)))
    df.at[i, "Horas_Paro_Produccion"] = np.nan
cand = np.setdiff1d(cand, neg)

# Vicio 1b: olvido de cierre (paradas "eternas")
eternas = rng.choice(cand, 22, replace=False)
for k, i in enumerate(eternas):
    extra = rng.uniform(40, 90) if k < 14 else rng.uniform(750, 1600)
    df.at[i, "Fecha_Fin_Paro"] = df.at[i, "Fecha_Fin_Paro"] + pd.Timedelta(hours=float(extra))
    if k >= 19:  # sin respaldo en bitácora de producción -> insalvable
        df.at[i, "Horas_Paro_Produccion"] = np.nan
cand = np.setdiff1d(cand, eternas)

# Vicio 4: discrepancia OT vs paro real (horas OT infladas o subregistradas moderadamente)
disc = rng.choice(cand, 30, replace=False)
for i in disc:
    factor = rng.choice([0.3, 0.4, 2.0, 2.5, 3.0])
    real = df.at[i, "Horas_Paro_Produccion"]
    df.at[i, "Fecha_Fin_Paro"] = df.at[i, "Fecha_Inicio_Paro"] + pd.Timedelta(hours=float(real * factor))

# Vicio 3: modo de falla vacío / genérico cuando el texto es ambiguo, y mala codificación
for i in idx_corr:
    txt = df.at[i, "Descripcion_Operador"]
    if txt in AMBIGUOS:
        r = rng.random()
        if r < 0.45:
            df.at[i, "Modo_Falla"] = np.nan                     # sin codificar
        elif r < 0.75:
            df.at[i, "Modo_Falla"] = "FALLA ELECTRICA"          # codificación errónea
        if rng.random() < 0.3:
            df.at[i, "Causa_Raiz"] = np.nan                     # sin causa -> no recuperable
mal = rng.choice(idx_corr, 10, replace=False)
df.loc[mal, "Modo_Falla"] = df.loc[mal, "Modo_Falla"].astype(object).str.lower()  # minúsculas / formato

# IDs mal digitados
sucios = rng.choice(n, 25, replace=False)
df.loc[sucios, "Equipo_ID"] = df.loc[sucios, "Equipo_ID"].map(
    lambda s: rng.choice([s.lower(), s.replace("-", ""), " " + s + " "]))

# Duplicados exactos (OT cargada dos veces)
dup = df.loc[rng.choice(idx_corr, 6, replace=False)]
df = pd.concat([df, dup]).sort_values("Fecha_Reporte").reset_index(drop=True)

df.insert(0, "OT_ID", [f"OT-{24000 + i:05d}" for i in range(len(df))])
# los duplicados reciben el mismo OT_ID que su original
dmask = df.duplicated(subset=[c for c in df.columns if c != "OT_ID"], keep="first")
for i in df.index[dmask]:
    orig = df.index[(~dmask) & (df.drop(columns="OT_ID").eq(df.drop(columns="OT_ID").loc[i]) |
                                (df.drop(columns="OT_ID").isna() & df.drop(columns="OT_ID").loc[i].isna())).all(axis=1)][0]
    df.at[i, "OT_ID"] = df.at[orig, "OT_ID"]

df["Costo_HH_PEN"] = (df["HH_Reportadas"] * COSTO_HH).round(0)
df.to_csv("datos_prueba_OT.csv", index=False, encoding="utf-8-sig")
print(f"{len(df)} registros  |  correctivas: {(df.Tipo_OT=='Correctivo').sum()}  |  "
      f"preventivas: {(df.Tipo_OT=='Preventivo').sum()}  |  predictivas: {(df.Tipo_OT=='Predictivo').sum()}")
