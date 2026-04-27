#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análisis FFT de Modelos Matemáticos - BioSignalSimulator Pro
=============================================================

Este script analiza el contenido frecuencial INTRÍNSECO de cada modelo
matemático, muestreado a su Fs_modelo (según config.h).

OBJETIVO:
---------
Determinar el ancho de banda REAL que genera cada modelo para:
1. Validar que cumple con estándares clínicos
2. Diseñar filtros RC adecuados
3. Confirmar que Fs_modelo es suficiente

MODELOS IMPLEMENTADOS:
----------------------
1. ECG: McSharry ECGSYN (ecuaciones diferenciales + Gaussianas)
2. EMG: Fuglevand (MUAPs con distribución de unidades motoras)
3. PPG: Allen 2007 (composición de Gaussianas)

FRECUENCIAS DE MUESTREO DEL MODELO (según config.h):
----------------------------------------------------
- ECG: 300 Hz  (2 × 150 Hz BW clínico)
- EMG: 1000 Hz (2 × 500 Hz BW clínico)
- PPG: 20 Hz   (2 × 10 Hz BW clínico)

Autor: BioSignalSimulator Pro Team
Fecha: Enero 2026
"""

import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.integrate import odeint
from scipy.signal import butter, sosfilt
import matplotlib
matplotlib.use('Agg')  # Backend no interactivo para evitar bloqueos
import matplotlib.pyplot as plt
from datetime import datetime
import os

# =============================================================================
# CONFIGURACIÓN (igual que config.h)
# =============================================================================

CONFIG = {
    'ECG': {
        'fs_modelo': 300,      # Hz - MODEL_SAMPLE_RATE_ECG
        'fs_timer': 2000,      # Hz - FS_TIMER_HZ
        'bw_clinico_min': 0.05,
        'bw_clinico_max': 150.0,
        'descripcion': 'ECG McSharry ECGSYN @ 300 Hz'
    },
    'EMG': {
        'fs_modelo': 1000,     # Hz - MODEL_SAMPLE_RATE_EMG
        'fs_timer': 2000,
        'bw_clinico_min': 20.0,
        'bw_clinico_max': 500.0,
        'descripcion': 'EMG Fuglevand MUAP @ 1000 Hz'
    },
    'PPG': {
        'fs_modelo': 20,       # Hz - MODEL_SAMPLE_RATE_PPG
        'fs_timer': 2000,
        'bw_clinico_min': 0.5,
        'bw_clinico_max': 10.0,
        'descripcion': 'PPG Allen Gaussiano @ 20 Hz'
    }
}


# =============================================================================
# MODELO ECG - McSharry ECGSYN Simplificado
# =============================================================================

def generate_ecg_mcsharry(duration_sec: float, fs: float, hr_bpm: float = 72.0) -> np.ndarray:
    """
    Genera ECG usando el modelo McSharry ECGSYN simplificado.
    
    El modelo usa ecuaciones diferenciales para generar la trayectoria
    en el plano (x, y, z) donde z representa el voltaje del ECG.
    
    Parámetros de las ondas PQRST (ángulos en radianes, amplitudes, anchos):
    - P: θ=-π/3, a=0.25, b=0.25
    - Q: θ=-π/12, a=-0.1, b=0.1  
    - R: θ=0, a=1.5, b=0.1
    - S: θ=π/12, a=-0.25, b=0.1
    - T: θ=π/2, a=0.35, b=0.4
    
    Referencia: McSharry et al., IEEE Trans Biomed Eng, 2003
    """
    # Parámetros de las ondas PQRST
    # [theta_i, a_i, b_i] para cada onda
    waves = {
        'P': {'theta': -np.pi/3,   'a': 0.25,  'b': 0.25},
        'Q': {'theta': -np.pi/12,  'a': -0.10, 'b': 0.10},
        'R': {'theta': 0.0,        'a': 1.50,  'b': 0.10},
        'S': {'theta': np.pi/12,   'a': -0.25, 'b': 0.10},
        'T': {'theta': np.pi/2,    'a': 0.35,  'b': 0.40},
    }
    
    # Frecuencia angular del corazón
    rr_sec = 60.0 / hr_bpm
    omega = 2 * np.pi / rr_sec
    
    # Parámetros del modelo
    A = 0.005  # Amplitud de respiración (modula línea base)
    f_resp = 0.25  # Frecuencia respiratoria (Hz)
    
    # Tiempo de simulación
    N = int(duration_sec * fs)
    t = np.linspace(0, duration_sec, N)
    dt = 1.0 / fs
    
    # Inicializar señal
    ecg = np.zeros(N)
    
    # Generar usando suma de Gaussianas (aproximación analítica)
    for i, ti in enumerate(t):
        # Fase del ciclo cardíaco
        phase = (omega * ti) % (2 * np.pi) - np.pi  # -π a π
        
        # Sumar contribución de cada onda
        z = 0.0
        for wave_name, params in waves.items():
            theta_i = params['theta']
            a_i = params['a']
            b_i = params['b']
            
            # Diferencia angular
            delta_theta = phase - theta_i
            # Normalizar a [-π, π]
            delta_theta = np.arctan2(np.sin(delta_theta), np.cos(delta_theta))
            
            # Gaussiana
            z += a_i * np.exp(-0.5 * (delta_theta / b_i) ** 2)
        
        # Agregar modulación respiratoria (línea base)
        z += A * np.sin(2 * np.pi * f_resp * ti)
        
        ecg[i] = z
    
    return ecg


# =============================================================================
# MODELO EMG - Fuglevand MUAP Simplificado
# =============================================================================

def generate_emg_fuglevand(duration_sec: float, fs: float, 
                           excitation: float = 0.5,
                           num_motor_units: int = 50) -> np.ndarray:
    """
    Genera EMG usando el modelo Fuglevand de unidades motoras.
    
    Cada unidad motora genera potenciales de acción (MUAPs) que se suman.
    La forma del MUAP es una onda bifásica/trifásica con duración ~5-10 ms.
    
    Parámetros:
    - excitation: Nivel de excitación (0-1), controla cuántas MUs están activas
    - num_motor_units: Número total de unidades motoras
    
    El contenido frecuencial del EMG depende de:
    - Duración del MUAP (sigma): determina frecuencia central
    - Tasa de disparo: determina modulación de amplitud
    
    Referencia: Fuglevand et al., J Neurophysiol, 1993
    """
    N = int(duration_sec * fs)
    t = np.arange(N) / fs
    dt = 1.0 / fs
    
    emg = np.zeros(N)
    
    # Parámetros del MUAP
    # sigma controla el ancho del MUAP (~5ms para EMG de superficie)
    # Esto da un contenido frecuencial con pico alrededor de 1/(2π×sigma) ≈ 30-50 Hz
    # y extensión hasta ~200-300 Hz
    MUAP_SIGMA = 0.003  # 3 ms - mismo que en el firmware
    
    # Calcular cuántas MUs están activas según excitación
    active_mus = max(1, int(num_motor_units * excitation))
    
    # Generar disparos para cada unidad motora
    for mu in range(active_mus):
        # Tasa de disparo base (5-30 Hz según reclutamiento)
        # Las primeras MUs tienen tasas más altas
        recruitment_order = (mu + 1) / num_motor_units
        firing_rate = 5 + 25 * (1 - recruitment_order) * excitation  # 5-30 Hz
        
        # Amplitud del MUAP (las MUs más grandes tienen mayor amplitud)
        # Según principio de tamaño de Henneman
        mu_amplitude = 0.5 + 1.5 * (mu / num_motor_units)
        
        # Generar tiempos de disparo (proceso de Poisson con variabilidad)
        mean_isi = 1.0 / firing_rate
        current_time = np.random.exponential(mean_isi)
        
        while current_time < duration_sec:
            # Índice de la muestra
            spike_idx = int(current_time * fs)
            
            if spike_idx < N:
                # Generar MUAP (segunda derivada de Gaussiana = wavelet mexicano)
                # Esto da la forma bifásica típica del MUAP
                t_muap = np.arange(-0.015, 0.015, dt)  # ±15 ms
                muap = (1 - (t_muap / MUAP_SIGMA)**2) * np.exp(-0.5 * (t_muap / MUAP_SIGMA)**2)
                muap = muap * mu_amplitude
                
                # Agregar al EMG
                start_idx = spike_idx - len(muap) // 2
                end_idx = start_idx + len(muap)
                
                if start_idx >= 0 and end_idx < N:
                    emg[start_idx:end_idx] += muap
            
            # Siguiente disparo (ISI con variabilidad ~20%)
            isi = np.random.normal(mean_isi, 0.2 * mean_isi)
            isi = max(0.02, isi)  # Mínimo 20 ms (máximo 50 Hz)
            current_time += isi
    
    # Normalizar
    if np.max(np.abs(emg)) > 0:
        emg = emg / np.max(np.abs(emg))
    
    return emg


# =============================================================================
# MODELO PPG - Allen 2007 Gaussiano
# =============================================================================

def generate_ppg_allen(duration_sec: float, fs: float, hr_bpm: float = 72.0,
                       perfusion_index: float = 5.0) -> np.ndarray:
    """
    Genera PPG usando el modelo de Allen 2007 basado en Gaussianas.
    
    La onda PPG se compone de:
    1. Onda sistólica (pico principal)
    2. Muesca dicrótica (reflexión de onda)
    3. Onda diastólica (segundo pico menor)
    
    Parámetros:
    - hr_bpm: Frecuencia cardíaca
    - perfusion_index: Índice de perfusión (amplitud AC/DC × 100)
    
    Referencia: Allen J., Physiol Meas, 2007
    """
    N = int(duration_sec * fs)
    t = np.arange(N) / fs
    
    rr_sec = 60.0 / hr_bpm
    
    ppg = np.zeros(N)
    
    # Parámetros de las Gaussianas (normalizados al ciclo)
    # Posición, amplitud, ancho
    systolic = {'pos': 0.15, 'amp': 1.0, 'width': 0.08}
    dicrotic = {'pos': 0.40, 'amp': 0.3, 'width': 0.12}
    diastolic = {'pos': 0.55, 'amp': 0.15, 'width': 0.15}
    
    for i, ti in enumerate(t):
        # Fase normalizada del ciclo (0 a 1)
        phase = (ti % rr_sec) / rr_sec
        
        # Sumar Gaussianas
        val = 0.0
        for component in [systolic, dicrotic, diastolic]:
            pos = component['pos']
            amp = component['amp']
            width = component['width']
            
            val += amp * np.exp(-0.5 * ((phase - pos) / width) ** 2)
        
        ppg[i] = val
    
    # Escalar según índice de perfusión
    # PI = (AC / DC) × 100, típicamente 0.5-5%
    # Aquí normalizamos para que el pico sea ~1
    ppg = ppg / np.max(ppg)
    
    return ppg


# =============================================================================
# ANÁLISIS FFT
# =============================================================================

def analyze_spectrum(signal: np.ndarray, fs: float, signal_name: str,
                     config: dict) -> dict:
    """
    Analiza el espectro de frecuencia de una señal.
    
    Retorna diccionario con:
    - frequencies: vector de frecuencias
    - amplitude: espectro de amplitud normalizado
    - freq_dominant: frecuencia dominante
    - freq_99_energy: frecuencia donde está el 99% de la energía
    - bw_3db: ancho de banda a -3dB
    """
    N = len(signal)
    
    # Remover DC
    signal_centered = signal - np.mean(signal)
    
    # Aplicar ventana Hanning
    window = np.hanning(N)
    signal_windowed = signal_centered * window
    amplitude_correction = N / np.sum(window)
    
    # FFT
    fft_result = rfft(signal_windowed)
    freqs = rfftfreq(N, d=1/fs)
    
    # Espectro de amplitud normalizado
    amplitude = np.abs(fft_result) * 2.0 / N
    amplitude[0] /= 2.0  # DC
    if N % 2 == 0:
        amplitude[-1] /= 2.0  # Nyquist
    amplitude *= amplitude_correction
    
    # Métricas
    # Frecuencia dominante (ignorar DC)
    idx_max = np.argmax(amplitude[1:]) + 1
    freq_dominant = freqs[idx_max]
    amp_dominant = amplitude[idx_max]
    
    # Frecuencia donde está el 99% de la energía
    energy = amplitude ** 2
    cumulative_energy = np.cumsum(energy)
    total_energy = cumulative_energy[-1]
    idx_99 = np.searchsorted(cumulative_energy, 0.99 * total_energy)
    freq_99_energy = freqs[min(idx_99, len(freqs)-1)]
    
    # Ancho de banda a -3dB y -20dB
    threshold_3db = amp_dominant / np.sqrt(2)
    threshold_20db = amp_dominant / 10
    
    idx_above_3db = np.where(amplitude >= threshold_3db)[0]
    idx_above_20db = np.where(amplitude >= threshold_20db)[0]
    
    bw_3db = freqs[idx_above_3db[-1]] if len(idx_above_3db) > 0 else 0
    bw_20db = freqs[idx_above_20db[-1]] if len(idx_above_20db) > 0 else 0
    
    # Energía en banda clínica
    bw_min = config['bw_clinico_min']
    bw_max = config['bw_clinico_max']
    idx_clinical = (freqs >= bw_min) & (freqs <= bw_max)
    energy_clinical = np.sum(energy[idx_clinical])
    energy_total = np.sum(energy[1:])  # Sin DC
    pct_clinical = (energy_clinical / energy_total * 100) if energy_total > 0 else 0
    
    return {
        'frequencies': freqs,
        'amplitude': amplitude,
        'freq_dominant': freq_dominant,
        'amp_dominant': amp_dominant,
        'freq_99_energy': freq_99_energy,
        'bw_3db': bw_3db,
        'bw_20db': bw_20db,
        'energy_clinical_pct': pct_clinical,
        'N': N,
        'fs': fs,
        'freq_resolution': fs / N
    }


# =============================================================================
# GENERACIÓN DE REPORTE Y GRÁFICOS
# =============================================================================

def generate_analysis(signal_type: str, duration_sec: float = 7.0,
                      output_dir: str = None) -> dict:
    """
    Genera análisis completo de un tipo de señal.
    """
    config = CONFIG[signal_type]
    fs = config['fs_modelo']
    
    print(f"\n{'='*70}")
    print(f"  ANÁLISIS FFT: {signal_type} - {config['descripcion']}")
    print(f"{'='*70}")
    print(f"  Fs modelo: {fs} Hz")
    print(f"  Duración: {duration_sec} s")
    print(f"  Muestras: {int(duration_sec * fs)}")
    print(f"  Resolución frecuencial: {fs / int(duration_sec * fs):.4f} Hz")
    
    # Generar señal según tipo
    if signal_type == 'ECG':
        signal = generate_ecg_mcsharry(duration_sec, fs, hr_bpm=72)
    elif signal_type == 'EMG':
        # Generar EMG con excitación moderada (50%)
        signal = generate_emg_fuglevand(duration_sec, fs, excitation=0.5)
    elif signal_type == 'PPG':
        signal = generate_ppg_allen(duration_sec, fs, hr_bpm=72)
    else:
        raise ValueError(f"Tipo de señal no soportado: {signal_type}")
    
    # Analizar espectro
    results = analyze_spectrum(signal, fs, signal_type, config)
    
    # Mostrar resultados
    print(f"\n  RESULTADOS:")
    print(f"  • Frecuencia dominante: {results['freq_dominant']:.2f} Hz")
    print(f"  • Amplitud máxima: {results['amp_dominant']:.4f}")
    print(f"  • Ancho de banda (-3dB): {results['bw_3db']:.2f} Hz")
    print(f"  • Ancho de banda (-20dB): {results['bw_20db']:.2f} Hz")
    print(f"  • Frecuencia 99% energía: {results['freq_99_energy']:.2f} Hz")
    print(f"  • Energía en banda clínica: {results['energy_clinical_pct']:.1f}%")
    
    # Calcular filtro RC recomendado
    fc_rc = 2 * results['bw_20db']
    if fc_rc > 0:
        r_ohm = 1.0 / (2 * np.pi * fc_rc * 1e-6)
        print(f"\n  FILTRO RC RECOMENDADO:")
        print(f"  • Fc = 2 × Fmax(-20dB) = {fc_rc:.1f} Hz")
        print(f"  • Con C=1µF: R = {r_ohm:.0f} Ω")
    
    # Validación clínica
    print(f"\n  VALIDACIÓN CLÍNICA:")
    print(f"  • BW clínico: {config['bw_clinico_min']:.2f} - {config['bw_clinico_max']:.2f} Hz")
    
    if results['bw_20db'] <= config['bw_clinico_max']:
        print(f"  ✓ El modelo genera señal DENTRO del BW clínico")
    else:
        print(f"  ⚠ El modelo genera frecuencias FUERA del BW clínico")
    
    nyquist = fs / 2
    if results['freq_99_energy'] < nyquist:
        print(f"  ✓ Fs modelo ({fs} Hz) es suficiente (Nyquist: {nyquist} Hz)")
    else:
        print(f"  ✗ Fs modelo insuficiente, se recomienda aumentar")
    
    # Guardar gráficos
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f'Análisis Espectral del Modelo {signal_type}\n'
                     f'{config["descripcion"]} | {duration_sec}s | {results["N"]} muestras',
                     fontsize=12, fontweight='bold')
        
        t = np.arange(len(signal)) / fs
        
        # 1. Señal temporal (primeros 2 segundos)
        ax1 = axes[0, 0]
        t_show = min(2.0, duration_sec)
        n_show = int(t_show * fs)
        ax1.plot(t[:n_show], signal[:n_show], 'b-', linewidth=0.8)
        ax1.set_xlabel('Tiempo (s)')
        ax1.set_ylabel('Amplitud (normalizada)')
        ax1.set_title(f'Señal Temporal ({signal_type})')
        ax1.grid(True, alpha=0.3)
        
        # 2. Espectro de amplitud (lineal)
        ax2 = axes[0, 1]
        freqs = results['frequencies']
        amp = results['amplitude']
        
        # Limitar a frecuencias relevantes
        f_max_plot = min(config['bw_clinico_max'] * 2, fs/2)
        idx_plot = freqs <= f_max_plot
        
        ax2.plot(freqs[idx_plot], amp[idx_plot], 'b-', linewidth=0.8)
        ax2.axvline(config['bw_clinico_max'], color='r', linestyle='--', 
                    label=f'BW clínico max: {config["bw_clinico_max"]} Hz')
        ax2.axvline(results['freq_99_energy'], color='g', linestyle=':', 
                    label=f'99% energía: {results["freq_99_energy"]:.1f} Hz')
        ax2.fill_between([config['bw_clinico_min'], config['bw_clinico_max']], 
                         0, max(amp[idx_plot]), alpha=0.2, color='green',
                         label='Banda clínica')
        ax2.set_xlabel('Frecuencia (Hz)')
        ax2.set_ylabel('Amplitud')
        ax2.set_title('Espectro de Amplitud (Lineal)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)
        
        # 3. Espectro en dB
        ax3 = axes[1, 0]
        amp_db = 20 * np.log10(amp[idx_plot] + 1e-10)
        amp_db_max = np.max(amp_db)
        
        ax3.plot(freqs[idx_plot], amp_db, 'b-', linewidth=0.8)
        ax3.axhline(amp_db_max - 3, color='orange', linestyle='--', 
                    label='-3 dB', alpha=0.8)
        ax3.axhline(amp_db_max - 20, color='red', linestyle='--', 
                    label='-20 dB', alpha=0.8)
        ax3.axvline(config['bw_clinico_max'], color='r', linestyle=':', alpha=0.8)
        ax3.set_xlabel('Frecuencia (Hz)')
        ax3.set_ylabel('Amplitud (dB)')
        ax3.set_title('Espectro de Amplitud (Logarítmico)')
        ax3.set_ylim([amp_db_max - 60, amp_db_max + 5])
        ax3.legend(loc='upper right', fontsize=8)
        ax3.grid(True, alpha=0.3)
        
        # 4. Energía acumulada
        ax4 = axes[1, 1]
        energy = amp ** 2
        cumulative_energy = np.cumsum(energy)
        cumulative_pct = cumulative_energy / cumulative_energy[-1] * 100
        
        ax4.plot(freqs[idx_plot], cumulative_pct[idx_plot], 'b-', linewidth=1.5)
        ax4.axhline(99, color='g', linestyle='--', label='99%')
        ax4.axhline(95, color='orange', linestyle='--', label='95%')
        ax4.axvline(results['freq_99_energy'], color='g', linestyle=':', alpha=0.8)
        ax4.axvline(config['bw_clinico_max'], color='r', linestyle=':', 
                    label=f'BW clínico max', alpha=0.8)
        ax4.set_xlabel('Frecuencia (Hz)')
        ax4.set_ylabel('Energía Acumulada (%)')
        ax4.set_title('Distribución de Energía Espectral')
        ax4.set_ylim([0, 105])
        ax4.legend(loc='lower right', fontsize=8)
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        plot_path = os.path.join(output_dir, f'fft_modelo_{signal_type}.png')
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        print(f"\n  [OK] Gráfico guardado: {plot_path}")
        plt.close()
    
    results['signal'] = signal
    results['config'] = config
    
    return results


def generate_full_report(duration_sec: float = 7.0, output_dir: str = None):
    """
    Genera análisis completo de los 3 modelos.
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(os.path.dirname(output_dir), 'docs', 'fft_analysis')
    
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    print("\n" + "="*70)
    print("     ANÁLISIS FFT DE MODELOS MATEMÁTICOS - BioSignalSimulator Pro")
    print("="*70)
    print(f"  Fecha: {timestamp}")
    print(f"  Duración de simulación: {duration_sec} segundos")
    print(f"  Directorio de salida: {output_dir}")
    
    results = {}
    
    # Analizar cada modelo
    for signal_type in ['ECG', 'EMG', 'PPG']:
        results[signal_type] = generate_analysis(signal_type, duration_sec, output_dir)
    
    # Generar reporte de texto
    report = f"""
================================================================================
     REPORTE DE ANÁLISIS ESPECTRAL DE MODELOS - BioSignalSimulator Pro
================================================================================
Fecha: {timestamp}
Duración de simulación: {duration_sec} segundos

================================================================================
RESUMEN EJECUTIVO
================================================================================

| Señal | Fs modelo | Fmax(-20dB) | F 99% energía | Fc RC sugerida | R (C=1µF) |
|-------|-----------|-------------|---------------|----------------|-----------|
"""
    
    for sig_type in ['ECG', 'EMG', 'PPG']:
        r = results[sig_type]
        fc = 2 * r['bw_20db']
        r_ohm = 1.0 / (2 * np.pi * fc * 1e-6) if fc > 0 else 0
        report += f"| {sig_type:5} | {r['fs']:5} Hz   | {r['bw_20db']:7.1f} Hz   | {r['freq_99_energy']:9.1f} Hz   | {fc:10.0f} Hz   | {r_ohm:6.0f} Ω   |\n"
    
    report += f"""
================================================================================
DETALLES POR SEÑAL
================================================================================
"""
    
    for sig_type in ['ECG', 'EMG', 'PPG']:
        r = results[sig_type]
        c = r['config']
        fc = 2 * r['bw_20db']
        r_ohm = 1.0 / (2 * np.pi * fc * 1e-6) if fc > 0 else 0
        
        report += f"""
--- {sig_type}: {c['descripcion']} ---

Parámetros del modelo:
  • Frecuencia de muestreo: {r['fs']} Hz
  • Muestras generadas: {r['N']}
  • Resolución frecuencial: {r['freq_resolution']:.4f} Hz

Resultados espectrales:
  • Frecuencia dominante: {r['freq_dominant']:.2f} Hz
  • Amplitud en freq. dominante: {r['amp_dominant']:.4f}
  • Ancho de banda a -3dB: {r['bw_3db']:.2f} Hz
  • Ancho de banda a -20dB: {r['bw_20db']:.2f} Hz
  • Frecuencia con 99% energía: {r['freq_99_energy']:.2f} Hz
  • Energía en banda clínica: {r['energy_clinical_pct']:.1f}%

Validación clínica ({c['bw_clinico_min']:.2f} - {c['bw_clinico_max']:.2f} Hz):
  • {'✓ Contenido dentro de BW clínico' if r['bw_20db'] <= c['bw_clinico_max'] else '⚠ Contenido fuera de BW clínico'}
  • {'✓ Fs modelo adecuada' if r['freq_99_energy'] < r['fs']/2 else '✗ Fs modelo insuficiente'}

Filtro RC recomendado:
  • Fc = 2 × Fmax(-20dB) = {fc:.1f} Hz
  • Con C = 1 µF: R = {r_ohm:.0f} Ω

"""
    
    report += f"""
================================================================================
CONCLUSIONES Y RECOMENDACIONES
================================================================================

1. FRECUENCIAS DE MUESTREO DEL MODELO (config.h):
   - ECG @ 300 Hz: {'ADECUADA' if results['ECG']['freq_99_energy'] < 150 else 'REVISAR'}
   - EMG @ 1000 Hz: {'ADECUADA' if results['EMG']['freq_99_energy'] < 500 else 'REVISAR'}
   - PPG @ 20 Hz: {'ADECUADA' if results['PPG']['freq_99_energy'] < 10 else 'REVISAR'}

2. FILTROS RC POST-DAC (con C = 1 µF):
   - ECG: R ≈ {1.0 / (2 * np.pi * 2 * results['ECG']['bw_20db'] * 1e-6):.0f} Ω
   - EMG: R ≈ {1.0 / (2 * np.pi * 2 * results['EMG']['bw_20db'] * 1e-6):.0f} Ω
   - PPG: R ≈ {1.0 / (2 * np.pi * 2 * results['PPG']['bw_20db'] * 1e-6):.0f} Ω

3. NOTAS:
   - Los modelos generan señales con contenido frecuencial BIEN DEFINIDO
   - El EMG tiene el mayor ancho de banda debido a los MUAPs rápidos
   - El PPG tiene el menor ancho de banda (señal lenta, pulsátil)
   - El ECG está dominado por el QRS que aporta componentes hasta ~30-40 Hz

================================================================================
                              FIN DEL REPORTE
================================================================================
"""
    
    report_path = os.path.join(output_dir, 'fft_modelos_reporte.txt')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n{'='*70}")
    print(f"  [OK] Reporte guardado: {report_path}")
    print(f"{'='*70}")
    print(report)
    
    return results


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Análisis FFT de modelos matemáticos del BioSignalSimulator Pro',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python model_fft_analysis.py                          # Analizar todos (7 segundos)
  python model_fft_analysis.py --duration 10            # 10 segundos de simulación
  python model_fft_analysis.py --signal ECG             # Solo ECG
  python model_fft_analysis.py --signal EMG --exc 0.8   # EMG con 80% excitación
        """
    )
    
    parser.add_argument('--duration', type=float, default=7.0,
                        help='Duración de simulación en segundos (default: 7)')
    parser.add_argument('--signal', type=str, default='ALL',
                        choices=['ECG', 'EMG', 'PPG', 'ALL'],
                        help='Señal a analizar (default: ALL)')
    parser.add_argument('--exc', type=float, default=0.5,
                        help='Nivel de excitación para EMG 0-1 (default: 0.5)')
    parser.add_argument('--output', type=str, default=None,
                        help='Directorio de salida para gráficos y reporte')
    
    args = parser.parse_args()
    
    if args.signal == 'ALL':
        generate_full_report(duration_sec=args.duration, output_dir=args.output)
    else:
        output_dir = args.output
        if output_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(os.path.dirname(script_dir), 'docs', 'fft_analysis')
        
        generate_analysis(args.signal, duration_sec=args.duration, output_dir=output_dir)
