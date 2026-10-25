import pymupdf as fitz, sys
out = sys.argv[1]
doc = fitz.open()
p = doc.new_page()
p.insert_text((72, 90), "Contratto di prova tk-pdf", fontsize=22, fontname="hebo")
p.insert_text((72, 130), "Il cliente Mario Rossi accetta le condizioni riportate qui sotto.", fontsize=12)
p.insert_text((72, 150), "Importo totale: 1.250,00 euro - Scadenza: 30/09/2026", fontsize=12)
tw = fitz.Widget(); tw.field_name="nome"; tw.field_type=fitz.PDF_WIDGET_TYPE_TEXT; tw.rect=fitz.Rect(72,200,300,222); tw.text_fontsize=11; tw.field_value=""
p.add_widget(tw)
cb = fitz.Widget(); cb.field_name="accetto"; cb.field_type=fitz.PDF_WIDGET_TYPE_CHECKBOX; cb.rect=fitz.Rect(72,240,88,256); cb.field_value=False
p.add_widget(cb)
co = fitz.Widget(); co.field_name="pagamento"; co.field_type=fitz.PDF_WIDGET_TYPE_COMBOBOX; co.rect=fitz.Rect(72,270,250,292); co.choice_values=["Bonifico","Contanti","Carta"]; co.field_value="Bonifico"
p.add_widget(co)
for i in range(2, 6):
    pg = doc.new_page()
    pg.insert_text((72, 100), f"Pagina numero {i}", fontsize=28)
    pg.insert_textbox(fitz.Rect(72,140,520,700), ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30), fontsize=11)
doc[3].set_rotation(90)
doc.save(out)
print("ok", doc.page_count)
