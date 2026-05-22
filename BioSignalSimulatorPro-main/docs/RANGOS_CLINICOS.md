# Rangos clinicos y parametros usados en los modelos

Este documento consolida los rangos clinicos y parametros usados para ajustar los modelos de generacion (ECG, EMG, PPG) y para construir las variantes patologicas. Las tablas se basan en las referencias proporcionadas por el equipo.

## ECG

### Tabla 1. Complejo PQRST normal (Lead II)

| Componente | Duracion | Amplitud (mV) |
|---|---|---|
| Onda P | < 110 ms | 0.15 - 0.25 |
| Intervalo PR | 120 - 200 ms | -- |
| Complejo QRS | 70 - 100 ms | -- |
| Onda Q | < 40 ms | < 25% de R |
| Onda R | -- | 0.8 - 1.2 |
| Onda S | -- | -0.05 a -0.50 |
| Segmento ST | -- | ~ 0 (isoelectrico) |
| Onda T | -- | 0.20 - 0.40 |
| Intervalo QT | 320 - 440 ms | -- |
| QTc (Bazett) | 320 - 460 ms | -- |
| HR | 60 - 100 BPM | -- |

Fuentes: ecgwaves.com, "Reference values for adult ECG" (amplitudes y rangos generales); SalusPlay, "Lectura del electrocardiograma" (duraciones e intervalos P, PR, QRS, QT/QTc).

### Tabla 2. Rangos QTc

| Clasificacion | QTc (ms) | Riesgo |
|---|---|---|
| QTc corto | < 320 | Arritmias ventriculares |
| Normal | 320 - 460 | Sin riesgo |
| QTc prolongado | > 460 | Torsades de Pointes |

Fuente: ecgwaves.com, "Reference values for adult ECG".
Nota: SalusPlay reporta QTc < 0.45 s en hombres y < 0.47 s en mujeres.

### Tabla 3. Condiciones ECG (patologias)

| Condicion | HR (BPM) | RR (ms) | PR (ms) | QRS (ms) | ST/T |
|---|---|---|---|---|---|
| Ritmo normal | 60-100 | 600-1000 | 120-200 | 80-120 | ST=0, T 0.2-0.6 mV |
| Taquicardia sinusal | >100 | <600 | 120-200 | 80-120 | Normales |
| Bradicardia sinusal | <60 | >1000 | 170-200 | 80-120 | Normales |
| Fibrilacion auricular | Variable | Irregular | -- | 80-120 | Secundarios |
| Fibrilacion ventricular | -- | -- | -- | -- | Caotico 4-10 Hz |
| Bloqueo AV 1er grado | 60-100 | 600-1000 | >200 | 80-120 | Normales |
| Elevacion ST (STEMI) | Variable | Variable | 120-200 | 80-120 | ST >= 0.2 mV |
| Depresion ST | Variable | Variable | 120-200 | 80-120 | ST 0.05-0.2 mV |

Fuente: ecgwaves.com, "Reference values for adult ECG".

### Tabla 4. Variabilidad RR

| Condicion | CV% RR | Interpretacion |
|---|---|---|
| Normal/Sinus | < 10% | Regular |
| Fibrilacion auricular | 15-35% | Irregularmente irregular |
| Fibrilacion ventricular | N/A | Caotico |

Fuente: ecgwaves.com, "Reference values for adult ECG".

## EMG

### Tabla 5. Condiciones EMG (rangos usados en el modelo)

| Condicion | Excitacion (MVC) | MUs activas | FR media (Hz) | RMS pico (mV) | Estado |
|---|---|---|---|---|---|
| Reposo | 0.5% | 0 | 0 | 0.001 | Solo ruido termico |
| Leve | 12% | 68-70 | 8-10 | 0.52 | Durante contraccion |
| Moderada | 35% | 100 | 15-17 | 1.7 | Durante contraccion |
| Alta | 80% | 100 | 31-37 | 2.8 | Durante contraccion |
| Temblor Parkinson | Variable | Variable | 4-6 Hz modulacion | 0.1-0.5 | Temblor continuo |
| Fatiga | 50% sostenido | 100 | Decay progresivo | 1.5 -> 0.4 | MDF 120 -> 80 Hz |

Fuentes:
- Frontiers in Neurology (2021), "Tremor Syndromes: An Updated Review" (temblor en reposo en PD tipicamente 4-6 Hz).
- IntechOpen, "The Usefulness of Mean and Median Frequencies in Electromyography Analysis" (fatiga produce desplazamiento del espectro hacia frecuencias bajas y disminucion de MNF/MDF).

Nota: El valor MDF 120 -> 80 Hz es una meta de simulacion coherente con el descenso reportado en la literatura.

### Tabla 6. Frecuencias de disparo EMG

| Parametro | Valor | Unidad |
|---|---|---|
| FR minima (reclutamiento) | 6-8 | Hz |
| FR maxima (MVC) | 30-50 | Hz |
| Ganancia FR | ~40 | Hz/unidad |
| CV ISI | 15-25 | % |

### Tabla 7. Tipos de unidades motoras

| Tipo | Umbral | Amplitud | Fatigabilidad |
|---|---|---|---|
| I (S) | Bajo (0-20%) | Pequena | Resistente |
| IIa (FR) | Medio (20-50%) | Media | Moderada |
| IIb (FF) | Alto (50-100%) | Grande | Fatigable |

### Nota de amplitud EMG cruda (sEMG)

- Rango reportado previo a amplificacion: 0-10 mV (±5 mV).
- Senales sEMG son de baja amplitud: varios uV hasta 4-5 mV; 90-95% de la energia en 20-400 Hz.

Fuentes:
- https://pmc.ncbi.nlm.nih.gov/articles/PMC1455479/
- https://www.mdpi.com/1424-8220/14/5/8235

## PPG

### Tabla 8. Condiciones PPG (rangos de PI y morfologia)

| Condicion | PI (%) | Morfologia / notas | Muesca dicrotica |
|---|---|---|---|
| Normal | 2.9-6.1 | Pico sistolico claro; upstroke rapido; muesca sutil; d/s 0.1-0.4 | Posicion: 20-50%; Amplitud: >=20%; Anchura: 20-60 ms |
| Arritmia | 1.0-5.0 | Latidos irregulares; amplitud variable; plantilla promedio dispersa | Posicion: variable; Amplitud: 10-30%; Anchura: 20-70 ms |
| Weak perfusion | 0.5-2.1 | AC muy reducido; pico atenuado; muesca ausente o tenue | Posicion: <20% o ausente; Amplitud: <10%; no detectable |
| Vasodilatacion | 5.0-10.0 | Pico mas alto y ancho; muesca mas marcada; mejor relleno diastolico | Posicion: 25-55%; Amplitud: 20-40%; Anchura: 30-60 ms |
| Strong perfusion | 7.0-20.0 | Senal robusta; muesca y reflejo vascular prominentes; alta AC | Posicion: 30-60%; Amplitud: >=30%; Anchura: 30-80 ms |
| Vasoconstriccion | 0.7-0.8 | Pulso pequeno y aplanado; upstroke menos pronunciado; muesca tenue | Posicion: <20% o ausente; Amplitud: <10%; no medible |

### Tabla 9. Indice de perfusion

| Clase | Profundidad | Interpretacion |
|---|---|---|
| I | < 20% | Vasodilatacion / tono bajo |
| II | 20-35% | Normal bajo |
| III | 20-50% | Tono vascular normal |
| IV | > 50% | Vasoconstriccion / rigidez arterial |

### Tabla 10. Modelo de duracion sistole/diastole

| HR (BPM) | RR (ms) | Sistole (ms) | Diastole (ms) | Fraccion sistole |
|---|---|---|---|---|
| 60 | 1000 | ~320 | ~680 | 32% |
| 75 | 800 | ~300 | ~500 | 37% |
| 90 | 667 | ~285 | ~382 | 43% |
| 120 | 500 | ~270 | ~230 | 54% |

Fuentes PPG:
- Sun, X., He, H., Xu, M., & Long, Y. (2024). Peripheral perfusion index of pulse oximetry in adult patients: a narrative review. European Journal of Medical Research, 29, 457. https://link.springer.com/article/10.1186/s40001-024-02048-3
- De la Pena Sanabria, I., et al. (2017). Peripheral perfusion index in the neonatal ICU. doi:10.1016/j.rprh.2017.10.015
- University of California San Diego. (2017). Cardiac Cycle (teaching notes). https://cvil.ucsd.edu/wp-content/uploads/2017/02/cardiac-cycle.pdf
- Aguilar, F. G., Monares Z., E., et al. (2022). Algoritmo de Emergencias Medicas de Chiapas para pacientes en estado de choque. Medicina Critica.
- Allen J. (2007). Photoplethysmography and its application in clinical physiological measurement. Physiological Measurement, 28(3):R1-R39.

## Referencias generales

- ecgwaves.com. Reference values for adult ECG. https://ecgwaves.com/docs/reference-values-for-adult-ecg/
- SalusPlay. TEMA 3. LECTURA DEL ELECTROCARDIOGRAMA. https://www.salusplay.com/apuntes/cuidados-medico-quirurgicos/tema-3-lectura-del-electrocardiograma
- PMC1455479. Electrical noise and factors affecting EMG signal. https://pmc.ncbi.nlm.nih.gov/articles/PMC1455479/
- Grujic Supuk T., Kuzmanic Skelin A., Cic M. (2014). Design, Development and Testing of a Low-Cost sEMG System. Sensors, 14(5):8235. https://www.mdpi.com/1424-8220/14/5/8235
- Frontiers in Neurology (2021). Tremor Syndromes: An Updated Review. https://www.frontiersin.org/articles/10.3389/fneur.2021.684835/full
- IntechOpen. The Usefulness of Mean and Median Frequencies in Electromyography Analysis. https://www.intechopen.com/chapters/40123
- Sun, X., He, H., Xu, M., & Long, Y. (2024). Peripheral perfusion index of pulse oximetry in adult patients: a narrative review. https://link.springer.com/article/10.1186/s40001-024-02048-3
- De la Pena Sanabria, I., et al. (2017). Peripheral perfusion index in the neonatal ICU. doi:10.1016/j.rprh.2017.10.015
- University of California San Diego (2017). Cardiac Cycle. https://cvil.ucsd.edu/wp-content/uploads/2017/02/cardiac-cycle.pdf
- Aguilar, F. G., Monares Z., E., et al. (2022). Algoritmo de Emergencias Medicas de Chiapas. Medicina Critica.
- Allen J. (2007). Photoplethysmography and its application in clinical physiological measurement. Physiological Measurement, 28(3):R1-R39.
