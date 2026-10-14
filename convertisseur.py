"""Conversion du format N2F observé : date;journal;compte;libellé;débit;crédit;."""
import csv
import io
import re
import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

FIELDS = ['Date', 'Code journal', 'Numéro de compte', 'Libellé écriture', 'Débit', 'Crédit', 'PieceRef']

def money(value):
    value = value.strip().replace('\u00a0', '').replace('\u202f', '').replace(' ', '').replace(',', '.')
    try:
        n = Decimal(value or '0')
    except InvalidOperation:
        raise ValueError(f'Montant invalide : {value!r}')
    if not n.is_finite() or n != n.quantize(Decimal('.01')) or n < 0:
        raise ValueError(f'Montant négatif, non fini ou avec plus de deux décimales : {value}')
    return int(n * 100)

def parse(data):
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('Encodage non reconnu (UTF-8 ou Windows-1252 attendu).')
    rows = []
    for line, raw in enumerate(csv.reader(io.StringIO(text, newline=''), delimiter=';'), 1):
        if not raw or not any(x.strip() for x in raw):
            continue
        if len(raw) not in (6, 7) or (len(raw) == 7 and raw[6].strip()):
            raise ValueError(f'Ligne {line} : 6 colonnes et une éventuelle colonne finale vide attendues.')
        date, journal, account, label, debit, credit = [x.strip() for x in raw[:6]]
        try:
            date = datetime.strptime(date, '%d/%m/%Y').strftime('%d/%m/%Y')
        except ValueError:
            raise ValueError(f'Ligne {line} : date invalide {date!r}. Export sans en-têtes attendu.')
        if not re.fullmatch('[A-Za-z]{1,5}', journal) or not account or not label:
            raise ValueError(f'Ligne {line} : journal, compte ou libellé invalide.')
        d, c = money(debit), money(credit)
        if (d and c) or not (d or c):
            raise ValueError(f'Ligne {line} : renseigner un seul côté non nul.')
        rows.append(dict(date=date, journal=journal, account=account, label=label, debit=d, credit=c, line=line))
    if not rows:
        raise ValueError('Fichier vide.')
    return rows

def fingerprint(rows):
    return hashlib.sha256(repr([tuple(r[k] for k in ('date','journal','account','label','debit','credit')) for r in rows]).encode()).hexdigest()[:16].upper()

def fmt(cents):
    return f'{cents // 100},{cents % 100:02d}'

def csv_bytes(rows, fields=None):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=fields or list(rows[0]), delimiter=';', lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode('utf-8-sig')

def default_account(source):
    return '401' + source[1:] if source.startswith('F') else source

def convert(files, mapping=None, split_labels=False):
    """files: liste de (nom, octets). Échec intégral si une écriture est déséquilibrée."""
    mapping = mapping or {}
    output, audit, summaries, warnings = [], [], [], []
    seen = set()
    for name, data in files:
        rows = parse(data)
        key = fingerprint(rows)
        if key in seen:
            raise ValueError(f'{name} : fichier identique déjà présent dans le lot, même après renommage.')
        seen.add(key)
        groups = []
        if all(r['journal'] == 'FG' and r['account'].isdigit() for r in rows):
            buckets = defaultdict(list)
            for r in rows:
                buckets[(r['date'], r['journal'])].append(r)
            for bucket in buckets.values():
                by_label = defaultdict(list)
                for row in bucket:
                    by_label[row['label']].append(row)
                if split_labels and all(sum(r['debit']-r['credit'] for r in g)==0 for g in by_label.values()):
                    groups.extend(by_label.values())
                    warnings.append(f'{name} : séparation par libellé équilibré. Des dépenses au même libellé restent regroupées.')
                else:
                    groups.append(bucket)
                    if split_labels:
                        warnings.append(f'{name} : séparation par libellé impossible ; conservation du groupe fichier/date/journal équilibré.')
        elif all(r['journal'] == 'AC' for r in rows):
            for r in rows:
                if r['account'].startswith('F'):
                    groups.append([])
                if not groups:
                    raise ValueError(f'{name} : achat sans ligne fournisseur F en tête.')
                groups[-1].append(r)
        else:
            raise ValueError(f'{name} : format non pris en charge. Attendu : FG numérique ou AC avec fournisseurs F.')
        for index, group in enumerate(groups, 1):
            if len({(r['date'], r['journal']) for r in group}) != 1:
                raise ValueError(f'{name} : dates/journaux différents dans la pièce {index}.')
            d, c = sum(r['debit'] for r in group), sum(r['credit'] for r in group)
            if d != c:
                raise ValueError(f'{name}, pièce {index} : débit {fmt(d)}, crédit {fmt(c)}. Aucune correction automatique.')
            ref = f'N2F-{key}-{index:03d}'
            # Pennylane demande un libellé commun par pièce : préserver les
            # descriptions en les réunissant, au lieu de les remplacer par le fichier.
            labels = list(dict.fromkeys(r['label'] for r in group))
            label = ' | '.join(labels)
            for r in group:
                source = r['account']
                target = str(mapping.get(source, default_account(source))).strip()
                if not re.fullmatch(r'[A-Za-z0-9]+', target) or not (target.isdigit() or target.startswith(('401','411','410','421','455','467'))):
                    raise ValueError(f'Compte cible invalide : {target!r}')
                out = dict(zip(FIELDS, [r['date'],r['journal'],target,label,fmt(r['debit']),fmt(r['credit']),ref]))
                output.append(out)
                audit.append(dict(Fichier=name,Ligne=r['line'],PieceRef=ref,CompteSource=source,CompteCible=target,LibelleSource=r['label'],Debit=fmt(r['debit']),Credit=fmt(r['credit'])))
        total = sum(r['debit'] for r in rows)
        summaries.append(dict(Fichier=name,Lignes=len(rows),Ecritures=len(groups),Debit=fmt(total),Credit=fmt(total),Dates=' / '.join(sorted({r['date'] for r in rows}))))
        amounts = re.findall(r'(\d[\d ]*,\d{2})\s*€', name)
        if amounts and money(amounts[-1]) != total:
            warnings.append(f'{name} : nom du fichier = {amounts[-1]} €, total comptable = {fmt(total)} €. Montants sources conservés.')
        if any(r['account'].startswith('471') for r in rows):
            warnings.append(f'{name} : compte 471 présent, affectation à revoir si nécessaire.')
    return output, audit, summaries, warnings

FEC_FIELDS = ['JournalCode','JournalLib','EcritureNum','EcritureDate','CompteNum','CompteLib','CompAuxNum','CompAuxLib','PieceRef','PieceDate','EcritureLib','Debit','Credit','EcritureLet','DateLet','ValidDate','Montantdevise','Idevise']

def fec_bytes(output, audit):
    """Structure FEC pour import, non FEC fiscal certifié : données absentes non inventées."""
    if len(output) != len(audit):
        raise ValueError('Contrôle des lignes incohérent.')
    buffer = io.StringIO(newline='')
    w = csv.DictWriter(buffer, fieldnames=FEC_FIELDS, delimiter='\t', lineterminator='\r\n')
    w.writeheader()
    for r, a in zip(output, audit):
        date = datetime.strptime(r['Date'], '%d/%m/%Y').strftime('%Y%m%d')
        f = dict.fromkeys(FEC_FIELDS, '')
        f.update(JournalCode=r['Code journal'], JournalLib={'FG':'Frais généraux','AC':'Achats'}.get(r['Code journal'],r['Code journal']),
                 EcritureNum=r['PieceRef'], EcritureDate=date, CompteNum=r['Numéro de compte'],
                 PieceRef=r['PieceRef'], EcritureLib=a['LibelleSource'], Debit=r['Débit'], Credit=r['Crédit'])
        w.writerow(f)
    return buffer.getvalue().encode('utf-8-sig')
