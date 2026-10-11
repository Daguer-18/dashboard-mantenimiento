# Tarea: Tratamiento de datos de confiabilidad + Dashboard de mantenimiento

## Archivos
| Archivo | Para qué sirve |
|---|---|
| `limpieza.py` | Depura la base de OTs (reglas R0–R7), calcula KPIs y Weibull con censura. Genera `salida/` |
| `app.py` | Dashboard interactivo en Streamlit (entregable 2) |
| `generar_datos_prueba.py` / `datos_prueba_OT.csv` | Datos SINTÉTICOS solo para probar. **No entregar resultados con estos datos.** |

## Cómo usarlo
```bash
pip install -r requirements.txt
python limpieza.py archivo_del_docente.csv      # o .xlsx  -> carpeta salida/ con resumen.md
streamlit run app.py                            # luego sube el archivo en la barra lateral
```
Si las columnas del archivo del docente tienen otros nombres, edita el diccionario
`COLUMNAS` al inicio de `limpieza.py` (clave = nombre interno, valor = nombre en el archivo).

## Reglas de depuración
| Regla | Vicio que ataca | Acción |
|---|---|---|
| R0 | IDs mal digitados (`mb-01`, `MB01`) | Normalizar a `MB-01` |
| R1 | OT cargada dos veces | Descartar duplicado |
| R2 | OT sin cierre | Incompleta → backlog; no entra al MTTR |
| R3 | Duración ≤ 0 | Si invertir fechas cuadra con producción → invertir; si no, imputar con producción; sin respaldo → aislar del MTTR (la falla sí cuenta para MTBF) |
| R4 | Duración > 720 h (olvido de cierre) | Imputar con bitácora de producción; sin respaldo → aislar |
| R5 | OT vs. paro real difieren > 50 % y > 2 h | Adoptar el paro de producción |
| R6 | TTR > Q3 + 1.5·IQR (por tipo de equipo) | Investigar: se conserva si hay espera de repuesto o producción lo confirma |
| R7 | Modo de falla vacío/ambiguo/mal codificado | Reclasificar a ISO 14224 por causa raíz → texto → `UNK` |

Censura a la derecha: los equipos sin fallas y el tramo entre la última falla y el corte
entran como **suspensiones** en Weibull (MLE) y Kaplan-Meier. No se descartan.
