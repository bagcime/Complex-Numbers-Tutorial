# app.py
from flask import Flask, render_template_string, request, session, redirect, url_for
import pandas as pd
import json
from pathlib import Path
import re
import os
from pathlib import Path

# -----------------------------
# Helpers (backend)
# -----------------------------
def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(s).lower())

def resolve_lab_aliases(df_columns):
    cols_norm = {_norm(c): c for c in df_columns}
    def pick(*candidates, tokens=None):
        for cand in candidates:
            nc = _norm(cand)
            if nc in cols_norm:
                return cols_norm[nc]
        if tokens:
            toks = [_norm(t) for t in tokens]
            for n, orig in cols_norm.items():
                if all(t in n for t in toks):
                    return orig
        return None
    return {
        "DATE_DIF": pick("DATE_DIF", "ENCDATEDIFFNO", "DATE_DIFFNO", "DATE_DIFF", tokens=["date","dif"]),
        "Absolute Basophils":    pick("Absolute Basophils", tokens=["baso","abs"]),
        "Absolute Eosinophils":  pick("Absolute Eosinophils", tokens=["eosin","abs"]),
        "Absolute Lymphocytes":  pick("Absolute Lymphocytes", tokens=["lymph","abs"]),
        "Absolute Neutrophils":  pick("Absolute Neutrophils", tokens=["neut","abs"]),
        "FEV1 PRE":              pick("FEV1 PRE", "FEV1_PRE", tokens=["fev1","pre"]),
        "FEV1/FVC PRE":          pick("FEV1/FVC PRE", "FEV1_FVC PRE", "FEV1/FVC_PRE", "FEV1_FVC_PRE", tokens=["fev1","fvc","pre"]),
        "FEF25-75% PRE":         pick("FEF25-75% PRE", "FEF25-75 PRE", "FEF25_75 PRE", "FEF2575 PRE", tokens=["fef","25","75","pre"]),
        "FEV1 %PRE PRED":        pick("FEV1 %PRE PRED", "FEV1 % PRED PRE", "FEV1 PERCENT PRED PRE", "FEV1 %PRED PRE", tokens=["fev1","pred","pre"]),
        "ATS_SEVERE":            pick("ATS_SEVERE", "ATS SEVERE", tokens=["ats","severe"]),
    }

def try_float(x):
    try:
        if pd.isna(x):
            return None
        v = float(str(x).strip())
        return int(v) if abs(v - int(v)) < 1e-9 else v
    except Exception:
        s = str(x).strip()
        return s if s else None

def try_01(x):
    if pd.isna(x):
        return None
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y"}: return 1
    if s in {"0", "false", "no", "n"}:  return 0
    try:
        v = float(s)
        return 1 if v >= 0.5 else 0
    except Exception:
        return None

SECTION_HEADS = [
    r'Chief Complaint\(s\)', r'HPI', r'Review of Systems', r'Physical Exam',
    r'ASSESSMENT AND PLAN', r'Surgical History', r'Family History',
    r'Social History', r'Medications', r'Allergies', r'Vital Signs',
    r'ORDERS GENERATED DURING THIS VISIT'
]
SECTION_RE = re.compile(r'(' + r'|'.join(SECTION_HEADS) + r')', re.I)

def make_friendly_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    t = re.sub(r'\s+', ' ', text).strip()
    t = re.sub(r'\([^)]*\)', '', t)  # remove (...) content
    t = t.replace(".,", ". ").replace(",.", ". ").replace("..", ". ")
    t = re.sub(r'\s*,\s*,\s*', ', ', t)
    t = SECTION_RE.sub(r'\n\n\1\n', t)
    t = re.sub(r'\s*•\s*', r'\n• ', t)
    t = re.sub(r'\s+-\s+', r'\n- ', t)
    t = re.sub(r'\.\s+([A-Z<])', r'.\n\1', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

# -----------------------------
# Data (paths + columns)
# -----------------------------
Candidate_patients = [
    '093677e8732d9be5f6a454c94a9ab24b2e2488844d136cdb1b051726de0496a0', '1068c536d79911f22f1b79eb2d95024e503d21bacef2f89a4fc8880f66f542c7',
    '11ae630785f0b15a0c0e7f1fbe9c9db3381b4f86e7a5113a3378a47c02378fa8', '12d3a4264383bea4cb277f0a59a369af7da29399818f77a350d14f18d63c75c1',
    '186568ce6a00d28f1795832a4d4d3ce5ed13a2b4aa08032c5892f736d54c940a', '1998cb928ae8cb19d6f2b0cdcb9d98d268432a2ce55aa5dabdc6ca390d90aee4',
    '21dab5fdab7758150ed7732b1c2cc6577994c1eff7b5d19079ff05bc7d8e3fa0', '2639617e821a769377ccc21ec5c91a6daa87c38481ff6a6ccd4e7456e9d2f2f2',
    '2b44e87b89a5d0af7dd03769587858a4ca82488518edad312a3069fb9ae667d2', '39f33a374a3cb24a628eee1748f44d7965f36c85529ccca11a7494dda9ada2c4',
    '3b9837b693644674227f6062c74ddcee60d20a5e1a2cb9b3dc2f6375287df816', '3f15725dd8fcfa5e8ed524253821a4d483d3e58df50d8ae6843a444234322c1b',
    '43c6f031fdc0a19c175f1e4bea80beb8f9a0e60fe2fcb41df9a7c61d0281af2d', '43cf71fd4cd63760083628a670c4712a996cfa4cafdde713b65cb8b9aca77a56',
    '43f79621cb5f84134fa4fe4e2b10b9a3c7b412077fca124f1fa9b7db8a57c30d', '48063f7f6a359ac1d3522c9fb6690b42fef13fef5929078e2ee5532853f60f9a',
    '493715f00b646824366b4050bf2339239884c79e7f98cd7cc10413e59325fe5d', '4c52ca6379edc6b75bad9860ed7257e2332e7d5c6a8749f324b85d6db7713088',
    '4d417d71b712234ad4f998a4e1dc65c864d1343e74ecef0205d5c2181782889e', '548a0d8f66e79cd42be537e281a0a21d3d9eb2d77644225515b3dadaea4b91a7',
    '5bfb3a7dfbcb6d988604efd97481be17c605b64fb84e65316eab88bfaf8716c9', '5fa754fb54b7697dd3cfda78b9547c27bcb4d2cbbb54dfed0fc66eb4177ee89c',
    '6883e9438dc75f4bc575422171056631cd9d6190fdd5b35747398ee0314502d8', '74f31e53f88723ca8dbc9f83c76cfb6242c4c93b45a61efb17fc08d1d0c44636',
    '75cf64578ba02a1db9b9bb3862e20f0f70e2e9d18369902224b521f327138097', '7742ee2f77d7c42dcd2695baca7e3da16eba682730936735fa403b17e90f3f1f',
    '8069bad8490e3abb5e1bcfb638dee9236551ec4eb6e440aadf3d4226ae77de5e', '8ccb80939c536ef0d1f02ced8a87dcee14c896c8185335110aed9f69e65f25e0',
    '964535e218e1b4f634922a72d6cdab5ca3f0fc27ff9d99bf6e9d48acfc393689', '989b1f99b3e6fcabe24352c17119d21653476925fb7bf0fca6763af246b4d2ce',
    '9b4f1fa104c4865241ef9fb1af9e9831d31fcddbfae0e165c5b5559779288cd2', 'a3c3fc616afc800bc6e988732ca7ee4123b2cd3236200cba22c2df260da51adf',
    'a919975d691024c5039e6a9fdc889059fe160c5386c841431ae4e775ae553047', 'a9581b4eb06e89b306bb0f17b927e48bb3a2c7177decc6a1758eb8a280c31a03',
    'ad359f2285edc94a05f871ed8d697ce9769404a25e2f0e5296b568ce909dd806', 'bbb534ca4f8c42f9832ff1dcf6c16a0a70e5160929da04845c9252895a03e465',
    'bd148960ce581f6a8e1525323e564a49c0cd3a6129b5ad060068f7c14b2022cc', 'bd3623e6acea807ce6b324ca433817bd68d5c9ee67425a91844d6c066b9cd350',
    'cc3ae5d530baea05e17cee14206ec08e0ae19e1367fd94b8f75bc6b35517fe1d', 'd32c10b5221666792cb9216c56a3ac7e9bb738331f7ee906a7b433d465eb2f60',
    'da41d397381cad64f4a0445289a32ce5310415d32d4220945ecf940d6c27d46e', 'db23cd86db6a18c739b50170afff488e46e2e99f3dad4a4ae9e00d2d53097553',
    'e625774c5894bd0c46f02faf9128f44ce75f71a6179966a0cbe92f23e93f62bc', 'e796c349ef95edd881321ab9a46157ec3324f65043aef68bd28b3865775e2d5f',
    'e9a0e2eebbcb0852a1df886796b2b83b20fabf12915a869bca55075004dcad40', 'ea5a2f7309cd20392148261d5b4dbf2d0ad661a9c44c47657443fbf106651c89',
    'ec45eb22b91b0b11d9ee602f58f5018ce8fe0dbc05a387e1e9e1e7d8c5d16e8f', 'ef53f28e926a043941d13ab0ed3e5f7b26128b1845b828ef3dcccfd5c61ef3ef',
    'f15267d63eef5411e215713e4c391150c21c36eee0657828c7a0715dcc47854d', 'f5508540305299fbc0b19f38f8a12eb7a7d749657bc80927fea01855fe3d0198',
    'f8bf447f59942422e1eb5184bfbff98dbf8c50f0e75560b4459a10018fb0a477', 'f93eca19233635908c317ccb257191298730ec95bea82480c64d6c99f6148e1f',
    'f9404416f17c53078005719616eb59feb0ebc003c43c7f9a7f64e948dd45e9e3', 'fd681521ca0060022841cb1aba3553905fd9848526d6534d40c8534f44a48e67',
    'ff6e06cac995559c83d18e9a4a2e7b6492403e29f867fe7285253ec9781192a9','05e9e5f86ab9896924ce674a3facfce3b7919f0e67166b3756118b54a0d848bf',
 '09324b2781b063b8dcc8c02f37bbbe09748f25354cdfc3014419262ed61a2c92',
 '0b4e089e9175a9fd595f98dc0422a4a0c9d74f93957e9b8d1351c5e75c48c73e',
 '0c9e2d403dd6da03558c689c485c8810a42892571f0275fc73c6b9002cdf8f03',
 '11fb7ed8a75454cf1d72ce4c5e85f66a25dbfbb472e5facb98105c59a90ca07c',
 '12482d7673a2939fe1bf36116f8a93b01e234969df3eeaf59be51601c258ddc0',
 '13c44243e5c2979a59a26413a5a71646c78dc99e68ca24e282f6ac7a7a09d606',
 '150de55917b0310f1b07ad4351df440a574e86d43296e234d7efef501c93357c',
 '18444a69e22468331a60a8fd7c19653d97563eaeddd348714396cdd78f5bf73a',
 '1fdb691727283a0ec612688736ccf6e46d948a827e899cd484f73f395256f605',
 '240fd7f3e1680592b46afe17bb189420690280e74d3612eb5020845566fad14e',
 '29796e8ea962aec3c722d0cf9f0603f5e11c2742ba564aa8d520e839ccb4a748',
 '2b53713a4544a488a42338af15f616950cd9b361d840831c4d9af65b27869615',
 '2e302daa4eb84caae6d06ba70534c618494d6c68dc3cc34c5a2678649faf2efe',
 '2ec5ad9a7ddd18460b201d0cd24d5a1adfe3f783b71ad88cec6c54871e4ff0c2',
 '38163c30ed1d2f4e7fb8f630452c903e621f3a57788ee0d51118ee93c4fd5e4a',
 '3a1f4f69f6919e8e33e9dd48d8f8693899cda3dead82f0b5a71347ebda921f35',
 '3a4dac6db124c81be5a57375a11b240b678dbebd04ed4d78cdbf7e5ef002c17b',
 '3aafe54c5f29b2403e6cbd83436439bb356c43ba4095d7a202e3d353818b796a',
 '3fd2be2a5c589dbe47dd7b8b3bcb5bfb21c3d78520639f8270d6ee1bbea3a080',
 '40d083871367bc6fd0fd72a0b2f5c737ad06159173025f829ed719e6ee31c255',
 '44e389303e8daf746a3d19b2622bcc83cc862fbd2cd24be7126d78a2f940867b',
 '45e7c69259c4bd844f6992c12581c04de32e3633b7dbd8ed697907771a75967f',
 '4d751b80c4022c796283da87b884574521ba7021e4176c9b92b0eb05c5d85cb6',
 '4f079ee2e52e1fe9ea977ece79c7e87c0ea04238ecfbb867ae85cb6289dac9a2',
 '4f80241b2097f7f06695f599f72b1c8850322c6bdd2a21bd4c92cdbf17a04aa6',
 '502173a79549b4f2706b6e4f2eb33ff47a3dac3b76e8e02dc37d35e0c8cc48ac',
 '54f12501101c5f8d7a421e16ab2f05d756e2bf8c6ee744d1698094f0277d2cde',
 '590e9b3a6464478b5ccaf716dc1c6c19785cf5a8e27f8a107d0df713be6cbf55',
 '597dbe5cb7f596a94da900c6a85f025682ca16528f4efe2df1e016ff8f4ec303',
 '5d963a68f37d7d1ddbbae2932f3cc25aa6cce8483430150f5554cf887ac502a1',
 '62cb2caaf9177c360866303073b338b5ae44ed7b87dd14bb5d455952582f2ddc',
 '62d0c80996db8c9f75701ed279aa645cec496b8eb484787a35ddf3dabf0e864e',
 '63a57ce39e5303742a6b9933a676973ada3ccf380452117202ba497163519542',
 '667eba21ca68cfa06c3e5412c005c1eca73b363aa550357a48d2cb7691ebee81',
 '693c0b1d0d86fd76dd1c5b18d623f5e83a263af375ca223a8ffa7bb0a2975a65',
 '6d76aabf1c718779face1cddd16fe651152cc7e8a8942d1980d6960e64d19c43',
 '6dcc88c782387f8744f6021e23725f9ed9afcf7dea32a64c09bae58117198413',
 '6f885f2f0e34b69648a1e03818005a62ba1468c4f83451bb517e35e3f721cff2',
 '707f9a1ec584830ee11acc4c67321544199a61df39de5de0be1cffd139caf384',
 '70d646c3cdae58c6f16f71b1f56ba0e802ecfcb37784562d7d8c2bbe0490a700',
 '7292de60dfa95b28e350732b7cb23cb971716ad56a3c0ca13352be18e3810f62',
 '76b1d974307d4911681323aa11131ea6c223bff136893e8d522084719ea0b1bc',
 '77157b74ed89f22b9b9c3deeff729589e2f664a720f290c2ed084b8fe209beb2',
 '7beb98462e37dec41c7e024c44d2740cf855b6bd55b22318e8638efcecb198bf',
 '8da2fac41034753de7bda33e1d6db4a6dc486fd781d494e782f6df38fec6e5ab',
 '9695268a8446f8b11580a1c1f3e4b554b8cc35d29dac467c3295b525501acadc',
 '96e415026efe7b4d54e862ec4bad95090c2d8ad0f081a933b4e5852e0ead9788',
 '98666a27b70d12cafee5f7d9ec30b9161c7e9bdde11cc1b79644add65add4819',
 '9bb507542c08b39e2faa2ad28a810758eae509acb6092e6f891a9f40457260e4',
 '9de226d33f9cf1c3f56d0cc7dbb94ff4e0aab16e8264775fffdf5b03f91c8117',
 'a114d4daed6dec83009fded3930f1006ce051b2b21077351b7586286fbffe83c',
 'a381c561203b597054864705380e601d6408046b37677e0fb54b85f3d587e7a5',
 'a92341f83303e7feaea89fc7ece6063bf5e4245e31f827f21fc40f4d582f85b2',
 'ac85341c1f71b1bc32d4ebc977dbae55d017166553a219a0a85dae1b8fe08808',

 '1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd',
 '226e9dc8e979fbe7791a69e7b08b616d8aee4177c5a8a61af42fe45f9c9e6141',
 '34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a',
 '5df8790240b4823f36b0e3cd0dbe62772a26a99114191eb09916fa598d4f59b2',
 '71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b',
 '831eb7fb4ed4b394b3dd4011bb51fe4f83a31bd5015bc8c2ae24da350251fe8c',
 '938a7ecbd42589dfebaa2ad28a810758eae509acb6092e6f891a9f40457260e4',
 'cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b',
 'ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92',
 'da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f'
]

patient_bio_used=['1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd',
 '226e9dc8e979fbe7791a69e7b08b616d8aee4177c5a8a61af42fe45f9c9e6141',
 '34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a',
 '5df8790240b4823f36b0e3cd0dbe62772a26a99114191eb09916fa598d4f59b2',
 '71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b',
 '831eb7fb4ed4b394b3dd4011bb51fe4f83a31bd5015bc8c2ae24da350251fe8c',
 '938a7ecbd42589dfebaa2ad28a810758eae509acb6092e6f891a9f40457260e4',
 'cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b',
 'ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92',
 'da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f']

Patient_bio_used_with_data = [  # PATIENTHASHMRN, DATE_DIF pairs
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27318,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",27871,
"34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a",28263,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28371,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27531,
"5df8790240b4823f36b0e3cd0dbe62772a26a99114191eb09916fa598d4f59b2",28232,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27864,
"831eb7fb4ed4b394b3dd4011bb51fe4f83a31bd5015bc8c2ae24da350251fe8c",28070,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27742,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27564,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28489,
"226e9dc8e979fbe7791a69e7b08b616d8aee4177c5a8a61af42fe45f9c9e6141",27762,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27650,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28630,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28357,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",27819,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27287,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28417,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28158,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28564,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27231,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27773,
"34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a",28287,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27895,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27004,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27285,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28579,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",26991,
"34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a",28609,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",28333,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27258,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28032,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28006,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",26956,
"34a432e4b994c6e23eb9884e02faeeec1ffaaccd205f90f232789e0a074f778a",28260,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",27980,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",27986,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27041,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27172,
"5df8790240b4823f36b0e3cd0dbe62772a26a99114191eb09916fa598d4f59b2",28235,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28315,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28571,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27476,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28355,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28503,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27311,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28496,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27406,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27668,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27959,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28624,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",28334,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27591,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28489,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",28016,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28322,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",27822,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28095,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27350,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27683,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27619,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27712,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28491,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28282,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28449,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",28155,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27803,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27497,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27378,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28294,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27647,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",27829,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28033,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27923,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28427,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",27981,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27468,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27831,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28644,
"226e9dc8e979fbe7791a69e7b08b616d8aee4177c5a8a61af42fe45f9c9e6141",27766,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28460,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28399,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28307,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",28283,
"da079d5c3eccdefce202d126a9ef5d8dac7f32a64c24c531782021e5ba8a1f9f",28617,
"cd64c7d700e5715bec6565496b6bffe761a6bcc3b353bdd94d75bf94ed79122b",27313,
"71f956ae32f537eb45150834c87ff69d22f957428c817189fefbc23d558bd61b",28095,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27144,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28266,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27437,
"ce1027b31d7ce9cabaebcd920a669e0b0fbbc0dadaef36112ec399e182124f92",28123,
"1ef9ebd014b9951a0458cb14e450f803bbb88becb188c78e55b94580685386bd",27200,
"938a7ecbd42589dfebaa2ad28a810758eae509acb6092e6f891a9f40457260e4",28224,
]

BASE_DIR = Path(__file__).resolve().parent
NOTES_CSV = Path(os.getenv("NOTES_CSV", BASE_DIR /  "Asthma_Symp.csv"))
LABS_CSV  = Path(os.getenv("LABS_CSV",  BASE_DIR /  "symptom_patient_merged.csv"))
# NEW: optional medications CSV path (defaults to local file)
MEDS_CSV  = Path(os.getenv("MEDS_CSV",  BASE_DIR /  "Medication_1600_ATS_severe.csv"))

CSV_FILE_NOTES = NOTES_CSV
CSV_FILE_LABS  = LABS_CSV

DATA_LOADED = False
LOAD_ERR = None

def ensure_data_loaded():
    global DATA_LOADED, LOAD_ERR
    global PATIENTS_NOTES, LABS_BY_PATIENT, DEMO_BY_PATIENT, PATIENTS, BIO_EVENTS

    if DATA_LOADED:
        return

    try:
        PATIENTS_NOTES = load_notes(CSV_FILE_NOTES)
        LABS_BY_PATIENT, DEMO_BY_PATIENT = load_labs(CSV_FILE_LABS)

        allowed = set(LABS_BY_PATIENT.keys())
        PATIENTS = {pid: val for pid, val in PATIENTS_NOTES.items() if pid in allowed}
        LABS_BY_PATIENT = {pid: LABS_BY_PATIENT[pid] for pid in PATIENTS if pid in LABS_BY_PATIENT}
        DEMO_BY_PATIENT = {pid: DEMO_BY_PATIENT.get(pid, {"AGE": None, "SEX": "", "BMI": None}) for pid in PATIENTS}

        BIO_EVENTS = build_bio_events(Patient_bio_used_with_data, set(PATIENTS.keys()))

        DATA_LOADED = True
    except FileNotFoundError as e:
        LOAD_ERR = f"Data files not found. NOTES_CSV='{CSV_FILE_NOTES}', LABS_CSV='{CSV_FILE_LABS}'. Error: {e}"
    except Exception as e:
        LOAD_ERR = f"Failed to load data: {e}"

LAB_COLUMNS_SHOW = [
    "Absolute Basophils", "Absolute Eosinophils", "Absolute Lymphocytes",
    "Absolute Neutrophils", "FEV1 PRE", "FEV1/FVC PRE",
    "FEF25-75% PRE", "FEV1 %PRE PRED"
]
DEMO_COLUMNS = ["AGE", "SEX", "BMI"]

SYMPTOM_COLS = [
    "wheezing_current", "wheezing_previous",
    "shortness_of_breath_current", "shortness_of_breath_previous",
    "chest_tightness_current", "chest_tightness_previous",
    "coughing_current", "coughing_previous",
    "rapid_breathing_current", "rapid_breathing_previous",
    "exercise_induced_symptoms_current", "exercise_induced_symptoms_previous",
    "nocturnal_symptoms_current", "nocturnal_symptoms_previous",
    "exacerbation_current", "exacerbation_previous",
    "general_asthma_symptoms_worsening_current"
]

REF_RANGES = {
    "Absolute Basophils":   "0.00 - 0.20 × 10³/µL",
    "Absolute Eosinophils": "0.00 - 0.50 × 10³/µL",
    "Absolute Lymphocytes": "1.00 - 4.80 × 10³/µL",
    "Absolute Neutrophils": "1.50 - 8.00 × 10³/µL",
    "FEV1 PRE":             "Varies by individual",
    "FEV1 %PRE PRED":       "> 80% of predicted",
    "FEV1/FVC PRE":         "> 70% (often > 75%)",
    "FEF25-75% PRE":        "No single reference"
}

# -----------------------------
# Loaders
# -----------------------------
def load_notes(csv_path: Path):
    df = pd.read_csv(csv_path, dtype={"PATIENTHASHMRN": str})
    df = df[df["PATIENTHASHMRN"].isin(Candidate_patients)]
    needed = ["PATIENTHASHMRN", "ENCDATEDIFFNO", "DEIDENTIFIED_TEXT"]
    for c in needed:
        if c not in df.columns:
            raise ValueError(f"Missing column in notes CSV: {c}")
    df["ENCDATEDIFFNO"] = pd.to_numeric(df["ENCDATEDIFFNO"], errors="coerce")
    df = df.dropna(subset=["ENCDATEDIFFNO"]).reset_index(drop=True)

    patients = {}
    for pid, g in df.groupby("PATIENTHASHMRN"):
        g = g.sort_values("ENCDATEDIFFNO")
        notes = []
        for r in g.itertuples(index=False):
            raw = str(r.DEIDENTIFIED_TEXT)
            notes.append({
                "date": float(r.ENCDATEDIFFNO),
                "text": raw,
                "pretty": make_friendly_text(raw)
            })
        if notes:
            dvals = [n["date"] for n in notes]
            patients[pid] = {"notes": notes, "min_date": min(dvals), "max_date": max(dvals)}
    return patients

def load_labs(csv_path: Path):
    df = pd.read_csv(csv_path, dtype={"PATIENTHASHMRN": str})
    alias = resolve_lab_aliases(df.columns)
    date_col = alias.get("DATE_DIF") or "DATE_DIF"
    if date_col not in df.columns:
        df[date_col] = pd.NA
    for col in SYMPTOM_COLS:
        if col not in df.columns:
            df[col] = pd.NA
    df[date_col] = pd.to_numeric(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).reset_index(drop=True)

    labs_by_patient = {}
    demo_by_patient = {}
    for pid, g in df.groupby("PATIENTHASHMRN"):
        g = g.sort_values(date_col)

        series = []
        for _, row in g.iterrows():
            item = {"date": try_float(row.get(date_col))}
            for c in LAB_COLUMNS_SHOW:
                src = alias.get(c)
                val = row.get(src) if src in row else None
                item[c] = try_float(val)
            for c in SYMPTOM_COLS:
                item[c] = try_01(row.get(c))
            series.append(item)
        labs_by_patient[pid] = series

        gg = g.dropna(subset=["AGE", "SEX", "BMI"], how="all")
        if len(gg) > 0:
            last = gg.sort_values(date_col).iloc[-1]
            demo_by_patient[pid] = {
                "AGE": try_float(last.get("AGE")),
                "SEX": str(last.get("SEX")) if pd.notna(last.get("SEX")) else "",
                "BMI": try_float(last.get("BMI")),
            }
        else:
            demo_by_patient[pid] = {"AGE": None, "SEX": "", "BMI": None}
    return labs_by_patient, demo_by_patient

# ---------- NEW: medications loader (patient + date aware) ----------
def load_medications(csv_path: Path):
    """
    Returns:
      meds_by_patient: { pid: [ {date: float|None, meds: [str,...]} , ...] }
      err: str|None
    Supports either:
      - one or more text columns with med lists (column name contains med/drug/rx/name)
      - many 0/1 flag columns (header is medication name)
    """
    if not csv_path.exists():
        return {}, f"Medications file not found at: {csv_path}"
    try:
        df = pd.read_csv(csv_path, dtype={"PATIENTHASHMRN": str})
    except Exception as e:
        return {}, f"Failed to read medications CSV: {e}"

    if "PATIENTHASHMRN" not in df.columns:
        return {}, "Medications CSV must include PATIENTHASHMRN."

    # date column best-effort
    date_col = None
    for cand in ["DATE_DIF", "ENCDATEDIFFNO", "DATE_DIFFNO", "DATE_DIFF"]:
        if cand in df.columns:
            date_col = cand
            break
    if date_col is None:
        df["DATE_DIF"] = pd.NA
        date_col = "DATE_DIF"
    df[date_col] = pd.to_numeric(df[date_col], errors="coerce")

    # identify med text columns
    def is_med_text_col(col):
        c = col.lower()
        return any(k in c for k in ["med", "drug", "rx", "name"]) and df[col].dtype == object
    text_med_cols = [c for c in df.columns if is_med_text_col(c)]

    # identify binary med columns (0/1)
    NON_MED_LIKE = {
        "patienthashmrn", "date_dif", "encdatediffno", "date_diffno", "date_diff",
        "age", "sex", "bmi", "ats_severe", "atssevere",
        "note", "notes", "provider", "encounter", "visit", "mrn", "id"
    }
    bin_med_cols = []
    for c in df.columns:
        lc = _norm(c)
        if lc in NON_MED_LIKE: 
            continue
        # boolean dtypes
        if df[c].dtype == bool:
            bin_med_cols.append(c)
            continue
        # numeric {0,1}
        try:
            vals = pd.unique(df[c].dropna().astype(float))
            if len(vals) and set(vals).issubset({0.0, 1.0}):
                if not any(tok in c.lower() for tok in ["date","age","sex","bmi","count","score","risk","flag"]):
                    bin_med_cols.append(c)
        except Exception:
            pass

    split_re = re.compile(r'[;,\|/]+|\s{2,}')
    def row_meds(row):
        meds = []
        for c in text_med_cols:
            val = row.get(c)
            if pd.isna(val): 
                continue
            s = str(val).strip()
            if not s: 
                continue
            parts = [p.strip() for p in split_re.split(s) if p.strip()]
            meds.extend(parts)
        for c in bin_med_cols:
            v = row.get(c)
            if pd.isna(v): 
                continue
            try:
                if float(v) == 1.0:
                    meds.append(str(c).strip())
            except Exception:
                if str(v).strip().lower() in {"true","t","yes","y"}:
                    meds.append(str(c).strip())
        # normalize + dedupe case-insensitively
        out, seen = [], set()
        for m in meds:
            mm = re.sub(r'\s+', ' ', m).strip()
            if not mm: 
                continue
            key = mm.lower()
            if key not in seen:
                seen.add(key)
                out.append(mm)
        return out

    meds_by_patient = {}
    work = df.dropna(subset=["PATIENTHASHMRN"])
    # prefer rows with valid date if present
    if work[date_col].notna().any():
        work = work.dropna(subset=[date_col])

    for pid, g in work.groupby("PATIENTHASHMRN"):
        series = []
        for _, row in g.sort_values(date_col, na_position="last").iterrows():
            series.append({"date": try_float(row.get(date_col)), "meds": row_meds(row)})
        meds_by_patient[pid] = series
    return meds_by_patient, None

PATIENTS_NOTES = load_notes(CSV_FILE_NOTES)
LABS_BY_PATIENT, DEMO_BY_PATIENT = load_labs(CSV_FILE_LABS)

allowed = set(LABS_BY_PATIENT.keys())
PATIENTS = {pid: val for pid, val in PATIENTS_NOTES.items() if pid in allowed}
LABS_BY_PATIENT = {pid: LABS_BY_PATIENT[pid] for pid in PATIENTS.keys() if pid in LABS_BY_PATIENT}
DEMO_BY_PATIENT = {pid: DEMO_BY_PATIENT.get(pid, {"AGE": None, "SEX": "", "BMI": None}) for pid in PATIENTS.keys()}

# ---------- NEW: load meds & restrict to current PATIENTS ----------
MEDS_BY_PATIENT_ALL, MEDS_ERR = load_medications(MEDS_CSV)
MEDS_BY_PATIENT = {pid: MEDS_BY_PATIENT_ALL.get(pid, []) for pid in PATIENTS.keys()}

def build_symptom_groups():
    groups = {}
    for c in SYMPTOM_COLS:
        if c.endswith("_current"):
            base = c[:-8]
            groups.setdefault(base, {})["current"] = c
        elif c.endswith("_previous"):
            base = c[:-9]
            groups.setdefault(base, {})["previous"] = c
        else:
            groups.setdefault(c, {})["current"] = c
    order = [
        "wheezing", "shortness_of_breath", "chest_tightness", "coughing",
        "rapid_breathing", "exercise_induced_symptoms", "nocturnal_symptoms",
        "exacerbation", "general_asthma_symptoms_worsening_current"
    ]
    for base in groups.keys():
        if base not in order:
            order.append(base)
    return groups, order

SYM_GROUPS, SYM_ORDER = build_symptom_groups()

def build_bio_events(flat_list, valid_patients):
    bio = {}
    n = len(flat_list)
    for i in range(0, n - 1, 2):
        pid = str(flat_list[i])
        try:
            d = float(flat_list[i+1])
        except Exception:
            continue
        if pid in valid_patients:
            bio.setdefault(pid, []).append(d)
    for pid in list(bio.keys()):
        uniq = sorted(set(bio[pid]))
        bio[pid] = uniq
    return bio

BIO_EVENTS = build_bio_events(Patient_bio_used_with_data, set(PATIENTS.keys()))

# -----------------------------
# Template (UI)
# -----------------------------
TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Patient Timeline & Biological Propriety (Offline)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{
      --border:#cfe0f5; --muted:#eef4ff; --bg:#f1f7ff; --pagebg:#f7fbff; --text:#0b1220;
      --accent:#0ea5e9; --primary:#2563eb; --red:#f43f5e;
      --good:#10b981; --bad:#ef4444; --unk:#64748b;
      --tile1:#e0f2fe; --tile1b:#93c5fd;
      --tile2:#e2e8f0; --tile2b:#94a3b8;
      --tile3:#e8f5e9; --tile3b:#86efac;
      --purple:#6366f1; --purpleD:#4f46e5;
    }
    body{ font-family: Arial, sans-serif; color:var(--text); background:var(--pagebg); margin:0; padding:24px; }
    h2,h3{ margin:8px 0; }
    .small{ color:#555; font-size:13px; }

    .row{ display:flex; gap:28px; align-items:flex-start; }
    .left{ flex:0 0 58%; display:flex; flex-direction:column; gap:14px; }
    .right{ flex:1; display:flex; flex-direction:column; gap:14px; }

    .card{ border:1px solid var(--border); border-radius:14px; background:#fff; padding:16px; box-shadow:0 2px 6px rgba(15,23,42,.06); }
    .card.resizable{ resize:both; overflow:auto; min-width:280px; min-height:180px; }
    .panel-head{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding-bottom:10px; margin-bottom:12px; border-bottom:1px solid var(--border); }
    .panel-title{ font-size:20px; font-weight:700; letter-spacing:.2px; }

    .box{ height:440px; overflow-y:auto; padding:14px; background:var(--bg); border:1px solid var(--border); border-radius:10px; white-space:pre-wrap; line-height:1.45; font-family:'Times New Roman', serif; font-size:16px; }
    .box.resizable{ resize:vertical; min-height:180px; }

    .controls{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .controls-stack{ display:flex; flex-direction:column; gap:6px; }
    select{ padding:8px 10px; border-radius:10px; border:1px solid #cbd5e1; background:#fff; }
    button{ padding:10px 16px; border:1px solid #bbb; background:#fff; border-radius:10px; cursor:pointer; }
    button.primary{ background:var(--primary); color:#fff; border-color:var(--primary); }
    button.ghost{ background:#fff; }
    .btn-purple{ background:var(--purple); color:#fff; border:1px solid var(--purple); }
    .btn-purple:hover{ background:var(--purpleD); border-color:var(--purpleD); }

    .annotator { display:flex; align-items:center; gap:10px; }
    .badge { background:var(--muted); border:1px solid var(--border); color:#0b1220; padding:6px 10px; border-radius:999px; font-weight:700; }
    .annotator input { padding:8px 10px; border-radius:10px; border:1px solid #cbd5e1; }

    /* Biologic section */
    .bio-group{ display:flex; flex-direction:column; gap:8px; border:1px solid var(--border); border-radius:10px; padding:10px; background:var(--muted); }
    .bio-line{ display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
    .bio-line label{ font-weight:600; }
    .bio-line input[type="radio"]{ transform:scale(1.05); }
    .bio-extra{ display:none; gap:12px; align-items:center; flex-wrap:wrap; }
    .bio-extra input[type="date"]{ padding:8px 10px; border-radius:8px; border:1px solid #cbd5e1; }

    /* Timeline */
    #timeline-section{ border:1px solid var(--border); border-radius:14px; padding:10px 14px; background:#fff; margin:10px 0 12px 0; box-shadow:0 1px 4px rgba(15,23,42,.05); }
    .timeline{ position:relative; height:68px; border-top:4px solid var(--accent); border-radius:2px; margin:12px 6px 6px 6px; }
    .dot{ width:14px; height:14px; border-radius:50%; position:absolute; transform:translateX(-50%); }
    .dot.blue{ background:#175b82; border:2px solid #0b2f41; }
    .dot.red{ background:var(--red); border:2px solid #9a1212; }
    .dot.bio{ width:12px; height:12px; background:var(--good); border:2px solid #065f46; border-radius:2px; transform:translateX(-50%) rotate(45deg); }
    .dot.gray{ background:#94a3b8; border:2px solid #64748b; }
    .date-label{ position:absolute; top:28px; transform:translateX(-50%); font-size:12px; color:#111; white-space:nowrap; background:#fff; padding:1px 3px; border-radius:3px; border:1px solid #eee; }

    /* Demographics */
    .demog-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .tile{ border-radius:14px; padding:14px; }
    .tile h4{ margin:0 0 6px 0; font-size:14px; color:#334155; text-align:left; }
    .tile .value{ font-size:28px; font-weight:600; text-align:left; }

    /* Tables */
    .labs-table{ width:100%; border-collapse:collapse; }
    .labs-table th, .labs-table td{ border:1px solid #e5e7eb; padding:12px 14px; text-align:left; }
    .labs-table thead th{ background:var(--muted); font-size:14px; }
    .labs-table tbody td, .labs-table tbody th{ font-size:16px; }

    /* Symptoms */
    .sym-grid{ display:grid; grid-template-columns:40px 40px 1fr; gap:8px 12px; align-items:center; }
    .sym-head{ font-weight:700; }
    .icon{ display:inline-block; width:20px; height:20px; line-height:20px; text-align:center; font-weight:800; font-size:16px; }
    .icon.good{ color:var(--good); } .icon.bad{ color:var(--bad); } .icon.unk{ color:var(--unk); }

    .header-line{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; }
    .patient-id{ font-weight:700; font-size:16px; }
    .muted{ color:#666; }
    textarea.notes{ width:100%; min-height:120px; resize:vertical; padding:12px; border:1px solid var(--border); border-radius:10px; font-size:14px; line-height:1.45; }

    /* NEW: Medications */
    .med-filter { width: 100%; margin: 8px 0 10px 0; padding: 8px 10px; border:1px solid #cbd5e1; border-radius:10px; }
    .med-box { height: 240px; overflow-y: auto; border: 1px solid var(--border); background: var(--bg); border-radius: 10px; padding: 10px 12px; font-size: 15px; line-height: 1.45; white-space: normal; }
    .med-item { padding: 6px 4px; border-bottom: 1px dashed #e5e7eb; }
    .med-item:last-child { border-bottom: none; }
  </style>
</head>
<body>
  <div class="header-line">
    <div>
      <div class="patient-id">Patient: <span id="patient-id"></span>
        <span class="small muted" id="patient-pos"></span>
        <span class="small muted" id="bio-flag"></span>
      </div>
      <div class="annotator" id="annotator-ui"></div>
    </div>
    <div class="controls-stack">
      <div class="controls">
        <button id="prev-patient-btn">⬅️ Previous Patient</button>
        <select id="patient-select"></select>
        <button id="next-patient-btn">Next Patient ➡️</button>
      </div>
    </div>
  </div>

  <div id="timeline-section">
    <div class="small"><strong>Time Line</strong>: blue = notes; red = selected; <span style="color:#065f46;">green diamonds</span> = biologic use</div>
    <div id="timeline" class="timeline"></div>
  </div>

  <div class="row">
    <div class="left">
      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Note Text</div>
          <div class="controls">
            <button class="ghost" id="prev-btn">⬅️ Previous Text</button>
            <button id="friendly-btn" class="btn-purple">👁 Friendly View</button>
            <button class="ghost" id="next-btn">Next Text ➡️</button>
          </div>
        </div>
        <div id="text-box" class="box resizable"></div>
      </div>

      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Annotator Note & Biologic Form</div>
        </div>
        <textarea id="free-note" class="notes" placeholder="Write your note..."></textarea>

        <!-- Biologic section -->
        <div class="bio-group" style="margin-top:10px;">
          <div class="bio-line">
            <label>Biologic use (y/n):</label>
            <label><input type="radio" name="bioUse" id="bioUseNo" value="no" checked> No</label>
            <label><input type="radio" name="bioUse" id="bioUseYes" value="yes"> Yes</label>
          </div>

          <div id="bio-yes-extra" class="bio-extra">
            <label>Start: <input type="date" id="bioStart"></label>
            <label>End: <input type="date" id="bioEnd"></label>
          </div>

          <div id="bio-no-extra" class="bio-extra" style="display:flex;">
            <div class="bio-line">
              <label>Is patient a candidate for biologic therapy? (y/n):</label>
              <label><input type="radio" name="bioCand" id="bioCandNo" value="no" checked> No</label>
              <label><input type="radio" name="bioCand" id="bioCandYes" value="yes"> Yes</label>
            </div>
          </div>
        </div>

        <div class="controls" style="margin-top:10px;">
          <button class="primary" id="save-annotation">Save Annotation</button>
          <button id="export-txt" class="ghost">💾 Save to TXT</button>
        </div>
        <div class="small muted">Saved locally in your browser (offline).</div>
      </div>

      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Annotations</div>
        </div>
        <div id="no-anns" class="small">No annotations yet.</div>
        <div style="overflow-x:auto; display:none;" id="ann-table-wrap">
          <table class="labs-table">
            <thead>
              <tr>
                <th>PATIENTHASHMRN</th>
                <th>Note Date</th>
                <th>Biologic Use</th>
                <th>Date Range</th>
                <th>Candidate?</th>
                <th>Free Note</th>
                <th>Annotator</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="ann-body"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="right">
      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Demographics</div>
        </div>
        <div id="demo-content" class="demog-grid"></div>
      </div>

      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Spirometry & Labs – closest to selected note</div>
        </div>
        <div id="lab-content"></div>
      </div>

      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Symptoms – symptom_patient_merged.csv</div>
        </div>
        <div class="small" style="margin-bottom:8px;">
          <span class="icon good">✓</span> present (1) &nbsp;&nbsp;
          <span class="icon bad">✕</span> absent (0)
        </div>
        <div id="sym-content"></div>
      </div>

      <!-- NEW: Medications panel AT THE BOTTOM -->
      <div class="card resizable">
        <div class="panel-head">
          <div class="panel-title">Medications — closest to selected note</div>
        </div>
        <div class="small muted" id="med-date"></div>
        <div class="small muted" id="med-err" style="display:none;"></div>
        <input id="med-filter" class="med-filter" placeholder="Filter these medications..." />
        <div id="med-box" class="med-box"></div>
      </div>
    </div>
  </div>

<script>
  // --------- Embedded data ----------
  const PATIENTS = {{ patients_json|safe }};
  const LABS = {{ labs_json|safe }};
  const DEMO = {{ demo_json|safe }};
  const LAB_FIELDS = {{ lab_fields_json|safe }};
  const SYM_GROUPS = {{ sym_groups_json|safe }};
  const SYM_ORDER = {{ sym_order_json|safe }};
  const REF_RANGES = {{ ref_ranges_json|safe }};
  const BIO = {{ bio_json|safe }};  // { pid: [dates...] }
  // NEW:
  const MEDS = {{ meds_json|safe }};
  const MEDS_ERR = {{ meds_err|safe }};

  const PATIENT_IDS = Object.keys(PATIENTS);
  let currentPatient = PATIENT_IDS[0] || "";
  let pos = 0;
  let friendlyMode = false;

  function lockBioRadioForPatient(){
    const yes = document.getElementById("bioUseYes");
    const no  = document.getElementById("bioUseNo");
    const hasBio = Array.isArray(BIO[currentPatient]) && BIO[currentPatient].length > 0;

    if (hasBio){
      yes.checked = true;  no.checked = false;
      yes.disabled = true; no.disabled = true;
      document.getElementById("bio-yes-extra").style.display = "flex";
      document.getElementById("bio-no-extra").style.display  = "none";
    } else {
      yes.checked = false; no.checked = true;
      yes.disabled = true; no.disabled = true;
      document.getElementById("bio-yes-extra").style.display = "none";
      document.getElementById("bio-no-extra").style.display  = "flex";
    }
  }

  /* ---------- Annotator UI ---------- */
  function getAnnotator(){ return localStorage.getItem("annotator_name") || ""; }
  function setAnnotator(name){ localStorage.setItem("annotator_name", name); }
  function renderAnnotatorUI(){
    const host = document.getElementById("annotator-ui");
    host.innerHTML = "";
    const name = getAnnotator();
    if (name){
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = "Annotator: " + name;
      const changeBtn = document.createElement("button");
      changeBtn.className = "ghost";
      changeBtn.textContent = "Change";
      changeBtn.onclick = () => {
        const v = prompt("Set annotator name:", name);
        if (v === null) return;
        const trimmed = (v || "").trim();
        if (!trimmed){ alert("Annotator cannot be empty."); return; }
        setAnnotator(trimmed);
        renderAnnotatorUI();
      };
      host.appendChild(badge);
      host.appendChild(changeBtn);
      return;
    }
    const inp = document.createElement("input");
    inp.id = "annotator-input";
    inp.placeholder = "Your name (saved)";
    const btn = document.createElement("button");
    btn.className = "primary";
    btn.textContent = "Set";
    btn.onclick = () => {
      const v = (document.getElementById("annotator-input").value || "").trim();
      if (!v){ alert("Please enter annotator name."); return; }
      setAnnotator(v);
      renderAnnotatorUI();
    };
    host.appendChild(inp);
    host.appendChild(btn);
  }

  /* ---------- Helpers ---------- */
  function el(tag, attrs={}, text=null){
    const e=document.createElement(tag);
    Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,v));
    if(text!==null) e.textContent=text;
    return e;
  }
  const titleCase = s => s.replace(/\\b\\w/g, c => c.toUpperCase());

  /* ---------- Patient nav ---------- */
  function renderPatientSelect(){
    const sel=document.getElementById("patient-select"); sel.innerHTML="";
    PATIENT_IDS.forEach(pid=>{ const o=el("option",{},pid); o.value=pid; if(pid===currentPatient) o.selected=true; sel.appendChild(o); });
    sel.onchange=()=>switchPatient(sel.value);
  }
  function renderHeader(){
    document.getElementById("patient-id").textContent=currentPatient;
    const total=PATIENTS[currentPatient]?.notes?.length||0;
    document.getElementById("patient-pos").textContent= total ? ` (note ${pos+1} of ${total})` : "";
    const biolist = BIO[currentPatient] || [];
    document.getElementById("bio-flag").textContent = biolist.length ? ` | Biologic use: ${biolist.length} date(s)` : "";
  }

  /* ---------- Text & timeline ---------- */
  function renderText(){
    const note = PATIENTS[currentPatient].notes[pos];
    const box  = document.getElementById("text-box");
    const btn  = document.getElementById("friendly-btn");
    const txt  = friendlyMode && note.pretty ? note.pretty : (note.text || "");
    box.textContent = txt;
    box.scrollTop = 0;
    btn.textContent = friendlyMode ? "🔤 Raw View" : "👁 Friendly View";
  }

  function renderTimeline(){
    const section = document.getElementById("timeline-section");
    const tl = document.getElementById("timeline");
    tl.innerHTML="";
    const P = PATIENTS[currentPatient] || {notes:[], min_date:0, max_date:0};
    const notes = P.notes || [];
    const B = BIO[currentPatient] || [];

    section.style.display="block";

    if ((notes.length === 0) && B.length === 0){
      const d=el("div",{class:"dot gray"});
      d.style.left = "50%";
      d.style.top  = "-6px";
      d.title = "No timeline data";
      tl.appendChild(d);
      return;
    }

    let minD = P.min_date ?? 0, maxD = P.max_date ?? 1;
    if (B.length){
      const bmin = Math.min.apply(null, B);
      const bmax = Math.max.apply(null, B);
      if (minD===undefined || minD===null) minD=bmin;
      if (maxD===undefined || maxD===null) maxD=bmax;
      if (bmin < minD) minD = bmin;
      if (bmax > maxD) maxD = bmax;
    }
    if (minD===maxD){ maxD = minD + 1; }
    const span = (maxD - minD) || 1;

    const slots = {};
    notes.forEach((n,i)=>{
      const pct = ((n.date - minD) / span) * 100;
      const key = Math.round(pct*10)/10;
      const stack = (slots[key]||0); slots[key] = stack + 1;

      const d=el("div",{class:"dot "+(i===pos?"red":"blue")});
      d.style.left = pct + "%";
      d.style.top  = (-6 - stack*16) + "px";
      d.title = "ENCDATEDIFFNO: " + n.date;
      d.onclick = ()=>{ pos=i; renderAllForNote(); };
      tl.appendChild(d);

      const lab=el("div",{class:"date-label"});
      lab.style.left = pct + "%";
      lab.textContent = String(n.date);
      tl.appendChild(lab);
    });

    B.forEach((bd)=>{
      const pct = ((bd - minD) / span) * 100;
      const key = Math.round(pct*10)/10;
      const stack = (slots[key]||0); slots[key] = stack + 1;

      const m=el("div",{class:"dot bio"});
      m.style.left = pct + "%";
      m.style.top  = (-6 - stack*16) + "px";
      m.title = "Biologic use date: " + bd;

      m.onclick = ()=>{
        let bestI = 0, bestDist = Infinity;
        (P.notes||[]).forEach((n,i)=>{
          const dist = Math.abs((n.date ?? bd) - bd);
          if (dist < bestDist){ bestDist = dist; bestI = i; }
        });
        pos = bestI;
        renderAllForNote();
      };
      tl.appendChild(m);
    });
  }

  /* ---------- Labs, demo, symptoms ---------- */
  function valText(v){
    if (v===null || typeof v==="undefined" || v==="") return "—";
    if (typeof v === "number") return (Math.abs(v - Math.trunc(v)) < 1e-9) ? String(Math.trunc(v)) : String(Number(v.toFixed(3)));
    return String(v);
  }
  function sexText(v){
    if (v===null || v===undefined || v==="") return "—";
    const s=String(v).trim().toLowerCase();
    if (s==="0" || s==="0.0") return "Female";
    if (s==="1" || s==="1.0") return "Male";
    return s.toUpperCase() in {"F":1,"M":1} ? (s.toUpperCase()==="F"?"Female":"Male") : s;
  }
  function renderDemographics(){
    const d=DEMO[currentPatient]||{};
    const host=document.getElementById("demo-content"); host.innerHTML="";
    const tiles=[
      {title:"Age", value:d.AGE,  bg:"var(--tile1)", bd:"var(--tile1b)"},
      {title:"Sex", value:sexText(d.SEX),  bg:"var(--tile2)", bd:"var(--tile2b)"},
      {title:"BMI", value:d.BMI,  bg:"var(--tile3)", bd:"var(--tile3b)"},
    ];
    tiles.forEach(t=>{
      const div=document.createElement("div");
      div.className="tile";
      div.style.background=t.bg;
      div.style.border=`1px solid ${t.bd}`;
      const h4=document.createElement("h4"); h4.textContent=t.title;
      const v=document.createElement("div"); v.className="value";
      v.textContent=(t.value==null||t.value==="")?"—":String(t.value);
      div.appendChild(h4); div.appendChild(v); host.appendChild(div);
    });
  }
  function closestLabRec(pid, targetDate){
    const arr=LABS[pid]||[]; let best=null, bestDist=Infinity;
    for(const r of arr){ const d=(r.date==null? targetDate : r.date); const dist=Math.abs(d-targetDate); if(dist<bestDist){ best=r; bestDist=dist; } }
    return best;
  }
  function renderLabsForCurrentNote(){
    const pid=currentPatient;
    const targetDate=PATIENTS[pid].notes[pos].date;
    const best=closestLabRec(pid, targetDate);
    const host=document.getElementById("lab-content");
    if(!best){ host.innerHTML='<div class="small muted">No lab/spirometry record for this patient.</div>'; return; }

    const demo = DEMO[pid] || {};
    const age = typeof demo.AGE === "number" ? demo.AGE : (parseFloat(demo.AGE) || null);
    const isChild = (age != null) && (age < 18);

    let html = '<table class="labs-table"><thead><tr>';
    html += '<th>Lab Result</th><th>Your Value</th>';
    if (!isChild){
      html += '<th>Typical Reference Range (Adults)</th>';
    }
    html += '</tr></thead><tbody>';

    html += '<tr><th>Closest DATE_DIF</th><td>' + valText(best.date) + '</td>' + (isChild ? '' : '<td>—</td>') + '</tr>';

    LAB_FIELDS.forEach(f=>{
      const v = best.hasOwnProperty(f)? best[f] : null;
      const rawRef = (REF_RANGES && REF_RANGES[f]) ? REF_RANGES[f] : "—";
      const ref = (()=>{
        const low = String(rawRef).toLowerCase();
        if (low.includes("varies") || low.includes("no single")) return "—";
        const tokens = String(rawRef).match(/\\d+(?:\\.\\d+)?%?/g) || [];
        if (tokens.length === 0) return "—";
        if (tokens.length === 1) return tokens[0];
        return tokens.slice(0,2).join(" - ");
      })();
      html += '<tr><th>' + f + '</th><td>' + valText(v) + '</td>' + (isChild ? '' : '<td>' + ref + '</td>') + '</tr>';
    });
    html += "</tbody></table>";
    host.innerHTML = html;
  }

  function iconHTML(v){
    if (v===1 || v==="1") return '<span class="icon good">✓</span>';
    if (v===0 || v==="0") return '<span class="icon bad">✕</span>';
    return '<span class="icon unk" style="visibility:hidden">·</span>';
  }

  function renderSymptoms(){
    const pid=currentPatient;
    const targetDate=PATIENTS[pid].notes[pos].date;
    const best=closestLabRec(pid, targetDate);
    const host=document.getElementById("sym-content"); host.innerHTML="";
    if(!best){ host.innerHTML='<div class="small muted">No symptom row found for this date.</div>'; return; }

    const wrap=el("div",{class:"sym-grid"});
    wrap.appendChild(el("div",{class:"sym-head"},"Previ."));
    wrap.appendChild(el("div",{class:"sym-head"},"Curr."));
    wrap.appendChild(el("div",{class:"sym-head"},"Symptom"));

    const SYM_ORDER = {{ sym_order_json|safe }};
    const SYM_GROUPS = {{ sym_groups_json|safe }};

    SYM_ORDER.forEach(base=>{
      const group=SYM_GROUPS[base]; if(!group) return;
      const rawLabel=base.replaceAll("_"," ").replace("general asthma symptoms worsening current","general asthma symptoms worsening");
      const label=titleCase(rawLabel);

      const pv=(group.previous && (group.previous in best))? best[group.previous] : null;
      const cv=(group.current  && (group.current  in best))? best[group.current ] : null;

      const pcell=el("div"); pcell.innerHTML = iconHTML(pv);
      const ccell=el("div"); ccell.innerHTML = iconHTML(cv);

      wrap.appendChild(pcell);
      wrap.appendChild(ccell);
      wrap.appendChild(el("div",{},label));
    });
    host.appendChild(wrap);
  }

  // ---------- NEW: Medications ----------
  function closestMedRec(pid, targetDate){
    const arr = MEDS[pid] || [];
    let best=null, bestDist=Infinity;
    for(const r of arr){
      const d = (r.date==null || Number.isNaN(r.date)) ? targetDate : r.date;
      const dist = Math.abs((d ?? targetDate) - targetDate);
      if (dist < bestDist){ best=r; bestDist=dist; }
    }
    return best;
  }

  function renderMedications(){
    const errEl = document.getElementById("med-err");
    const dateEl = document.getElementById("med-date");
    const box = document.getElementById("med-box");
    const filterEl = document.getElementById("med-filter");

    if (MEDS_ERR && MEDS_ERR !== "null"){ errEl.style.display="block"; errEl.textContent = MEDS_ERR; }
    else { errEl.style.display="none"; }

    const pid = currentPatient;
    const P = PATIENTS[pid];
    if (!P || (P.notes||[]).length===0){ box.innerHTML = '<div class="small muted">No notes for this patient.</div>'; dateEl.textContent = ""; return; }

    const targetDate = P.notes[pos].date;
    const best = closestMedRec(pid, targetDate);

    if (!best || !Array.isArray(best.meds) || best.meds.length===0){
      dateEl.textContent = `Closest medication row to note DATE_DIF ${targetDate}: none`;
      box.innerHTML = '<div class="small muted">No medications on/near this date.</div>';
      return;
    }

    dateEl.textContent = `Closest medication DATE_DIF: ${best.date==null?'—':best.date} (note selected: ${targetDate})`;

    const f = (filterEl.value||"").trim().toLowerCase();
    const list = f ? best.meds.filter(m => String(m).toLowerCase().includes(f)) : best.meds;

    if (list.length === 0){
      box.innerHTML = '<div class="small muted">No medications match your filter.</div>';
      return;
    }

    const frag = document.createDocumentFragment();
    list.forEach(m=>{
      const div = document.createElement("div");
      div.className = "med-item";
      div.textContent = m;
      frag.appendChild(div);
    });
    box.innerHTML = "";
    box.appendChild(frag);
  }

  /* ---------- Annotation storage ---------- */
  function loadPatientAnnotations(pid){
    try { return JSON.parse(localStorage.getItem("ann_"+pid)) || []; } catch(e){ return []; }
  }
  function savePatientAnnotations(pid, arr){
    try { localStorage.setItem("ann_"+pid, JSON.stringify(arr)); } catch(e){}
  }

  function deleteAnnotation(pid, ts, fp){
    const arr = loadPatientAnnotations(pid);
    if (ts) {
      const newArr = arr.filter(r => String(r.ts || "") !== String(ts || ""));
      savePatientAnnotations(pid, newArr);
      return;
    }
    let removed = false;
    const newArr = arr.filter(r => {
      if (removed) return true;
      const match =
        String(r.date)            === String(fp.date) &&
        String(r.annotator||"")   === String(fp.annotator||"") &&
        String(r.note||"")        === String(fp.note||"") &&
        String(!!r.bioUse)        === String(!!fp.bioUse) &&
        String(r.bioStart||"")    === String(fp.bioStart||"") &&
        String(r.bioEnd||"")      === String(fp.bioEnd||"") &&
        (fp.bioUse ? true : String(!!(r.bioCand)) === String(!!(fp.bioCand)));
      if (match) { removed = true; return false; }
      return true;
    });
    savePatientAnnotations(pid, newArr);
  }

  function loadAllAnnotations(){
    const out=[];
    for (let i=0;i<localStorage.length;i++){
      const k = localStorage.key(i);
      if (k && k.startsWith("ann_")){
        try{
          const pid = k.slice(4);
          const arr = JSON.parse(localStorage.getItem(k) || "[]");
          arr.forEach(r => out.push({...r, pid}));
        }catch(e){}
      }
    }
    out.sort((a,b)=> (b.ts||0)-(a.ts||0) || (b.date||0)-(a.date||0));
    return out;
  }
  function renderAnnTable(){
    const anns=loadAllAnnotations();
    const wrap=document.getElementById("ann-table-wrap");
    const empty=document.getElementById("no-anns");
    const body=document.getElementById("ann-body");
    if(anns.length===0){ wrap.style.display="none"; empty.style.display="block"; body.innerHTML=""; return; }
    empty.style.display="none"; wrap.style.display="block"; body.innerHTML="";
    anns.forEach(a=>{
      const tr=el("tr");
      tr.appendChild(el("td",{}, a.pid));
      tr.appendChild(el("td",{}, String(a.date)));
      tr.appendChild(el("td",{}, a.bioUse ? "Yes" : "No"));
      const dr = (a.bioUse && (a.bioStart||a.bioEnd)) ? `${a.bioStart||""} - ${a.bioEnd||""}` : "—";
      tr.appendChild(el("td",{}, dr));
      tr.appendChild(el("td",{}, (a.bioUse ? "—" : (a.bioCand ? "Yes" : "No"))));
      tr.appendChild(el("td",{}, a.note || ""));
      tr.appendChild(el("td",{}, a.annotator || "—"));

      const delTd = el("td");
      const btn = el("button", {
        type:"button",
        class:"ghost ann-del",
        "data-pid": a.pid,
        "data-ts":  String(a.ts || ""),
        "data-date": String(a.date ?? ""),
        "data-annotator": a.annotator || "",
        "data-note": a.note || "",
        "data-bious": a.bioUse ? "1" : "0",
        "data-biostart": a.bioUse ? (a.bioStart || "") : "",
        "data-bioend":   a.bioUse ? (a.bioEnd   || "") : "",
        "data-biocand":  a.bioUse ? "" : (a.bioCand ? "1" : "0")
      }, "🗑 Remove");
      delTd.appendChild(btn);
      tr.appendChild(delTd);

      body.appendChild(tr);
    });
  }

  /* ---------- Export to TXT ---------- */
  function downloadTxt(filename, text){
    const blob = new Blob([text], {type:"text/plain"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  }
  function exportAnnotations(){
    const who = getAnnotator();
    if (!who){ alert("Please set the annotator name first."); return; }
    const anns = loadAllAnnotations();
    let lines = [];
    lines.push(`Annotator: ${who}`);
    lines.push(`Exported: ${new Date().toISOString()}`);
    lines.push("");
    anns.forEach(a=>{
      lines.push(`PATIENT: ${a.pid}`);
      lines.push(`NoteDate: ${a.date}`);
      lines.push(`BiologicUse: ${a.bioUse ? "Yes" : "No"}`);
      if (a.bioUse){
        lines.push(`DateRange: ${a.bioStart||""} - ${a.bioEnd||""}`);
      } else {
        lines.push(`Candidate: ${a.bioCand ? "Yes" : "No"}`);
      }
      if (a.note) lines.push(`Note: ${a.note}`);
      lines.push(`---`);
    });
    downloadTxt(`${who}_annotations.txt`, lines.join("\\n"));
  }

  /* ---------- Navigation ---------- */
  function nextNote(){ pos=(pos+1)%PATIENTS[currentPatient].notes.length; renderAllForNote(); }
  function prevNote(){ pos=(pos-1+PATIENTS[currentPatient].notes.length)%PATIENTS[currentPatient].notes.length; renderAllForNote(); }
  function nextPatient(){ const i=PATIENT_IDS.indexOf(currentPatient); const j=(i+1)%PATIENT_IDS.length; switchPatient(PATIENT_IDS[j]); }
  function prevPatient(){ const i=PATIENT_IDS.indexOf(currentPatient); const j=(i-1+PATIENT_IDS.length+PATIENT_IDS.length)%PATIENT_IDS.length; switchPatient(PATIENT_IDS[j]); }
  function switchPatient(pid){
    currentPatient=pid; pos=0;
    document.getElementById("free-note").value="";
    document.getElementById("bioUseNo").checked = true;
    document.getElementById("bioUseYes").checked = false;
    document.getElementById("bio-yes-extra").style.display = "none";
    document.getElementById("bio-no-extra").style.display  = "flex";
    document.getElementById("bioCandNo").checked = true;
    document.getElementById("bioCandYes").checked = false;
    document.getElementById("bioStart").value = "";
    document.getElementById("bioEnd").value = "";
    lockBioRadioForPatient();
    renderAll();
  }

  /* ---------- Render orchestration ---------- */
  function renderAll(){
    renderAnnotatorUI();
    renderPatientSelect(); renderHeader();
    lockBioRadioForPatient();
    renderText(); renderTimeline();
    renderAnnTable(); renderDemographics(); renderLabsForCurrentNote(); renderSymptoms();
    renderMedications(); // NEW
    document.getElementById("med-filter").oninput = renderMedications; // NEW
  }
  function renderAllForNote(){
    renderHeader(); renderText(); renderTimeline();
    renderLabsForCurrentNote(); renderSymptoms();
    renderMedications(); // NEW
  }

  /* ---------- Boot ---------- */
  document.addEventListener("DOMContentLoaded", ()=>{
    if (PATIENT_IDS.length===0){ alert("No eligible patients (filtered by labs CSV)."); return; }
    renderAll();

    document.getElementById("next-btn").onclick=(e)=>{ e.preventDefault(); nextNote(); };
    document.getElementById("prev-btn").onclick=(e)=>{ e.preventDefault(); prevNote(); };
    document.getElementById("next-patient-btn").onclick=(e)=>{ e.preventDefault(); nextPatient(); };
    document.getElementById("prev-patient-btn").onclick=(e)=>{ e.preventDefault(); prevPatient(); };
    document.getElementById("friendly-btn").onclick=()=>{ friendlyMode=!friendlyMode; renderText(); };

    const useNo = document.getElementById("bioUseNo");
    const useYes = document.getElementById("bioUseYes");
    useNo.onchange = () => { if (useNo.checked){ document.getElementById("bio-yes-extra").style.display="none"; document.getElementById("bio-no-extra").style.display="flex"; } };
    useYes.onchange = () => { if (useYes.checked){ document.getElementById("bio-yes-extra").style.display="flex"; document.getElementById("bio-no-extra").style.display="none"; } };

    document.getElementById("save-annotation").onclick=(e)=>{
      e.preventDefault();
      const annotator = getAnnotator();
      if (!annotator){ alert("Please set the annotator name first."); return; }

      const P = PATIENTS[currentPatient];
      const note = P.notes[pos];
      const textNote = document.getElementById("free-note").value || "";

      const bioUse   = document.getElementById("bioUseYes").checked;
      const bioStart = document.getElementById("bioStart").value || "";
      const bioEnd   = document.getElementById("bioEnd").value || "";
      const bioCand  = document.getElementById("bioCandYes").checked;

      const rec = {
        date: note.date,
        note: textNote,
        annotator: annotator,
        bioUse: !!bioUse,
        bioStart: bioUse ? bioStart : "",
        bioEnd:   bioUse ? bioEnd   : "",
        bioCand:  bioUse ? null : !!bioCand,
        ts: Date.now()
      };
      const arr = loadPatientAnnotations(currentPatient);
      arr.unshift(rec);
      savePatientAnnotations(currentPatient, arr);
      renderAnnTable();
      alert("Annotation saved.");
    };

    document.getElementById("export-txt").onclick=(e)=>{ e.preventDefault(); exportAnnotations(); };

    document.getElementById("ann-body").addEventListener("click", (e)=>{
      const btn = e.target.closest(".ann-del");
      if (!btn) return;
      e.preventDefault();
      const pid = btn.getAttribute("data-pid");
      const ts  = btn.getAttribute("data-ts");

      const fp = {
        date: btn.dataset.date,
        annotator: btn.dataset.annotator || "",
        note: btn.dataset.note || "",
        bioUse: btn.dataset.bious === "1",
        bioStart: btn.dataset.biostart || "",
        bioEnd: btn.dataset.bioend || "",
        bioCand: btn.dataset.biocand === "" ? null : (btn.dataset.biocand === "1")
      };

      if (!pid) return;
      if (confirm("Remove this annotation?")){
        deleteAnnotation(pid, ts, fp);
        renderAnnTable();
      }
    });
  });
</script>
</body>
</html>
"""

LOGIN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sign in</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root{ --border:#cfe0f5; --bg:#f1f7ff; --text:#0b1220; --primary:#2563eb; }
    body{ font-family: Arial, sans-serif; background:var(--bg); margin:0; padding:32px; }
    .card{
      max-width: 460px;
      min-height: 340px;           /* taller to avoid mismatch */
      margin: 64px auto;
      background:#fff;
      border:1px solid var(--border);
      border-radius:14px;
      padding:28px;
      box-shadow:0 2px 6px rgba(15,23,42,.06);
      box-sizing: border-box;
    }
    h2{ margin:0 0 16px 0; }
    label{ display:block; margin:12px 0 8px; font-weight:700; }
    input{ width:100%; padding:12px 14px; border:1px solid #cbd5e1; border-radius:10px; font-size:16px; }
    button{ margin-top:20px; width:100%; padding:12px 16px; background:var(--primary); color:#fff; border:none; border-radius:10px; cursor:pointer; font-size:16px; }
    .err{ color:#b91c1c; margin-top:12px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Sign in</h2>
    <form method="post">
      <label for="userid">User ID</label>
      <input id="userid" name="userid" autocomplete="username" required />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button type="submit">Enter</button>
      {% if error %}<div class="err">{{ error }}</div>{% endif %}
    </form>
  </div>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uid = (request.form.get("userid") or "").strip()
        pw  = (request.form.get("password") or "").strip()
        # hard-coded: ID=1, PASSWORD=1
        if uid == "1" and pw == "1":
            session["authed"] = True
            return redirect(url_for("ui"))
        return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials.")
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return
    if not session.get("authed"):
        return redirect(url_for("login"))

@app.route("/")
def ui():
    if not session.get("authed"):
        return redirect(url_for("login"))
    return render_template_string(
        TEMPLATE,
        patients_json=json.dumps(PATIENTS, ensure_ascii=False),
        labs_json=json.dumps(LABS_BY_PATIENT, ensure_ascii=False),
        demo_json=json.dumps(DEMO_BY_PATIENT, ensure_ascii=False),
        lab_fields_json=json.dumps(LAB_COLUMNS_SHOW),
        sym_groups_json=json.dumps(SYM_GROUPS),
        sym_order_json=json.dumps(SYM_ORDER),
        ref_ranges_json=json.dumps(REF_RANGES),
        bio_json=json.dumps(BIO_EVENTS),
        # NEW:
        meds_json=json.dumps(MEDS_BY_PATIENT, ensure_ascii=False),
        meds_err=json.dumps(MEDS_ERR, ensure_ascii=False),
    )

def main():
    app.run(debug=True)

if __name__ == "__main__":
    main()
