"""Lecture des rapports N2F. Les PDF sont recopiés sans modification."""
import hashlib
import io
import re
import zipfile
from datetime import datetime
from pypdf import PdfReader
from convertisseur import money, fmt, fec_bytes, csv_bytes, FIELDS

MAX_BYTES = 350 * 1024 * 1024

def describe(name, data, origin):
    key = hashlib.sha256(data).hexdigest()
    result = dict(id=key, name=name, origin=origin, data=data, note='', person='', period='', total=None, reimbursable=None, pages=0, warning='')
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError('PDF protégé')
        result['pages'] = len(reader.pages)
        text = '\n'.join(p.extract_text() or '' for p in reader.pages[:5])
        lines = text.splitlines()
        result['person'] = lines[0].strip() if lines else ''
        note = re.search(r'Note de frais n[°º]\s*(\d+)',text)
        result['note'] = note.group(1) if note else ''
        total = re.search(r'Total\s+\d+\s+([\d\s,.]+)\s*€\s+([\d\s,.]+)\s*€\s+([\d\s,.]+)\s*€',text)
        if total:
            result['total'] = money(total.group(3))
        rem = re.search(r'Total remboursable\s*:\s*([\d\s,.]+)\s*€',text)
        if rem:
            result['reimbursable'] = money(rem.group(1))
        period = re.search(r'du\s+(\d{2}/\d{2}/\d{4})\s+au\s+(\d{2}/\d{2}/\d{4})',text)
        if period:
            result['period'] = period.group(1)+' → '+period.group(2)
        if not note:
            result['warning'] = 'Numéro de note non détecté : vérifier le PDF.'
    except Exception as e:
        result['warning'] = f'Lecture des métadonnées impossible ({type(e).__name__}). Association manuelle possible.'
    return result

def load_documents(files):
    docs, notices, seen = [], [], set()
    consumed = 0
    for filename, data in files:
        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                entries = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.pdf')]
                if len(entries) > 500:
                    raise ValueError('Plus de 500 PDF dans une archive.')
                for index, entry in enumerate(entries):
                    consumed += entry.file_size
                    if consumed > MAX_BYTES:
                        raise ValueError('Les PDF décompressés dépassent 350 Mo. Réduire le lot.')
                    # Lire ZipInfo, jamais le nom : les noms sont parfois dupliqués.
                    payload = z.read(entry)
                    key = hashlib.sha256(payload).hexdigest()
                    if key in seen:
                        notices.append(f'Copie exacte ignorée : {entry.filename}')
                        continue
                    seen.add(key)
                    docs.append(describe(entry.filename,payload,f'{filename} / entrée {index+1}'))
        elif filename.lower().endswith('.pdf'):
            consumed += len(data)
            if consumed > MAX_BYTES:
                raise ValueError('Les PDF dépassent 350 Mo.')
            key = hashlib.sha256(data).hexdigest()
            if key in seen:
                notices.append(f'Copie exacte ignorée : {filename}')
                continue
            seen.add(key)
            docs.append(describe(filename,data,filename))
        else:
            raise ValueError('Justificatifs attendus en PDF ou ZIP de PDF.')
    return docs, notices

def inventory(docs):
    return [dict(Document=d['id'][:12],Fichier=d['name'],Note=d['note'],Collaborateur=d['person'],Periode=d['period'],
                 TTC=fmt(d['total']) if d['total'] is not None else '',
                 Remboursable=fmt(d['reimbursable']) if d['reimbursable'] is not None else '',Pages=d['pages'],Alerte=d['warning']) for d in docs]

def make_bundle(output,audit,summaries,warnings,docs,links):
    """links = {reference_source: id_pdf}. Les autres références restent sans PJ."""
    docmap = {d['id']:d for d in docs}
    known = {r['PieceRef'] for r in output}
    if any(ref not in known or ident not in docmap for ref,ident in links.items()):
        raise ValueError('Association de PJ inconnue.')
    renamed = {}
    for ref, ident in links.items():
        d = docmap[ident]
        # Conserver l'identifiant unique de l'écriture même si un PDF sert à plusieurs pièces.
        renamed[ref] = f"NDF{d['note']}-{ref[4:]}" if d['note'] else ref
    out = [dict(r,PieceRef=renamed.get(r['PieceRef'],r['PieceRef'])) for r in output]
    aud = [dict(r,PieceRef=renamed.get(r['PieceRef'],r['PieceRef'])) for r in audit]
    estimate = sum(len(docmap[ident]['data']) for ident in links.values())
    if estimate > MAX_BYTES:
        raise ValueError('Les PJ répétées dépassent 350 Mo. Utiliser le regroupement par note ou réduire le lot.')
    attachments = io.BytesIO()
    association=[]
    with zipfile.ZipFile(attachments,'w',zipfile.ZIP_DEFLATED) as z:
        for ref in dict.fromkeys(r['PieceRef'] for r in output):
            ident=links.get(ref)
            if ident:
                d=docmap[ident];target=renamed.get(ref,ref)
                z.writestr(target+'.pdf',d['data'])
                association.append(dict(PieceRef=target,PDF=d['name'],Note=d['note'],Statut='Associée'))
            else:
                association.append(dict(PieceRef=ref,PDF='',Note='',Statut='Sans PJ'))
    package=io.BytesIO()
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('Ecritures_type_FEC.txt',fec_bytes(out,aud))
        z.writestr('Import_Pennylane.csv',csv_bytes(out,FIELDS))
        if links:
            z.writestr('PJ.zip',attachments.getvalue())
        z.writestr('Controle_lignes.csv',csv_bytes(aud))
        z.writestr('Controle_fichiers.csv',csv_bytes(summaries))
        z.writestr('Correspondance_PJ.csv',csv_bytes(association))
        if docs:
            z.writestr('Inventaire_PDF.csv',csv_bytes(inventory(docs)))
        z.writestr('LIRE_AVANT_IMPORT.txt',
            'Importer UN SEUL fichier comptable : Import_Pennylane.csv (libellé commun descriptif par pièce) OU Ecritures_type_FEC.txt (libellés de ligne originaux). Ne pas importer les deux.\n'
            'Le type FEC est partiel : CompteLib, PieceDate, ValidDate et autres données absentes restent vides. Il ne constitue pas un FEC fiscal conforme.\n'
            'Le CSV est destiné à Saisie > Imports > Écritures. Joindre ensuite PJ.zip ; les PDF portent exactement la PieceRef sans extension.\n'
            'Le FEC détaillé nécessite un regroupement par EcritureNum/PieceRef ; si le mapping Pennylane sépare par libellé, utiliser le CSV commun. Import réel non testé.\n'
            'Les PDF entiers sont préservés, pas découpés ticket par ticket. Les pièces non associées sont signalées dans Correspondance_PJ.csv.\n'
            'Les numéros N2F enrichissent les références, avec un suffixe technique pour éviter les collisions.\n\n'+'\n'.join(warnings))
    return package.getvalue()
