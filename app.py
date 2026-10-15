"""
Dashboard de Mantenimiento — Estación de Bombeo / Planta Industrial
Ejecutar:   streamlit run app.py
Requiere:   pip install streamlit plotly pandas numpy scipy openpyxl tabulate
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import limpieza as L

st.set_page_config(page_title="Dashboard de Mantenimiento", page_icon="🛠️", layout="wide")

# Paleta (categórica validada para daltonismo) y semáforo reservado para estados
AZUL, NARANJA, AQUA, AMARILLO = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRIS = "#a3a29c"
ESTADO = {"ok": ("#0ca30c", "✅", "En meta"), "warn": ("#fab219", "⚠️", "Advertencia"),
          "crit": ("#d03b3b", "⛔", "Fuera de control")}
LAYOUT = dict(margin=dict(l=10, r=10, t=40, b=10), font=dict(size=13),
              plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
              xaxis=dict(gridcolor="rgba(128,128,128,.15)"), yaxis=dict(gridcolor="rgba(128,128,128,.15)"),
              hoverlabel=dict(font_size=13))

st.markdown("""<style>
.kpi{border:1px solid rgba(128,128,128,.25);border-radius:10px;padding:12px 14px;height:100%}
.kpi .t{font-size:.82rem;opacity:.75}.kpi .v{font-size:1.7rem;font-weight:650;line-height:1.2}
.kpi .s{font-size:.8rem;margin-top:4px}.kpi .bar{height:4px;border-radius:2px;margin-bottom:8px}
</style>""", unsafe_allow_html=True)


def tile(col, titulo, valor, estado=None, nota=""):
    color, icono, txt = ESTADO.get(estado, (GRIS, "", ""))
    col.markdown(f"""<div class="kpi"><div class="bar" style="background:{color}"></div>
    <div class="t">{titulo}</div><div class="v">{valor}</div>
    <div class="s">{icono} {txt}{' · ' if txt and nota else ''}{nota}</div></div>""", unsafe_allow_html=True)


def semaforo(v, verde, ambar, mayor_mejor=True):
    if pd.isna(v):
        return None
    if mayor_mejor:
        return "ok" if v >= verde else "warn" if v >= ambar else "crit"
    return "ok" if v <= verde else "warn" if v <= ambar else "crit"


# Calificación en 4 niveles (rangos referenciales: ajústalos a lo que indique tu docente)
NIVELES = [("Excelente", "#0ca30c", "✅"), ("Bueno", "#2a78d6", "🔵"),
           ("Aceptable", "#fab219", "⚠️"), ("Peligro", "#d03b3b", "⛔")]
CALIF = {
    "Ao": dict(nombre="Disponibilidad operacional (Ao)", u="%", mayor=True, cortes=(98, 95, 90),
               defin="Porcentaje del tiempo calendario en que el activo estuvo listo para operar.",
               formula=r"A_o=\frac{MTBM}{MTBM+MDT}\times100=\frac{H_{cal}-H_{paro}}{H_{cal}}\times100"),
    "Down": dict(nombre="Downtime", u="%", mayor=False, cortes=(2, 5, 10),
                 defin="Porcentaje del tiempo calendario en que el equipo estuvo detenido por mantenimiento (correctivo + preventivo).",
                 formula=r"Downtime=\frac{H_{paro}}{H_{cal}}\times100=100-A_o"),
    "MTBF": dict(nombre="MTBF", u="h", mayor=True, cortes=(2000, 1000, 500),
                 defin="Tiempo medio de operación entre fallas funcionales. Mide la CONFIABILIDAD.",
                 formula=r"MTBF=\frac{\text{Horas operativas}}{N^{\circ}\text{ de fallas funcionales}}"),
    "MTTR": dict(nombre="MTTR", u="h", mayor=False, cortes=(4, 8, 24),
                 defin="Tiempo medio para restablecer el equipo tras una falla (incluye espera de repuestos). Mide la MANTENIBILIDAD.",
                 formula=r"MTTR=\frac{\text{Horas netas de reparación}}{N^{\circ}\text{ de intervenciones correctivas}}"),
    "MTTF": dict(nombre="MTTF (Weibull)", u="h", mayor=True, cortes=(2000, 1000, 500),
                 defin="Vida media esperada hasta la falla, estimada con Weibull incluyendo los datos censurados (equipos que no fallaron).",
                 formula=r"MTTF=\eta\,\Gamma\left(1+\frac{1}{\beta}\right)"),
    "Adh": dict(nombre="Adherencia al preventivo", u="%", mayor=True, cortes=(95, 90, 80),
                defin="Porcentaje de OT preventivas ejecutadas dentro de la tolerancia respecto de las programadas.",
                formula=r"Adherencia=\frac{\text{OT prev. ejecutadas a tiempo}}{\text{OT prev. programadas}}\times100"),
    "Backlog": dict(nombre="Backlog", u="sem", mayor=False, cortes=(2, 4, 6),
                    defin="Semanas que tomaría al equipo de mantenimiento atender todas las OT pendientes con su capacidad actual.",
                    formula=r"Backlog=\frac{\text{HH de OT pendientes}}{\text{Capacidad semanal disponible (HH)}}"),
    "Costo": dict(nombre="Costo correctivo / preventivo", u="", mayor=False, cortes=(0.25, 0.5, 1.0),
                  defin="Balance financiero entre lo que se gasta reparando y lo que se invierte en prevenir.",
                  formula=r"R_c=\frac{\text{Costo mant. correctivo}}{\text{Costo mant. preventivo}}"),
}


def nivel(kpi, v):
    if v is None or pd.isna(v):
        return None
    c, may = CALIF[kpi]["cortes"], CALIF[kpi]["mayor"]
    for i, corte in enumerate(c):
        if (v >= corte) if may else (v <= corte):
            return i
    return 3


def rango_txt(kpi):
    c, may, u = CALIF[kpi]["cortes"], CALIF[kpi]["mayor"], CALIF[kpi]["u"]
    if may:
        return [f"≥ {c[0]:g} {u}", f"{c[1]:g} – {c[0]:g} {u}", f"{c[2]:g} – {c[1]:g} {u}", f"< {c[2]:g} {u}"]
    return [f"≤ {c[0]:g} {u}", f"{c[0]:g} – {c[1]:g} {u}", f"{c[1]:g} – {c[2]:g} {u}", f"> {c[2]:g} {u}"]


def tile_kpi(col, kpi, v, fmt, nota=""):
    i = nivel(kpi, v)
    color, icono, txt = (NIVELES[i][1], NIVELES[i][2], NIVELES[i][0]) if i is not None else (GRIS, "", "")
    val = fmt.format(v) if v is not None and pd.notna(v) else "—"
    col.markdown(f"""<div class="kpi"><div class="bar" style="background:{color}"></div>
    <div class="t">{CALIF[kpi]['nombre']}</div><div class="v">{val}</div>
    <div class="s">{icono} {txt}{' · ' if txt and nota else ''}{nota}</div></div>""", unsafe_allow_html=True)


def velocimetro(kpi, v, rango_max):
    c, may = CALIF[kpi]["cortes"], CALIF[kpi]["mayor"]
    lo = 0 if not may else min(c[2] - (c[0] - c[2]), v if pd.notna(v) else c[2])
    lo = max(0, lo)
    if may:
        lims = [(lo, c[2]), (c[2], c[1]), (c[1], c[0]), (c[0], rango_max)]
        cols = [NIVELES[3][1], NIVELES[2][1], NIVELES[1][1], NIVELES[0][1]]
    else:
        lims = [(0, c[0]), (c[0], c[1]), (c[1], c[2]), (c[2], rango_max)]
        cols = [NIVELES[0][1], NIVELES[1][1], NIVELES[2][1], NIVELES[3][1]]
    i = nivel(kpi, v)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=v if pd.notna(v) else 0,
        number=dict(suffix=f" {CALIF[kpi]['u']}", valueformat=".1f", font=dict(size=30)),
        title=dict(text=f"{CALIF[kpi]['nombre']}<br><span style='font-size:13px'>{NIVELES[i][2] + ' ' + NIVELES[i][0] if i is not None else ''}</span>",
                   font=dict(size=15)),
        gauge=dict(axis=dict(range=[lo, rango_max], tickwidth=1), bar=dict(color="rgba(0,0,0,0)", thickness=0),
                   steps=[dict(range=r, color=cc) for r, cc in zip(lims, cols)], borderwidth=0,
                   threshold=dict(line=dict(color="#2c2c2a", width=5), thickness=0.9,
                                  value=min(max(v, lo), rango_max) if pd.notna(v) else lo))))
    fig.update_layout(margin=dict(l=25, r=25, t=70, b=10), height=250, paper_bgcolor="rgba(0,0,0,0)")
    return fig


# ----------------------------------------------------------- DATOS
st.sidebar.title("🛠️ Mantenimiento")
archivo = st.sidebar.file_uploader("Base de OTs (CSV / Excel)", type=["csv", "xlsx", "xls"])
prueba = Path(__file__).with_name("datos_prueba_OT.csv")


@st.cache_data(show_spinner="Depurando datos…")
def procesar(contenido: bytes | None, nombre: str):
    if contenido is None:
        raw = L.cargar(prueba)
    else:
        tmp = Path(st.session_state.get("tmpdir", ".")) / f"_subido_{nombre}"
        tmp.write_bytes(contenido)
        raw = L.cargar(tmp)
    df, bit = L.depurar(raw)
    return df, bit


if archivo is None and not prueba.exists():
    st.info("Sube el archivo de OTs en la barra lateral."); st.stop()
df_all, bit = procesar(archivo.getvalue() if archivo else None, archivo.name if archivo else "prueba")
if archivo is None:
    st.warning("Mostrando **datos de prueba sintéticos**. Sube el archivo del curso en la barra lateral para el análisis real.")

ini, fin = L.periodo(df_all)

# ----------------------------------------------------------- FILTROS
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
st.sidebar.subheader("Periodo")
anios = sorted(df_all["t_inicio"].dropna().dt.year.unique())
f_anio = st.sidebar.selectbox("Año", ["Todos"] + [int(a) for a in anios])
f_mes = st.sidebar.selectbox("Mes", ["Todos"] + MESES, disabled=f_anio == "Todos",
                             help="Elige primero un año")
st.sidebar.subheader("Filtros")
crit_opts = sorted(df_all["criticidad"].dropna().unique())
esp_opts = sorted(df_all["especialidad"].dropna().unique())
sub_opts = sorted(df_all["subsistema"].dropna().unique())
f_crit = st.sidebar.multiselect("Criticidad del equipo", crit_opts, default=crit_opts)
f_esp = st.sidebar.multiselect("Especialidad de mantenimiento", esp_opts, default=esp_opts)
f_sub = st.sidebar.multiselect("Subsistema (ISO 14224)", sub_opts, default=sub_opts)
eq_disp = sorted(df_all.loc[df_all["criticidad"].isin(f_crit) & df_all["subsistema"].isin(f_sub), "equipo"].dropna().unique())
f_eq = st.sidebar.multiselect("Equipo", eq_disp, default=[], placeholder="Todos los equipos")
st.sidebar.subheader("Parámetros")
capacidad = st.sidebar.number_input("Capacidad semanal (HH)", 20, 5000, 288, 8,
                                    help="Técnicos disponibles × horas por semana. Ej.: 6 × 48 = 288")
tol = st.sidebar.slider("Tolerancia adherencia (días)", 0, 10, 3)
h_plan = st.sidebar.number_input("Horas planificadas de operación al año", 1000, 8784, 8760, 10,
                                 help="8,760 = operación continua 24/7. Si la planta planifica menos horas "
                                      "(p.ej. 8,200 h en la cementera), ingrésalo aquí: MTBF y Ao se calculan sobre esa base.")
FRAC = h_plan / 8760

# ventana de tiempo seleccionada
if f_anio == "Todos":
    ini_w, fin_w = ini, fin
elif f_mes == "Todos":
    ini_w, fin_w = max(ini, pd.Timestamp(f_anio, 1, 1)), min(fin, pd.Timestamp(f_anio + 1, 1, 1))
else:
    m_ = MESES.index(f_mes) + 1
    ini_w = pd.Timestamp(f_anio, m_, 1)
    fin_w = min(fin, ini_w + pd.offsets.MonthBegin(1))
if fin_w <= ini_w:
    st.error("No hay datos para ese periodo."); st.stop()
H_VENT = (fin_w - ini_w).total_seconds() / 3600

# df_eq: todo el historial de los equipos filtrados (para Weibull y backlog)
df_eq = df_all[df_all["criticidad"].isin(f_crit) & df_all["especialidad"].isin(f_esp) & df_all["subsistema"].isin(f_sub)]
if f_eq:
    df_eq = df_eq[df_eq["equipo"].isin(f_eq)]
# df: OT dentro de la ventana de tiempo
df = df_eq[(df_eq["t_inicio"] >= ini_w) & (df_eq["t_inicio"] < fin_w)]
if df_eq.empty or df.empty:
    st.error("Ningún registro coincide con los filtros."); st.stop()
equipos_sel = sorted(df_eq["equipo"].dropna().unique())
n_eq = len(equipos_sel)

k = L.kpis_por_equipo(df, ini_w, fin_w, FRAC)
adh, adh_ok, adh_tot = L.adherencia(df, tol, fin_w)
bl_sem, bl_hh, bl_n = L.backlog(df_eq, capacidad)
cc, cp = L.costos(df)
ratio = cc / cp if cp else np.nan
fallas_tot = int(k["N_fallas"].sum())
down = k["Horas_paro_correctivo"].sum() + k["Horas_paro_preventivo"].sum()
H_tot = n_eq * H_VENT * FRAC
ao_g = 100 * (H_tot - down) / H_tot
down_pct = 100 - ao_g
mtbf_g = (H_tot - down) / fallas_tot if fallas_tot else np.nan
corr_ttr = df[(df["tipo_ot"] == "Correctivo") & df["Usar_TTR"]]["TTR_validado_h"]
mttr_g = corr_ttr.mean()
vida_flota = L.tiempos_vida(df_eq.assign(flota="Flota"), ini, fin, agrupar="flota")
wb_flota = L.tabla_weibull(vida_flota)
mttf_g = wb_flota["MTTF_h"].iat[0] if len(wb_flota) else np.nan


def evolucion_mensual(d, d_eq):
    filas = []
    for m0 in pd.date_range(ini_w.replace(day=1), fin_w - pd.Timedelta(seconds=1), freq="MS"):
        m1 = min(m0 + pd.offsets.MonthBegin(1), fin_w)
        h = n_eq * (m1 - max(m0, ini_w)).total_seconds() / 3600 * FRAC
        g = d[(d["t_inicio"] >= m0) & (d["t_inicio"] < m1)]
        ttr = g[g["Usar_TTR"] & g["tipo_ot"].isin(["Correctivo", "Preventivo"])]["TTR_validado_h"].sum()
        fal = int(((g["tipo_ot"] == "Correctivo") & g["Usar_Evento"]).sum())
        mttr = g[(g["tipo_ot"] == "Correctivo") & g["Usar_TTR"]]["TTR_validado_h"].mean()
        p = g[(g["tipo_ot"] == "Preventivo") & g["f_programada"].notna()]
        ad = 100 * (p["t_inicio"] <= p["f_programada"] + pd.Timedelta(days=tol + 1)).mean() if len(p) else np.nan
        filas.append(dict(Mes=m0, Fallas=fal, Ao=100 * (h - ttr) / h, Down=100 * ttr / h,
                          MTBF=(h - ttr) / fal if fal else np.nan, MTTR=mttr, Adh=ad))
    return pd.DataFrame(filas)


ev = evolucion_mensual(df, df_eq)

st.title("Dashboard de Control de Mantenimiento")
st.caption(f"Periodo {ini_w:%d/%m/%Y} – {(fin_w - pd.Timedelta(seconds=1)):%d/%m/%Y} · {len(df):,} OT filtradas · "
           f"{n_eq} equipo{'s' if n_eq != 1 else ''} · "
           + ("operación continua 24/7" if h_plan >= 8760 else f"{h_plan:,} h planificadas/año"))

t1, t6, t2, t3, t4, t5, t7 = st.tabs(["Estratégico", "Evolución mensual", "Táctico", "Operativo",
                                      "Confiabilidad (Weibull)", "Calidad de datos", "Fichas de indicadores"])

# ============================================================ ESTRATÉGICO
with t1:
    c = st.columns(4)
    tile_kpi(c[0], "Ao", ao_g, "{:.2f} %")
    tile_kpi(c[1], "Down", down_pct, "{:.2f} %", f"{down:,.0f} h de paro")
    tile_kpi(c[2], "MTBF", mtbf_g, "{:,.0f} h", f"{fallas_tot} fallas")
    tile_kpi(c[3], "MTTR", mttr_g, "{:.1f} h", f"{len(corr_ttr)} reparaciones")
    st.write("")
    c = st.columns(4)
    tile_kpi(c[0], "MTTF", mttf_g, "{:,.0f} h", "historial completo, con censura")
    tile_kpi(c[1], "Adh", adh, "{:.1f} %", f"{adh_ok}/{adh_tot}")
    tile_kpi(c[2], "Backlog", bl_sem, "{:.2f} sem", f"{bl_hh:.0f} HH al corte")
    tile_kpi(c[3], "Costo", ratio, "{:.2f}", "meta ≤ 0.25")
    st.write("")
    g1, g2, g3 = st.columns(3)
    g1.plotly_chart(velocimetro("Ao", ao_g, 100), use_container_width=True)
    g2.plotly_chart(velocimetro("Adh", adh, 100), use_container_width=True)
    g3.plotly_chart(velocimetro("Backlog", bl_sem, max(8, (bl_sem or 0) * 1.2)), use_container_width=True)
    st.caption("Calificación: " + " · ".join(f"{ic} {n}" for n, _, ic in NIVELES) +
               " — rangos en la pestaña *Fichas de indicadores*.")

    st.write("")
    a, b = st.columns([1, 1])
    kk = k.sort_values("Ao_pct")
    colores = [NIVELES[nivel("Ao", v)][1] for v in kk["Ao_pct"]]
    fig = go.Figure(go.Bar(x=kk["Ao_pct"], y=kk["Equipo"], orientation="h", marker_color=colores,
                           marker_line_width=0, text=[f"{v:.1f} %" for v in kk["Ao_pct"]], textposition="outside",
                           customdata=kk[["Subsistema", "Criticidad"]],
                           hovertemplate="<b>%{y}</b><br>%{customdata[0]} · Clase %{customdata[1]}<br>Ao: %{x:.2f} %<extra></extra>"))
    fig.update_layout(**LAYOUT, title="Disponibilidad Ao por equipo (%)",
                      height=max(320, 26 * len(kk)), xaxis_range=[min(85, kk["Ao_pct"].min() - 1), 101.5], bargap=.25)
    a.plotly_chart(fig, use_container_width=True)
    a.caption("Color = calificación: " + " · ".join(f"{ic} {n} ({r})" for (n, _, ic), r in zip(NIVELES, rango_txt("Ao"))))

    m = df[(df["tipo_ot"] == "Correctivo") & df["Usar_TTR"]].copy()
    m["Mes"] = m["t_inicio"].dt.to_period("M").dt.to_timestamp()
    serie = m.groupby("Mes")["TTR_validado_h"].sum().reindex(
        pd.date_range(ini_w.replace(day=1), fin_w - pd.Timedelta(seconds=1), freq="MS"), fill_value=0)
    fig = go.Figure(go.Scatter(x=serie.index, y=serie.values, mode="lines+markers", line=dict(color=AZUL, width=2),
                               marker=dict(size=8), hovertemplate="%{x|%b %Y}<br>%{y:.0f} h de paro correctivo<extra></extra>"))
    fig.update_layout(**LAYOUT, title="Horas de paro correctivo por mes", height=360, yaxis_title="horas")
    b.plotly_chart(fig, use_container_width=True)

    diag = L.diagnostico(k)
    st.subheader("Cuello de botella por subsistema")
    st.dataframe(diag.rename(columns={"Horas_paro": "Horas paro correctivo", "Horas_op": "Horas operativas",
                                      "Pct_paro_total": "% del paro total"}), use_container_width=True)

# ============================================================ TÁCTICO
with t2:
    a, b = st.columns(2)
    kf = k[~k["MTBF_censurado"]].sort_values("MTBF_h")
    fig = go.Figure(go.Bar(x=kf["MTBF_h"], y=kf["Equipo"], orientation="h", marker_color=AZUL,
                           text=[f"{v:,.0f}" for v in kf["MTBF_h"]], textposition="outside",
                           hovertemplate="<b>%{y}</b><br>MTBF %{x:,.0f} h<extra></extra>"))
    fig.update_layout(**LAYOUT, title="MTBF por equipo (h) — menor = menos confiable", height=max(320, 26 * len(kf)),
                      xaxis_range=[0, kf["MTBF_h"].max() * 1.15])
    a.plotly_chart(fig, use_container_width=True)
    kf = kf.sort_values("MTTR_h")
    rep = (kf["MTTR_h"] - kf["Espera_repuesto_media_h"].fillna(0)).clip(lower=0)
    fig = go.Figure([
        go.Bar(x=rep, y=kf["Equipo"], orientation="h", name="Respuesta + reparación", marker_color=AZUL,
               hovertemplate="<b>%{y}</b><br>Reparación: %{x:.1f} h<extra></extra>"),
        go.Bar(x=kf["Espera_repuesto_media_h"].fillna(0), y=kf["Equipo"], orientation="h", name="Espera de repuesto",
               marker_color=NARANJA, hovertemplate="<b>%{y}</b><br>Espera repuesto: %{x:.1f} h<extra></extra>")])
    fig.update_layout(**LAYOUT, barmode="stack", title="MTTR por equipo (h) desglosado",
                      height=max(320, 26 * len(kf)), legend=dict(orientation="h", y=-0.12))
    fig.update_traces(marker_line_color="rgba(255,255,255,.9)", marker_line_width=1)
    b.plotly_chart(fig, use_container_width=True)

    st.subheader("Análisis de Pareto (80/20) — equipos críticos")
    p1, p2 = st.columns([1, 3])
    clase = p1.multiselect("Criticidad", crit_opts, default=["A"] if "A" in crit_opts else crit_opts[:1])
    dim = p1.radio("Agrupar por", ["Modo de falla (ISO 14224)", "Causa raíz", "Equipo"])
    medida = p1.radio("Medir por", ["Horas de paro", "Número de fallas"])
    col_dim = {"Modo de falla (ISO 14224)": "Modo_ISO_desc", "Causa raíz": "causa", "Equipo": "equipo"}[dim]
    pa = df[(df["tipo_ot"] == "Correctivo") & df["Usar_Evento"] & df["criticidad"].isin(clase)].copy()
    pa[col_dim] = pa[col_dim].fillna("Sin registrar")
    g = (pa.groupby(col_dim)["TTR_validado_h"].sum() if medida == "Horas de paro" else pa.groupby(col_dim).size())
    g = g.sort_values(ascending=False)
    if g.sum() > 0:
        acum = 100 * g.cumsum() / g.sum()
        vitales = (acum.shift(fill_value=0) < 80)
        fig = go.Figure(go.Bar(
            x=g.index, y=g.values, marker_color=[AZUL if v else GRIS for v in vitales],
            text=[f"{a_:.0f} %" for a_ in acum], textposition="outside",
            hovertemplate="<b>%{x}</b><br>%{y:.1f}<br>% acumulado: %{text}<extra></extra>"))
        fig.update_layout(**LAYOUT, height=440, yaxis_title=medida.lower(),
                          title="Azul = pocos vitales (hasta 80 % acumulado) · etiqueta = % acumulado")
        p2.plotly_chart(fig, use_container_width=True)
        p2.caption(f"{int(vitales.sum())} de {len(g)} categorías concentran el {acum[vitales].iloc[-1]:.0f} % de "
                   f"{'las horas de paro' if medida == 'Horas de paro' else 'las fallas'}.")

    st.subheader("KPIs por equipo")
    st.dataframe(k.drop(columns=["MTBF_censurado"]).rename(columns={"Ao_pct": "Ao %"}), use_container_width=True, hide_index=True)
    st.caption("Equipos sin fallas en el periodo (MTBF vacío) son datos censurados: su MTBF real es mayor que las horas operadas.")

# ============================================================ OPERATIVO
with t3:
    ab = df[df["Categoria"] == "Incompleto (OT abierta)"].copy()
    ab["Días abierta"] = ((fin - ab["t_inicio"]).dt.total_seconds() / 86400).round(1)
    c = st.columns(3)
    tile(c[0], "OT abiertas", f"{len(ab)}", None, f"{(ab['criticidad'] == 'A').sum()} en equipos clase A")
    tile(c[1], "En espera de repuesto", f"{(ab['estado_n'] == 'EN ESPERA DE REPUESTO').sum()}", None)
    tile(c[2], "HH pendientes", f"{bl_hh:.0f}", None, f"capacidad {capacidad} HH/sem")
    st.write("")
    a, b = st.columns([2, 1])
    a.subheader("OT abiertas (prioridad: criticidad, antigüedad)")
    a.dataframe(ab.sort_values(["criticidad", "Días abierta"], ascending=[True, False])[
        ["ot", "equipo", "criticidad", "especialidad", "tipo_ot", "descripcion", "estado", "Días abierta", "hh_estimadas"]]
        .rename(columns={"ot": "OT", "equipo": "Equipo", "criticidad": "Clase", "especialidad": "Especialidad",
                         "tipo_ot": "Tipo", "descripcion": "Descripción", "estado": "Estado", "hh_estimadas": "HH est."}),
        use_container_width=True, hide_index=True)
    be = ab.groupby("especialidad")["hh_estimadas"].sum().sort_values()
    fig = go.Figure(go.Bar(x=be.values, y=be.index, orientation="h", marker_color=AZUL,
                           text=[f"{v:.0f} HH" for v in be.values], textposition="outside",
                           hovertemplate="%{y}: %{x:.0f} HH<extra></extra>"))
    fig.update_layout(**LAYOUT, title="Backlog por especialidad", height=320)
    b.plotly_chart(fig, use_container_width=True)
    pred = df[df["tipo_ot"] == "Predictivo"].sort_values("t_inicio", ascending=False).head(10)
    if len(pred):
        st.subheader("Últimas inspecciones predictivas")
        st.dataframe(pred[["ot", "equipo", "criticidad", "t_inicio", "descripcion"]], use_container_width=True, hide_index=True)

# ============================================================ CONFIABILIDAD
with t4:
    agr = st.radio("Agrupar población por", ["subsistema", "tipo_equipo", "equipo"], horizontal=True,
                   format_func=lambda s: {"subsistema": "Subsistema", "tipo_equipo": "Tipo de equipo", "equipo": "Equipo"}[s])
    st.caption("Se usa el historial completo de los equipos filtrados (no solo el año/mes elegido): "
               "la vida de un equipo no se puede cortar por meses.")
    vida = L.tiempos_vida(df_eq, ini, fin, agrupar=agr)
    wb = L.tabla_weibull(vida)
    st.dataframe(wb, use_container_width=True, hide_index=True)
    st.caption("MLE con censura a la derecha: L = Π f(tᵢ) [fallas] · Π R(tⱼ) [suspensiones]. "
               "Supuesto: reparación 'tan buena como nueva' y equipo nuevo al inicio del estudio.")
    grupos = wb.dropna(subset=["beta"])["Grupo"].tolist()
    if grupos:
        gsel = st.selectbox("Curva de supervivencia", grupos)
        v = vida[vida["grupo"] == gsel]
        km = L.kaplan_meier(v["t"], v["falla"])
        bta, eta = wb.set_index("Grupo").loc[gsel, ["beta", "eta_h"]]
        tt = np.linspace(0, v["t"].max(), 200)
        fig = go.Figure([
            go.Scatter(x=km["t"], y=km["S"], mode="lines", line_shape="hv", name="Kaplan-Meier (no paramétrico)",
                       line=dict(color=AZUL, width=2), hovertemplate="t = %{x:.0f} h<br>S(t) = %{y:.2f}<extra></extra>"),
            go.Scatter(x=tt, y=np.exp(-(tt / eta) ** bta), mode="lines", name=f"Weibull β={bta:.2f}, η={eta:,.0f} h",
                       line=dict(color=NARANJA, width=2, dash="dash"), hovertemplate="t = %{x:.0f} h<br>R(t) = %{y:.2f}<extra></extra>")])
        fig.update_layout(**LAYOUT, height=420, xaxis_title="horas de operación", yaxis_title="confiabilidad R(t)",
                          yaxis_range=[0, 1.02], legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
        c = st.columns(3)
        tile(c[0], "Vida B10 (10 % de fallas)", f"{eta * (-np.log(.9)) ** (1 / bta):,.0f} h")
        tile(c[1], "Confiabilidad a 720 h (1 mes)", f"{100 * np.exp(-(720 / eta) ** bta):.1f} %")
        tile(c[2], "Fallas / suspensiones", f"{int(v['falla'].sum())} / {int((v['falla'] == 0).sum())}")

# ============================================================ CALIDAD
with t5:
    cal = L.resumen_calidad(df_all)
    c = st.columns(len(cal))
    for col, (cat, row) in zip(c, cal.iterrows()):
        tile(col, cat, f"{row['Porcentaje']:.1f} %", None, f"{int(row['Registros'])} registros")
    st.write("")
    sin_f = k.loc[k["MTBF_censurado"], "Equipo"].tolist()
    st.info(f"**Censura a la derecha:** {len(sin_f)} equipos sin fallas al corte ({', '.join(sin_f) or '—'}) y "
            f"{int((vida['falla'] == 0).sum())} suspensiones en total se incluyen en Weibull/Kaplan-Meier — no se descartan.")
    reglas = bit.groupby("Regla").agg(OT=("OT_ID", "nunique"), Accion=("Accion", lambda s: s.str.split(":").str[0].mode().iat[0]))
    st.subheader("Reglas aplicadas")
    st.dataframe(reglas, use_container_width=True)
    st.subheader("Bitácora de limpieza (trazabilidad por OT)")
    rsel = st.multiselect("Filtrar por regla", sorted(bit["Regla"].unique()), default=sorted(bit["Regla"].unique()))
    st.dataframe(bit[bit["Regla"].isin(rsel)], use_container_width=True, hide_index=True, height=360)
    st.download_button("Descargar bitácora (CSV)", bit.to_csv(index=False).encode("utf-8-sig"), "bitacora_limpieza.csv")
    st.download_button("Descargar base depurada (CSV)", df_all.rename(columns=L.COLUMNAS).to_csv(index=False).encode("utf-8-sig"),
                       "OT_depuradas.csv")

# ============================================================ EVOLUCIÓN MENSUAL
with t6:
    if len(ev) < 2:
        st.info("Elige un año o 'Todos' para ver la evolución mes a mes.")
    else:
        def linea(col, kpi, fmt_hover):
            c = CALIF[kpi]["cortes"]
            f = go.Figure()
            f.add_trace(go.Scatter(x=ev["Mes"], y=ev[kpi], mode="lines+markers", connectgaps=False,
                                   line=dict(color=AZUL, width=2),
                                   marker=dict(size=9, color=[NIVELES[nivel(kpi, v)][1] if pd.notna(v) else GRIS for v in ev[kpi]],
                                               line=dict(color="white", width=1.5)),
                                   hovertemplate="%{x|%b %Y}<br>" + fmt_hover + "<extra></extra>", showlegend=False))
            for corte, (n_, colr, _) in zip(c, NIVELES):
                f.add_hline(y=corte, line=dict(color=colr, width=1, dash="dot"),
                            annotation_text=f"{n_} {'≥' if CALIF[kpi]['mayor'] else '≤'} {corte:g}",
                            annotation_position="right", annotation_font_size=10, annotation_font_color="#73726c")
            f.update_layout(**LAYOUT, title=f"{CALIF[kpi]['nombre']} ({CALIF[kpi]['u']})", height=330)
            f.update_layout(margin=dict(l=10, r=110, t=40, b=10))
            col.plotly_chart(f, use_container_width=True)

        a, b = st.columns(2)
        linea(a, "Ao", "Ao: %{y:.2f} %")
        linea(b, "Down", "Downtime: %{y:.2f} %")
        a, b = st.columns(2)
        linea(a, "MTBF", "MTBF: %{y:,.0f} h")
        linea(b, "MTTR", "MTTR: %{y:.1f} h")
        linea(st, "Adh", "Adherencia: %{y:.1f} %")
        st.caption("Color del punto = calificación del mes. MTBF vacío = mes sin fallas (no se puede calcular; es buena señal).")

        st.subheader("Tabla de seguimiento mensual")
        tabla = ev.copy()
        tabla["Mes"] = tabla["Mes"].dt.strftime("%b %Y")
        tabla = tabla.set_index("Mes")[["Fallas", "Ao", "Down", "MTBF", "MTTR", "Adh"]]

        def pintar(colname):
            def f(v):
                i = nivel(colname, v)
                return "" if i is None else f"background-color:{NIVELES[i][1]}33"
            return f
        sty = tabla.style.format({"Ao": "{:.2f} %", "Down": "{:.2f} %", "MTBF": "{:,.0f} h", "MTTR": "{:.1f} h",
                                  "Adh": "{:.1f} %"}, na_rep="—")
        for col_ in ["Ao", "Down", "MTBF", "MTTR", "Adh"]:
            sty = sty.map(pintar(col_), subset=[col_])
        st.dataframe(sty.relabel_index(["Fallas", "Ao", "Downtime", "MTBF", "MTTR", "Adherencia"], axis=1),
                     use_container_width=True, height=min(38 * (len(tabla) + 1), 700))

# ============================================================ FICHAS
with t7:
    st.caption("Rangos de calificación referenciales; puedes ajustarlos en el diccionario CALIF al inicio de app.py.")
    actuales = {"Ao": (ao_g, "{:.2f} %"), "Down": (down_pct, "{:.2f} %"), "MTBF": (mtbf_g, "{:,.0f} h"),
                "MTTR": (mttr_g, "{:.1f} h"), "MTTF": (mttf_g, "{:,.0f} h"), "Adh": (adh, "{:.1f} %"),
                "Backlog": (bl_sem, "{:.2f} sem"), "Costo": (ratio, "{:.2f}")}
    claves = list(CALIF)
    for fila in range(0, len(claves), 2):
        cols = st.columns(2)
        for col, kpi in zip(cols, claves[fila:fila + 2]):
            info = CALIF[kpi]
            v, fmt = actuales[kpi]
            i = nivel(kpi, v)
            with col.container(border=True):
                st.markdown(f"#### {info['nombre']}")
                st.write(info["defin"])
                st.latex(info["formula"])
                st.markdown(f"**Valor actual (filtros aplicados):** {fmt.format(v) if pd.notna(v) else '—'} "
                            f"{(NIVELES[i][2] + ' ' + NIVELES[i][0]) if i is not None else ''}")
                st.markdown(" ".join(
                    f"<span style='display:inline-block;padding:2px 8px;margin:2px;border-radius:6px;"
                    f"background:{c_}22;border:1px solid {c_}'>{ic} <b>{n_}</b> {r}</span>"
                    for (n_, c_, ic), r in zip(NIVELES, rango_txt(kpi))), unsafe_allow_html=True)
