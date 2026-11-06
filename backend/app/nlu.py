"""Turns what people say into facts. Handles Hindi, romanised Hindi and English.

Deterministic first, so the app works with no API keys and every extraction is
testable. llm.py fills in only when these patterns find nothing.
"""
import re

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_HI_NUMBERS = """शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस
बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस
चालीस इकतालीस बयालीस तैंतालीस चौवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ
साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी
अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे""".split()
_ROMAN_NUMBERS = """shunya ek do teen char paanch chhah saat aath nau das gyarah barah terah chaudah pandrah solah satrah atharah unnis
bees ikkis bais teis chaubis pachchis chhabbis sattais atthais untis tees ikattis battis taintis chauntis paintis chhattis saintis adtis untalis
chalis iktalis bayalis taintalis chauvalis paintalis chhiyalis saintalis adtalis unchas pachas ikyavan bavan tirpan chauvan pachpan chhappan sattavan atthavan unsath
saath iksath basath tirsath chaunsath painsath chhiyasath sadsath adsath unhattar sattar ikhattar bahattar tihattar chauhattar pachhattar chhihattar sathattar athhattar unyasi
assi ikyasi bayasi tirasi chaurasi pachasi chhiyasi sattasi atthasi navasi nabbe ikyanve baanve tiranve chauranve pachanve chhiyanve sattanve atthanve ninyanve""".split()
_WORD_NUMBERS = {w: i for i, w in enumerate(_HI_NUMBERS)} | {w: i for i, w in enumerate(_ROMAN_NUMBERS)}
_WORD_NUMBERS |= {"पांच": 5, "छः": 6, "छ": 6, "सौ": 100, "panch": 5, "chhe": 6, "sau": 100}
_FRACTION_WORDS = {"डेढ़": 1.5, "ढाई": 2.5, "dedh": 1.5, "dhai": 2.5, "सवा": 1.25, "sawa": 1.25}
_LAKH = ("लाख", "lakh", "lac")
_THOUSAND = r"लाख|lakh|lac|हजार|hazar|hajar|thousand"

_NEG = r"(?:नहीं|नही|ना\b|मत\b|nahi|nahin|nhi|nahee|\bno\b|\bnot\b|don'?t|doesn'?t|without|बिना)"
_GIRL = r"(?:पोतियाँ|पोती|बेटियाँ|बेटियां|बेटी|लड़कियाँ|लड़की|नातिन|बिटिया|poti|betiyan|beti|ladki|natin|bitiya|granddaughters?|daughters?|girls?)"
_OTHER_KIN = r"(?:बेटा|बेटे|पोता|पति|बहू|bete|beta|pota|pati|\bson\b|husband)"
# A comma between digits groups a number (40,000 or 1,20,000), and "Rs." is a currency, so neither ends a clause.
_CLAUSE_SPLIT = re.compile(r"(?<!\d),|,(?!\d)|[।;!?\n]|(?<!\brs)\.(?!\d)|\s(?:और|aur|and)\s")

_UP_DISTRICTS = {
    "रायबरेली": "Raebareli", "raebareli": "Raebareli", "rae bareli": "Raebareli", "raibareli": "Raebareli", "rai bareli": "Raebareli",
    "raybareli": "Raebareli", "ray bareli": "Raebareli", "लखनऊ": "Lucknow", "lucknow": "Lucknow",
    "कानपुर": "Kanpur", "kanpur": "Kanpur", "वाराणसी": "Varanasi", "varanasi": "Varanasi", "बनारस": "Varanasi", "banaras": "Varanasi",
    "प्रयागराज": "Prayagraj", "prayagraj": "Prayagraj", "इलाहाबाद": "Prayagraj", "allahabad": "Prayagraj", "गोरखपुर": "Gorakhpur", "gorakhpur": "Gorakhpur",
    "आगरा": "Agra", "agra": "Agra", "मेरठ": "Meerut", "meerut": "Meerut", "बरेली": "Bareilly", "bareilly": "Bareilly", "अयोध्या": "Ayodhya", "ayodhya": "Ayodhya",
    "सीतापुर": "Sitapur", "sitapur": "Sitapur", "उन्नाव": "Unnao", "unnao": "Unnao", "अमेठी": "Amethi", "amethi": "Amethi", "सुल्तानपुर": "Sultanpur", "sultanpur": "Sultanpur",
    "प्रतापगढ़": "Pratapgarh", "pratapgarh": "Pratapgarh", "जौनपुर": "Jaunpur", "jaunpur": "Jaunpur", "आजमगढ़": "Azamgarh", "azamgarh": "Azamgarh",
    "बलिया": "Ballia", "ballia": "Ballia", "गोंडा": "Gonda", "gonda": "Gonda", "बहराइच": "Bahraich", "bahraich": "Bahraich", "हरदोई": "Hardoi", "hardoi": "Hardoi",
}
_UP_TERMS = r"(?:उत्तर प्रदेश|यूपी|uttar pradesh|\bu\.p\.|^up$|\b(?:in|from)\s+up\b|\bup\s+(?:se|me|mein|ka|ki|ke|resident)\b)"
_OTHER_STATES = r"(?:बिहार|राजस्थान|मध्य प्रदेश|झारखंड|दिल्ली|हरियाणा|पंजाब|महाराष्ट्र|bihar|rajasthan|madhya pradesh|jharkhand|delhi|haryana|punjab|maharashtra)"

_ARTISAN = r"(?:बढ़ई|लोहार|कुम्हार|सुनार|मोची|दर्जी|नाई|राजमिस्त्री|धोबी|माली|carpenter|blacksmith|potter|goldsmith|cobbler|tailor|barber|mason|washerman|badhai|lohar|kumhar|sunar|mochi|darzi)"

_DOC_TERMS = {
    "aadhaar": r"(?:आधार|aadhaar|aadhar)", "ration_card": r"(?:राशन कार्ड|ration card)",
    "bank_passbook": r"(?:पासबुक|passbook)", "income_certificate": r"(?:आय प्रमाण|इनकम सर्टिफिकेट|income certificate|aay praman)",
    "birth_certificate": r"(?:जन्म प्रमाण|birth certificate|janm praman)",
    "death_certificate": r"(?:मृत्यु प्रमाण|death certificate|mrityu praman)", "land_record": r"(?:खतौनी|khatauni|land record)",
    "mcp_card": r"(?:\bmcp\b|जच्चा|ममता कार्ड)", "school_id": r"(?:स्कूल का पहचान|school id|college id)",
}

_YES = r"(?:^|\s)(?:हाँ|हां|हा|जी|ठीक|सही|बिल्कुल|है|haan|han|ha|ji|yes|yeah|hai|correct|sahi|theek)(?:\s|$|[,।.!])"
_NO = r"(?:नहीं|नही|ना\b|nahi|nahin|nhi|\bno\b|nope|\bnot\b|galat|गलत)"
_DONT_KNOW = r"(?:पता नहीं|मालूम नहीं|नहीं पता|नहीं मालूम|pata nahi|malum nahi|don'?t know|not sure)"
_SEND = r"(?:भेज|bhej|submit|सबमिट|send|जमा कर)"
_STOP_SEND = r"(?:मत भेज|नहीं भेज|ना भेज|रुक|रोक|mat bhej|nahi bhej|na bhej|\bruk|\brok|don'?t send|do not send|cancel|\bstop\b)"


_EN_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_EN_TENS = {w: (i + 2) * 10 for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_EN_NUMBER = re.compile(r"\b(" + "|".join(_EN_TENS) + r")(?:[\s-](" + "|".join(list(_EN_UNITS)[1:10]) + r"))?\b|\b(" + "|".join(_EN_UNITS) + r")\b")


def _english_number(match: re.Match) -> str:
    if match.group(1):
        return str(_EN_TENS[match.group(1)] + (_EN_UNITS[match.group(2)] if match.group(2) else 0))
    return str(_EN_UNITS[match.group(3)])


def normalize(text: str) -> str:
    # Nukta spellings vary between typists and speech engines, so fold them away.
    folded = text.translate(_DEV_DIGITS).replace("ज़", "ज").replace("ड़", "ड़").replace("ढ़", "ढ़")
    return _EN_NUMBER.sub(_english_number, " ".join(folded.split()).lower())


def _fold(pattern: str) -> str:
    return pattern.replace("ज़", "ज")


def _search(pattern: str, text: str):
    return re.search(_fold(pattern), text)


def _number_word(text: str) -> int | None:
    for token in re.split(r"[\s,।.]+", text):
        if token in _WORD_NUMBERS:
            return _WORD_NUMBERS[token]
    return None


def first_int(text: str) -> int | None:
    match = re.search(r"\d+", text)
    return int(match.group()) if match else _number_word(text)


def parse_money(text: str) -> int | None:
    """₹ amount as a yearly figure: '5 हज़ार महीना' becomes 60000."""
    text = normalize(text)
    amount = None
    match = re.search(rf"(\d+(?:\.\d+)?)\s*({_THOUSAND}|k\b)", text)
    if match:
        amount = float(match.group(1)) * (100000 if match.group(2) in _LAKH else 1000)
    if amount is None:
        for word, value in _FRACTION_WORDS.items():
            found = re.search(word + rf"\s*({_THOUSAND})", text)
            if found:
                amount = value * (100000 if found.group(1) in _LAKH else 1000)
    if amount is None:
        found = re.search(rf"(\S+)\s*({_THOUSAND})", text)
        if found and found.group(1) in _WORD_NUMBERS:
            amount = _WORD_NUMBERS[found.group(1)] * (100000 if found.group(2) in _LAKH else 1000)
    if amount is None:
        match = re.search(r"\d[\d,]*", text)
        if match:
            amount = float(match.group().replace(",", ""))
    if amount is None:
        return None
    if re.search(r"महीन|माह|mahin|month", text):
        amount *= 12
    return int(amount)


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(text) if c and c.strip()]


def _bool_near(pattern: str, text: str) -> bool | None:
    """Was the thing mentioned, and was it negated in the same clause?"""
    for clause in _clauses(text):
        if _search(pattern, clause):
            return not re.search(_NEG, clause)
    return None


def yes_no(text: str) -> bool | None:
    norm = normalize(text)
    if re.search(_DONT_KNOW, norm):
        return None
    if re.search(_NO, norm):
        return False
    if re.search(_YES, f" {norm} "):
        return True
    return None


def is_dont_know(text: str) -> bool:
    return bool(re.search(_DONT_KNOW, normalize(text)))


def confirms_send(text: str) -> bool:
    """Only an explicit 'send it'. A bare 'yes' is not a submission."""
    norm = normalize(text)
    return bool(re.search(_SEND, norm)) and not re.search(_STOP_SEND, norm)


def refuses_send(text: str) -> bool:
    return bool(re.search(_STOP_SEND, normalize(text)))


def _extract_ages(text: str, facts: dict) -> None:
    for clause in _clauses(text):
        match = re.search(r"(\d{1,3}|\S+)\s*(?:साल|वर्ष|saal|sal\b|years?|yrs?)", clause)
        if match:
            raw = match.group(1)
            value = int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw)
            if value is None or value > 120:
                continue
            if _search(_GIRL, clause):
                facts["youngest_girl_age"] = (value, "said")
                facts.setdefault("girl_children_count", (1, "inferred"))
            elif not _search(_OTHER_KIN, clause) and "age" not in facts:
                facts["age"] = (value, "said")
            continue
        labelled = re.search(r"(?:उम्र|umar|umra|\bage\b)\D{0,12}(\d{1,3})", clause)
        if labelled and "age" not in facts:
            facts["age"] = (int(labelled.group(1)), "said")


def _extract_girls(norm: str, facts: dict) -> None:
    mentioned = _bool_near(_GIRL, norm)
    if mentioned is False:
        facts["girl_children_count"] = (0, "said")
        return
    if mentioned is None:
        return
    count = re.search(r"(\d+|\S+)\s*" + _GIRL, norm)
    if count:
        raw = count.group(1)
        value = int(raw) if raw.isdigit() else _WORD_NUMBERS.get(raw)
        if value is not None and value <= 12:
            facts["girl_children_count"] = (value, "said")
            return
    facts.setdefault("girl_children_count", (1, "inferred"))


def extract_facts(text: str, expected: str | None = None) -> dict:
    """Returns {key: (value, source)}. Source is 'said' or 'inferred'."""
    norm = normalize(text)
    facts: dict = {}
    _extract_ages(norm, facts)

    if _search(r"विधवा|vidhwa|vidhva|widow|पति नहीं रहे|pati nahi rahe|पति गुजर", norm):
        facts["is_widow"] = (True, "said")
        facts["gender"] = ("female", "inferred")
    if _search(r"महिला|औरत|स्त्री|\bwoman\b|\bfemale\b|mahila|aurat", norm):
        facts["gender"] = ("female", "said")
    if _search(r"पुरुष|आदमी|मर्द|\bman\b|\bmale\b|purush|aadmi", norm):
        facts["gender"] = ("male", "said")

    for term, district in _UP_DISTRICTS.items():
        if _search(term, norm):
            facts["district"] = (district, "said")
            facts["state_up"] = (True, "inferred")
            break
    if _search(_OTHER_STATES, norm):
        facts["state_up"] = (False, "said")
    elif _search(_UP_TERMS, norm):
        facts["state_up"] = (bool(_bool_near(_UP_TERMS, norm)), "said")

    if _search(r"गाँव|गांव|ग्रामीण|gaon|\bgav\b|village|rural", norm):
        facts["area"] = ("rural", "said")
    if _search(r"शहर|नगर|कस्बा|shahar|sheher|\bcity\b|\btown\b|urban", norm):
        facts["area"] = ("urban", "said")

    bpl = _bool_near(r"\bbpl\b|बीपीएल|अंत्योदय|antyodaya|गरीबी रेखा", norm)
    if bpl is not None:
        facts["bpl_card"] = (bpl, "said")

    land = re.search(r"(\d+(?:\.\d+)?)\s*(एकड़|एकड|acres?|ekad|बीघा|bigha|हेक्टेयर|hectare)", norm)
    if land:
        acres = float(land.group(1))
        if land.group(2) in ("बीघा", "bigha"):
            acres = round(acres * 0.625, 2)
        elif land.group(2) in ("हेक्टेयर", "hectare"):
            acres = round(acres * 2.47, 2)
        facts["land_acres"] = (acres, "said")
        facts["owns_farmland"] = (True, "said")
    else:
        farm = _bool_near(r"जमीन|खेत|zameen|jameen|jamin|farmland|\bland\b|\bkhet\b", norm)
        if farm is not None:
            facts["owns_farmland"] = (farm, "said")

    for clause in _clauses(norm):
        if _search(r"कमाई|आमदनी|कमाते|सालाना|income|kamai|aamdani|amdani|kamate|saalana", clause) or re.search(r"(?:^|\s)आय(?:\s|$)", clause):
            if not _search(r"आयकर|income tax|प्रमाण|certificate", clause):
                amount = parse_money(clause)
                if amount is not None:
                    facts["annual_income"] = (amount, "said")

    tax = _bool_near(r"आयकर|इनकम टैक्स|income tax|aaykar", norm)
    if tax is not None:
        facts["income_tax_payer"] = (tax, "said")
    govt = _bool_near(r"सरकारी नौकरी|सरकारी कर्मचारी|sarkari naukri|government (?:job|employee)|govt (?:job|employee)", norm)
    if govt is not None:
        facts["govt_employee"] = (govt, "said")
    lpg = _bool_near(r"गैस|सिलेंडर|\blpg\b|\bgas\b|cylinder", norm)
    if lpg is not None:
        facts["has_lpg"] = (lpg, "said")
    if _search(r"कच्चा|कच्ची|kutcha|kachcha|kaccha", norm):
        facts["has_pucca_house"] = (False, "said")
    else:
        pucca = _bool_near(r"पक्का घर|पक्का मकान|pucca|pakka", norm)
        if pucca is not None:
            facts["has_pucca_house"] = (pucca, "said")
    bank = _bool_near(r"बैंक खाता|बैंक में खाता|खाता है|खाता नहीं|bank account|bank khata|\bkhata\b", norm)
    if bank is not None:
        facts["has_bank_account"] = (bank, "said")
    preg = _bool_near(r"गर्भवती|garbhvati|pregnant|स्तनपान|breastfeeding", norm)
    if preg is not None:
        facts["pregnant_or_lactating"] = (preg, "said")
    artisan = _bool_near(_ARTISAN, norm)
    if artisan is not None:
        facts["traditional_artisan"] = (artisan, "said")
    student = _bool_near(r"कॉलेज|college|कक्षा (?:9|10|11|12)|(?:9|10|11|12)वीं|class (?:9|10|11|12)|(?:9|10|11|12)th", norm)
    if student is not None:
        facts["student_class_9plus"] = (student, "said")

    _extract_girls(norm, facts)

    for doc_id, pattern in _DOC_TERMS.items():
        state = _bool_near(pattern, norm)
        if state is not None:
            facts[f"doc_{doc_id}"] = (state, "said")
    if facts.get("doc_bank_passbook", (None,))[0] is True:
        facts.setdefault("has_bank_account", (True, "inferred"))

    name = re.search(
        r"(?:मेरा नाम|mera naam|my name is)\s*(?:है\s+|hai\s+|:)?\s*([^\s,।.]+(?:\s+[^\s,।.]+){0,3}?)\s*(?:है|hai|हूँ|हूं|hoon|,|।|\.|$)",
        text.translate(_DEV_DIGITS), re.IGNORECASE)
    if name:
        value = name.group(1).strip()
        facts["name"] = (value.title() if value.isascii() else value, "said")

    _apply_expected(norm, expected, facts)
    return facts


def _apply_expected(norm: str, expected: str | None, facts: dict) -> None:
    """A short reply only makes sense against the question that was just asked."""
    if not expected or expected in facts:
        return
    if expected in ("age", "youngest_girl_age", "girl_children_count"):
        value = first_int(norm)
        if value is None and expected == "girl_children_count" and yes_no(norm) is False:
            value = 0
        if value is not None:
            facts[expected] = (value, "said")
    elif expected == "annual_income":
        amount = parse_money(norm)
        if amount is None:
            amount = _number_word(norm)
        if amount is not None:
            facts[expected] = (amount, "said")
    else:
        from .engine.rules import load_catalog
        question = load_catalog()["questions"].get(expected)
        if question and question["type"] == "bool":
            answer = yes_no(norm)
            if answer is not None:
                facts[expected] = (answer, "said")


def extract_profile_field(field: str, text: str) -> str | None:
    """A form field being asked for right now. Digits survive spaces, as STT often adds them."""
    clean = text.translate(_DEV_DIGITS).strip()
    digits = re.sub(r"\D", "", clean)
    if field == "mobile":
        return digits[-10:] if len(digits) >= 10 else None
    if field == "aadhaar_last4":
        return digits[-4:] if len(digits) >= 4 else None
    if field == "bank_account":
        return digits if 9 <= len(digits) <= 18 else None
    if field == "ifsc":
        match = re.search(r"[A-Za-z]{4}\s*0\s*[A-Za-z0-9]{6}", clean)
        return re.sub(r"\s", "", match.group()).upper() if match else None
    if field in ("dob", "girl_dob"):
        match = re.search(r"(\d{1,2})[/\-. ](\d{1,2})[/\-. ](\d{4})", clean)
        return f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{match.group(3)}" if match else None
    if field == "annual_income":
        amount = parse_money(clean)
        return str(amount) if amount is not None else None
    if field == "land_acres":
        match = re.search(r"\d+(?:\.\d+)?", clean)
        return match.group() if match else None
    return clean.rstrip("।.") or None


def matches_scheme(text: str, schemes: dict) -> str | None:
    norm = normalize(text)
    best, best_len = None, 0
    for scheme in schemes.values():
        for alias in scheme["aliases"]:
            folded = normalize(alias)
            if folded in norm and len(folded) > best_len:
                best, best_len = scheme["id"], len(folded)
    return best


def detect_intent(text: str) -> str | None:
    norm = normalize(text)
    if re.search(r"क्यों|kyon|\bkyu\b|kyun|\bwhy\b", norm):
        return "why"
    if re.search(r"फॉर्म|फार्म|form|आवेदन कर|apply|aavedan kar|भर दो|bhar do", norm):
        return "apply"
    if re.search(r"स्थिति|क्या हुआ|कहाँ तक|status|kya hua|kahan tak|अपडेट|update", norm):
        return "status"
    if re.search(r"दस्तावेज|कागज|document|kagaz|dastavej", norm):
        return "documents"
    return None
