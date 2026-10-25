"""Software libero, donazione e licenze di tk-pdf.

Dalla 1.1.0 tk-pdf è software libero (AGPL-3.0) con tutte le funzioni per tutti: niente Pro, niente chiavi.
Qui restano la donazione libera («Offrimi un caffè»), il benvenuto del primo avvio e i testi delle licenze
(vedi tk_licenza.py e tk_licenza_qt.py, uguali in tutti i software TK).
"""
from PySide6.QtWidgets import QApplication

from tkpdf import VERSION
from tkpdf.util import resource_path

# codice sorgente esatto di questa versione (tag v<versione> sul repo pubblico)
URL_SORGENTE = "https://github.com/tecnikgeek-repo/tk-pdf-desktop/tree/v" + VERSION


def licenza():
    return getattr(QApplication.instance(), "licenza", None)


def _logo():
    from PySide6.QtGui import QPixmap
    from tkpdf.icon import render_icon
    return QPixmap.fromImage(render_icon(104))


def cartella_licenze():
    """Cartella `licenze/` del pacchetto (accanto a run.py; sul Mac in Contents/Resources)."""
    return resource_path("licenze")


def benvenuto(parent=None):
    """Prima apertura: software libero, nessuna garanzia, privacy e consenso alle statistiche (una volta sola)."""
    try:
        from tkpdf.tk_licenza_qt import benvenuto as mostra
        mostra(licenza(), "tk-pdf", URL_SORGENTE, parent=parent, logo=_logo())
    except Exception:
        pass


def mostra_licenze(parent=None):
    from tkpdf.tk_licenza_qt import LicenzeDialog
    LicenzeDialog("tk-pdf", VERSION, URL_SORGENTE, cartella_licenze(), parent).exec()


def casella_statistiche():
    from tkpdf.tk_licenza_qt import casella_statistiche as crea
    return crea(licenza())


def pulsante_caffe(nome_oggetto=""):
    from tkpdf.tk_licenza_qt import pulsante_caffe as crea
    return crea(licenza(), nome_oggetto=nome_oggetto)


def invito(parent=None, puo_mostrare=None):
    """Invito al caffè all'avvio: la prima volta e poi al massimo una volta al mese (vedi tk_licenza_qt)."""
    try:
        from tkpdf.tk_licenza_qt import invito_caffe
        invito_caffe(licenza(), "tk-pdf", parent, _logo(), puo_mostrare)
    except Exception:
        pass
