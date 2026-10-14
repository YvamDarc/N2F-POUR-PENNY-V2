import hashlib
import io
import zipfile
import streamlit as st
from convertisseur import parse,convert,default_account,csv_bytes,money,fmt
from pieces import load_documents,inventory,make_bundle

st.set_page_config(page_title='N2F → Pennylane · FEC et PJ',page_icon='📎',layout='wide')
st.title('N2F → Pennylane · FEC et justificatifs')
st.caption('Version 2 · Streamlit Community Cloud')
st.info('Les fichiers sont traités sur le serveur Streamlit, en mémoire pour votre session. Cette application n’écrit pas vos données sur disque et n’utilise aucun cache partagé.')
if st.button('Vider la session et les fichiers'):
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()
csv_uploads=st.file_uploader('1. Exports comptables N2F — un seul dossier',type=['csv'],accept_multiple_files=True,key='csvs')
pdf_uploads=st.file_uploader('2. Rapports avec justificatifs — ZIP ou PDF',type=['zip','pdf'],accept_multiple_files=True,key='pdfs')
st.caption('Les PDF seuls ne suffisent pas à reprendre les comptes, les dates comptables et les moyens de paiement. Ajoutez les CSV correspondants. Les archives contenant plusieurs PDF du même nom sont prises en charge.')
try:
    docs=[]
    if pdf_uploads:
        pdf_signature=tuple((f.name,hashlib.sha256(f.getvalue()).hexdigest()) for f in pdf_uploads)
        if st.session_state.get('pdf_signature')!=pdf_signature:
            with st.spinner('Lecture des rapports N2F…'):
                docs,notices=load_documents([(f.name,f.getvalue()) for f in pdf_uploads])
            st.session_state['pdf_signature']=pdf_signature
            st.session_state['documents']=docs
            st.session_state['pdf_notices']=notices
        docs=st.session_state['documents']
        st.subheader('Rapports détectés')
        st.dataframe(inventory(docs),hide_index=True,use_container_width=True)
        for notice in st.session_state.get('pdf_notices',[]):st.warning(notice)
        if any(d['reimbursable']==0 and d['total'] for d in docs):
            st.warning('Certaines notes ont un total remboursable nul : elles peuvent être payées par l’entreprise. Vérifiez les comptes de contrepartie du CSV ; aucun 467 n’est créé à partir des PDF.')
    else:
        for key in ('pdf_signature','documents','pdf_notices'):
            st.session_state.pop(key,None)
    if not csv_uploads:
        st.info('Ajoutez les CSV correspondant aux notes ci-dessus pour produire les écritures et associer les PDF.')
        st.stop()
    files=[(f.name,f.getvalue()) for f in csv_uploads]
    if len({name for name,_ in files})!=len(files):
        raise ValueError('Deux CSV ont le même nom : renommez-les pour permettre un contrôle sans ambiguïté.')
    accounts=sorted({r['account'] for _,data in files for r in parse(data)})
    st.subheader('3. Comptes et découpage')
    st.write('FPROLIANS devient **401PROLIANS**, FGOOGLE devient **401GOOGLE**. Vous pouvez reprendre vos comptes Pennylane ci-dessous.')
    edited=st.data_editor([{'Compte N2F':a,'Compte Pennylane':default_account(a)} for a in accounts],disabled=['Compte N2F'],hide_index=True,key='accounts_'+hashlib.sha256(repr(accounts).encode()).hexdigest()[:12])
    mapping={r['Compte N2F']:r['Compte Pennylane'] for r in edited}
    split=st.checkbox('Séparer les notes de frais par libellé équilibré',value=False,help='Par défaut : une pièce par fichier/date/journal, adaptée au PDF de note complet. En détail : les libellés identiques restent regroupés ; le PDF entier sera répété pour chaque pièce associée.')
    out,audit,summaries,warnings=convert(files,mapping,split)
    st.dataframe(summaries,hide_index=True,use_container_width=True)
    for w in warnings:st.warning(w)
    st.write('**Libellés conservés :** l’export de type FEC garde le libellé original de chaque ligne. Le CSV Pennylane réunit les libellés de la pièce en un libellé commun descriptif, pour éviter un découpage non équilibré à l’import.')
    if any(len(r['Libellé écriture'])>250 for r in out):
        st.warning('Certaines pièces ont un libellé commun long. Aucune troncature n’est appliquée. Le mode par libellé peut réduire sa longueur ; le FEC conserve les textes ligne par ligne.')
    refs=list(dict.fromkeys(r['PieceRef'] for r in out))
    docmap={d['id']:d for d in docs}
    def doc_label(ident):
        if not ident:return '— Sans pièce jointe —'
        d=docmap[ident]
        return f"Note {d['note'] or '?'} · {d['person'] or d['name']} · {d['period']} · TTC {fmt(d['total']) if d['total'] is not None else '?'} € · {ident[:6]}"
    st.subheader('4. Associer les justificatifs')
    st.caption('Chaque association est choisie explicitement. Un montant égal est seulement un indice. Le PDF complet sera renommé selon la référence de pièce, sans modifier son contenu.')
    links={}
    issues=[]
    for ref in refs:
        group=[r for r in out if r['PieceRef']==ref]
        source=next(a['Fichier'] for a in audit if a['PieceRef']==ref)
        total=sum(money(r['Débit']) for r in group)
        with st.expander(f"{source} · {group[0]['Date']} · {fmt(total)} € · {ref[-3:]}"):
            st.caption(ref)
            st.write(group[0]['Libellé écriture'])
            if docs:
                equal=[d for d in docs if d['total']==total]
                if equal:st.caption('Même montant (à vérifier) : '+', '.join('note '+d['note'] for d in equal))
                ident=st.selectbox('Rapport PDF associé',['']+list(docmap),format_func=doc_label,key='link_'+ref+'_'+hashlib.sha256(repr(list(docmap)).encode()).hexdigest()[:8])
                if ident:
                    links[ref]=ident
                    d=docmap[ident]
                    if d['total'] is None or d['total']!=total:
                        msg=f"{ref} : total PDF {fmt(d['total']) if d['total'] is not None else 'inconnu'} € / pièce comptable {fmt(total)} €."
                        issues.append(msg);st.warning(msg)
                    if d['period']:
                        from datetime import datetime
                        start,end=[datetime.strptime(s,'%d/%m/%Y') for s in d['period'].split(' → ')]
                        date=datetime.strptime(group[0]['Date'],'%d/%m/%Y')
                        if not start<=date<=end:
                            msg=f'{ref} : date comptable hors période du rapport. Un décalage de comptabilisation est possible ; vérifier.'
                            issues.append(msg);st.warning(msg)
            else:st.caption('Ajoutez un ZIP/PDF pour joindre le justificatif.')
    st.write(f'**{len(links)} / {len(refs)} pièces associées.** Les autres écritures seront exportées sans PJ.')
    used=set(links.values())
    if docs:st.caption(f'{len(docs)-len(used)} PDF non utilisés : ils seront listés dans l’inventaire, sans être joints aux écritures.')
    review=st.checkbox('J’ai vérifié les comptes, les associations de PJ, les dates et l’absence d’import antérieur.')
    acknowledge=True
    if issues:acknowledge=st.checkbox('Je confirme les associations malgré les écarts de montant ou de période signalés.')
    signature=hashlib.sha256(repr(([(n,hashlib.sha256(b).hexdigest()) for n,b in files],mapping,split,links,[d['id'] for d in docs])).encode()).hexdigest()
    if st.session_state.get('package_signature')!=signature:
        st.session_state.pop('package',None)
    if st.button('Préparer le pack écritures + PJ',type='primary',disabled=not(review and acknowledge)):
        with st.spinner('Préparation du ZIP…'):
            st.session_state['package']=make_bundle(out,audit,summaries,warnings+issues,docs,links)
            st.session_state['package_signature']=signature
    if 'package' in st.session_state and review and acknowledge:
        st.download_button('Télécharger le pack écritures + PJ',st.session_state['package'],'N2F_Pennylane_FEC_PJ.zip','application/zip')
    with st.expander('Contenu du pack et procédure Pennylane'):
        st.markdown('''- **Ecritures_type_FEC.txt** : 18 colonnes, libellés de ligne originaux, références stables.
- **Import_Pennylane.csv** : alternative avec libellé commun descriptif par pièce.
- **PJ.zip** : PDF renommés exactement comme PieceRef, avec l’extension .pdf.
- Contrôles des lignes, fichiers et associations ; inventaire des PDF.

Importez **un seul** des deux fichiers comptables. Le CSV est destiné à Saisie → Imports → Écritures ; associez PieceRef au numéro de pièce. Joignez ensuite PJ.zip. Le FEC détaillé nécessite un regroupement par numéro d’écriture/pièce : si Pennylane impose le même libellé par pièce, utilisez le CSV alternatif.

Ce fichier de type FEC est un support d’import partiel, pas un FEC fiscal conforme : libellés des comptes, dates de pièces et de validation absents ne sont pas inventés. Aucun import réel n’a été exécuté dans votre dossier.''')
        st.link_button('Documentation Pennylane','https://help.pennylane.com/fr/articles/18793-importer-des-ecritures')
except Exception as exc:
    st.error(f'Traitement interrompu : {exc}')
    st.stop()
