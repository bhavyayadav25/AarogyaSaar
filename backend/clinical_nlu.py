"""Phase AI-1B: lightweight clinical language understanding.

This module converts patient language into conservative, structured evidence.
It does not diagnose, recommend treatment, or invent missing information.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

SYMPTOMS = {
    "chest pain": ["chest pain", "chest discomfort", "chest pressure", "chest tightness", "seene mein dard", "seene me dard", "seene mein pressure", "seene me pressure", "seene mein tightness", "सीने में दर्द", "सीने में तकलीफ", "छाती में दर्द", "छाती में तकलीफ़", "বুকে ব্যথা", "বুকে চাপ"],
    "headache": ["headache", "head pain", "migraine", "sir dard", "sar dard", "सिरदर्द", "सिर में दर्द", "মাথাব্যথা", "মাথায় ব্যথা"],
    "dizziness": ["dizziness", "dizzy", "lightheaded", "chakkar", "चक्कर", "चक्कर आना", "মাথা ঘোরা"],
    "nausea": ["nausea", "nauseous", "ji michlana", "मतली", "বমি বমি ভাব"],
    "vomiting": ["vomiting", "vomit", "उल्टी", "বমি"],
    "abdominal pain": ["stomach pain", "abdominal pain", "belly pain", "pet me dard", "pet mein dard", "पेट में दर्द", "पेट दर्द", "পেটে ব্যথা"],
    "bloating": ["bloating", "bloated", "gas", "pet phoolna", "पेट फूलना", "गैस", "পেট ফাঁপা", "গ্যাস"],
    "fever": ["fever", "feverish", "high temperature", "bukhar", "बुखार", "ताप", "জ্বর"],
    "cough": ["cough", "coughing", "khansi", "खांसी", "खाँसी", "কাশি"],
    "shortness of breath": ["shortness of breath", "breathless", "difficulty breathing", "breathing difficulty", "saans phoolna", "saans phoolti", "saans lene me dikkat", "सांस फूलना", "सांस लेने में दिक्कत", "श्वास लेने में दिक्कत", "শ্বাসকষ্ট", "শ্বাস নিতে কষ্ট"],
    "wheeze": ["wheeze", "wheezing", "सीटी जैसी सांस", "শ্বাসে সাঁই সাঁই"],
    "sore throat": ["sore throat", "throat pain", "gale mein dard", "गले में दर्द", "গলা ব্যথা"],
    "fatigue": ["fatigue", "tired", "tiredness", "low energy", "weakness", "kamzori", "थकान", "कमजोरी", "দুর্বলতা", "ক্লান্তি"],
    "skin rash/itching": ["rash", "itching", "itchy", "skin irritation", "khujli", "दाने", "खुजली", "चकत्ते", "চুলকানি", "ফুসকুড়ি"],
    "urinary symptoms": ["burning urination", "burning while urinating", "frequent urination", "urine burning", "peshab mein jalan", "पेशाब में जलन", "প্রস্রাবে জ্বালা", "বারবার প্রস্রাব"],
    "back/joint pain": ["back pain", "joint pain", "knee pain", "shoulder pain", "muscle ache", "kamar dard", "ghutne mein dard", "कमर दर्द", "घुटने में दर्द", "জয়েন্টে ব্যথা", "কোমরে ব্যথা"],
    "generalized body ache": ["body ache", "body pain", "generalized body ache", "shareer mein dard", "sharir me dard", "शरीर में दर्द", "शरीर दर्द", "শরীরে ব্যথা", "সারা শরীরে ব্যথা"],
    "diarrhea": ["diarrhea", "loose motions", "loose stools", "dast", "दस्त", "पतले दस्त", "পাতলা পায়খানা", "ডায়রিয়া"],
    "constipation": ["constipation", "कब्ज", "কোষ্ঠকাঠিন্য"],
    "appetite change": ["loss of appetite", "poor appetite", "increased appetite", "bhook kam", "भूख कम", "ক্ষুধা কম", "খিদে কম"],
    "diabetes": ["diabetes", "diabetic", "sugar disease", "मधुमेह", "शुगर", "ডায়াবেটিস", "সুগার"],
    "hypertension": ["hypertension", "high blood pressure", "bp high", "उच्च रक्तचाप", "हाई ब्लड प्रेशर", "উচ্চ রক্তচাপ", "উচ্চ ব্লাড প্রেসার"],
    "heart disease": ["heart disease", "heart problem", "दिल की बीमारी", "हृदय रोग", "হৃদরোগ", "হৃদয়ের সমস্যা"],
    "asthma": ["asthma", "अस्थमा", "दमा", "হাঁপানি", "অ্যাজমা"],
}


NEGATIONS = [
    "no ", "not ", "without ", "never ", "don't ", "do not ", "didn't ", "did not ",
    "nahi ", "nahin ", "nahi hai", "nahin hai", "नहीं", "नही", "नहीं है", "नहीं हैं", "कोई नहीं",
    "nahi hota", "nahin hota", "nahi hoti", "nahin hoti"
]

DURATION_PATTERNS = [
    r"\b(?:for|since)\s+((?:\d+|one|two|three|four|five|six|seven|a|an))\s*(day|days|week|weeks|month|months|year|years)\b",
    r"\b(\d+)\s*(day|days|week|weeks|month|months|year|years)\s*(?:ago|se pehle)\b",
    r"\b(since yesterday|since last night|since morning|for a long time)\b",
    r"(\d+)\s*(din|dino|dinon)\s*(se|se hi)?",
    r"(\d+)\s*(hafte|hafton|mahine|mahino|saal)\s*(se|se hi)?",
    r"((?:\d+|এক|দুই|তিন|চার|পাঁচ|ছয়|ছয়|সাত))\s*(দিন|দিন ধরে|সপ্তাহ|সপ্তাহ ধরে|মাস|মাস ধরে|বছর|বছর ধরে)\s*(ধরে|আগে)?",
    r"((?:\d+|एक|दो|तीन|चार|पांच|पाँच|छह|छः|सात))\s*(दिन|दिनों|हफ्ते|हफ्तों|महीने|महीनों|साल)\s*(से|से ही)?",
]

NUMBER_WORDS = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"a":1,"an":1,"এক":1,"দুই":2,"তিন":3,"চার":4,"পাঁচ":5,"ছয়":6,"সাত":7}
SEVERITY = {
    "mild": ["mild", "slight", "little", "halka", "हल्का", "कम"],
    "moderate": ["moderate", "medium", "madhyam", "मध्यम"],
    "severe": ["severe", "very painful", "worst", "extreme", "unbearable", "bahut zyada", "बहुत तेज", "बहुत ज्यादा", "असहनीय"],
}

INTENT_MAP = {
    "chest pain": "chest",
    "headache": "headache",
    "abdominal pain": "abdominal",
    "fever": "fever",
    "cough": "respiratory",
    "shortness of breath": "respiratory",
    "skin rash/itching": "skin",
    "urinary symptoms": "urinary",
    "back/joint pain": "pain",
    "diarrhea": "abdominal",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def negated(text: str, start: int) -> bool:
    # Negation is intentionally local. A negation in one clause should not
    # leak across a conjunction into a later symptom.
    window = text[max(0, start - 45):start]
    for boundary in (" but ", " and ", " however ", "."):
        if boundary in window:
            window = window.rsplit(boundary, 1)[-1]
    # Hindi/Hinglish often puts the negation immediately before the concept.
    return any(n in window for n in NEGATIONS)


def extract_duration(text: str) -> List[str]:
    values: List[str] = []
    for pattern in DURATION_PATTERNS:
        values.extend(m.group(0) for m in re.finditer(pattern, text, flags=re.I))
    return list(dict.fromkeys(values))


def extract_severity(text: str) -> str | None:
    for level, terms in SEVERITY.items():
        if any(term in text for term in terms):
            return level
    nums = re.findall(r"\b(?:10|[0-9])\b", text)
    if nums:
        n = int(nums[0])
        if n <= 3:
            return "mild"
        if n <= 6:
            return "moderate"
        return "severe"
    return None


def extract_symptoms(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for canonical, variants in SYMPTOMS.items():
        for term in sorted(variants, key=len, reverse=True):
            pos = text.find(term.lower())
            if pos >= 0:
                is_negated = negated(text, pos)
                out.append({
                    "concept": canonical,
                    "mention": term,
                    "negated": is_negated,
                    "evidence": text[max(0, pos-35):min(len(text), pos+len(term)+35)].strip(),
                })
                break

    # Compositional Hinglish/Hindi patterns: patients frequently insert a
    # duration or other phrase between the body location and symptom quality.
    extra_patterns = [
        ("chest pain", r"\bseene?\s+(?:mein|me)\s+.{0,35}\b(?:pressure|tightness|dard)\b", "seene mein ... symptom"),
        ("shortness of breath", r"\bsaans\s+(?:bhi\s+)?(?:phoolti|phoolna|chadh(?:ti|na))\b", "saans phoolna"),
        ("headache", r"\b(?:sir|sar)\s+(?:mein|me)\s+.{0,25}\b(?:dard|pain)\b", "sir mein dard"),
        ("abdominal pain", r"\bpet\s+(?:mein|me)\s+.{0,25}\b(?:dard|pain)\b", "pet mein dard"),
    ]
    existing = {x["concept"] for x in out}
    for canonical, pattern, mention in extra_patterns:
        if canonical in existing:
            continue
        m = re.search(pattern, text, flags=re.I)
        if m:
            pos = m.start()
            out.append({
                "concept": canonical,
                "mention": mention,
                "negated": negated(text, pos),
                "evidence": m.group(0),
            })
    return out


def infer_intent(symptoms: List[Dict[str, Any]]) -> str:
    positive = [x["concept"] for x in symptoms if not x["negated"]]
    for symptom in positive:
        if symptom in INTENT_MAP:
            return INTENT_MAP[symptom]
    return "general"


def extract_clinical_entities(text: str, language: str = "en-IN") -> Dict[str, Any]:
    raw = text or ""
    normalized = normalize(raw)
    symptoms = extract_symptoms(normalized)
    durations = extract_duration(normalized)
    severity = extract_severity(normalized)
    positive = [x["concept"] for x in symptoms if not x["negated"]]
    negated_terms = [x["concept"] for x in symptoms if x["negated"]]
    return {
        "raw_text": raw.strip(),
        "normalized_text": normalized,
        "language": language,
        "symptoms": symptoms,
        "positive_symptoms": positive,
        "negated_symptoms": negated_terms,
        "duration_mentions": durations,
        "severity": severity,
        "intent": infer_intent(symptoms),
        "evidence": [x["evidence"] for x in symptoms],
        "engine": "AI-1B conservative clinical entity extraction",
        "diagnostic": False,
    }


# English canonical clinical rendering used for the doctor handoff.
# This is deliberately concept-based rather than word-by-word translation:
# only information that the local clinical NLU can safely map to a known
# clinical concept is rendered in English.
CONCEPT_PHRASES = {
    "fever": "fever",
    "generalized body ache": "generalized body ache",
    "headache": "headache",
    "dizziness": "dizziness",
    "nausea": "nausea",
    "vomiting": "vomiting",
    "abdominal pain": "abdominal pain",
    "bloating": "bloating",
    "cough": "cough",
    "shortness of breath": "shortness of breath",
    "wheeze": "wheezing",
    "sore throat": "sore throat",
    "fatigue": "fatigue/weakness",
    "skin rash/itching": "skin rash/itching",
    "urinary symptoms": "urinary symptoms",
    "back/joint pain": "back/joint pain",
    "diarrhea": "diarrhea",
    "constipation": "constipation",
    "appetite change": "appetite change",
    "diabetes": "diabetes",
    "hypertension": "hypertension",
    "heart disease": "heart disease",
    "asthma": "asthma",
}

def _duration_english(value: str) -> str:
    raw = normalize(value)
    number_words = {
        "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6", "छः": "6", "सात": "7",
        "এক": "1", "দুই": "2", "তিন": "3", "চার": "4", "পাঁচ": "5", "ছয়": "6", "ছয়": "6", "সাত": "7",
    }
    normalized_numbers = raw
    for word, number in number_words.items():
        normalized_numbers = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", number, normalized_numbers)
    replacements = [
        (r"(\d+)\s*days?", r"\1 days"),
        (r"(\d+)\s*weeks?", r"\1 weeks"),
        (r"(\d+)\s*months?", r"\1 months"),
        (r"(\d+)\s*years?", r"\1 years"),
        (r"(\d+)\s*(?:din|dino|dinon|दिन|দিন)\s*(?:se|से|ধরে)?", r"\1 days"),
        (r"(\d+)\s*(?:hafte|hafton|हफ्ते|हफ्तों|সপ্তাহ|সপ্তাহের)\s*(?:se|से|ধরে)?", r"\1 weeks"),
        (r"(\d+)\s*(?:mahine|mahino|महीने|महीनों|মাস|মাসের)\s*(?:se|से|ধরে)?", r"\1 months"),
        (r"(\d+)\s*(?:saal|साल|বছর)\s*(?:se|से|ধরে)?", r"\1 years"),
        (r"since yesterday", "since yesterday"),
        (r"since last night", "since last night"),
        (r"since morning", "since this morning"),
    ]
    for pattern, replacement in replacements:
        m = re.search(pattern, normalized_numbers, flags=re.I)
        if m:
            return re.sub(pattern, replacement, normalized_numbers, count=1, flags=re.I).strip()
    return raw

CONTROLLED_PHRASES = {
    "chief_complaint": {
        "fever": "fever", "bukhar": "fever", "बुखार": "fever", "জ্বর": "fever",
        "pain": "pain", "दर्द": "pain", "ব্যথা": "pain",
        "cough": "cough", "khansi": "cough", "खांसी": "cough", "খাঁসি": "cough", "কাশি": "cough",
        "weakness": "weakness", "kamzori": "weakness", "कमजोरी": "weakness", "দুর্বলতা": "weakness",
        "stomach problem": "stomach problem", "पेट की समस्या": "stomach problem", "পেটের সমস্যা": "stomach problem",
        "headache": "headache", "सिरदर्द": "headache", "মাথাব্যথা": "headache",
        "breathing problem": "breathing problem", "सांस की समस्या": "breathing problem", "श्वास की समस्या": "breathing problem", "শ্বাসের সমস্যা": "breathing problem",
        "injury": "injury", "चोट": "injury", "আঘাত": "injury",
    },
    "onset": {
        "today": "today", "आज": "today", "আজ": "today",
        "a few days": "a few days", "कुछ दिन": "a few days", "কয়েক দিন": "a few days", "কয়েক দিন": "a few days",
        "1-2 weeks": "1–2 weeks", "1–2 weeks": "1–2 weeks", "1-2 हफ्ते": "1–2 weeks", "১–২ সপ্তাহ": "1–2 weeks",
        "more than 2 weeks": "more than 2 weeks", "2 हफ्ते से ज्यादा": "more than 2 weeks", "২ সপ্তাহের বেশি": "more than 2 weeks",
    },
    "location": {
        "head": "head", "सिर": "head", "মাথা": "head", "chest": "chest", "सीना": "chest", "छाती": "chest", "বুক": "chest",
        "stomach": "stomach", "पेट": "stomach", "পেট": "stomach", "back": "back", "पीठ": "back", "পিঠ": "back",
        "arm": "arm", "बांह": "arm", "हाथ": "arm", "হাত": "arm", "leg": "leg", "पैर": "leg", "পা": "leg",
        "joint": "joint", "जोड़": "joint", "জয়েন্ট": "joint", "skin": "skin", "त्वचा": "skin", "চামড়া": "skin",
        "other": "other", "अन्य": "other", "অন্যান্য": "other",
    },
    "severity": {
        "mild": "mild", "हल्का": "mild", "হালকা": "mild",
        "moderate": "moderate", "मध्यम": "moderate", "মাঝারি": "moderate",
        "severe": "severe", "बहुत तेज": "severe", "बहुत ज्यादा": "severe", "तीव्र": "severe", "তীব্র": "severe",
        "not sure": "not sure", "पता नहीं": "not sure", "निश्चित नहीं": "not sure", "নিশ্চিত নই": "not sure",
    },
    "character": {
        "sharp": "sharp", "तेज": "sharp", "তীক্ষ্ণ": "sharp", "burning": "burning", "जलन": "burning", "জ্বালা": "burning",
        "throbbing": "throbbing", "धड़कता": "throbbing", "ধকধক": "throbbing",
        "tight or pressure": "tightness/pressure", "tight / pressure": "tightness/pressure", "जकड़न": "tightness/pressure", "চাপ/জকড়ন": "tightness/pressure",
        "heavy": "heavy", "भारी": "heavy", "ভারী": "heavy", "other": "other", "अन्य": "other", "অন্যান্য": "other",
    },
    "chest_radiation": {
        "no": "no radiation reported", "arm / shoulder": "radiation to arm/shoulder", "jaw / neck": "radiation to jaw/neck",
        "back": "radiation to back", "not sure": "not sure",
    },
}


def canonicalize_clinical_text(text: str, language: str = "en-IN", field: str = "") -> str:
    """Render multilingual patient text as conservative English clinical facts."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if language == "en-IN":
        return raw

    controlled = CONTROLLED_PHRASES.get(field, {})
    key = normalize(raw)
    if key in controlled:
        return controlled[key]

    entities = extract_clinical_entities(raw, language=language)
    positives = [
        CONCEPT_PHRASES[c]
        for c in entities.get("positive_symptoms", [])
        if c in CONCEPT_PHRASES
    ]
    negatives = [
        CONCEPT_PHRASES[c]
        for c in entities.get("negated_symptoms", [])
        if c in CONCEPT_PHRASES
    ]
    positives = list(dict.fromkeys(positives))
    negatives = list(dict.fromkeys(negatives))
    duration_source = (entities.get("duration_mentions") or [raw])[0]
    duration = _duration_english(duration_source)
    severity = entities.get("severity") if field in {"severity", "chief_complaint", "associated", "review_systems"} else None
    parts = []

    if positives:
        if len(positives) == 1:
            phrase = positives[0].capitalize()
        else:
            phrase = ", ".join(positives[:-1]) + " and " + positives[-1]
            phrase = phrase.capitalize()
        if duration:
            phrase += f" for {duration}"
        if severity:
            phrase += f", {severity} in severity"
        parts.append(phrase + ".")
    elif severity:
        parts.append(f"Patient reports {severity} severity.")

    if negatives:
        parts.append("No " + ", ".join(negatives) + " reported.")

    if duration and not parts:
        if field == "onset":
            return f"for {duration}"
        parts.append(f"Duration: {duration}.")

    if parts:
        return " ".join(parts)

    if field in {
        "onset", "location", "severity", "character", "chest_radiation",
        "chest_exertion", "chest_breathlessness", "headache_visual",
        "headache_nausea", "headache_trigger", "abdominal_food",
        "abdominal_bowel", "abdominal_urinary", "fever_pattern",
        "fever_infection", "respiratory_cough", "respiratory_activity",
        "respiratory_wheeze", "general_change", "general_impact",
        "past_history", "medications", "allergies", "family_history",
        "personal_history", "review_systems", "associated",
    }:
        # These fields frequently contain stable English card values. If the
        # patient supplied free text that cannot be safely normalized, avoid
        # exposing it in the doctor-facing canonical summary.
        return raw if language == "en-IN" else (
            "Patient-reported details require clinician review."
        )

    return "Patient-reported information requires clinician review; no additional English clinical concept could be safely normalized."

