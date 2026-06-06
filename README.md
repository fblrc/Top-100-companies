# Dashboard top societa' — fondamentali, rischio, tecnica

Dashboard auto-aggiornante delle maggiori societa' quotate per capitalizzazione.
Fonte dati gratuita (Yahoo Finance via `yfinance`); classifica ricostruita a ogni
esecuzione da stockanalysis.com. Pubblicata su GitHub Pages tramite GitHub Actions.

## Struttura del repository

```
.
├── dashboard.py                 # lo script (mettilo nella root)
├── requirements.txt
└── .github/
    └── workflows/
        └── build.yml
```

## Setup (una volta sola)

1. Crea un repository **pubblico** su GitHub e carica i tre file qui sopra.
2. Vai su **Settings → Pages** e imposta **Source: GitHub Actions**.
3. Vai sul tab **Actions**, apri *Build & deploy dashboard* e premi **Run workflow**
   (oppure fai un push su `main`).
4. Al termine del job `deploy` compare l'URL pubblico (es.
   `https://<utente>.github.io/<repo>/`).

## Aggiornamento

- **Automatico**: ogni giorno feriale alle 23:00 UTC (dopo la chiusura USA).
  Modifica la riga `cron` in `build.yml` per cambiare orario/frequenza.
- **Manuale**: tab Actions → Run workflow.

Ogni esecuzione produce uno **snapshot** ai prezzi di chiusura del giorno: la
pagina non e' "in tempo reale", si aggiorna a ogni run.

## Parametri utili

Nel workflow, riga `python dashboard.py ...`:

- `--top 50` invece di `--top 100` per alleggerire la pagina (~7 MB → ~3,5 MB).
- `--benchmark SPY` per calcolare il beta vs S&P 500 invece di MSCI ACWI.
- `--static` per usare la lista di riserva integrata (salta lo scraping della
  classifica): utile se stockanalysis.com non risponde dal runner.

## Limiti (onesti)

- La classifica include le societa' **quotate negli USA** (anche ADR estere come
  TSM, ASML, SAP, NVO, BABA): titoli solo esteri senza ADR (es. Saudi Aramco) non
  compaiono. In cambio ogni ticker e' compatibile con la fonte dati.
- `.info` di Yahoo e' non ufficiale: campi mancanti/incoerenti sono possibili.
- Beta e correlazione sono calcolati sui giorni di trading comuni e sono
  instabili nel tempo.
- Lo **Score composito** e i campi Tecnico/Valutazione sono una sintesi MECCANICA
  e trasparente degli indicatori, **non** una raccomandazione di acquisto/vendita
  e **non** una previsione. Non e' consulenza finanziaria.

## Nota

La dashboard pubblicata e' visibile a chiunque abbia l'URL. Usa solo dati di
mercato pubblici, quindi non espone nulla di privato.
